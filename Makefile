.PHONY: verify lint test dev clean-local-state

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

dev:
	./scripts/dev_start.sh

clean-local-state:
	# Removes data/runtime, data/candidate_profile.json, outputs, reports, browser artifacts, and caches.
	./scripts/clean_local_state.sh
