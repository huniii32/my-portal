"""Portal-wide constants: paths, timezone, registries, tunables.

One-process JSON store assumption lives here (DATA_LOCK) so every
router/service shares the same lock object.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
DATA_DIR = ROOT / "data"
GOALS_PATH = DATA_DIR / "goals.json"
TASKS_PATH = DATA_DIR / "tasks.json"
ASSISTANT_PREFERENCES_PATH = DATA_DIR / "assistant_preferences.json"
ASSISTANT_ACTIVITY_PATH = DATA_DIR / "assistant_activity.jsonl"
SEOUL = ZoneInfo("Asia/Seoul")
# ponytail: one process lock; use a shared database or file lock if uvicorn gains workers.
DATA_LOCK = threading.RLock()

VLLM_BASE_URL = os.getenv("PORTAL_VLLM_BASE_URL", "http://192.168.0.85:8000/v1")
VLLM_MODEL = os.getenv("PORTAL_VLLM_MODEL", "Qwen3.8-27B")

# 새 앱을 늘리려면 여기에 직접 적어야 한다. 런타임에 늘어나는 경로는 없다.
# group: "work"(회사) | "personal"(개인). /api/status는 관리형 앱만 다룬다.
APPS: dict[str, dict] = {
    "ipis": {
        "name": "IPIS CMT Web",
        "port": 5173,
        "health": "http://127.0.0.1:8000/api/health",
        "unit": "ipis-cmt-web.service",
        "command": ["systemctl", "--user", "start", "ipis-cmt-web.service"],
        "cwd": WORKSPACE / "IPIS_CMT_WEB",
        "group": "work",
    },
    "trading": {
        "name": "Trading Agent World",
        "port": 5174,
        "health": "http://127.0.0.1:8510/health",
        "unit": "trading-agent-dashboard.service",
        "command": ["systemctl", "--user", "start", "trading-agent-dashboard.service"],
        "cwd": WORKSPACE / "trading_agent_world",
        "group": "personal",
    },
}

# 외부 링크: health/launch 없이 새 탭으로 여는 바로가기. /api/launch 대상이 아니다.
LINKS: dict[str, dict] = {
    "rivals": {
        "name": "Rivals Deck",
        "purpose": "9이닝스 라이벌즈 덱관리",
        "url": "https://huniii32.github.io/mlb-rivals-deck/",
        "group": "personal",
    },
}

APP_GROUPS: list[dict] = [
    {"id": "work", "title": "회사"},
    {"id": "personal", "title": "개인"},
]

SERVICE_START_TIMEOUT = 30

# 트레이딩 감시(risk_watch.py 5분 cron)가 쓰는 위험 상태 파일을 읽기만 한다.
TRADING_RISK_STATUS = WORKSPACE / "trading_agent_world" / "data" / "memory" / "risk_status.json"
LIVE_ORDERS_PATH = WORKSPACE / "trading_agent_world" / "data" / "memory" / "live_orders.jsonl"
SYMBOL_NAMES_PATH = WORKSPACE / "trading_agent_world" / "data" / "memory" / "symbol_names.json"
TRADING_SYMBOL_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "035720": "카카오",
    "005380": "현대차",
    "069500": "KODEX 200",
    "229200": "KODEX 코스닥150",
    "360750": "TIGER 미국S&P500",
}

# 트레이딩 프로젝트가 매일 갱신하는 공휴일 캐시를 읽기만 한다.
TRADING_HOLIDAYS_CACHE = WORKSPACE / "trading_agent_world" / "data" / "memory" / "holidays_cache.json"

BRIEFING_POLL_SECONDS = 1.0
BRIEFING_HEARTBEAT_SECONDS = 15.0

# Web root: templates/*.html + static/* live under web/. During the
# migration both the new web/ paths and the legacy root paths are served.
WEB_DIR = ROOT / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
