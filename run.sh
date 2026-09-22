#!/usr/bin/env bash
# 워크스페이스 포털. 기본은 로컬 전용이다 — 태일넷에 열려면
# PORTAL_HOST=0.0.0.0 으로 실행한다(앱을 띄우는 엔드포인트가 있으니 신중히).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo ">> http://127.0.0.1:${PORTAL_PORT:-8080}"
exec .venv/bin/uvicorn server:app \
  --host "${PORTAL_HOST:-127.0.0.1}" --port "${PORTAL_PORT:-8080}" \
  --timeout-graceful-shutdown 5
