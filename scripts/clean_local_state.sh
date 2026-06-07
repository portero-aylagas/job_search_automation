#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# data/runtime includes job workspaces, candidate uploads, Karen transcripts,
# and Browser Use runtime state. It is local private/generated state.
rm -rf \
  "$ROOT_DIR/data/runtime" \
  "$ROOT_DIR/data/candidate_profile.json" \
  "$ROOT_DIR/reports" \
  "$ROOT_DIR/playwright-report" \
  "$ROOT_DIR/test-results" \
  "$ROOT_DIR/dist" \
  "$ROOT_DIR/.pytest_cache" \
  "$ROOT_DIR/.ruff_cache" \
  "$ROOT_DIR/.vite" \
  "$ROOT_DIR/__pycache__" \
  "$ROOT_DIR/src/__pycache__" \
  "$ROOT_DIR/tests/__pycache__" \
  "$ROOT_DIR/src/agents/__pycache__" \
  "$ROOT_DIR/src/api/__pycache__" \
  "$ROOT_DIR/src/services/__pycache__" \
  "$ROOT_DIR/src/workflow/__pycache__"

if [ -d "$ROOT_DIR/outputs" ]; then
  find "$ROOT_DIR/outputs" -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
fi
