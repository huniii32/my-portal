import base64
import io
import json
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import urllib.parse

import desktop_pet


def test_gtk3_asset_is_scaled_before_display_without_cairo_draw_hook():
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    assert "GdkPixbuf.Pixbuf.new_from_file_at_scale" in source
    assert "Gtk.Image.new_from_pixbuf" in source
    assert 'connect("draw"' not in source
    assert "GLib.idle_add(self._position_notification_cards_idle)" in source
    assert "timeout_add_seconds(8" not in source
    assert 'connect("button-press-event", self._notification_press, card)' in source
    assert "self._open_notification_detail(card)" in source


def test_primary_pet_position_uses_primary_workarea(monkeypatch):
    area = SimpleNamespace(x=2626, y=32)
    monitor = SimpleNamespace(get_workarea=lambda: area)
    display = SimpleNamespace(get_primary_monitor=lambda: monitor)
    monkeypatch.setattr(desktop_pet, "Gdk", SimpleNamespace(Display=SimpleNamespace(get_default=lambda: display)))
    assert desktop_pet.primary_pet_position() == (2716, 172)


def test_position_store_validates_corruption_and_writes_atomically(tmp_path):
    path = tmp_path / "state" / "position.json"
    assert desktop_pet.save_position((12, 34), path) is True
    assert desktop_pet.load_position(path) == (12, 34)
    assert not list(path.parent.glob("*.tmp"))
    path.write_text("{broken", encoding="utf-8")
    assert desktop_pet.load_position(path) is None
    assert desktop_pet.save_position((float("inf"), 4), path) is False


def test_position_is_clamped_to_workarea():
    area = SimpleNamespace(x=100, y=200, width=800, height=600)
    assert desktop_pet.clamp_position((-50, 999), area) == (100, 610)


def test_huge_integer_state_loads_without_float_overflow_and_clamps(tmp_path):
    path = tmp_path / "position.json"
    huge = 10**1000
    path.write_text(f'{{"x": {huge}, "y": {-huge}}}', encoding="utf-8")
    position = desktop_pet.load_position(path)
    area = SimpleNamespace(x=100, y=200, width=800, height=600)
    assert position == (huge, -huge)
    assert desktop_pet.clamp_position(position, area) == (720, 200)


def test_roaming_is_opt_in_and_reduced_motion_wins():
    assert desktop_pet.roaming_enabled({}) is False
    assert desktop_pet.roaming_enabled({"GOMBI_ROAM": "1"}) is True
    assert desktop_pet.roaming_enabled({"GOMBI_ROAM": "1", "GOMBI_REDUCED_MOTION": "1"}) is False


def test_notification_title_and_position_are_bounded():
    area = SimpleNamespace(x=0, y=0, width=800, height=600)
    assert desktop_pet.briefing_title({}) == "업무 비서 곰비"
    assert desktop_pet.briefing_title({"trading": {"alert": {"message": "위험"}}}) == "트레이딩 알림"
    assert desktop_pet.notification_position((100, 100), (180, 190), (320, 84), area) == (30, 8)
    assert desktop_pet.notification_position((700, 500), (180, 190), (320, 84), area) == (472, 408)


def test_hourly_notification_uses_short_title_and_preserves_full_detail():
    report = "시간별 체결 및 리스크 요약\n" + ("상세 항목. " * 800)
    previous = {"notifications": {"hourly": []}}
    current = {"notifications": {"hourly": [{"id": "hour-1", "type": "hourly", "title": "원본 제목", "message": "간단 요약", "detail": report}]}}
    notice = desktop_pet.briefing_notices(previous, current)[0]
    presentation = desktop_pet.notification_presentation(notice)
    assert notice["title"] == "트레이딩 정시 보고"
    assert presentation == {"title": "트레이딩 정시 보고", "summary": "", "detail": report}
    huge = desktop_pet.notification_presentation({"type": "hourly", "detail": "x" * (desktop_pet.MAX_NOTIFICATION_DETAIL_CHARS + 100)})
    assert len(huge["detail"]) == desktop_pet.MAX_NOTIFICATION_DETAIL_CHARS


def test_hourly_popup_hides_legacy_json_and_uses_compact_single_line_card():
    raw_dumps = [
        '```json\n[{"symbol":"005930","name":"삼성전자","qty":2}]\n```',
        "```json\nnull\n```",
        '정시 요약: {"positions":[{"symbol":"005930","name":"삼성전자","qty":2}]}',
        "보유 종목 [{'symbol': '005930', 'name': '삼성전자', 'qty': 2}]",
    ]
    for raw in raw_dumps:
        presentation = desktop_pet.notification_presentation({"type": "hourly", "detail": raw})
        assert presentation["title"] == "트레이딩 정시 보고"
        assert presentation["summary"] == ""
        assert "name" not in presentation["detail"]
        assert "삼성전자" not in presentation["detail"]
        assert presentation["detail"] == desktop_pet.LEGACY_HOURLY_DETAIL_FALLBACK
    assert desktop_pet.notification_card_size("hourly") == (240, 58)
    assert desktop_pet.notification_card_size("work") == (320, 84)


def test_notification_detail_geometry_is_bounded_and_centered():
    area = SimpleNamespace(x=100, y=50, width=900, height=700)
    assert desktop_pet.notification_popup_geometry(area) == (240, 140, 620, 520)
    narrow = SimpleNamespace(x=0, y=0, width=420, height=300)
    x, y, width, height = desktop_pet.notification_popup_geometry(narrow)
    assert (x, y, width, height) == (16, 16, 388, 268)


def test_notification_card_click_opens_safe_scrollable_detail_without_moving_pet():
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    assert "self._open_notification_detail(card)" in source
    assert 'window.connect("key-press-event", self._notification_detail_key, card)' in source
    assert 'window.connect("delete-event", self._notification_detail_delete, card)' in source
    assert 'close.connect("clicked", self._close_notification_detail, card, True)' in source
    assert "Gtk.ScrolledWindow()" in source
    assert "text.set_text(detail_text[:MAX_NOTIFICATION_DETAIL_CHARS])" in source
    detail_open = source[source.index("def _open_notification_detail"):source.index("def _notification_detail_key")]
    assert "window.move(" not in detail_open and "self.move(" not in detail_open
    assert "if self._detail_card is card and self._detail_window is not None:" in detail_open
    assert "self._close_notification_detail(None, card, False)" in detail_open
    close_detail = source[source.index("def _close_notification_detail"):source.index("def _position_notification_cards")]
    assert "if dismiss and target_card is not None:" in close_detail
    assert "self._hide_notification(target_card)" in close_detail
    escape_handler = source[source.index("def _notification_detail_key"):source.index("def _notification_detail_delete")]
    assert "event.keyval == Gdk.KEY_Escape" in escape_handler
    assert "self._close_notification_detail(None, card, False)" in escape_handler


def test_only_hourly_cards_open_detail_and_pet_teardown_closes_detail_first():
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    click_handler = source[source.index("def _notification_press"):source.index("def _hide_notification")]
    assert 'if card.get("type") == "hourly":' in click_handler
    assert "self._open_notification_detail(card)" in click_handler
    assert "self._hide_notification(card)" in click_handler
    destroy_handler = source[source.index("def _destroy"):source.index("else:", source.index("def _destroy"))]
    assert "if self._detail_window is not None:" in destroy_handler
    assert "self._close_notification_detail(None, self._detail_card, False)" in destroy_handler
    assert destroy_handler.index("_close_notification_detail") < destroy_handler.index('card["window"].destroy()')


def test_briefing_text_is_deterministic_and_includes_relevant_sections():
    data = {
        "pending": {"count": 1, "items": [{"title": "보고서"}]},
        "overdue": {"count": 2, "items": [{"title": "지난 회신"}]},
        "goals": {"week": {"items": [{"goal": "A"}]}, "day": {"items": []}},
        "trading": {"alert": {"title": "위험", "message": "손절 확인"}},
    }
    text = desktop_pet.briefing_text(data)
    assert text == "미완료 지난 업무 2개, 오늘 할 일 1개, 목표 1개, 주식 알림: 손절 확인예요. 먼저 확인할 일: 지난 회신"


def test_sse_parser_ignores_heartbeats_and_joins_data_lines():
    lines = [b": heartbeat\n", b"event: briefing\n", b"data: {\n", b"data: \"ok\"\n", b"data: }\n", b"\n"]
    assert list(desktop_pet.iter_sse_events(lines)) == [("briefing", '{\n"ok"\n}')]


def test_stream_reconnects_after_portal_restart():
    calls = []
    stop = threading.Event()

    class Response:
        def __enter__(self):
            return [b"event: briefing\n", b"data: {\"ready\": true}\n", b"\n"]

        def __exit__(self, *_args):
            stop.set()
            return False

    def opener(_url, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise OSError("portal down")
        return Response()

    events = desktop_pet.stream_briefings("http://127.0.0.1:8080/api/assistant/events", stop, opener=opener, reconnect_seconds=0)
    assert next(events) == {"ready": True}
    assert len(calls) == 2


def test_listener_skips_initial_briefing_and_duplicate_payload(monkeypatch):
    first = {"pending": {"count": 0}}
    changed = {"pending": {"count": 1}}
    monkeypatch.setattr(desktop_pet, "stream_briefings", lambda *_args: iter([first, first, changed, changed]))
    received = []
    listener = desktop_pet.BriefingListener("http://localhost", received.append)
    listener.run()
    assert len(received) == 1
    assert received[0]["type"] == "work"
    assert received[0]["title"] == "업무 알림"


def test_listener_ignores_trading_metadata_and_alert_churn(monkeypatch):
    first = {
        "source_date": "2026-09-16",
        "pending": {"count": 0},
        "overdue": {"count": 0},
        "goals": {"week": {"items": []}, "day": {"items": []}},
        "trading": {"updated": "one", "position_count": 1, "alert": {"title": "위험", "message": "확인"}},
    }
    metadata_change = deepcopy(first)
    metadata_change["trading"]["updated"] = "two"
    alert_change = deepcopy(first)
    alert_change["trading"]["alert"]["message"] = "즉시 확인"
    monkeypatch.setattr(desktop_pet, "stream_briefings", lambda *_args: iter([first, metadata_change, alert_change]))
    received = []
    desktop_pet.BriefingListener("http://localhost", received.append).run()
    assert received == []


def test_briefing_notices_emit_work_and_only_new_categorized_events():
    first = {
        "pending": {"count": 0},
        "overdue": {"count": 0},
        "goals": {"week": {"items": []}, "day": {"items": []}},
        "notifications": {
            "fills": [{"id": "fill-1", "type": "fill_buy", "title": "매수", "message": "기존"}],
            "hourly": [{"id": "hour-1", "type": "hourly", "title": "트레이딩 정시 보고", "message": "기존"}],
        },
    }
    current = deepcopy(first)
    current["pending"] = {"count": 1}
    current["notifications"]["fills"].extend([
        {"id": "fill-2", "type": "fill_sell", "title": "매도", "message": "새 체결"},
        {"id": "fill-2", "type": "fill_sell", "title": "매도", "message": "중복"},
    ])
    current["notifications"]["hourly"].append(
        {"id": "hour-2", "type": "hourly", "title": "트레이딩 정시 보고", "message": "새 보고"}
    )
    notices = desktop_pet.briefing_notices(first, current)
    assert [(item["type"], item["title"]) for item in notices] == [
        ("work", "업무 알림"),
        ("fill_sell", "매도"),
        ("hourly", "트레이딩 정시 보고"),
    ]
    assert "주식" not in notices[0]["message"]


def test_stacked_notification_positions_are_clamped_and_ordered():
    area = SimpleNamespace(x=100, y=50, width=900, height=700)
    positions = desktop_pet.stacked_notification_positions(
        (450, 500), (180, 190), [(334, 90), (334, 90), (334, 90)], area
    )
    assert len(positions) == 3
    assert positions[0][1] < positions[1][1] < positions[2][1]
    assert all(100 + 8 <= x <= 100 + 900 - 334 - 8 for x, _y in positions)
    assert all(50 + 8 <= y <= 50 + 700 - 90 - 8 for _x, y in positions)


def test_proactive_seen_state_is_atomic_bounded_and_initial_only_once(tmp_path, monkeypatch):
    path = tmp_path / "state" / "proactive_seen.json"
    first = {"notifications": {"fills": [{"id": "fill-old"}], "hourly": [{"id": "hour-old"}], "proactive": [{"id": "proactive-1", "title": "아침", "message": "계획"}]}}
    second = {"notifications": {"fills": [{"id": "fill-old"}], "hourly": [{"id": "hour-old"}], "proactive": [{"id": "proactive-1", "title": "아침", "message": "계획"}, {"id": "proactive-2", "title": "점검", "message": "확인"}]}}
    monkeypatch.setattr(desktop_pet, "stream_briefings", lambda *_args: iter([first, second]))
    received = []
    desktop_pet.BriefingListener("http://localhost", received.append, path).run()
    assert [notice["id"] for notice in received] == ["proactive-1", "proactive-2"]
    assert desktop_pet.load_seen_proactive(path) == ["proactive-1", "proactive-2"]
    monkeypatch.setattr(desktop_pet, "stream_briefings", lambda *_args: iter([second]))
    received = []
    desktop_pet.BriefingListener("http://localhost", received.append, path).run()
    assert received == []
    assert not list(path.parent.glob("*.tmp"))
    ordered = [f"proactive-{index}" for index in range(70)]
    assert desktop_pet.save_seen_proactive(ordered, path)
    assert desktop_pet.load_seen_proactive(path) == ordered[-64:]
    assert desktop_pet.save_seen_proactive(desktop_pet.load_seen_proactive(path), path)
    assert desktop_pet.load_seen_proactive(path)[-1] == "proactive-69"


def test_portal_control_position_stays_below_or_falls_back_above():
    area = SimpleNamespace(x=100, y=50, width=900, height=700)
    assert desktop_pet.portal_control_position((450, 100), (180, 190), (228, 40), area) == (426, 298)
    assert desktop_pet.portal_control_position((450, 600), (180, 190), (228, 40), area) == (426, 552)


def test_portal_control_is_separate_clickable_portal_button():
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    assert 'set_name("gombi-portal-control")' in source
    assert 'Gtk.Button(label="업무 관리")' in source
    assert 'Gtk.Button(label="비서 대화")' in source
    assert 'portal_button.connect("clicked", self._open_portal)' in source
    assert 'chat_button.connect("clicked", self._toggle_chat_window)' in source
    assert "def _open_portal" in source
    assert "self._position_portal_control()" in source


def test_portal_control_idle_repositions_after_wm_geometry_is_applied():
    if not hasattr(desktop_pet.GombiPet, "_position_portal_control_idle"):
        return

    calls = []

    class FakePet:
        def _position_portal_control(self):
            calls.append("position")

    assert desktop_pet.GombiPet._position_portal_control_idle(FakePet()) is False
    assert calls == ["position"]


def test_portal_control_configure_handler_uses_wm_event_geometry():
    if not hasattr(desktop_pet.GombiPet, "_configure_portal_control"):
        return

    area = SimpleNamespace(x=2626, y=32, width=1920, height=1080)
    positions = []

    class Control:
        def get_visible(self):
            return True

        def get_size(self):
            return (228, 40)

        def move(self, x, y):
            positions.append((x, y))

    class FakePet:
        _portal_control = Control()

        def _workarea_for_position(self, position):
            assert position == (2724, 1494)
            return area

        def _workarea(self):
            raise AssertionError("event workarea should be used")

    event = SimpleNamespace(x=2724, y=1494, width=180, height=190)
    assert desktop_pet.GombiPet._configure_portal_control(FakePet(), event) is False
    assert positions == [(2700, 1064)]


def test_trading_chat_url_auth_request_and_shared_history(tmp_path):
    password_file = tmp_path / "dashboard_password"
    password_file.write_text("local-secret\n", encoding="utf-8")
    password_file.chmod(0o600)
    environ = {
        "GOMBI_TRADING_URL": "http://localhost:8510",
        "GOMBI_TRADING_USERNAME": "trader",
        "GOMBI_TRADING_PASSWORD_FILE": str(password_file),
    }
    calls = []
    history_json = json.dumps({"items": [
        {"role": "user", "content": "안녕", "created_at": "today"},
        {"role": "assistant", "content": "무엇을 도와드릴까요?", "created_at": "today"},
        {"role": "system", "content": "ignore", "created_at": "today"},
    ]}).encode()

    class Response(io.BytesIO):
        def __init__(self, body, url, status=200):
            super().__init__(body)
            self.url = url
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return self.url

        def getcode(self):
            return self.status

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response(history_json, request.full_url)

    messages = desktop_pet.fetch_trading_chat_history(environ, opener=opener)
    assert messages == [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "무엇을 도와드릴까요?"},
    ]
    request, timeout = calls[0]
    assert request.get_method() == "GET"
    assert request.full_url.startswith("http://localhost:8510/api/office-chat/history?")
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query) == {
        "session_id": ["chat"], "limit": [str(desktop_pet.MAX_CHAT_HISTORY_ITEMS)]
    }
    assert base64.b64decode(request.get_header("Authorization").split(" ", 1)[1]).decode() == "trader:local-secret"
    assert timeout == desktop_pet.CHAT_HISTORY_TIMEOUT
    assert desktop_pet.assert_loopback_target(request.full_url).hostname == "localhost"


def test_trading_chat_send_payload_and_bounded_reply(tmp_path):
    password_file = tmp_path / "password"
    password_file.write_text("secret", encoding="utf-8")
    password_file.chmod(0o600)
    environ = {"GOMBI_TRADING_PASSWORD_FILE": str(password_file)}
    calls = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return "http://127.0.0.1:8510/api/assistant-chat"

        def getcode(self):
            return 200

    def opener(request, timeout):
        calls.append((request, timeout))
        return Response('{"reply":"  안녕하세요  ","model":"local"}'.encode("utf-8"))

    assert desktop_pet.send_trading_chat_message("질문", environ, opener) == "안녕하세요"
    request, timeout = calls[0]
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {"session_id": "chat", "message": "질문"}
    assert timeout == desktop_pet.CHAT_SEND_TIMEOUT


def test_trading_chat_rejects_non_loopback_bad_password_permissions_and_oversize(monkeypatch, tmp_path):
    for url in ("https://example.com", "http://127.0.0.1:8510/base", "ftp://localhost"):
        try:
            desktop_pet.validate_loopback_url(url)
        except desktop_pet.TradingChatError:
            pass
        else:
            raise AssertionError(f"accepted unsafe Trading URL: {url}")
    assert desktop_pet.validate_loopback_url("http://[::1]:8510") == "http://[::1]:8510"
    assert desktop_pet.assert_loopback_target("http://127.0.0.1:8510/api/chat?session_id=chat")

    password_file = tmp_path / "password"
    password_file.write_text("secret", encoding="utf-8")
    password_file.chmod(0o644)
    try:
        desktop_pet.read_trading_password(password_file)
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("permissive password file was accepted")
    try:
        desktop_pet._basic_auth_header("trader", "bad\nsecret")
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("newline password was accepted")

    class LargeResponse:
        def read(self, size):
            return b"x" * size

    monkeypatch.setattr(desktop_pet, "MAX_CHAT_RESPONSE_BYTES", 8)
    try:
        desktop_pet._read_chat_response(LargeResponse())
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("oversized Trading response was accepted")


def test_trading_password_requires_owned_regular_private_file_and_bounded_size(monkeypatch, tmp_path):
    password_file = tmp_path / "password"
    password_file.write_text("valid-secret\n", encoding="utf-8")
    password_file.chmod(0o600)
    assert desktop_pet.read_trading_password(password_file) == "valid-secret"

    link = tmp_path / "password-link"
    link.symlink_to(password_file)
    try:
        desktop_pet.read_trading_password(link)
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("symlink password path was accepted")

    directory = tmp_path / "password-directory"
    directory.mkdir(mode=0o700)
    try:
        desktop_pet.read_trading_password(directory)
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("non-regular password path was accepted")

    real_getuid = desktop_pet.os.getuid
    monkeypatch.setattr(desktop_pet.os, "getuid", lambda: real_getuid() + 1)
    try:
        desktop_pet.read_trading_password(password_file)
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("password file owned by another UID was accepted")
    monkeypatch.setattr(desktop_pet.os, "getuid", real_getuid)

    oversized = tmp_path / "oversized-password"
    oversized.write_text("x" * 4098, encoding="utf-8")
    oversized.chmod(0o600)
    try:
        desktop_pet.read_trading_password(oversized)
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("oversized password file was accepted")
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    assert "handle.read(4097)" in source
    assert 'getattr(os, "O_NOFOLLOW", 0)' in source


def test_default_trading_opener_ignores_environment_proxies(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.2:3128")
    monkeypatch.setenv("https_proxy", "http://127.0.0.3:3128")
    discovered = []
    monkeypatch.setattr(
        desktop_pet.urllib.request,
        "getproxies",
        lambda: discovered.append(True) or {"http": "http://127.0.0.2:3128"},
    )
    opener = desktop_pet._build_trading_opener().__self__
    redirects = [handler for handler in opener.handlers if isinstance(handler, desktop_pet.urllib.request.HTTPRedirectHandler)]
    assert discovered == []
    assert not any(isinstance(handler, desktop_pet.urllib.request.ProxyHandler) for handler in opener.handlers)
    assert any(type(handler) is desktop_pet._LoopbackRedirectHandler for handler in redirects)
    rejector = next(handler for handler in redirects if type(handler) is desktop_pet._LoopbackRedirectHandler)
    assert rejector.handler_order < desktop_pet.urllib.request.HTTPRedirectHandler.handler_order


def test_trading_chat_rejects_redirects_and_bad_response_schema():
    handler = desktop_pet._LoopbackRedirectHandler()
    try:
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:8510/elsewhere")
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("redirect was followed")
    for response in ({"items": "not a list"}, {"items": [{"role": "tool", "content": "hidden"}]}):
        if response["items"] == "not a list":
            try:
                desktop_pet.validate_chat_history(response)
            except desktop_pet.TradingChatError:
                pass
            else:
                raise AssertionError("bad history schema was accepted")
        else:
            assert desktop_pet.validate_chat_history(response) == []


def test_trading_chat_http_failure_and_external_response_fail_closed():
    class Response(io.BytesIO):
        def __init__(self, url, status):
            super().__init__(b'{"items":[]}')
            self.url = url
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return self.url

        def getcode(self):
            return self.status

    def failure(_request, timeout):
        return Response("http://127.0.0.1:8510/api/office-chat/history?session_id=chat", 503)

    try:
        desktop_pet.trading_chat_request(
            "http://127.0.0.1:8510", "trader", "secret", "GET", "/api/office-chat/history", opener=failure
        )
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("Trading HTTP error was accepted")

    def external(_request, timeout):
        return Response("https://example.com/api/office-chat/history", 200)

    try:
        desktop_pet.trading_chat_request(
            "http://127.0.0.1:8510", "trader", "secret", "GET", "/api/office-chat/history", opener=external
        )
    except desktop_pet.TradingChatError:
        pass
    else:
        raise AssertionError("external response target was accepted")


def test_chat_window_is_async_bounded_and_uses_shared_chat_session():
    source = Path(desktop_pet.__file__).read_text(encoding="utf-8")
    assert 'Gtk.Window(title="곰비 비서 대화")' in source
    assert "window.set_default_size(460, 560)" in source
    assert "window.set_resizable(True)" in source
    assert 'window.connect("delete-event", self._chat_window_delete)' in source
    assert 'entry.connect("activate", self._send_chat_message)' in source
    assert "threading.Thread(target=worker, name=\"gombi-chat-history\", daemon=True).start()" in source
    assert "threading.Thread(target=worker, name=\"gombi-chat-send\", daemon=True).start()" in source
    assert "GLib.idle_add(self._chat_history_loaded" in source
    assert "GLib.idle_add(self._chat_send_completed" in source
    assert '"session_id": "chat"' in source
    assert "len(message) > 8000" in source
    assert "self._chat_messages = messages[-MAX_CHAT_HISTORY_ITEMS:]" in source
    assert "body.set_text(content)" in source
    assert "body.set_markup" not in source
    assert "if self._chat_window is not None:" in source[source.index("def _destroy"):source.index("else:", source.index("def _destroy"))]
