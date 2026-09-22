"""Managed apps: status / catalog / launch."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from app.config import APPS, APP_GROUPS, LINKS, SERVICE_START_TIMEOUT

router = APIRouter()


async def _is_up(client: httpx.AsyncClient, key: str) -> bool:
    try:
        response = await client.get(APPS[key]["health"], timeout=2)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _journal_hint(entry: dict) -> str:
    return f"journalctl --user -u {entry['unit']} -n 100 -f"


async def _start_service(entry: dict) -> bool:
    """Start one allowlisted user unit without handing input to a shell."""
    process = None
    try:
        process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *entry["command"],
                cwd=entry["cwd"],
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            ),
            timeout=SERVICE_START_TIMEOUT,
        )
        returncode = await asyncio.wait_for(
            process.wait(), timeout=SERVICE_START_TIMEOUT
        )
        return returncode == 0
    except (OSError, asyncio.TimeoutError):
        if process is not None and process.returncode is None:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except (OSError, asyncio.TimeoutError):
                pass
        return False


@router.get("/api/status")
async def status() -> dict:
    async with httpx.AsyncClient() as client:
        flags = await asyncio.gather(*(_is_up(client, key) for key in APPS))
    return {
        key: {"name": entry["name"], "port": entry["port"], "up": up}
        for (key, entry), up in zip(APPS.items(), flags)
    }


@router.get("/api/apps")
def app_catalog() -> dict:
    """바로가기 목록: 관리형 앱 + 외부 링크를 그룹과 함께 돌려준다."""
    return {
        "groups": APP_GROUPS,
        "apps": [
            {"key": key, "name": entry["name"], "group": entry["group"], "kind": "managed"}
            for key, entry in APPS.items()
        ]
        + [
            {"key": key, "name": entry["name"], "group": entry["group"], "kind": "link", "url": entry["url"]}
            for key, entry in LINKS.items()
        ],
    }


@router.post("/api/launch/{key}")
async def launch(key: str) -> dict:
    entry = APPS.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="알 수 없는 앱입니다.")

    async with httpx.AsyncClient() as client:
        if await _is_up(client, key):
            return {"status": "already-up", "log": "", "port": entry["port"]}

    if not await _start_service(entry):
        raise HTTPException(
            status_code=503,
            detail=f"앱을 시작하지 못했습니다. 로그 확인: {_journal_hint(entry)}",
        )
    return {"status": "launched", "log": _journal_hint(entry), "port": entry["port"]}
