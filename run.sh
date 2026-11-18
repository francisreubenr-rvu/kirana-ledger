#!/usr/bin/env bash
# Start the server on all interfaces so the ESP32 on the same Wi-Fi can reach it.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
PY=python; [ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" -m uvicorn server.main:app --host 0.0.0.0 --port "${PORT:-8000}"
