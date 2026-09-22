"""Work digest endpoints: read + refresh (today only, generation-locked)."""

from __future__ import annotations

import asyncio
from datetime import date

import work_digest
from fastapi import APIRouter, HTTPException, Request

from app import storage as _storage

router = APIRouter()

_DIGEST_REFRESH_LOCK = asyncio.Lock()


def _digest_day_or_422(selected: str | None) -> date:
    try:
        return work_digest.parse_day(selected)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="날짜는 YYYY-MM-DD 형식이어야 합니다.") from error


@router.get("/api/work-digest")
def read_work_digest(date: str | None = None) -> dict:
    selected = _digest_day_or_422(date)
    digest = work_digest.load_digest(selected)
    if digest is None:
        raise HTTPException(status_code=404, detail="해당 날짜의 업무 회고가 아직 없습니다.")
    return digest


@router.post("/api/work-digest/refresh")
async def refresh_work_digest(request: Request, date: str | None = None) -> dict:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="JSON 요청만 허용됩니다.")
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        if origin.rstrip("/").split("://")[-1] != host:
            raise HTTPException(status_code=403, detail="허용되지 않은 요청 출처입니다.")
    selected = _digest_day_or_422(date)
    if selected != _storage._today_seoul():
        raise HTTPException(status_code=422, detail="업무 회고 새로고침은 서울 오늘 날짜만 지원합니다.")
    if _DIGEST_REFRESH_LOCK.locked():
        raise HTTPException(status_code=409, detail="업무 회고를 이미 정리하고 있습니다.")
    async with _DIGEST_REFRESH_LOCK:
        try:
            return await asyncio.to_thread(work_digest.generate_digest, selected, force=True)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="업무 회고를 생성하지 못했습니다.") from error
