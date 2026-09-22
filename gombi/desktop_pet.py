"""Native GTK3 Gombi pet for the local suhun portal."""

from __future__ import annotations

import base64
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Iterable, Iterator
from typing import Any, Callable

try:  # Keep pure helpers importable on test machines without a display.
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
except (ImportError, ValueError):  # pragma: no cover - exercised by deployment
    Gdk = GdkPixbuf = GLib = Gtk = None


LOGGER = logging.getLogger("suhun.gombi")
PORTAL_URL = os.environ.get("GOMBI_PORTAL_URL", "http://127.0.0.1:8080").rstrip("/")
EVENTS_URL = "/api/assistant/events"
def _portal_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _mascot_asset() -> Path:
    root = _portal_root()
    for candidate in (
        root / "web" / "static" / "assets" / "mascot" / "pixel-1.png",
        root / "assets" / "mascot" / "pixel-1.png",  # legacy flat layout
    ):
        if candidate.is_file():
            return candidate
    return root / "web" / "static" / "assets" / "mascot" / "pixel-1.png"


ASSET_PATH = _mascot_asset()
NOTIFY_SEND = "/usr/bin/notify-send"
RECONNECT_SECONDS = 2.0
STREAM_TIMEOUT_SECONDS = 45.0
WINDOW_SIZE = (180, 190)
MAX_NOTIFICATION_DETAIL_CHARS = 20_000
LEGACY_HOURLY_DETAIL_FALLBACK = "이전 형식의 정시 보고라 원문 대신 요약을 표시합니다. 다음 보고부터 읽기 쉬운 상세 항목이 제공됩니다."
TRADING_URL = os.environ.get("GOMBI_TRADING_URL", "http://127.0.0.1:8510").rstrip("/")
TRADING_USERNAME = os.environ.get("GOMBI_TRADING_USERNAME", "trader")
TRADING_PASSWORD_FILE = Path(
    os.environ.get(
        "GOMBI_TRADING_PASSWORD_FILE",
        str(Path(__file__).resolve().parents[2] / "trading_agent_world" / "data" / "memory" / "dashboard_password"),
    )
)
MAX_CHAT_HISTORY_ITEMS = 100
MAX_CHAT_MESSAGE_CHARS = 20_000
MAX_CHAT_RESPONSE_BYTES = 1_500_000
CHAT_HISTORY_TIMEOUT = 15.0
CHAT_SEND_TIMEOUT = 130.0


class TradingChatError(RuntimeError):
    """A bounded, user-safe local Trading chat request error."""


def assert_loopback_target(url: str) -> urllib.parse.SplitResult:
    """Validate a full API target before accepting a response from it."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except (AttributeError, TypeError, ValueError) as error:
        raise TradingChatError("Trading 주소가 올바르지 않습니다.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise TradingChatError("Trading 주소는 로컬호스트만 사용할 수 있습니다.")
    try:
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except ValueError as error:
        raise TradingChatError("Trading 주소의 포트가 올바르지 않습니다.") from error
    return parsed


def validate_loopback_url(url: str) -> str:
    """Accept only an origin URL targeting an explicit loopback hostname."""
    parsed = assert_loopback_target(url)
    if parsed.path not in {"", "/"} or parsed.query:
        raise TradingChatError("Trading 주소는 기본 경로만 사용할 수 있습니다.")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def trading_password_path(environ: Any | None = None) -> Path:
    values = os.environ if environ is None else environ
    configured = values.get("GOMBI_TRADING_PASSWORD_FILE")
    return Path(configured) if configured else TRADING_PASSWORD_FILE


def read_trading_password(path: Path) -> str:
    fd: int | None = None
    try:
        path_info = path.lstat()
        if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(path_info.st_mode):
            raise TradingChatError("Trading 비밀번호 경로는 일반 파일이어야 합니다.")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        file_info = os.fstat(fd)
        if (
            not stat.S_ISREG(file_info.st_mode)
            or file_info.st_uid != os.getuid()
            or file_info.st_mode & 0o077
            or file_info.st_dev != path_info.st_dev
            or file_info.st_ino != path_info.st_ino
            or file_info.st_size > 4097
        ):
            raise TradingChatError("Trading 비밀번호 파일 권한을 확인해 주세요.")
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = None
            raw_password = handle.read(4097)
            if os.fstat(handle.fileno()).st_size > 4097:
                raise TradingChatError("Trading 비밀번호 파일이 너무 깁니다.")
        password = raw_password.decode("utf-8").rstrip("\r\n")
    except TradingChatError:
        raise
    except (OSError, UnicodeError) as error:
        raise TradingChatError("Trading 비밀번호 파일을 읽을 수 없습니다.") from error
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    if not password or len(password) > 4096:
        raise TradingChatError("Trading 비밀번호가 비어 있거나 너무 깁니다.")
    return password


def _basic_auth_header(username: str, password: str) -> str:
    if not username or len(username) > 256 or ":" in username or "\n" in username or "\r" in username:
        raise TradingChatError("Trading 사용자 이름이 올바르지 않습니다.")
    if "\n" in password or "\r" in password:
        raise TradingChatError("Trading 비밀번호 형식이 올바르지 않습니다.")
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


class _LoopbackRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block redirects before urllib can forward credentials off loopback."""

    handler_order = urllib.request.HTTPRedirectHandler.handler_order - 1

    def redirect_request(self, request: Any, response: Any, code: int, message: str, headers: Any, new_url: str) -> Any:
        raise TradingChatError("Trading 서버가 리디렉션을 반환해 요청을 중단했습니다.")


def _build_trading_opener() -> Callable[..., Any]:
    """Build a loopback client that ignores ambient proxy configuration."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _LoopbackRedirectHandler(),
    )
    return opener.open


def _read_chat_response(response: Any) -> bytes:
    raw = response.read(MAX_CHAT_RESPONSE_BYTES + 1)
    if not isinstance(raw, bytes) or len(raw) > MAX_CHAT_RESPONSE_BYTES:
        raise TradingChatError("Trading 응답이 너무 큽니다.")
    return raw


def trading_chat_request(
    base_url: str,
    username: str,
    password: str,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
    timeout: float = 15.0,
) -> Any:
    """Send a bounded authenticated request to the loopback Trading API."""
    base = validate_loopback_url(base_url)
    if endpoint not in {"/api/office-chat/history", "/api/assistant-chat"}:
        raise TradingChatError("Trading 대화 경로가 올바르지 않습니다.")
    method = method.upper()
    if (endpoint, method) not in {
        ("/api/office-chat/history", "GET"),
        ("/api/assistant-chat", "POST"),
    }:
        raise TradingChatError("Trading 대화 요청 방식이 올바르지 않습니다.")
    url = f"{base}{endpoint}"
    data: bytes | None = None
    headers = {"Authorization": _basic_auth_header(username, password), "Accept": "application/json"}
    if method == "GET":
        url += "?" + urllib.parse.urlencode({"session_id": "chat", "limit": MAX_CHAT_HISTORY_ITEMS})
    else:
        if not isinstance(payload, dict) or payload.get("session_id") != "chat":
            raise TradingChatError("Trading 대화 요청 내용이 올바르지 않습니다.")
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 8000:
            raise TradingChatError("메시지는 1~8,000자여야 합니다.")
        data = json.dumps({"session_id": "chat", "message": message}, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    request_opener = opener or _build_trading_opener()
    try:
        with request_opener(request, timeout=timeout) as response:
            response_url = response.geturl() if callable(getattr(response, "geturl", None)) else request.full_url
            assert_loopback_target(response_url)
            status = response.getcode() if callable(getattr(response, "getcode", None)) else 200
            if status < 200 or status >= 300:
                raise TradingChatError("Trading 서버가 요청을 처리하지 못했습니다.")
            raw = _read_chat_response(response)
    except TradingChatError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as error:
        raise TradingChatError("Trading 서버에 연결할 수 없습니다.") from error
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise TradingChatError("Trading 응답 형식이 올바르지 않습니다.") from error


def validate_chat_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise TradingChatError("Trading 대화 기록 형식이 올바르지 않습니다.")
    messages: list[dict[str, str]] = []
    for item in value["items"][-MAX_CHAT_HISTORY_ITEMS:]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        messages.append({"role": role, "content": content[:MAX_CHAT_MESSAGE_CHARS]})
    return messages


def _trading_chat_config(environ: Any | None = None) -> tuple[str, str, str]:
    values = os.environ if environ is None else environ
    url = validate_loopback_url(values.get("GOMBI_TRADING_URL", TRADING_URL))
    username = values.get("GOMBI_TRADING_USERNAME", TRADING_USERNAME)
    password = read_trading_password(trading_password_path(values))
    return url, username, password


def fetch_trading_chat_history(
    environ: Any | None = None, opener: Callable[..., Any] | None = None
) -> list[dict[str, str]]:
    url, username, password = _trading_chat_config(environ)
    response = trading_chat_request(
        url, username, password, "GET", "/api/office-chat/history", opener=opener, timeout=CHAT_HISTORY_TIMEOUT
    )
    return validate_chat_history(response)


def send_trading_chat_message(
    message: str, environ: Any | None = None, opener: Callable[..., Any] | None = None
) -> str:
    url, username, password = _trading_chat_config(environ)
    response = trading_chat_request(
        url,
        username,
        password,
        "POST",
        "/api/assistant-chat",
        {"session_id": "chat", "message": message},
        opener=opener,
        timeout=CHAT_SEND_TIMEOUT,
    )
    if not isinstance(response, dict) or not isinstance(response.get("reply"), str):
        raise TradingChatError("Trading 답변 형식이 올바르지 않습니다.")
    reply = response["reply"].strip()
    if not reply:
        raise TradingChatError("Trading에서 빈 답변을 받았습니다.")
    return reply[:MAX_CHAT_MESSAGE_CHARS]


def position_path(environ: Any | None = None) -> Path:
    values = os.environ if environ is None else environ
    state_home = values.get("XDG_STATE_HOME")
    return Path(state_home) / "suhun-gombi" / "position.json" if state_home else Path.home() / ".local" / "state" / "suhun-gombi" / "position.json"


def proactive_seen_path(environ: Any | None = None) -> Path:
    values = os.environ if environ is None else environ
    state_home = values.get("XDG_STATE_HOME")
    return Path(state_home) / "suhun-gombi" / "proactive_seen.json" if state_home else Path.home() / ".local" / "state" / "suhun-gombi" / "proactive_seen.json"


def load_seen_proactive(path: Path | None = None) -> list[str]:
    try:
        raw = json.loads((path or proactive_seen_path()).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    known: set[str] = set()
    for value in raw:
        if isinstance(value, str) and value[:80] == value and value not in known:
            known.add(value)
            values.append(value)
    return values[-64:]


def save_seen_proactive(seen: Iterable[str], path: Path | None = None) -> bool:
    target = path or proactive_seen_path()
    values: list[str] = []
    known: set[str] = set()
    for value in seen:
        if isinstance(value, str) and value[:80] == value and value not in known:
            known.add(value)
            values.append(value)
    values = values[-64:]
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
        return True
    except OSError:
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def normalize_position(position: Any) -> tuple[int, int] | None:
    if isinstance(position, dict):
        values = (position.get("x"), position.get("y"))
    elif isinstance(position, (tuple, list)) and len(position) == 2:
        values = (position[0], position[1])
    else:
        return None
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            normalized.append(value)
        elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
            normalized.append(int(value))
        else:
            return None
    if len(normalized) != 2:
        return None
    return normalized[0], normalized[1]


def load_position(path: Path | None = None) -> tuple[int, int] | None:
    try:
        raw = json.loads((path or position_path()).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    try:
        return normalize_position(raw)
    except (OverflowError, TypeError, ValueError):
        return None


def save_position(position: Any, path: Path | None = None) -> bool:
    normalized = normalize_position(position)
    if normalized is None:
        return False
    target = path or position_path()
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"x": normalized[0], "y": normalized[1]}), encoding="utf-8")
        temporary.replace(target)
        return True
    except OSError:
        return False
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def clamp_position(position: Any, workarea: Any, window_size: tuple[int, int] = WINDOW_SIZE) -> tuple[int, int]:
    x, y = normalize_position(position) or (0, 0)
    min_x, min_y = int(workarea.x), int(workarea.y)
    max_x = max(min_x, min_x + int(workarea.width) - window_size[0])
    max_y = max(min_y, min_y + int(workarea.height) - window_size[1])
    return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))


def primary_pet_position() -> tuple[int, int]:
    """Place startup inside the primary monitor workarea when available."""
    try:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display is not None else None
        workarea = monitor.get_workarea() if monitor is not None else None
        if workarea is not None:
            return workarea.x + 90, workarea.y + 140
    except (AttributeError, TypeError, ValueError):
        pass
    return 40, 40


def roaming_enabled(environ: Any | None = None) -> bool:
    values = os.environ if environ is None else environ
    return values.get("GOMBI_ROAM") == "1" and values.get("GOMBI_REDUCED_MOTION") != "1"


def briefing_title(data: dict[str, Any]) -> str:
    trading = data.get("trading")
    return "트레이딩 알림" if isinstance(trading, dict) and trading.get("alert") is not None else "업무 비서 곰비"


def work_text(data: dict[str, Any]) -> str:
    def section(name: str) -> dict[str, Any]:
        value = data.get(name)
        return value if isinstance(value, dict) else {}

    overdue = section("overdue")
    pending = section("pending")
    goals = section("goals")
    parts: list[str] = []
    if overdue.get("count"):
        parts.append(f"지난 업무 {overdue['count']}개")
    if pending.get("count"):
        parts.append(f"오늘 할 일 {pending['count']}개")
    goal_count = sum(
        len(goals[period].get("items") or [])
        for period in ("week", "day")
        if isinstance(goals.get(period), dict)
    )
    if goal_count:
        parts.append(f"목표 {goal_count}개")
    if not parts:
        return "업무 목록이 바뀌었어요."
    return ", ".join(parts) + "가 있어요."


def notification_position(
    mascot_position: tuple[int, int],
    mascot_size: tuple[int, int],
    card_size: tuple[int, int],
    workarea: Any,
) -> tuple[int, int]:
    """Center a card above the mascot and keep it inside the monitor workarea."""
    area_x, area_y = int(workarea.x), int(workarea.y)
    area_width, area_height = int(workarea.width), int(workarea.height)
    mascot_x, mascot_y = mascot_position
    mascot_width, mascot_height = mascot_size
    card_width, card_height = card_size
    min_x = area_x + 8
    max_x = max(min_x, area_x + area_width - card_width - 8)
    min_y = area_y + 8
    max_y = max(min_y, area_y + area_height - card_height - 8)
    x = mascot_x + (mascot_width - card_width) // 2
    y = mascot_y - card_height - 8
    if y < min_y:
        y = mascot_y + mascot_height + 8
    return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))


def stacked_notification_positions(
    mascot_position: tuple[int, int],
    mascot_size: tuple[int, int],
    card_sizes: list[tuple[int, int]],
    workarea: Any,
    gap: int = 8,
) -> list[tuple[int, int]]:
    if not card_sizes:
        return []
    area_x, area_y = int(workarea.x), int(workarea.y)
    area_width, area_height = int(workarea.width), int(workarea.height)
    mascot_x, mascot_y = mascot_position
    mascot_width, mascot_height = mascot_size
    total_height = sum(height for _width, height in card_sizes) + gap * (len(card_sizes) - 1)
    min_y = area_y + 8
    max_y = max(min_y, area_y + area_height - total_height - 8)
    y = mascot_y - total_height - 8
    if y < min_y:
        y = mascot_y + mascot_height + 8
    y = max(min_y, min(max_y, y))
    positions = []
    for width, height in card_sizes:
        min_x = area_x + 8
        max_x = max(min_x, area_x + area_width - width - 8)
        x = mascot_x + (mascot_width - width) // 2
        positions.append((max(min_x, min(max_x, x)), y))
        y += height + gap
    return positions


def portal_control_position(
    mascot_position: tuple[int, int],
    mascot_size: tuple[int, int],
    control_size: tuple[int, int],
    workarea: Any,
    gap: int = 8,
) -> tuple[int, int]:
    """Place the 업무 관리 pill below the mascot, falling back above the monitor edge."""
    area_x, area_y = int(workarea.x), int(workarea.y)
    area_width, area_height = int(workarea.width), int(workarea.height)
    mascot_x, mascot_y = mascot_position
    mascot_width, mascot_height = mascot_size
    control_width, control_height = control_size
    min_x, min_y = area_x + 8, area_y + 8
    max_x = max(min_x, area_x + area_width - control_width - 8)
    max_y = max(min_y, area_y + area_height - control_height - 8)
    x = mascot_x + (mascot_width - control_width) // 2
    y = mascot_y + mascot_height + gap
    if y > max_y:
        y = mascot_y - control_height - gap
    return max(min_x, min(max_x, x)), max(min_y, min(max_y, y))


def briefing_key(data: dict[str, Any]) -> str:
    """Stable key for the fields that can change the displayed notification."""
    trading = data.get("trading")
    displayed = {
        "source_date": data.get("source_date"),
        "pending": data.get("pending"),
        "overdue": data.get("overdue"),
        "goals": data.get("goals"),
        "trading": {"alert": trading.get("alert")} if isinstance(trading, dict) else {"alert": None},
    }
    return json.dumps(displayed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def briefing_text(data: dict[str, Any]) -> str:
    """Build concise Korean text from the bounded server briefing."""
    def section(name: str) -> dict[str, Any]:
        value = data.get(name)
        return value if isinstance(value, dict) else {}

    overdue = section("overdue")
    pending = section("pending")
    goals = section("goals")
    parts: list[str] = []
    overdue_count = int(overdue.get("count") or 0)
    pending_count = int(pending.get("count") or 0)
    goal_count = sum(
        len(goals[period].get("items") or [])
        for period in ("week", "day")
        if isinstance(goals.get(period), dict)
    )
    if overdue_count:
        parts.append(f"미완료 지난 업무 {overdue_count}개")
    if pending_count:
        parts.append(f"오늘 할 일 {pending_count}개")
    if goal_count:
        parts.append(f"목표 {goal_count}개")
    trading = data.get("trading")
    alert = trading.get("alert") if isinstance(trading, dict) else None
    if isinstance(alert, dict):
        alert_text = str(alert.get("message") or alert.get("title") or "").strip()
        if alert_text:
            parts.append(f"주식 알림: {alert_text[:120]}")
    if not parts:
        return "오늘 미완료 할 일이 없어요."
    first = (overdue.get("items") or [])[:1] or (pending.get("items") or [])[:1]
    title = str(first[0].get("title", "")).strip() if first and isinstance(first[0], dict) else ""
    if title:
        title = f" 먼저 확인할 일: {title[:45]}{'…' if len(title) > 45 else ''}"
    return f"{', '.join(parts)}예요.{title}"


def iter_sse_events(lines: Iterable[str | bytes]) -> Iterator[tuple[str, str]]:
    """Parse SSE event/data lines, ignoring heartbeat comments."""
    event_name = "message"
    data_lines: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value or "message"
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield event_name, "\n".join(data_lines)


def stream_briefings(
    url: str,
    stop_event: threading.Event,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = STREAM_TIMEOUT_SECONDS,
    reconnect_seconds: float = RECONNECT_SECONDS,
) -> Iterator[dict[str, Any]]:
    """Yield briefing events and reconnect until stopped or the caller exits."""
    open_url = opener or urllib.request.urlopen
    while not stop_event.is_set():
        try:
            with open_url(url, timeout=timeout) as response:
                for event, payload in iter_sse_events(response):
                    if stop_event.is_set():
                        return
                    if event != "briefing":
                        continue
                    try:
                        value = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        yield value
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as error:
            LOGGER.debug("portal SSE unavailable: %s", type(error).__name__)
        if stop_event.wait(reconnect_seconds):
            return


def notify_briefing(text: str) -> None:
    """Show one local desktop notification without invoking a shell."""
    if not shutil.which(NOTIFY_SEND):
        return
    try:
        subprocess.run(
            [NOTIFY_SEND, "곰비", text],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


class BriefingListener(threading.Thread):
    def __init__(self, url: str, on_change: Callable[[dict[str, Any]], None], seen_path: Path | None = None):
        super().__init__(name="gombi-briefing", daemon=True)
        self.url = url
        self.on_change = on_change
        self.stop_event = threading.Event()
        self.seen_path = seen_path or proactive_seen_path()
        self.seen_proactive = load_seen_proactive(self.seen_path)
        self.seen_proactive_set = set(self.seen_proactive)

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        previous = None
        for data in stream_briefings(self.url, self.stop_event):
            if previous is None:
                previous = data
                changed = False
                for notice in proactive_notices(data):
                    notice_id = notice.get("id")
                    if notice_id and notice_id not in self.seen_proactive_set:
                        self.on_change(notice)
                        self.seen_proactive = (self.seen_proactive + [notice_id])[-64:]
                        self.seen_proactive_set = set(self.seen_proactive)
                        changed = True
                if changed:
                    save_seen_proactive(self.seen_proactive, self.seen_path)
                continue
            for notice in briefing_notices(previous, data):
                notice_id = notice.get("id")
                if notice.get("type") == "proactive":
                    if not notice_id or notice_id in self.seen_proactive_set:
                        continue
                    self.seen_proactive = (self.seen_proactive + [notice_id])[-64:]
                    self.seen_proactive_set = set(self.seen_proactive)
                    save_seen_proactive(self.seen_proactive, self.seen_path)
                self.on_change(notice)
            previous = data


def _notification_ids(data: dict[str, Any], category: str) -> list[str]:
    notifications = data.get("notifications")
    values = notifications.get(category, []) if isinstance(notifications, dict) else []
    return [str(value.get("id")) for value in values if isinstance(value, dict) and value.get("id")]


def proactive_notices(data: dict[str, Any]) -> list[dict[str, str]]:
    notifications = data.get("notifications")
    values = notifications.get("proactive", []) if isinstance(notifications, dict) else []
    notices = []
    seen: set[str] = set()
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict) or not value.get("id"):
            continue
        notice_id = str(value["id"])
        if notice_id in seen:
            continue
        seen.add(notice_id)
        notices.append({
            "id": notice_id,
            "type": "proactive",
            "title": str(value.get("title") or "곰비 알림"),
            "message": str(value.get("message") or ""),
            "detail": str(value.get("detail") or value.get("message") or "")[:MAX_NOTIFICATION_DETAIL_CHARS],
        })
    return notices


def briefing_notices(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    notices: list[dict[str, str]] = []
    work_fields = ("pending", "overdue", "goals")
    if any(previous.get(field) != current.get(field) for field in work_fields):
        notices.append({"type": "work", "title": "업무 알림", "message": work_text(current)})
    previous_ids = {category: set(_notification_ids(previous, category)) for category in ("fills", "hourly", "proactive")}
    notifications = current.get("notifications")
    if isinstance(notifications, dict):
        for category in ("fills", "hourly", "proactive"):
            values = notifications.get(category, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict) or not value.get("id") or str(value["id"]) in previous_ids[category]:
                    continue
                previous_ids[category].add(str(value["id"]))
                notice_type = str(value.get("type") or category)
                notices.append(
                    {
                        "id": str(value["id"]),
                        "type": notice_type,
                        "title": "트레이딩 정시 보고" if notice_type == "hourly" else str(value.get("title") or ("곰비 알림" if category == "proactive" else "정시 트레이딩 보고")),
                        "message": str(value.get("message") or ""),
                        "detail": str(value.get("detail") or value.get("message") or "")[:MAX_NOTIFICATION_DETAIL_CHARS],
                    }
                )
    return notices


def notification_presentation(notice: dict[str, Any]) -> dict[str, str]:
    notice_type = str(notice.get("type") or "work")
    detail = str(notice.get("detail") or notice.get("message") or "")[:MAX_NOTIFICATION_DETAIL_CHARS]
    if notice_type == "hourly":
        if _looks_like_raw_hourly_dump(detail):
            detail = LEGACY_HOURLY_DETAIL_FALLBACK
        return {"title": "트레이딩 정시 보고", "summary": "", "detail": detail}
    return {
        "title": str(notice.get("title") or "업무 알림")[:100],
        "summary": str(notice.get("message") or "")[:240],
        "detail": detail,
    }


def _looks_like_raw_hourly_dump(text: str) -> bool:
    candidate = text.strip()[:20_000]
    if not candidate:
        return False
    decoder = json.JSONDecoder()
    for attempts, match in enumerate(re.finditer(r"[\[{]", candidate), start=1):
        if attempts > 128:
            break
        try:
            parsed, _end = decoder.raw_decode(candidate, match.start())
        except json.JSONDecodeError:
            continue
        if parsed is None or isinstance(parsed, (dict, list)):
            return True
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
    if unfenced.lower() in {"null", "none"}:
        return True
    return bool(re.search(
        r"[\[{][\s\S]{0,3000}['\"](?:symbol|name|positions|last_hour|trades_today)['\"]\s*:",
        candidate,
        re.IGNORECASE,
    ))


def notification_card_size(notice_type: str) -> tuple[int, int]:
    return (240, 58) if notice_type == "hourly" else (320, 84)


def notification_popup_geometry(workarea: Any, preferred_size: tuple[int, int] = (620, 520), margin: int = 16) -> tuple[int, int, int, int]:
    area_x, area_y = int(workarea.x), int(workarea.y)
    area_width, area_height = int(workarea.width), int(workarea.height)
    width = min(preferred_size[0], max(1, area_width - margin * 2))
    height = min(preferred_size[1], max(1, area_height - margin * 2))
    x = area_x + (area_width - width) // 2
    y = area_y + (area_height - height) // 2
    return x, y, width, height


if Gtk is not None:

    class GombiPet(Gtk.Window):
        def __init__(self, portal_url: str = PORTAL_URL, asset_path: Path = ASSET_PATH):
            super().__init__(title="곰비")
            self.portal_url = portal_url.rstrip("/")
            self._drag_origin: tuple[float, float] | None = None
            self._window_origin: tuple[int, int] | None = None
            self._notification_cards: list[dict[str, Any]] = []
            self._detail_window: Any | None = None
            self._detail_card: dict[str, Any] | None = None
            self._portal_control: Any | None = None
            self._chat_window: Any | None = None
            self._chat_history_box: Any | None = None
            self._chat_scrolled: Any | None = None
            self._chat_input: Any | None = None
            self._chat_send_button: Any | None = None
            self._chat_status: Any | None = None
            self._chat_messages: list[dict[str, str]] = []
            self._chat_loading = False
            self._chat_busy = False
            self._chat_load_id = 0
            self._chat_request_id = 0
            self._pet_destroyed = False
            self.set_decorated(False)
            self.set_keep_above(True)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_resizable(False)
            self.set_name("gombi-window")
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            screen = Gdk.Screen.get_default()
            if screen is not None and screen.is_composited():
                visual = screen.get_rgba_visual()
                if visual is not None:
                    self.set_visual(visual)
            self.set_default_size(*WINDOW_SIZE)
            self._reduced_motion = os.environ.get("GOMBI_REDUCED_MOTION") == "1"
            self._roam_enabled = roaming_enabled()
            self._roam_timer = 0
            self._roam_dx = 1.4
            self._roam_dy = 0.8
            self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
            self.connect("button-press-event", self._press)
            self.connect("motion-notify-event", self._motion)
            self.connect("button-release-event", self._release)
            self.connect("configure-event", self._configure_portal_control)
            self.connect("destroy", self._destroy)

            fixed = Gtk.Fixed()
            self.add(fixed)
            provider = Gtk.CssProvider()
            provider.load_from_data(b"#gombi-window { background-color: rgba(0, 0, 0, 0); }")
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(asset_path), 150, 150, True)
            image = Gtk.Image.new_from_pixbuf(pixbuf)
            fixed.put(image, 15, 38)
            self.show_all()
            self._portal_control = self._create_portal_control(screen)
            self._portal_control.show_all()
            self._position_portal_control()
            GLib.idle_add(self._position_portal_control_idle)
            if self._roam_enabled:
                self._roam_timer = GLib.timeout_add(40, self._roam)
            self._listener = BriefingListener(f"{self.portal_url}{EVENTS_URL}", self._briefing_changed)
            self._listener.start()

        def _create_portal_control(self, screen: Any) -> Any:
            window = Gtk.Window()
            window.set_decorated(False)
            window.set_keep_above(True)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.set_resizable(False)
            window.set_accept_focus(False)
            window.set_name("gombi-portal-control")
            window.set_default_size(228, 40)
            if screen is not None and screen.is_composited():
                visual = screen.get_rgba_visual()
                if visual is not None:
                    window.set_visual(visual)
            provider = Gtk.CssProvider()
            provider.load_from_data(
                b"#gombi-portal-control { background-color: rgba(255, 255, 255, 0.96); border: 1px solid #e2e5ea; border-radius: 16px; }"
                b"#gombi-portal-control-button { background: transparent; border: 0; color: #343a43; font-size: 10pt; font-weight: 700; padding: 6px 14px; }"
            )
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            portal_button = Gtk.Button(label="업무 관리")
            portal_button.set_name("gombi-portal-control-button")
            portal_button.set_relief(Gtk.ReliefStyle.NONE)
            portal_button.set_can_focus(False)
            portal_button.connect("clicked", self._open_portal)
            chat_button = Gtk.Button(label="비서 대화")
            chat_button.set_name("gombi-portal-control-button")
            chat_button.set_relief(Gtk.ReliefStyle.NONE)
            chat_button.set_can_focus(False)
            chat_button.connect("clicked", self._toggle_chat_window)
            controls.pack_start(portal_button, True, True, 0)
            controls.pack_start(chat_button, True, True, 0)
            window.add(controls)
            return window

        def _create_chat_window(self) -> Any:
            window = Gtk.Window(title="곰비 비서 대화")
            window.set_default_size(460, 560)
            window.set_resizable(True)
            window.set_keep_above(True)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.set_name("gombi-trading-chat")

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            outer.set_margin_top(12)
            outer.set_margin_bottom(12)
            outer.set_margin_start(12)
            outer.set_margin_end(12)
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(label="비서 대화")
            title.set_xalign(0)
            title.set_hexpand(True)
            close = Gtk.Button(label="닫기")
            close.connect("clicked", self._hide_chat_window)
            header.pack_start(title, True, True, 0)
            header.pack_end(close, False, False, 0)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_hexpand(True)
            scrolled.set_vexpand(True)
            history = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            history.set_margin_top(6)
            history.set_margin_bottom(6)
            history.set_margin_start(6)
            history.set_margin_end(6)
            scrolled.add(history)

            status = Gtk.Label()
            status.set_xalign(0)
            status.set_line_wrap(True)
            composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            entry.set_placeholder_text("메시지를 입력하세요")
            entry.set_max_length(8000)
            entry.set_hexpand(True)
            entry.connect("activate", self._send_chat_message)
            send = Gtk.Button(label="보내기")
            send.connect("clicked", self._send_chat_message)
            composer.pack_start(entry, True, True, 0)
            composer.pack_end(send, False, False, 0)

            outer.pack_start(header, False, False, 0)
            outer.pack_start(scrolled, True, True, 0)
            outer.pack_start(status, False, False, 0)
            outer.pack_start(composer, False, False, 0)
            window.add(outer)
            window.connect("delete-event", self._chat_window_delete)
            self._chat_window = window
            self._chat_history_box = history
            self._chat_scrolled = scrolled
            self._chat_input = entry
            self._chat_send_button = send
            self._chat_status = status
            return window

        def _toggle_chat_window(self, *_args: Any) -> None:
            window = self._chat_window or self._create_chat_window()
            if window.get_visible():
                window.hide()
                return
            window.show_all()
            window.present()
            if not self._chat_loading and not self._chat_busy:
                self._load_chat_history()

        def _chat_window_delete(self, _widget: Any, _event: Any) -> bool:
            self._hide_chat_window()
            return True

        def _hide_chat_window(self, *_args: Any) -> None:
            if self._chat_window is not None:
                self._chat_window.hide()

        def _set_chat_controls(self, enabled: bool) -> None:
            if self._chat_input is not None:
                self._chat_input.set_sensitive(enabled)
            if self._chat_send_button is not None:
                self._chat_send_button.set_sensitive(enabled)

        def _load_chat_history(self) -> None:
            if self._chat_loading or self._chat_busy or self._pet_destroyed:
                return
            self._chat_loading = True
            self._chat_load_id += 1
            load_id = self._chat_load_id
            self._set_chat_controls(False)
            self._chat_status.set_text("공유 대화를 불러오는 중이에요…")

            def worker() -> None:
                try:
                    messages = fetch_trading_chat_history()
                    error = ""
                except Exception:
                    messages = []
                    error = "대화 기록을 불러오지 못했어요. Trading 서버를 확인해 주세요."
                GLib.idle_add(self._chat_history_loaded, load_id, messages, error)

            threading.Thread(target=worker, name="gombi-chat-history", daemon=True).start()

        def _chat_history_loaded(self, load_id: int, messages: list[dict[str, str]], error: str) -> bool:
            if self._pet_destroyed or load_id != self._chat_load_id:
                return False
            self._chat_loading = False
            if error:
                self._chat_status.set_text(error)
            else:
                self._chat_messages = messages[-MAX_CHAT_HISTORY_ITEMS:]
                self._render_chat_history()
                self._chat_status.set_text("")
            self._set_chat_controls(not self._chat_busy)
            return False

        def _render_chat_history(self) -> None:
            if self._chat_history_box is None:
                return
            for child in self._chat_history_box.get_children():
                self._chat_history_box.remove(child)
            for item in self._chat_messages[-MAX_CHAT_HISTORY_ITEMS:]:
                self._append_chat_widget(item)
            self._scroll_chat_to_bottom()

        def _append_chat_widget(self, item: dict[str, str]) -> None:
            if self._chat_history_box is None:
                return
            role = item.get("role")
            content = item.get("content", "")[:MAX_CHAT_MESSAGE_CHARS]
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            heading = Gtk.Label(label="나" if role == "user" else "비서")
            heading.set_xalign(0)
            body = Gtk.Label()
            body.set_text(content)
            body.set_line_wrap(True)
            body.set_max_width_chars(62)
            body.set_xalign(0)
            body.set_selectable(True)
            row.pack_start(heading, False, False, 0)
            row.pack_start(body, False, False, 0)
            self._chat_history_box.pack_start(row, False, False, 0)
            row.show_all()

        def _scroll_chat_to_bottom(self) -> bool:
            if self._chat_scrolled is None:
                return False
            adjustment = self._chat_scrolled.get_vadjustment()
            adjustment.set_value(adjustment.get_upper())
            return False

        def _append_chat_message(self, role: str, content: str) -> None:
            item = {"role": role, "content": content[:MAX_CHAT_MESSAGE_CHARS]}
            self._chat_messages.append(item)
            self._chat_messages = self._chat_messages[-MAX_CHAT_HISTORY_ITEMS:]
            self._append_chat_widget(item)
            GLib.idle_add(self._scroll_chat_to_bottom)

        def _send_chat_message(self, *_args: Any) -> bool:
            if self._chat_loading or self._chat_busy or self._pet_destroyed or self._chat_input is None:
                return True
            message = self._chat_input.get_text()
            if not message.strip():
                self._chat_status.set_text("메시지를 입력해 주세요.")
                return True
            if len(message) > 8000:
                self._chat_status.set_text("메시지는 8,000자 이내로 입력해 주세요.")
                return True
            message = message.strip()
            self._chat_input.set_text("")
            self._append_chat_message("user", message)
            self._chat_busy = True
            self._chat_request_id += 1
            request_id = self._chat_request_id
            self._set_chat_controls(False)
            self._chat_status.set_text("전송 중이에요…")

            def worker() -> None:
                try:
                    reply = send_trading_chat_message(message)
                    error = ""
                except Exception:
                    reply = ""
                    error = "답변을 받지 못했어요. 잠시 후 다시 시도해 주세요."
                GLib.idle_add(self._chat_send_completed, request_id, reply, error)

            threading.Thread(target=worker, name="gombi-chat-send", daemon=True).start()
            return True

        def _chat_send_completed(self, request_id: int, reply: str, error: str) -> bool:
            if self._pet_destroyed or request_id != self._chat_request_id:
                return False
            self._chat_busy = False
            if error:
                self._chat_status.set_text(error)
            else:
                self._append_chat_message("assistant", reply)
                self._chat_status.set_text("")
            self._set_chat_controls(not self._chat_loading)
            return False

        def _create_notification_window(self, screen: Any, notice_type: str) -> tuple[Any, Any, Any, Any]:
            window = Gtk.Window()
            window.set_decorated(False)
            window.set_keep_above(True)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.set_resizable(False)
            window.set_accept_focus(False)
            window.set_name("gombi-notification")
            window.set_default_size(*notification_card_size(notice_type))
            if screen is not None and screen.is_composited():
                visual = screen.get_rgba_visual()
                if visual is not None:
                    window.set_visual(visual)
            provider = Gtk.CssProvider()
            provider.load_from_data(
                b"#gombi-notification { background-color: rgba(255, 255, 255, 0.97); border: 1px solid #e2e5ea; border-radius: 18px; }"
                b"#gombi-notification-badge-work, #gombi-notification-badge-fill_buy, #gombi-notification-badge-fill_sell, #gombi-notification-badge-hourly, #gombi-notification-badge-proactive { font-size: 9pt; font-weight: 700; }"
                b"#gombi-notification-badge-work { color: #6b7280; }"
                b"#gombi-notification-badge-fill_buy, #gombi-notification-badge-fill_sell { color: #4b8c68; }"
                b"#gombi-notification-badge-hourly { color: #4d7fa8; }"
                b"#gombi-notification-badge-proactive { color: #9b6b3e; }"
                b"#gombi-notification-title { color: #20242b; font-size: 12pt; font-weight: 700; }"
                b"#gombi-notification-body { color: #68717e; font-size: 10pt; }"
            )
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(11)
            box.set_margin_bottom(11)
            box.set_margin_start(17)
            box.set_margin_end(17)
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            badge = Gtk.Label(label={"work": "업무", "fill_buy": "✓ 체결", "fill_sell": "✓ 체결", "hourly": "◷ 정시", "proactive": "◉ 곰비"}.get(notice_type, "알림"))
            badge.set_name(f"gombi-notification-badge-{notice_type}")
            title = Gtk.Label()
            title.set_name("gombi-notification-title")
            title.set_xalign(0)
            body = Gtk.Label()
            body.set_name("gombi-notification-body")
            body.set_line_wrap(True)
            body.set_max_width_chars(38)
            if notice_type != "hourly":
                body.set_size_request(286, 42)
            body.set_xalign(0)
            header.add(badge)
            header.add(title)
            box.add(header)
            box.add(body)
            window.add(box)
            return window, badge, title, body

        def _create_notification_detail_window(self, screen: Any, title_text: str, detail_text: str, card: dict[str, Any]) -> Any:
            window = Gtk.Window()
            window.set_decorated(False)
            window.set_keep_above(True)
            window.set_skip_taskbar_hint(True)
            window.set_skip_pager_hint(True)
            window.set_resizable(True)
            window.set_accept_focus(True)
            window.set_name("gombi-notification-detail")
            workarea = self._workarea()
            geometry = notification_popup_geometry(workarea) if workarea is not None else (0, 0, 620, 520)
            window.set_default_size(geometry[2], geometry[3])
            if screen is not None and screen.is_composited():
                visual = screen.get_rgba_visual()
                if visual is not None:
                    window.set_visual(visual)
            provider = Gtk.CssProvider()
            provider.load_from_data(
                b"#gombi-notification-detail { background-color: rgba(255, 255, 255, 0.99); border: 1px solid #d8dde5; border-radius: 16px; }"
                b"#gombi-notification-detail-title { color: #20242b; font-size: 13pt; font-weight: 700; }"
                b"#gombi-notification-detail-text { color: #424a55; font-size: 10pt; }"
            )
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            outer.set_margin_top(16)
            outer.set_margin_bottom(14)
            outer.set_margin_start(18)
            outer.set_margin_end(18)
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            heading = Gtk.Label(label=title_text)
            heading.set_name("gombi-notification-detail-title")
            heading.set_xalign(0)
            heading.set_hexpand(True)
            close = Gtk.Button(label="알림 닫기")
            close.set_can_focus(True)
            close.connect("clicked", self._close_notification_detail, card, True)
            header.pack_start(heading, True, True, 0)
            header.pack_end(close, False, False, 0)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_hexpand(True)
            scrolled.set_vexpand(True)
            text = Gtk.Label()
            text.set_name("gombi-notification-detail-text")
            text.set_text(detail_text[:MAX_NOTIFICATION_DETAIL_CHARS])
            text.set_line_wrap(True)
            text.set_max_width_chars(76)
            text.set_xalign(0)
            text.set_yalign(0)
            text.set_selectable(True)
            scrolled.add(text)
            outer.pack_start(header, False, False, 0)
            outer.pack_start(scrolled, True, True, 0)
            window.add(outer)
            window.add_events(Gdk.EventMask.KEY_PRESS_MASK)
            window.connect("key-press-event", self._notification_detail_key, card)
            window.connect("delete-event", self._notification_detail_delete, card)
            return window

        def _position_notification_detail(self, window: Any) -> None:
            workarea = self._workarea()
            if workarea is None:
                return
            x, y, width, height = notification_popup_geometry(workarea, window.get_size())
            window.move(x, y)

        def _position_notification_detail_idle(self, window: Any) -> bool:
            if window is self._detail_window and window.get_visible():
                self._position_notification_detail(window)
            return False

        def _open_notification_detail(self, card: dict[str, Any]) -> None:
            if self._detail_card is card and self._detail_window is not None:
                self._close_notification_detail(None, card, False)
                return
            if self._detail_window is not None:
                self._close_notification_detail(None, self._detail_card, False)
            screen = Gdk.Screen.get_default()
            window = self._create_notification_detail_window(screen, card["title"], card["detail"], card)
            self._detail_window = window
            self._detail_card = card
            window.show_all()
            self._position_notification_detail(window)
            window.present()
            GLib.idle_add(self._position_notification_detail_idle, window)

        def _notification_detail_key(self, _widget: Any, event: Any, card: dict[str, Any]) -> bool:
            if event.keyval == Gdk.KEY_Escape:
                self._close_notification_detail(None, card, False)
                return True
            return False

        def _notification_detail_delete(self, _widget: Any, _event: Any, card: dict[str, Any]) -> bool:
            self._close_notification_detail(None, card, False)
            return True

        def _close_notification_detail(self, _widget: Any, card: dict[str, Any] | None, dismiss: bool) -> bool:
            window = self._detail_window
            active_card = self._detail_card
            self._detail_window = None
            self._detail_card = None
            if window is not None:
                window.hide()
                window.destroy()
            target_card = card or active_card
            if dismiss and target_card is not None:
                self._hide_notification(target_card)
            return False

        def _position_notification_cards(self) -> None:
            cards = [card for card in self._notification_cards if card["window"].get_visible()]
            if not cards:
                return
            workarea = self._workarea()
            if workarea is None:
                return
            positions = stacked_notification_positions(
                self.get_position(),
                self.get_size(),
                [card["window"].get_size() for card in cards],
                workarea,
            )
            for card, position in zip(cards, positions):
                card["window"].move(*position)

        def _position_portal_control(self) -> None:
            control = self._portal_control
            if control is None or not control.get_visible():
                return
            workarea = self._workarea()
            if workarea is None:
                return
            position = portal_control_position(self.get_position(), self.get_size(), control.get_size(), workarea)
            control.move(*position)

        def _position_portal_control_idle(self) -> bool:
            self._position_portal_control()
            return False

        def _configure_portal_control(self, _widget: Any, event: Any) -> bool:
            """Follow the WM-applied mascot geometry rather than a stale GDK position."""
            control = self._portal_control
            if control is None or not control.get_visible():
                return False
            mascot_position = (int(event.x), int(event.y))
            mascot_size = (max(1, int(event.width)), max(1, int(event.height)))
            workarea = self._workarea_for_position(mascot_position) or self._workarea()
            if workarea is not None:
                position = portal_control_position(mascot_position, mascot_size, control.get_size(), workarea)
                control.move(*position)
            return False

        def _roam(self) -> bool:
            if self._drag_origin is not None:
                return True
            workarea = self._workarea()
            if workarea is None:
                return True
            x, y = self.get_position()
            next_x = x + self._roam_dx
            next_y = y + self._roam_dy
            if next_x < workarea.x or next_x + 180 > workarea.x + workarea.width:
                self._roam_dx *= -1
                next_x = x + self._roam_dx
            if next_y < workarea.y or next_y + 190 > workarea.y + workarea.height:
                self._roam_dy *= -1
                next_y = y + self._roam_dy
            self.move(round(next_x), round(next_y))
            self._position_portal_control()
            return True

        def _workarea(self) -> Any:
            display = Gdk.Display.get_default()
            window = self.get_window()
            if display is not None and window is not None:
                monitor = display.get_monitor_at_window(window)
                if monitor is not None:
                    return monitor.get_workarea()
            screen = Gdk.Screen.get_default()
            if screen is None:
                return None
            x, y = self.get_position()
            monitor_index = screen.get_monitor_at_point(x, y)
            if monitor_index < 0:
                monitor_index = screen.get_primary_monitor()
            if monitor_index < 0:
                return None
            return screen.get_monitor_workarea(monitor_index)

        def _workarea_for_position(self, position: tuple[int, int]) -> Any:
            display = Gdk.Display.get_default()
            if display is not None:
                for index in range(display.get_n_monitors()):
                    monitor = display.get_monitor(index)
                    area = monitor.get_workarea() if monitor is not None else None
                    if area is not None and area.x <= position[0] < area.x + area.width and area.y <= position[1] < area.y + area.height:
                        return area
                primary = display.get_primary_monitor()
                if primary is not None:
                    return primary.get_workarea()
            return None

        def restore_position(self) -> None:
            saved = load_position()
            if saved is None:
                self.move(*primary_pet_position())
                self._position_portal_control()
                GLib.idle_add(self._position_portal_control_idle)
                return
            workarea = self._workarea_for_position(saved)
            if workarea is None:
                self.move(*primary_pet_position())
                self._position_portal_control()
                GLib.idle_add(self._position_portal_control_idle)
                return
            self.move(*clamp_position(saved, workarea, WINDOW_SIZE))
            self._position_portal_control()
            GLib.idle_add(self._position_portal_control_idle)

        def _press(self, _widget: Any, event: Any) -> bool:
            if event.button != 1:
                return False
            self._drag_origin = (event.x_root, event.y_root)
            self._window_origin = self.get_position()
            return True

        def _motion(self, _widget: Any, event: Any) -> bool:
            if self._drag_origin is None or self._window_origin is None:
                return False
            dx = event.x_root - self._drag_origin[0]
            dy = event.y_root - self._drag_origin[1]
            self.move(round(self._window_origin[0] + dx), round(self._window_origin[1] + dy))
            self._position_notification_cards()
            self._position_portal_control()
            return True

        def _open_portal(self, *_args: Any) -> None:
            webbrowser.open(self.portal_url)

        def _release(self, _widget: Any, event: Any) -> bool:
            if event.button != 1 or self._drag_origin is None:
                return False
            origin = self._drag_origin
            self._drag_origin = self._window_origin = None
            self._position_notification_cards()
            self._position_portal_control()
            moved = abs(event.x_root - origin[0]) >= 5 or abs(event.y_root - origin[1]) >= 5
            if moved:
                save_position(self.get_position())
            else:
                self._open_portal()
            return True

        def _briefing_changed(self, notice: dict[str, str]) -> None:
            text = notice.get("message", "")
            notify_briefing(text)
            GLib.idle_add(self._show_notification, notice)

        def _show_notification(self, notice: dict[str, str]) -> bool:
            if len(self._notification_cards) >= 3:
                self._hide_notification(self._notification_cards[0])
            screen = Gdk.Screen.get_default()
            presentation = notification_presentation(notice)
            notice_type = notice.get("type", "work")
            window, badge, title, body = self._create_notification_window(screen, notice_type)
            badge.set_text({"work": "업무", "fill_buy": "✓ 체결", "fill_sell": "✓ 체결", "hourly": "◷ 정시", "proactive": "◉ 곰비"}.get(notice_type, "알림"))
            title.set_text(presentation["title"])
            body.set_text(presentation["summary"])
            if notice_type == "hourly":
                badge.hide()
                body.hide()
            window.set_tooltip_text("클릭하면 전체 내용을 확인할 수 있어요.")
            window.show_all()
            if notice_type == "hourly":
                badge.hide()
                body.hide()
            card = {
                "window": window,
                "type": notice_type,
                "title": presentation["title"],
                "detail": presentation["detail"],
            }
            window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            window.connect("button-press-event", self._notification_press, card)
            self._notification_cards.append(card)
            GLib.idle_add(self._position_notification_cards_idle)
            return False

        def _position_notification_cards_idle(self) -> bool:
            self._position_notification_cards()
            return False

        def _notification_press(self, _widget: Any, event: Any, card: dict[str, Any]) -> bool:
            if event.button != 1:
                return False
            if card.get("type") == "hourly":
                self._open_notification_detail(card)
            else:
                self._hide_notification(card)
            return True

        def _hide_notification(self, card: dict[str, Any]) -> bool:
            if self._detail_card is card:
                self._close_notification_detail(None, card, False)
            if card in self._notification_cards:
                self._notification_cards.remove(card)
            card["window"].hide()
            card["window"].destroy()
            self._position_notification_cards()
            return False

        def _destroy(self, _widget: Any) -> None:
            self._pet_destroyed = True
            self._listener.stop()
            if self._roam_timer:
                GLib.source_remove(self._roam_timer)
            if self._detail_window is not None:
                self._close_notification_detail(None, self._detail_card, False)
            for card in self._notification_cards:
                card["window"].destroy()
            self._notification_cards.clear()
            if self._chat_window is not None:
                self._chat_window.destroy()
                self._chat_window = None
            if self._portal_control is not None:
                self._portal_control.destroy()
                self._portal_control = None
            Gtk.main_quit()

else:

    class GombiPet:  # pragma: no cover - only used when GTK is unavailable
        def __init__(self, *_args: Any, **_kwargs: Any):
            raise RuntimeError("PyGObject GTK3 is required to run the desktop pet")


def main() -> None:
    if Gtk is None:
        raise SystemExit("PyGObject GTK3 is required to run the desktop pet")
    pet = GombiPet()
    pet.restore_position()
    Gtk.main()


if __name__ == "__main__":
    main()
