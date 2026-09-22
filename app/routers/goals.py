"""Goals CRUD: full replace + per-item create/patch/delete."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from pydantic import ValidationError

from app import storage as _storage
from app.config import DATA_LOCK
from app.models import GoalItem, GoalProgressUpdate, Goals
from app.storage import (
    StorageError,
    _goal_identity,
    load_goals,
    load_tasks,
    save_goals,
    save_tasks,
)

router = APIRouter()


@router.get("/api/goals")
def read_goals() -> Goals:
    with DATA_LOCK:
        return load_goals()


@router.put("/api/goals")
def write_goals(goals: Goals) -> Goals:
    # ponytail: AI가 같은 목표를 week/day 양쪽에 넣는 실수를 반복해서(2026-09-16),
    # 저장 시점에 day 쪽 중복을 떨어낸다 — 주간은 유지, 일간에서 제거.
    week_keys = {(item.project, item.goal.strip()) for item in goals.week.items}
    goals.day.items = [item for item in goals.day.items if (item.project, item.goal.strip()) not in week_keys]
    with DATA_LOCK:
        try:
            save_goals(goals)
        except OSError as error:
            raise HTTPException(status_code=503, detail="목표를 저장하지 못했습니다.") from error
    return goals


@router.post("/api/goals/{period}", status_code=201)
def create_goal(period: Literal["week", "day"], item: GoalItem) -> Goals:
    with DATA_LOCK:
        goals = load_goals()
        goal_period = getattr(goals, period)
        if period == "week" and not goal_period.start:
            today = _storage._today_seoul()
            goal_period.start = (today - timedelta(days=today.weekday())).isoformat()
        if period == "day" and not goal_period.date:
            goal_period.date = _storage._today_seoul().isoformat()
        goal_period.items.append(item)
        try:
            save_goals(goals)
        except OSError as error:
            raise HTTPException(status_code=503, detail="목표를 저장하지 못했습니다.") from error
    return goals


@router.patch("/api/goals/{period}/{index}")
def update_goal_progress(
    period: Literal["week", "day"],
    index: int = ApiPath(ge=0),
    update: GoalProgressUpdate = ...,
) -> Goals:
    if update.current is not None and (not math.isfinite(update.current) or update.current < 0):
        raise HTTPException(status_code=422, detail="완료 수치는 0 이상의 유한한 수여야 합니다.")
    with DATA_LOCK:
        goals = load_goals()
        goal_period = getattr(goals, period)
        period_date = goal_period.start if period == "week" else goal_period.date
        if index >= len(goal_period.items):
            raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다.")
        if period_date != update.expected_date or _goal_identity(goal_period.items[index]) != _goal_identity(update.expected):
            raise HTTPException(status_code=409, detail="목표가 다른 곳에서 변경되었습니다. 새로고침 후 다시 저장하세요.")
        item = goal_period.items[index]
        if update.current is not None:
            item.current = update.current
        if update.project is not None:
            item.project = update.project
        if update.goal is not None:
            item.goal = update.goal.strip()
        if update.target is not None:
            item.target = update.target
        if update.unit is not None:
            item.unit = update.unit.strip()
        if update.kind is not None:
            item.kind = update.kind
        if update.memo is not None:
            item.memo = update.memo.strip()
        try:
            Goals.model_validate(goals.model_dump())
        except ValidationError as error:
            raise HTTPException(status_code=422, detail="목표 형식이 올바르지 않습니다.") from error
        try:
            save_goals(goals)
        except OSError as error:
            raise HTTPException(status_code=503, detail="목표를 저장하지 못했습니다.") from error
    return goals


@router.delete("/api/goals/{period}/{index}")
def delete_goal(period: Literal["week", "day"], index: int = ApiPath(ge=0)) -> Goals:
    with DATA_LOCK:
        goals = load_goals()
        goal_period = getattr(goals, period)
        if index >= len(goal_period.items):
            raise HTTPException(status_code=404, detail="목표를 찾을 수 없습니다.")
        removed = goal_period.items.pop(index)
        try:
            tasks = load_tasks()
            for task in tasks:
                if task.goal_id == removed.id:
                    task.goal_id = None
            save_tasks(tasks)
            save_goals(goals)
        except (StorageError, OSError) as error:
            raise HTTPException(status_code=503, detail="목표를 삭제하지 못했습니다.") from error
    return goals
