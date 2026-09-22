"""JSON file storage: goals / tasks / assistant preferences / activity."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app import config as _config
from app.config import DATA_LOCK, SEOUL
from app.models import AssistantPreferences, Goals, TaskItem


class StorageError(Exception):
    pass


def _valid_clock(value: str) -> str:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("시간은 HH:MM 형식이어야 합니다.")
    try:
        hour, minute = (int(part) for part in value.split(":"))
    except ValueError as error:
        raise ValueError("시간은 HH:MM 형식이어야 합니다.") from error
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("시간은 HH:MM 형식이어야 합니다.")
    return f"{hour:02d}:{minute:02d}"


def _goal_identity(item) -> dict:
    """낙관적 동시성 비교용: 연결 키(id)는 제외하고業務 내용만 비교한다."""
    return item.model_dump(exclude={"id"})


def _goal_ids(goals: Goals) -> set[str]:
    return {item.id for item in (*goals.week.items, *goals.day.items)}


def load_goals() -> Goals:
    """읽기는 절대 예외를 던지지 않는다 — 목표 파일 하나 때문에 화면 전체가
    죽으면 안 된다. 손상된 파일은 .bak으로 옮겨 원본을 남긴다.
    id 없던旧 파일은 id를 부여해 저장(할 일 연결 키)한다."""
    try:
        raw = json.loads(_config.GOALS_PATH.read_text(encoding="utf-8"))
        goals = Goals.model_validate(raw)
    except FileNotFoundError:
        return Goals()
    except (json.JSONDecodeError, ValidationError, OSError):
        try:
            backup = _config.GOALS_PATH.with_name(_config.GOALS_PATH.name + ".bak")
            suffix = 1
            while backup.exists():
                backup = _config.GOALS_PATH.with_name(f"{_config.GOALS_PATH.name}.bak.{suffix}")
                suffix += 1
            _config.GOALS_PATH.replace(backup)
        except OSError:
            pass
        return Goals()
    if isinstance(raw, dict) and any(
        not isinstance(item, dict) or not item.get("id")
        for key in ("week", "day")
        for item in (raw.get(key, {}) or {}).get("items", []) or []
    ):
        try:
            save_goals(goals)
        except OSError:
            pass
    return goals


def save_goals(goals: Goals) -> None:
    temporary = _config.GOALS_PATH.with_name(_config.GOALS_PATH.name + ".tmp")
    try:
        temporary.write_text(goals.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(_config.GOALS_PATH)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_tasks() -> list[TaskItem]:
    try:
        raw = json.loads(_config.TASKS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("tasks must be a list")
        return [TaskItem.model_validate(item) for item in raw]
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, ValidationError, OSError, UnicodeError, ValueError) as error:
        raise StorageError from error


def save_tasks(tasks: list[TaskItem]) -> None:
    temporary = _config.TASKS_PATH.with_name(_config.TASKS_PATH.name + ".tmp")
    try:
        temporary.write_text(json.dumps([task.model_dump() for task in tasks], ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(_config.TASKS_PATH)
    except OSError as error:
        raise StorageError from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_assistant_preferences() -> AssistantPreferences:
    try:
        return AssistantPreferences.model_validate(json.loads(_config.ASSISTANT_PREFERENCES_PATH.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, ValidationError, OSError, UnicodeError, TypeError):
        return AssistantPreferences()


def save_assistant_preferences(preferences: AssistantPreferences) -> None:
    _atomic_write_text(_config.ASSISTANT_PREFERENCES_PATH, preferences.model_dump_json(indent=2))


def task_storage_error() -> HTTPException:
    return HTTPException(status_code=503, detail="할 일 저장소를 읽거나 저장하지 못했습니다. 원본 파일은 보존되었습니다.")


def _today_seoul() -> date:
    return datetime.now(SEOUL).date()


def _read_assistant_activity() -> list[dict]:
    entries: list[dict] = []
    try:
        lines = _config.ASSISTANT_ACTIVITY_PATH.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return entries
    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(value, dict) or value.get("action") not in {"create_task", "complete_task", "reschedule_task"} or value.get("status") not in {"success", "failure"}:
            continue
        entry = {
            "timestamp": str(value.get("timestamp", ""))[:40],
            "action": value["action"],
            "status": value["status"],
        }
        if isinstance(value.get("title"), str):
            entry["title"] = value["title"].strip()[:200]
        if isinstance(value.get("date"), str):
            try:
                entry["date"] = TaskItem.valid_date(value["date"])
            except ValueError:
                pass
        entries.append(entry)
    return entries[-20:]


def _record_assistant_activity(action: str, status: str, task: TaskItem | None = None, date_value: str | None = None) -> None:
    entry = {
        "timestamp": datetime.now(SEOUL).isoformat(timespec="seconds"),
        "action": action,
        "status": status,
    }
    if task is not None:
        entry.update({"title": task.title[:200], "date": task.date})
    elif date_value is not None:
        entry["date"] = date_value
    entries = _read_assistant_activity()
    entries.append(entry)
    _atomic_write_text(
        _config.ASSISTANT_ACTIVITY_PATH,
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in entries[-20:]),
    )


def _read_goals_for_briefing() -> Goals:
    """Read-only goal loading: the briefing must never hide or repair bad data."""
    try:
        return Goals.model_validate(json.loads(_config.GOALS_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return Goals()
    except (json.JSONDecodeError, ValidationError, OSError, UnicodeError) as error:
        raise StorageError from error
