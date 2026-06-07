#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="$ROOT_DIR/.conda/bin:$PATH"

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
uvicorn src.api:app --host 127.0.0.1 --port 8001 --reload &
PIDS+=("$!")

echo "Starting Vite frontend on http://127.0.0.1:5173"
npm run frontend:dev &
PIDS+=("$!")

echo "Press Ctrl+C to stop both development servers."
wait -n "${PIDS[@]}"
