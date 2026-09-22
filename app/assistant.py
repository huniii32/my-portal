"""Assistant briefing / proactive slots / SSE helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import work_digest

from app.config import SEOUL
from app.models import AssistantPreferences, GoalItem
from app.storage import (
    DATA_LOCK,
    StorageError,
    _read_goals_for_briefing,
    load_assistant_preferences,
    load_tasks,
)
from app.trading import _trading_notifications, _trading_risk


def _clock_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def quiet_hours_active(now: datetime, quiet_start: str, quiet_end: str) -> bool:
    """Return whether a quiet window is active, including windows crossing midnight."""
    from app.storage import _valid_clock

    current = now.hour * 60 + now.minute
    start, end = _clock_minutes(_valid_clock(quiet_start)), _clock_minutes(_valid_clock(quiet_end))
    if start == end:
        return False
    return (current >= start or current < end) if start > end else start <= current < end


def proactive_slot(now: datetime, preferences: AssistantPreferences) -> str | None:
    if quiet_hours_active(now, preferences.quiet_start, preferences.quiet_end):
        return None
    current = now.hour * 60 + now.minute
    due = [(slot, _clock_minutes(getattr(preferences, slot))) for slot in ("morning", "midday", "wrap_up")]
    active = [(minute, slot) for slot, minute in due if current >= minute]
    return max(active)[1] if active else None


def _proactive_message(briefing: dict, slot: str) -> str | None:
    pending = briefing.get("pending") if isinstance(briefing.get("pending"), dict) else {}
    overdue = briefing.get("overdue") if isinstance(briefing.get("overdue"), dict) else {}
    goals = briefing.get("goals") if isinstance(briefing.get("goals"), dict) else {}
    overdue_count = int(overdue.get("count") or 0)
    pending_count = int(pending.get("count") or 0)
    goal_count = sum(
        len(goals.get(period, {}).get("items") or [])
        for period in ("week", "day")
        if isinstance(goals.get(period), dict)
    )
    parts = []
    if overdue_count:
        parts.append(f"기한 지난 업무 {overdue_count}개")
    if pending_count:
        parts.append(f"오늘 할 일 {pending_count}개")
    if goal_count:
        parts.append(f"목표 {goal_count}개")
    if not parts:
        return "오늘 업무를 계획해 볼까요?" if slot == "morning" else None
    prefix = {"morning": "아침 계획", "midday": "점심 점검", "wrap_up": "마무리 점검"}[slot]
    return f"{prefix}: {', '.join(parts)}를 확인해 보세요."


def proactive_notifications(
    briefing: dict,
    now: datetime | None = None,
    preferences: AssistantPreferences | None = None,
) -> list[dict]:
    preferences = preferences or load_assistant_preferences()
    if not preferences.proactive_enabled:
        return []
    now = now or datetime.now(SEOUL)
    notices: list[dict] = []
    slot = proactive_slot(now, preferences)
    date_key = now.date().isoformat()
    if slot is not None:
        message = _proactive_message(briefing, slot)
        if message:
            notices.append({
                "id": f"proactive:{date_key}:{slot}",
                "type": "proactive",
                "slot": slot,
                "title": {"morning": "아침 업무 계획", "midday": "점심 업무 점검", "wrap_up": "업무 마무리"}[slot],
                "message": message[:180],
            })
    digest = briefing.get("digest")
    wrap_up = _clock_minutes(preferences.wrap_up)
    current_minutes = now.hour * 60 + now.minute
    if isinstance(digest, dict) and digest.get("date") == date_key and current_minutes >= wrap_up and not quiet_hours_active(now, preferences.quiet_start, preferences.quiet_end):
        bullets = digest.get("completed") or digest.get("in_progress") or digest.get("cautions") or []
        message = str(bullets[0]) if isinstance(bullets, list) and bullets else "오늘의 업무 기록을 정리했어요."
        notices.append({"id": f"digest:{date_key}", "type": "proactive", "slot": "digest", "title": "오늘의 AI 업무 회고", "message": message[:180]})
    return notices


def _brief_goal_items(items: list[GoalItem]) -> list[dict]:
    return [
        {
            "id": item.id,
            "project": item.project,
            "goal": item.goal,
            "current": item.current,
            "target": item.target,
            "unit": item.unit,
            "kind": item.kind,
            "memo": item.memo,
        }
        for item in items[:5]
    ]


def assistant_briefing() -> dict:
    """Deterministic, bounded facts for the on-screen secretary."""
    from app.storage import _today_seoul

    today = _today_seoul()
    monday = today - timedelta(days=today.weekday())
    with DATA_LOCK:
        tasks = load_tasks()
        goals = _read_goals_for_briefing()
    unfinished = sorted((task for task in tasks if not task.done), key=lambda task: (task.date, task.id))
    due = [task for task in unfinished if task.date == today.isoformat()]
    overdue = [task for task in unfinished if task.date < today.isoformat()]
    week_items = goals.week.items if goals.week.start == monday.isoformat() else []
    day_items = goals.day.items if goals.day.date == today.isoformat() else []
    briefing = {
        "source_date": today.isoformat(),
        "pending": {"count": len(due), "items": [task.model_dump() for task in due[:5]]},
        "overdue": {"count": len(overdue), "items": [task.model_dump() for task in overdue[:5]]},
        "trading": _trading_risk(),
        "notifications": _trading_notifications(),
        "digest": work_digest.load_digest(today),
        "goals": {
            "week": {"start": monday.isoformat(), "items": _brief_goal_items(week_items)},
            "day": {"date": today.isoformat(), "items": _brief_goal_items(day_items)},
        },
    }
    briefing["notifications"]["proactive"] = proactive_notifications(briefing)
    return briefing


def _briefing_key(briefing: dict) -> str:
    return json.dumps(briefing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _briefing_event(briefing: dict) -> str:
    payload = json.dumps(briefing, ensure_ascii=False, separators=(",", ":"))
    return f"event: briefing\ndata: {payload}\n\n"


async def _assistant_event_stream(request, initial: dict):
    """Stream fresh briefings without keeping a second copy of portal data."""
    import asyncio

    from app.config import BRIEFING_HEARTBEAT_SECONDS, BRIEFING_POLL_SECONDS

    current = initial
    current_key = _briefing_key(current)
    yield _briefing_event(current)
    last_heartbeat = asyncio.get_running_loop().time()
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(BRIEFING_POLL_SECONDS)
        if await request.is_disconnected():
            return
        try:
            candidate = assistant_briefing()
        except StorageError:
            candidate = None
        if candidate is not None:
            candidate_key = _briefing_key(candidate)
            if candidate_key != current_key:
                current, current_key = candidate, candidate_key
                yield _briefing_event(current)
        now = asyncio.get_running_loop().time()
        if now - last_heartbeat >= BRIEFING_HEARTBEAT_SECONDS:
            yield ": heartbeat\n\n"
            last_heartbeat = now
