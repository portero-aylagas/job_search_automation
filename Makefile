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
	rm -rf data/runtime data/candidate_profile.json
	@if [ -d outputs ]; then \
		find outputs -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +; \
	fi
