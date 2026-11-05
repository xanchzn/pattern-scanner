#!/bin/sh
set -eu
cd /app/backend
uvicorn main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
cd /app/frontend
./node_modules/.bin/next start -H 0.0.0.0 -p "${PORT:-3000}" &
WEB_PID=$!
shutdown() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; wait || true; }
trap shutdown INT TERM
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 2; done
shutdown
exit 1
