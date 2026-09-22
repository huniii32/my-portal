"""워크스페이스 메인 포털 — backward-compat 진입점.

실구현은 app/ 패키지에 있다:
  app/config.py          경로·레지스트리·상수
  app/models.py          goals/tasks/assistant/chat 모델
  app/storage.py         JSON 저장소
  app/assistant.py       브리핑·proactive·SSE
  app/trading.py         트레이딩 읽기 전용 요약
  app/holidays.py        공휴일 캐시·폴백
  app/chat.py            아침 정리 프롬프트
  app/routers/*.py       엔드포인트

`uvicorn server:app`, `from server import app, APPS`는 그대로 동작한다.
"""

from app import *  # noqa: F401,F403
from app import app  # noqa: F401
