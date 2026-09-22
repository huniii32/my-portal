"""Holidays: trading cache first, hardcoded fallback second. Read-only."""

from __future__ import annotations

import json

from app import config as _config

HOLIDAYS_FALLBACK: frozenset[str] = frozenset(
    {
        "2026-01-01",
        "2026-02-16",
        "2026-02-17",
        "2026-02-18",
        "2026-03-02",
        "2026-05-01",
        "2026-05-05",
        "2026-05-25",
        "2026-06-03",
        "2026-07-17",
        "2026-08-17",
        "2026-09-24",
        "2026-09-25",
        "2026-10-05",
        "2026-10-09",
        "2026-12-25",
    }
)

HOLIDAY_NAMES: dict[str, str] = {
    "2026-01-01": "신정",
    "2026-02-16": "설날 연휴",
    "2026-02-17": "설날",
    "2026-02-18": "설날 연휴",
    "2026-03-01": "삼일절",
    "2026-03-02": "대체공휴일",
    "2026-05-01": "노동절",
    "2026-05-05": "어린이날",
    "2026-05-24": "부처님오신날",
    "2026-05-25": "대체공휴일",
    "2026-06-03": "지방선거",
    "2026-06-06": "현충일",
    "2026-07-17": "제헌절",
    "2026-08-15": "광복절",
    "2026-08-17": "대체공휴일",
    "2026-09-24": "추석 연휴",
    "2026-09-25": "추석",
    "2026-09-26": "추석 연휴",
    "2026-10-03": "개천절",
    "2026-10-05": "대체공휴일",
    "2026-10-09": "한글날",
    "2026-12-25": "성탄절",
    "2027-01-01": "신정",
    "2027-02-06": "설날 연휴",
    "2027-02-07": "설날 연휴",
    "2027-02-08": "설날",
    "2027-02-09": "설날 연휴",
    "2027-03-01": "삼일절",
    "2027-05-01": "노동절",
    "2027-05-03": "대체공휴일",
    "2027-05-05": "어린이날",
    "2027-05-13": "부처님오신날",
    "2027-06-06": "현충일",
    "2027-07-17": "제헌절",
    "2027-07-19": "대체공휴일",
    "2027-08-15": "광복절",
    "2027-08-16": "대체공휴일",
    "2027-09-14": "추석 연휴",
    "2027-09-15": "추석",
    "2027-09-16": "추석 연휴",
    "2027-10-03": "개천절",
    "2027-10-04": "대체공휴일",
    "2027-10-09": "한글날",
    "2027-10-11": "대체공휴일",
    "2027-12-25": "성탄절",
    "2027-12-27": "대체공휴일",
}


def _holiday_days_for_year(year: int) -> tuple[list[str], str]:
    """트레이딩 캐시 → 하드코딩 폴백 순. 읽기는 절대 예외를 던지지 않는다."""
    prefix = f"{year:04d}-"
    try:
        raw = json.loads(_config.TRADING_HOLIDAYS_CACHE.read_text(encoding="utf-8"))
        entry = raw.get("years", {}).get(str(year))
        days = entry.get("days", []) if isinstance(entry, dict) else []
        cleaned = sorted(
            {
                day
                for day in days
                if isinstance(day, str)
                and len(day) == 10
                and day.startswith(prefix)
                and day[4] == "-"
                and day[7] == "-"
            }
        )
        if cleaned:
            return cleaned, "api-cache"
    except (OSError, ValueError, AttributeError):
        pass
    return sorted(day for day in HOLIDAYS_FALLBACK if day.startswith(prefix)), "fallback"
