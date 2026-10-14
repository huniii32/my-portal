# 노트북 이전 가이드 (portal)

회사 PC(`~/suhun/portal`)에서 개인 노트북으로 옮길 때 그대로는 안 돌아가는 지점 정리.

## 1. 폴더 배치 — 가장 먼저

portal은 **형제 폴더**를 경로로 직접 읽는다 (`app/config.py`의 `WORKSPACE = portal의 부모`).

```
<아무 폴더>/
├─ portal/                 ← git clone https://github.com/huniii32/my-portal.git portal
└─ trading_agent_world/    ← git clone https://github.com/huniii32/trading-agent-world.git trading_agent_world
```

- trading 저장소 이름은 `trading-agent-world`(하이픈)지만 폴더명은 **`trading_agent_world`(밑줄)** 로
  클론해야 한다. 아니면 매매 알림·리스크 상태·공휴일 캐시를 못 찾는다.
- `IPIS_CMT_WEB`은 회사 업무라 옮기지 않는다 → 앱 카드의 IPIS는 항상 "꺼짐"으로 보인다.
  필요 없으면 `app/config.py`의 `APPS["ipis"]`를 지운다.

## 2. LLM(Qwen) — 초기화됨

- `PORTAL_VLLM_BASE_URL` 기본값을 비웠다(원래 회사 내부망 3호기 `192.168.0.85`).
  비어 있으면 아침 채팅은 "LLM 미설정" 오류를, 업무 회고는 요약 없이 원본 근거만 보여준다.
- 노트북에서 쓰려면 OpenAI 호환 엔드포인트를 지정한다.
  ```bash
  export PORTAL_VLLM_BASE_URL=http://127.0.0.1:11434/v1   # 예: Ollama
  export PORTAL_VLLM_MODEL=qwen3:8b
  ```
  API 키 헤더를 보내지 않으므로 키가 필요한 클라우드 API는 코드 수정이 필요하다
  (`app/routers/chat.py`, `digest/collector.py`).

## 3. 실행

```bash
cd portal && ./run.sh      # .venv 없으면 자동 생성 + requirements 설치
```

- Python 3.11+ 필요. `data/`(목표·업무 JSON)는 git에 없다 → 빈 상태로 시작한다.
  기존 데이터를 가져가려면 회사 PC의 `portal/data/`를 따로 복사한다.

## 4. 회사 PC 전용이라 그대로 못 쓰는 것

| 대상 | 문제 | 조치 |
|---|---|---|
| `systemd/suhun-portal.service` 등 | `%h/suhun/portal` 경로·`ipis-cmt-web.service` 의존 | 쓸 거면 경로 수정 후 `~/.config/systemd/user/`에 설치. 안 쓰면 `./run.sh`로 충분 |
| `systemd/suhun-tailscale-proxy@.socket` | 회사 PC Tailscale IP `100.97.194.62` 하드코딩 | 노트북 `tailscale ip -4`로 `ListenStream=` 교체, 아니면 설치하지 않음 |
| `systemd/suhun-work-digest.service` | `-home-ipis-woker1-suhun` 경로(Claude 기록)·`~/suhun/.git`·`HANDOFF.md` 바인딩 | 노트북 홈/사용자명에 맞게 고치거나 회고 기능 미사용 |
| 앱 실행 버튼 (`/api/launch`) | `systemctl --user start ipis-cmt-web / trading-agent-dashboard` 호출 | 노트북에 해당 user unit이 없으면 실패. trading은 `trading_agent_world/dev.sh`로 직접 띄운다 |
| 곰비 데스크톱 펫 (`desktop_pet.py`) | GTK3(PyGObject) + X11 전제, Linux 전용 | Linux: `sudo apt install python3-gi gir1.2-gtk-3.0` 후 시스템 `python3`로 실행. Windows/macOS는 미지원 |
| `digest/collector.py` | `~/.codex`, `~/.claude/projects/...`, opencode DB를 읽음 | 노트북에 없으면 해당 출처만 비고 나머지는 동작 |

## 5. 알려진 테스트 실패

`test/test_goals_tasks.py::test_goal_edit_updates_fields_with_concurrency_check`는
날짜 하드코딩(`2026-09-14`)이라 이전과 무관하게 실패한다.
