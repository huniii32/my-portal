"""Pages + static assets. No directory mount — allowlisted files only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import ROOT, STATIC_DIR, TEMPLATES_DIR

router = APIRouter()


def _page(name: str) -> FileResponse:
    # StaticFiles로 디렉터리를 mount하지 않는다 — 다른 저장소의 .env가 노출된다.
    candidate = TEMPLATES_DIR / name
    legacy = ROOT / name
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(legacy)


@router.get("/")
def index() -> FileResponse:
    return _page("index.html")


@router.get("/apps")
def apps_page() -> FileResponse:
    return _page("apps.html")


@router.get("/tasks")
def tasks_page() -> FileResponse:
    return _page("tasks.html")


@router.get("/goals")
def goals_page() -> FileResponse:
    return _page("goals.html")


@router.get("/organize")
def organize_page() -> FileResponse:
    return _page("organize.html")


def _static_candidates(asset_path: str) -> list:
    """New web/static layout first, legacy root layout as fallback."""
    legacy_map = {
        "calendar-favicon.svg": ROOT / "assets" / "calendar-favicon.svg",
        "portal.css": ROOT / "portal.css",
        "portal.js": ROOT / "portal.js",
        "assistant.css": ROOT / "assistant.css",
        "assistant.js": ROOT / "assistant.js",
        "mascot.js": ROOT / "mascot.js",
    }
    if asset_path == "calendar-favicon.svg":
        # assets/ 아래에서 함께 관리된다(mascot/vendor와 동일 레이아웃).
        return [STATIC_DIR / "assets" / asset_path, legacy_map[asset_path]]
    if asset_path in legacy_map:
        return [STATIC_DIR / asset_path, legacy_map[asset_path]]
    # mascot/* and vendor/* live under assets/ in both layouts.
    return [STATIC_DIR / "assets" / asset_path, ROOT / "assets" / asset_path]


STATIC_ALLOWLIST = (
    {"calendar-favicon.svg", "portal.css", "portal.js", "assistant.css", "assistant.js", "mascot.js"}
    | {f"mascot/old-manggom-complete.png"}
    | {f"mascot/reference-{n}.png" for n in range(1, 5)}
    | {f"mascot/pixel-{n}.png" for n in range(1, 7)}
    | {"vendor/three.module.js", "vendor/three.core.js", "vendor/three-LICENSE"}
)


@router.get("/assets/{asset_path:path}")
def static_asset(asset_path: str) -> FileResponse:
    """Serve only the secretary's named local assets; never expose portal files."""
    if asset_path not in STATIC_ALLOWLIST:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    for candidate in _static_candidates(asset_path):
        if candidate.is_file():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
