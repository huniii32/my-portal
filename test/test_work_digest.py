import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import storage as server_storage
import work_digest


def test_jsonl_collector_filters_day_roles_tools_and_redacts(tmp_path):
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"timestamp": "2026-09-16T09:00:00+09:00", "type": "response_item", "payload": {"role": "user", "content": "오늘 API_KEY=secret-value 업무를 정리해줘"}}),
            json.dumps({"timestamp": "2026-09-16T09:01:00+09:00", "role": "assistant", "content": "완료: 보고서 초안을 저장했습니다."}),
            json.dumps({"timestamp": "2026-09-16T09:01:30+09:00", "role": "assistant", "content": [{"type": "image_url", "text": "이미지 캡션"}]}),
            json.dumps({"timestamp": "2026-09-16T09:03:00+09:00", "type": "last-prompt", "content": "다음 요청"}),
            json.dumps({"timestamp": "2026-09-16T09:02:00+09:00", "type": "tool_result", "content": "stdout password=hidden"}),
            json.dumps({"timestamp": "2026-09-16T09:04:00+09:00", "type": "unknown_event", "content": "알 수 없는 지시"}),
            json.dumps({"timestamp": "2026-09-16T09:05:00+09:00", "type": "unknown_event", "role": "user", "content": "알 수 없는 role 지시"}),
            json.dumps({"timestamp": "2026-09-16T09:06:00+09:00", "type": "unknown_event", "message": {"role": "user", "content": "알 수 없는 message 지시"}}),
            json.dumps({"timestamp": "2026-09-15T23:59:00+09:00", "role": "user", "content": "어제 요청"}),
            "{malformed",
        ]),
        encoding="utf-8",
    )
    values = work_digest.collect_jsonl(path, "codex", date(2026, 9, 16))
    texts = [item["text"] for item in values]
    assert any("오늘" in text for text in texts)
    assert any("완료" in text for text in texts)
    assert all("secret-value" not in text and "password" not in text for text in texts)
    assert all("어제" not in text for text in texts)
    assert not any("stdout" in text for text in texts)
    assert not any("이미지 캡션" in text for text in texts)
    assert not any("알 수 없는 지시" in text for text in texts)
    assert not any("알 수 없는 role 지시" in text for text in texts)
    assert not any("알 수 없는 message 지시" in text for text in texts)


def test_secret_probes_are_redacted_or_excluded_from_model_evidence(monkeypatch):
    # NOTE: 가짜 탐지 probe는 파일에 리터럴 패턴으로 두면 GitHub push protection에
    # 걸리므로, prefix와 본문을 나눠 런타임에 조합한다. 실행 시 문자열은 동일하다.
    join = lambda *parts: "".join(parts)
    probes = [
        join("ghp_", "abcdefghijklmnopqrstuvwxyz1234567890"),
        join("sk-proj-", "abcdefghijklmnopqrstuvwxyz123456"),
        join("AKIA", "1234567890ABCDEF"),
        join("AIza", "SyAbcdefghijklmnopqrstuvwxyz123456"),
        join("xoxb-", "1234567890-abcdefghijklmnop"),
        join("-----BEGIN PRIVATE", " KEY-----\nsecret\n-----END PRIVATE", " KEY-----"),
        join("Authorization token AbCdEf0123456789_abcdefghijklmnopqrstuvwxyz"),
    ]
    assert all(work_digest.contains_secret(value) for value in probes)
    evidence = [{"tool": "codex", "kind": "user_request", "text": probes[0], "ref": "opaque", "title": ""}]
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b'{"choices":[{"message":{"content":"{}"}}]}'

    def opener(request, **_kwargs):
        captured["body"] = request.data.decode()
        return Response()

    work_digest.summarize_with_model(date(2026, 9, 16), evidence, opener=opener)
    assert probes[0] not in captured.get("body", "")


def test_opencode_reader_is_read_only_text_parts_and_bounded(tmp_path):
    path = tmp_path / "opencode.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE session(id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, data TEXT);
        CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
    """)
    stamp = int(datetime(2026, 9, 16, 1, 0).timestamp() * 1000)
    connection.execute("INSERT INTO session VALUES ('s1','오늘 세션')", )
    connection.execute("INSERT INTO message VALUES ('m1','s1',?)", (json.dumps({"role": "user"}),))
    connection.execute("INSERT INTO part VALUES ('p1','m1','s1',?,?)", (stamp, json.dumps({"type": "text", "text": "작업 요청"})))
    connection.execute("INSERT INTO part VALUES ('p2','m1','s1',?,?)", (stamp, json.dumps({"type": "tool", "text": "비밀 출력"})))
    connection.commit()
    connection.close()
    values = work_digest.collect_opencode(path, date(2026, 9, 16))
    assert [item["text"] for item in values] == ["오늘 세션", "작업 요청"]


def test_collect_evidence_deduplicates_and_bounds(tmp_path):
    codex = tmp_path / "codex"
    claude = tmp_path / "claude"
    codex.mkdir()
    claude.mkdir()
    record = {"timestamp": "2026-09-16T09:00:00+09:00", "role": "user", "content": "같은 요청"}
    (codex / "a.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    (claude / "b.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    values = work_digest.collect_evidence(date(2026, 9, 16), codex_root=codex, claude_root=claude, opencode_db=tmp_path / "none.db", handoff=tmp_path / "none.md", workspace=tmp_path)
    assert len([item for item in values if item["text"] == "같은 요청"]) == 1


def test_jsonl_scan_is_tail_bounded_and_recent_file_first(tmp_path):
    root = tmp_path / "codex"
    root.mkdir()
    early = root / "early.jsonl"
    late = root / "late.jsonl"
    early.write_text(json.dumps({"timestamp": "2026-09-16T09:00:00+09:00", "role": "user", "content": "초기 기록"}) + "\n" + ("x" * 600), encoding="utf-8")
    late.write_text(json.dumps({"timestamp": "2026-09-16T09:01:00+09:00", "role": "user", "content": "최근 기록"}) + "\n", encoding="utf-8")
    import os
    os.utime(early, (1, 1))
    os.utime(late, (2, 2))
    bounded = work_digest.collect_jsonl(early, "codex", date(2026, 9, 16), max_bytes=128)
    assert not any(item["text"] == "초기 기록" for item in bounded)
    values = work_digest.collect_evidence(date(2026, 9, 16), codex_root=root, claude_root=tmp_path / "none", opencode_db=tmp_path / "none.db", handoff=tmp_path / "none.md", workspace=tmp_path, max_files=1)
    assert any(item["text"] == "최근 기록" for item in values)
    assert work_digest.scan_metrics()["files"] <= 2


def test_codex_history_fallback_is_strict_and_day_filtered(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text("\n".join([
        json.dumps({"session_id": "s1", "ts": "2026-09-15T09:00:00+09:00", "text": "오늘의 Codex 요청"}),
        json.dumps({"session_id": "s2", "ts": "2026-09-16T09:00:00+09:00", "text": "다른 날짜"}),
        json.dumps({"session_id": "s3", "ts": "2026-09-15T10:00:00+09:00", "text": "ghp_" + "abcdefghijklmnopqrstuvwxyz1234567890"}),
        json.dumps({"session_id": "s4", "ts": "2026-09-15T11:00:00+09:00", "content": "잘못된 shape"}),
    ]) + "\n", encoding="utf-8")
    values = work_digest.collect_codex_history(path, date(2026, 9, 15))
    assert [item["text"] for item in values] == ["오늘의 Codex 요청"]
    assert all(item["kind"] == "user_request" for item in values)


def test_codex_date_directory_wins_over_newer_other_day_files(tmp_path):
    root = tmp_path / "sessions"
    selected_dir = root / "2026" / "09" / "15"
    other_dir = root / "2026" / "09" / "16"
    selected_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)
    selected = selected_dir / "selected.jsonl"
    selected.write_text("{}\n", encoding="utf-8")
    for index in range(33):
        (other_dir / f"new-{index}.jsonl").write_text("{}\n", encoding="utf-8")
    paths = work_digest._recent_jsonl_paths(root, date(2026, 9, 15), 1, codex=True)
    assert paths == [selected]


def test_codex_selected_directory_enumeration_stops_at_cap(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    selected_dir = root / "2026" / "09" / "15"
    selected_dir.mkdir(parents=True)
    first = selected_dir / "first.jsonl"
    first.write_text("{}\n", encoding="utf-8")
    (selected_dir / "second.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(work_digest, "MAX_ENUM_ENTRIES", 1)
    paths = work_digest._recent_jsonl_paths(root, date(2026, 9, 15), 10, codex=True)
    assert len(paths) <= 1


def test_bounded_sources_each_get_a_turn_and_discovery_is_bounded(tmp_path, monkeypatch):
    codex = tmp_path / "codex"
    claude = tmp_path / "claude"
    codex.mkdir()
    claude.mkdir()
    stamp = "2026-09-16T09:00:00+09:00"
    (claude / "session.jsonl").write_text(json.dumps({"timestamp": stamp, "type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Claude 결과"}]}}) + "\n", encoding="utf-8")
    for index in range(40):
        (codex / f"history-{index}.jsonl").write_text("{}\n", encoding="utf-8")
    (codex / "rollout.jsonl").write_text(json.dumps({"timestamp": stamp, "role": "assistant", "content": "Codex 결과"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(work_digest, "collect_opencode", lambda *_args, **_kwargs: [{"tool": "opencode", "kind": "assistant_final", "text": "OpenCode 결과", "ref": "opaque", "title": ""}])
    values = work_digest.collect_evidence(date(2026, 9, 16), codex_root=codex, claude_root=claude, opencode_db=tmp_path / "none.db", handoff=tmp_path / "none.md", workspace=tmp_path, max_files=2)
    assert {item["tool"] for item in values} >= {"codex", "claude", "opencode"}
    discovered = work_digest.discover_source_paths(codex_root=codex, claude_root=claude, opencode_db=tmp_path / "db", handoff=tmp_path / "handoff", selected=date(2026, 9, 16), max_files=1)
    assert len([path for path in discovered if path.suffix == ".jsonl"]) <= 3


def test_model_malformed_response_falls_back_without_raw_evidence(tmp_path, monkeypatch):
    evidence = [{"tool": "codex", "kind": "user_request", "text": "password=secret 요청", "ref": "codex:opaque", "title": ""}]
    monkeypatch.setattr(work_digest, "summarize_with_model", lambda *_args, **_kwargs: None)
    result = work_digest.generate_digest(date(2026, 9, 16), store_path=tmp_path / "digest.json", source_paths=[tmp_path / "source"], evidence=evidence, now=datetime(2026, 9, 16, 18, 5, tzinfo=work_digest.SEOUL))
    assert result["mode"] == "fallback"
    assert all("secret" not in json.dumps(result) and "password" not in json.dumps(result) for _ in [0])
    assert "password=secret" not in (tmp_path / "digest.json").read_text(encoding="utf-8")


def test_fallback_uses_aggregates_instead_of_verbatim_evidence(tmp_path, monkeypatch):
    subject = "내부 비밀 프로젝트의 아주 구체적인 제목"
    monkeypatch.setattr(work_digest, "summarize_with_model", lambda *_args, **_kwargs: None)
    result = work_digest.generate_digest(
        date(2026, 9, 16), store_path=tmp_path / "digest.json", source_paths=[tmp_path / "source"],
        evidence=[{"tool": "git", "kind": "commit", "text": subject, "ref": "opaque", "title": ""}],
        model_summary=None, now=datetime(2026, 9, 16, 18, 5, tzinfo=work_digest.SEOUL),
    )
    assert subject not in json.dumps(result, ensure_ascii=False)
    assert "완료 기록" in result["completed"][0]


def test_model_json_is_strictly_bounded_and_malformed_is_rejected():
    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self.body

    evidence = [{"tool": "codex", "kind": "user_request", "text": "요청", "ref": "opaque", "title": ""}]
    content = "```json\n" + json.dumps({"completed": ["완료"], "in_progress": [], "cautions": [], "tomorrow": []}, ensure_ascii=False) + "\n```"
    timeouts = []
    payloads = []
    def opener(_request, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        payloads.append(json.loads(_request.data.decode()))
        return Response(json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode())
    summary = work_digest.summarize_with_model(date(2026, 9, 16), evidence, opener=opener)
    assert summary == {"completed": ["완료"], "in_progress": [], "cautions": [], "tomorrow": []}
    assert timeouts == [work_digest.WORK_DIGEST_MODEL_TIMEOUT]
    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": False}
    malformed = lambda *_args, **_kwargs: Response(b"{bad")
    assert work_digest.summarize_with_model(date(2026, 9, 16), evidence, opener=malformed) is None


def test_model_timeout_is_safely_clamped():
    assert work_digest._bounded_model_timeout("5") == 10
    assert work_digest._bounded_model_timeout("240") == 180
    assert work_digest._bounded_model_timeout("invalid") == 120


def test_store_is_atomic_bounded_and_reuses_signature(tmp_path):
    store = tmp_path / "digest.json"
    source = tmp_path / "source.log"
    source.write_text("metadata", encoding="utf-8")
    evidence = [{"tool": "git", "kind": "commit", "text": "완료", "ref": "git:one", "title": ""}]
    for offset in range(35):
        day = date(2026, 8, 1).fromordinal(date(2026, 8, 1).toordinal() + offset)
        work_digest.generate_digest(day, force=True, store_path=store, source_paths=[source], evidence=evidence, model_summary={"completed": ["완료"], "in_progress": [], "cautions": [], "tomorrow": []}, now=datetime.combine(day, datetime.min.time(), tzinfo=work_digest.SEOUL))
    assert len(work_digest.load_digests(store)) == 30
    assert store.stat().st_mode & 0o777 == 0o600
    before = store.read_text(encoding="utf-8")
    reused = work_digest.generate_digest(date(2026, 9, 4), store_path=store, source_paths=[source], evidence=evidence, model_summary={"completed": ["달라진 입력"], "in_progress": [], "cautions": [], "tomorrow": []})
    assert reused["completed"] == ["완료"]
    assert store.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.tmp"))


def test_digest_api_and_once_per_day_notification(monkeypatch):
    import server

    digest = {"date": "2026-09-16", "generated_at": "2026-09-16T18:05:00+09:00", "mode": "fallback", "source_counts": {"codex": 1}, "completed": ["완료"], "in_progress": [], "cautions": [], "tomorrow": [], "source_refs": []}
    monkeypatch.setattr(server.work_digest, "load_digest", lambda selected=None, **_kwargs: digest if str(selected) == "2026-09-16" else None)
    client = TestClient(server.app)
    assert client.get("/api/work-digest?date=2026-09-16").json()["date"] == "2026-09-16"
    preferences = server.AssistantPreferences(morning="09:00", midday="12:00", wrap_up="18:00", quiet_start="23:00", quiet_end="07:00")
    briefing = {"digest": digest, "pending": {"count": 0}, "overdue": {"count": 0}, "goals": {"week": {"items": []}, "day": {"items": []}}}
    notices = server.proactive_notifications(briefing, datetime(2026, 9, 16, 18, 6), preferences)
    assert [item["id"] for item in notices if item["id"].startswith("digest:")] == ["digest:2026-09-16"]
    monkeypatch.setattr(server_storage, "_today_seoul", lambda: date(2026, 9, 16))
    monkeypatch.setattr(server.work_digest, "generate_digest", lambda selected, force=False: digest)
    headers = {"Content-Type": "application/json", "Origin": "http://testserver"}
    assert client.post("/api/work-digest/refresh?date=2026-09-16", headers=headers, json={}).json()["date"] == "2026-09-16"
    assert client.post("/api/work-digest/refresh?date=2026-09-15", headers=headers, json={}).status_code == 422
    assert client.get("/api/work-digest?date=2026-09-15").status_code == 404
    assert client.post("/api/work-digest/refresh?date=2026-09-16").status_code == 415
    assert client.post("/api/work-digest/refresh?date=2026-09-16", headers={"Content-Type": "application/json", "Origin": "https://evil.example"}, json={}).status_code == 403
