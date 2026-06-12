#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python interpreter not found: $PYTHON" >&2
    echo "Set PYTHON to a valid interpreter, or install python3." >&2
    exit 127
fi

"$PYTHON" -m ruff --version >/dev/null 2>&1 || {
    echo "ruff is required. Install Python dependencies with: $PYTHON -m pip install -r requirements.txt" >&2
    exit 127
}

"$PYTHON" -m pytest --version >/dev/null 2>&1 || {
    echo "pytest is required. Install Python dependencies with: $PYTHON -m pip install -r requirements.txt" >&2
    exit 127
}

mkdir -p reports

"$PYTHON" -m ruff check .

"$PYTHON" scripts/report_large_files.py

"$PYTHON" - <<'PY'
from pathlib import Path
import compileall

paths = [Path("app.py"), Path("src"), Path("tests")]
existing = [str(path) for path in paths if path.exists()]

if existing:
    ok = all(compileall.compile_file(path, quiet=1) if Path(path).is_file() else compileall.compile_dir(path, quiet=1) for path in existing)
    if not ok:
        raise SystemExit(1)
else:
    print("No Python application paths found; skipping compile step.")
PY

if find tests -type f \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | grep -q .; then
    "$PYTHON" -m pytest --junitxml=reports/pytest.xml
else
    echo "No tests found; skipping pytest."
fi

if [ -f package.json ]; then
    npm run frontend:typecheck
    npm run frontend:test
    npm run frontend:build
    npm run frontend:e2e
fi
