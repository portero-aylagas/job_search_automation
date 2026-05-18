.PHONY: verify lint test

verify:
	./verify.sh

lint:
	ruff check .

test:
	@if find tests -type f \( -name 'test_*.py' -o -name '*_test.py' \) 2>/dev/null | grep -q .; then \
		pytest; \
	else \
		echo "No tests found; skipping pytest."; \
	fi
