"""suhun portal FastAPI assembly.

`uvicorn server:app` 진입점은 그대로 유지된다 — server.py가 여기서
조립된 app을 re-export한다.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import config as config
from app.assistant import (
    _assistant_event_stream,
    assistant_briefing,
    proactive_notifications,
    proactive_slot,
    quiet_hours_active,
)
from app.chat import recent_commits, system_prompt
from app.config import (
    APPS,
    APP_GROUPS,
    ASSISTANT_ACTIVITY_PATH,
    ASSISTANT_PREFERENCES_PATH,
    BRIEFING_HEARTBEAT_SECONDS,
    BRIEFING_POLL_SECONDS,
    DATA_LOCK,
    GOALS_PATH,
    LINKS,
    LIVE_ORDERS_PATH,
    SEOUL,
    SERVICE_START_TIMEOUT,
    SYMBOL_NAMES_PATH,
    TASKS_PATH,
    TRADING_HOLIDAYS_CACHE,
    TRADING_RISK_STATUS,
    TRADING_SYMBOL_NAMES,
    VLLM_BASE_URL,
    VLLM_MODEL,
)
from app.holidays import HOLIDAY_NAMES, HOLIDAYS_FALLBACK
from app.models import (
    AssistantAction,
    AssistantPreferences,
    AssistantPreferencesPatch,
    AssistantTaskSnapshot,
    ChatMessage,
    ChatRequest,
    DayGoals,
    GoalItem,
    GoalProgressUpdate,
    Goals,
    TaskCreate,
    TaskItem,
    TaskLinkUpdate,
    TaskUpdate,
    WeekGoals,
)
from app.routers import apps as apps_router
from app.routers import assistant as assistant_router
from app.routers import chat as chat_router
from app.routers import digest as digest_router
from app.routers import goals as goals_router
from app.routers import holidays as holidays_router
from app.routers import pages as pages_router
from app.routers import tasks as tasks_router
from app.routers.apps import _is_up, _journal_hint, _start_service
from app.storage import (
    StorageError,
    _read_assistant_activity,
    _record_assistant_activity,
    _today_seoul,
    load_assistant_preferences,
    load_goals,
    load_tasks,
    save_assistant_preferences,
    save_goals,
    save_tasks,
    task_storage_error,
)
from app.trading import (
    _trading_fill_notifications,
    _trading_hourly_notifications,
    _trading_notifications,
    _trading_risk,
)

import work_digest as work_digest

app = FastAPI(title="suhun portal")
app.include_router(apps_router.router)
app.include_router(goals_router.router)
app.include_router(tasks_router.router)
app.include_router(assistant_router.router)
app.include_router(digest_router.router)
app.include_router(holidays_router.router)
app.include_router(chat_router.router)
app.include_router(pages_router.router)

__all__ = [
    "app",
    "config",
    "APPS",
    "APP_GROUPS",
    "LINKS",
    "DATA_LOCK",
    "GOALS_PATH",
    "TASKS_PATH",
    "ASSISTANT_PREFERENCES_PATH",
    "ASSISTANT_ACTIVITY_PATH",
    "SEOUL",
    "VLLM_BASE_URL",
    "VLLM_MODEL",
    "SERVICE_START_TIMEOUT",
    "TRADING_RISK_STATUS",
    "LIVE_ORDERS_PATH",
    "SYMBOL_NAMES_PATH",
    "TRADING_SYMBOL_NAMES",
    "TRADING_HOLIDAYS_CACHE",
    "BRIEFING_POLL_SECONDS",
    "BRIEFING_HEARTBEAT_SECONDS",
    "HOLIDAYS_FALLBACK",
    "HOLIDAY_NAMES",
    "StorageError",
    "Goals",
    "WeekGoals",
    "DayGoals",
    "GoalItem",
    "GoalProgressUpdate",
    "TaskItem",
    "TaskCreate",
    "TaskUpdate",
    "TaskLinkUpdate",
    "AssistantPreferences",
    "AssistantPreferencesPatch",
    "AssistantTaskSnapshot",
    "AssistantAction",
    "ChatMessage",
    "ChatRequest",
    "load_goals",
    "save_goals",
    "load_tasks",
    "save_tasks",
    "load_assistant_preferences",
    "save_assistant_preferences",
    "task_storage_error",
    "_today_seoul",
    "_read_assistant_activity",
    "_record_assistant_activity",
    "assistant_briefing",
    "_assistant_event_stream",
    "proactive_notifications",
    "proactive_slot",
    "quiet_hours_active",
    "recent_commits",
    "system_prompt",
    "_is_up",
    "_journal_hint",
    "_start_service",
    "_trading_risk",
    "_trading_notifications",
    "_trading_fill_notifications",
    "_trading_hourly_notifications",
    "work_digest",
]
