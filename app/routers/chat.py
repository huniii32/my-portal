"""Morning chat: relay 3호기 vLLM SSE (stateless, browser holds history)."""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.chat import system_prompt
from app.config import VLLM_BASE_URL, VLLM_MODEL
from app.models import ChatRequest

router = APIRouter()


@router.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """3호기 vLLM의 SSE를 그대로 중계한다. 대화 이력은 브라우저가 들고 있다가
    매 요청에 보내므로 서버는 대화 상태를 두지 않는다."""
    body = {
        "model": VLLM_MODEL,
        "messages": [{"role": "system", "content": system_prompt()}]
        + [message.model_dump() for message in request.messages],
        "stream": True,
        "max_tokens": 2048,
        "temperature": 0.3,
    }

    async def relay():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{VLLM_BASE_URL}/chat/completions", json=body
                ) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': f'vLLM {response.status_code}'})}\n\n"
                        return
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            yield f"{line}\n\n"
        except httpx.HTTPError as error:
            # 3호기가 죽어도 화면 전체가 아니라 채팅 영역만 실패해야 한다.
            yield f"data: {json.dumps({'error': f'3호기 연결 실패: {error}'})}\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream")
