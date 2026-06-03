.PHONY: verify lint test clean-local-state

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

clean-local-state:
	# Removes data/runtime, data/candidate_profile.json, generated outputs, reports, and caches.
	./scripts/clean_local_state.sh
