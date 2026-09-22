"""Holidays endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import storage as _storage
from app.holidays import HOLIDAY_NAMES, _holiday_days_for_year

router = APIRouter()


@router.get("/api/holidays")
def read_holidays(year: int | None = None) -> dict:
    selected = year if year is not None else _storage._today_seoul().year
    if selected < 1900 or selected > 2100:
        raise HTTPException(status_code=422, detail="연도는 1900~2100 사이여야 합니다.")
    days, source = _holiday_days_for_year(selected)
    return {
        "year": selected,
        "days": days,
        "names": {day: HOLIDAY_NAMES[day] for day in days if day in HOLIDAY_NAMES},
        "source": source,
    }
