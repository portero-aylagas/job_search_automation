#!/usr/bin/env bash
set -euo pipefail

mkdir -p reports

ruff check .

python scripts/report_large_files.py

python - <<'PY'
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
    pytest --junitxml=reports/pytest.xml
else
    echo "No tests found; skipping pytest."
fi

if [ -f package.json ]; then
    npm run frontend:typecheck
    npm run frontend:test
    npm run frontend:build
    npm run frontend:e2e
fi
