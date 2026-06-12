#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python interpreter not found: $PYTHON" >&2
  echo "Set PYTHON to a valid interpreter, or install python3." >&2
  exit 127
fi

PIDS=()

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [ "${#PIDS[@]}" -gt 0 ]; then
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
  exit "$status"
}

trap cleanup EXIT INT TERM

echo "Starting FastAPI backend on http://127.0.0.1:8001"
"$PYTHON" -m uvicorn src.api:app --host 127.0.0.1 --port 8001 --reload &
PIDS+=("$!")

echo "Starting Vite frontend on http://127.0.0.1:5173"
npm run frontend:dev &
PIDS+=("$!")

echo "Press Ctrl+C to stop both development servers."
wait -n "${PIDS[@]}"
