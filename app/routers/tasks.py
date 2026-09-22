"""Tasks CRUD: date/range read, create, patch, link, delete."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from fastapi import Query
from fastapi.responses import Response

from app.config import DATA_LOCK
from app.models import TaskCreate, TaskItem, TaskLinkUpdate, TaskUpdate
from app.storage import (
    StorageError,
    _goal_ids,
    load_goals,
    load_tasks,
    save_tasks,
    task_storage_error,
)

router = APIRouter()


@router.get("/api/tasks")
def read_tasks(
    date: str | None = None,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
) -> list[TaskItem]:
    try:
        if from_date is not None or to_date is not None:
            start = from_date or to_date
            end = to_date or from_date
            TaskItem.valid_date(start)
            TaskItem.valid_date(end)
            if start > end:
                raise ValueError("시작 날짜는 종료 날짜보다 늦을 수 없습니다.")
            with DATA_LOCK:
                return [task for task in load_tasks() if start <= task.date <= end]
        selected = date if date is not None else datetime.today().strftime("%Y-%m-%d")
        TaskItem.valid_date(selected)
        with DATA_LOCK:
            return [task for task in load_tasks() if task.date == selected]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error) or "날짜는 YYYY-MM-DD 형식이어야 합니다.") from error
    except StorageError as error:
        raise task_storage_error() from error


@router.post("/api/tasks", status_code=201)
def create_task(task: TaskCreate) -> TaskItem:
    with DATA_LOCK:
        try:
            tasks = load_tasks()
            if len(tasks) >= 1000:
                raise HTTPException(status_code=409, detail="할 일은 최대 1,000개까지 저장할 수 있습니다.")
            if task.goal_id is not None and task.goal_id not in _goal_ids(load_goals()):
                raise HTTPException(status_code=422, detail="연결할 목표를 찾을 수 없습니다.")
            created = TaskItem(
                id=uuid4().hex,
                date=task.date,
                title=task.title,
                done=False,
                goal_id=task.goal_id,
                priority=task.priority,
                memo=task.memo,
            )
            tasks.append(created)
            save_tasks(tasks)
            return created
        except StorageError as error:
            raise task_storage_error() from error


@router.patch("/api/tasks/{task_id}")
def update_task(task_id: str = ApiPath(pattern=r"^[0-9a-f]{32}$"), update: TaskUpdate = ...) -> TaskItem:
    with DATA_LOCK:
        try:
            tasks = load_tasks()
            for task in tasks:
                if task.id == task_id:
                    if update.done is not None:
                        task.done = update.done
                    if update.title is not None:
                        task.title = update.title.strip()
                    if update.priority is not None:
                        task.priority = update.priority
                    if update.memo is not None:
                        task.memo = update.memo.strip()
                    save_tasks(tasks)
                    return task
        except StorageError as error:
            raise task_storage_error() from error
    raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")


@router.patch("/api/tasks/{task_id}/link")
def link_task(task_id: str = ApiPath(pattern=r"^[0-9a-f]{32}$"), update: TaskLinkUpdate = ...) -> TaskItem:
    with DATA_LOCK:
        try:
            tasks = load_tasks()
            if update.goal_id is not None and update.goal_id not in _goal_ids(load_goals()):
                raise HTTPException(status_code=422, detail="연결할 목표를 찾을 수 없습니다.")
            for task in tasks:
                if task.id == task_id:
                    task.goal_id = update.goal_id
                    save_tasks(tasks)
                    return task
        except StorageError as error:
            raise task_storage_error() from error
    raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")


@router.delete("/api/tasks/{task_id}", status_code=204, response_class=Response)
def delete_task(task_id: str = ApiPath(pattern=r"^[0-9a-f]{32}$")) -> Response:
    with DATA_LOCK:
        try:
            tasks = load_tasks()
            kept = [task for task in tasks if task.id != task_id]
            if len(kept) == len(tasks):
                raise HTTPException(status_code=404, detail="할 일을 찾을 수 없습니다.")
            save_tasks(kept)
        except StorageError as error:
            raise task_storage_error() from error
    return Response(status_code=204)
