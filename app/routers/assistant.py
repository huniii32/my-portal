"""Assistant (gombi secretary): briefing, preferences, actions, activity, SSE."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import assistant as _assistant_mod
from app.assistant import _assistant_event_stream
from app.config import DATA_LOCK
from app.models import (
    AssistantAction,
    AssistantPreferences,
    AssistantPreferencesPatch,
    TaskItem,
)
from app.storage import (
    StorageError,
    _read_assistant_activity,
    _record_assistant_activity,
    load_assistant_preferences,
    load_tasks,
    save_assistant_preferences,
    save_tasks,
    task_storage_error,
)
from gombi import desktop_pet as _gombi_pet

router = APIRouter()


@router.get("/api/assistant/briefing")
def read_assistant_briefing() -> dict:
    try:
        return _assistant_mod.assistant_briefing()
    except StorageError as error:
        raise HTTPException(
            status_code=503,
            detail="업무 비서가 저장소를 읽지 못했습니다. 원본 파일은 변경하지 않았습니다.",
        ) from error


@router.get("/api/assistant/preferences")
def read_assistant_preferences() -> AssistantPreferences:
    with DATA_LOCK:
        return load_assistant_preferences()


@router.patch("/api/assistant/preferences")
def update_assistant_preferences(patch: AssistantPreferencesPatch) -> AssistantPreferences:
    with DATA_LOCK:
        current = load_assistant_preferences()
        values = current.model_dump()
        values.update({key: value for key, value in patch.model_dump().items() if value is not None})
        updated = AssistantPreferences.model_validate(values)
        try:
            save_assistant_preferences(updated)
        except OSError as error:
            raise HTTPException(status_code=503, detail="비서 설정을 저장하지 못했습니다.") from error
        return updated


@router.get("/api/assistant/events")
async def assistant_events(request: Request) -> StreamingResponse:
    try:
        initial = _assistant_mod.assistant_briefing()
    except StorageError as error:
        raise HTTPException(
            status_code=503,
            detail="업무 비서가 저장소를 읽지 못했습니다. 원본 파일은 변경하지 않았습니다.",
        ) from error
    return StreamingResponse(
        _assistant_event_stream(request, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/assistant/activity")
def read_assistant_activity() -> list[dict]:
    with DATA_LOCK:
        return _read_assistant_activity()


@router.post("/api/gombi/show")
def show_gombi_pet() -> dict:
    """숨긴 데스크톱 곰비 펫을 다시 보여달라고 요청한다. 입력 없이 신호 파일만 남긴다."""
    if not _gombi_pet.request_pet_show():
        raise HTTPException(status_code=503, detail="곰비 펫에 표시 요청을 전달하지 못했습니다.")
    return {"status": "requested"}


@router.post("/api/assistant/actions")
def execute_assistant_action(action: AssistantAction) -> TaskItem:
    with DATA_LOCK:
        try:
            tasks = load_tasks()
            target: TaskItem
            if action.action == "create_task":
                if len(tasks) >= 1000:
                    raise HTTPException(status_code=409, detail="할 일은 최대 1,000개까지 저장할 수 있습니다.")
                target = TaskItem(id=uuid4().hex, title=action.title or "", date=action.date or "", done=False)
                tasks.append(target)
            else:
                target = next((task for task in tasks if task.id == action.task_id), None)
                if target is None:
                    raise HTTPException(status_code=409, detail="제안된 할 일이 이미 변경되었거나 없습니다.")
                expected = action.expected
                if expected is None or target.id != expected.id or target.title != expected.title or target.date != expected.date or target.done != expected.done:
                    raise HTTPException(status_code=409, detail="제안된 할 일이 이미 변경되었거나 없습니다.")
                if action.action == "complete_task":
                    target.done = True
                else:
                    target.date = action.date or target.date
            save_tasks(tasks)
        except HTTPException:
            try:
                _record_assistant_activity(action.action, "failure", date_value=action.date)
            except OSError:
                pass
            raise
        except StorageError as error:
            try:
                _record_assistant_activity(action.action, "failure", date_value=action.date)
            except OSError:
                pass
            raise task_storage_error() from error
        try:
            _record_assistant_activity(action.action, "success", target)
        except OSError:
            pass
        return target
