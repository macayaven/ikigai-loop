.PHONY: check test eval demo

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest
	@command -v gitleaks >/dev/null 2>&1 || (echo "error: gitleaks not found on PATH; install it, never skip this step" >&2; exit 1)
	gitleaks git --redact

test:
	uv run pytest

eval:
	mkdir -p logs
	# Keep Inspect's state inside the repo (sandbox-friendly, harmless elsewhere).
	XDG_DATA_HOME=$(CURDIR)/logs/.xdg XDG_CACHE_HOME=$(CURDIR)/logs/.xdg/cache INSPECT_TRACE_FILE=$(CURDIR)/logs/trace.log \
	uv run inspect eval evals/hello.py --model mockllm/model --log-dir logs

demo:
	@echo "not yet"
