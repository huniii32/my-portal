"""목표 직접관리 + 할 일-목표 연결 테스트.

규칙:
- 목표는 id(연결 키)를 갖고, 수치형/체크형(kind)을 구분한다.
- 구 파일(id 없음)은 읽을 때 id를 부여해 저장한다.
- 할 일은 goal_id·priority·memo를 갖고, 기간 조회(from/to)가 된다.
"""
import json

from fastapi.testclient import TestClient

from app import config as server_config
from server import app

client = TestClient(app)


def _goals_payload(**overrides):
    payload = {
        "week": {"start": "2026-09-14", "items": []},
        "day": {"date": "2026-09-15", "items": []},
    }
    payload.update(overrides)
    return payload


def test_goal_create_assigns_id_and_defaults(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    response = client.post(
        "/api/goals/week",
        json={"project": "ipis", "goal": "전화 돌리기", "target": 10, "current": 0, "unit": "건"},
    )
    assert response.status_code == 201
    item = response.json()["week"]["items"][0]
    assert len(item["id"]) == 32
    assert item["kind"] == "numeric"
    assert item["memo"] == ""


def test_goal_create_checklist_needs_no_target(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    response = client.post(
        "/api/goals/day",
        json={"project": "ipis", "goal": "출근 준비", "kind": "checklist"},
    )
    assert response.status_code == 201
    assert response.json()["day"]["items"][0]["kind"] == "checklist"


def test_goal_create_rejects_bad_numeric(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    assert client.post("/api/goals/week", json={"project": "ipis", "goal": "x", "target": 0}).status_code == 422
    assert client.post("/api/goals/week", json={"project": "nope", "goal": "x", "target": 1}).status_code == 422


def test_goal_edit_updates_fields_with_concurrency_check(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    assert client.post(
        "/api/goals/week",
        json={"project": "ipis", "goal": "A", "target": 10, "current": 0, "unit": "건"},
    ).status_code == 201
    current = client.get("/api/goals").json()
    item = current["week"]["items"][0]
    body = {
        "goal": "A 수정",
        "target": 20,
        "memo": "메모",
        "expected": item,
        "expected_date": "2026-09-14",
    }
    response = client.patch("/api/goals/week/0", json=body)
    assert response.status_code == 200
    updated = response.json()["week"]["items"][0]
    assert updated["goal"] == "A 수정"
    assert updated["target"] == 20
    assert updated["memo"] == "메모"
    assert updated["id"] == item["id"]
    # 같은 expected로 다시 보내면 409
    assert client.patch("/api/goals/week/0", json=body).status_code == 409
    # 변경 내용 없이 보내면 422
    assert client.patch(
        "/api/goals/week/0",
        json={"expected": updated, "expected_date": "2026-09-14"},
    ).status_code == 422


def test_goal_delete_unlinks_tasks(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    monkeypatch.setattr(server_config, "TASKS_PATH", tmp_path / "tasks.json")
    assert client.post(
        "/api/goals/day",
        json={"project": "ipis", "goal": "B", "kind": "checklist"},
    ).status_code == 201
    goal_id = client.get("/api/goals").json()["day"]["items"][0]["id"]
    task = client.post(
        "/api/tasks",
        json={"date": "2026-09-15", "title": "연결된 일", "goal_id": goal_id},
    ).json()
    assert task["goal_id"] == goal_id
    assert client.delete("/api/goals/day/0").status_code == 200
    assert client.get("/api/goals").json()["day"]["items"] == []
    remaining = client.get("/api/tasks?date=2026-09-15").json()
    assert remaining[0]["goal_id"] is None
    assert remaining[0]["title"] == "연결된 일"


def test_legacy_goals_file_gets_ids_on_read(tmp_path, monkeypatch):
    import server

    path = tmp_path / "goals.json"
    monkeypatch.setattr(server_config, "GOALS_PATH", path)
    path.write_text(
        json.dumps(
            {"week": {"start": "2026-09-14", "items": [{"project": "ipis", "goal": "旧", "target": 1, "unit": "건"}]},
             "day": {"date": "2026-09-15", "items": []}},
        ),
        encoding="utf-8",
    )
    body = client.get("/api/goals").json()
    assert len(body["week"]["items"][0]["id"]) == 32
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["week"]["items"][0]["id"] == body["week"]["items"][0]["id"]


def test_task_create_with_goal_priority_memo(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    monkeypatch.setattr(server_config, "TASKS_PATH", tmp_path / "tasks.json")
    assert client.post(
        "/api/goals/week",
        json={"project": "ipis", "goal": "C", "kind": "checklist"},
    ).status_code == 201
    goal_id = client.get("/api/goals").json()["week"]["items"][0]["id"]
    created = client.post(
        "/api/tasks",
        json={"date": "2026-09-15", "title": "  중요한 일  ", "goal_id": goal_id, "priority": "high", "memo": "오전까지"},
    ).json()
    assert created["title"] == "중요한 일"
    assert created["priority"] == "high"
    assert created["memo"] == "오전까지"
    # 없는 목표에 연결하면 422
    assert client.post(
        "/api/tasks",
        json={"date": "2026-09-15", "title": "x", "goal_id": "0" * 32},
    ).status_code == 422


def test_task_update_fields_and_link_endpoint(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "GOALS_PATH", tmp_path / "goals.json")
    monkeypatch.setattr(server_config, "TASKS_PATH", tmp_path / "tasks.json")
    assert client.post(
        "/api/goals/week",
        json={"project": "ipis", "goal": "D", "kind": "checklist"},
    ).status_code == 201
    goal_id = client.get("/api/goals").json()["week"]["items"][0]["id"]
    task = client.post("/api/tasks", json={"date": "2026-09-15", "title": "할 일"}).json()
    assert task["priority"] == "mid"
    assert task["goal_id"] is None
    updated = client.patch(
        f"/api/tasks/{task['id']}", json={"title": "바뀐 일", "priority": "low", "memo": "메모"}
    ).json()
    assert updated["title"] == "바뀐 일"
    assert updated["priority"] == "low"
    assert client.patch(f"/api/tasks/{task['id']}", json={}).status_code == 422
    linked = client.patch(f"/api/tasks/{task['id']}/link", json={"goal_id": goal_id}).json()
    assert linked["goal_id"] == goal_id
    assert client.patch(f"/api/tasks/{task['id']}/link", json={"goal_id": "0" * 32}).status_code == 422
    unlinked = client.patch(f"/api/tasks/{task['id']}/link", json={"goal_id": None}).json()
    assert unlinked["goal_id"] is None


def test_tasks_range_query(tmp_path, monkeypatch):
    import server

    monkeypatch.setattr(server_config, "TASKS_PATH", tmp_path / "tasks.json")
    for day in ("2026-09-14", "2026-09-15", "2026-09-20"):
        assert client.post("/api/tasks", json={"date": day, "title": f"{day} 일"}).status_code == 201
    body = client.get("/api/tasks?from=2026-09-14&to=2026-09-15").json()
    assert [task["date"] for task in body] == ["2026-09-14", "2026-09-15"]
    assert client.get("/api/tasks?from=2026-09-15&to=2026-09-14").status_code == 422
    assert client.get("/api/tasks?from=bad&to=2026-09-15").status_code == 422
    # 기존 단일 날짜 조회는 그대로 동작한다
    assert len(client.get("/api/tasks?date=2026-09-20").json()) == 1
