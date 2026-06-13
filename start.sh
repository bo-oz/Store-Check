#!/usr/bin/env bash
# Starts backend + frontend in parallel. Press Ctrl-C to stop both.
set -e
cd "$(dirname "$0")"

echo "▶ Starting FastAPI backend on :8000"
(cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

echo "▶ Starting Vue dev server on :5173"
(cd frontend && npm run dev -- --port 5173) &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
wait
