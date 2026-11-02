.PHONY: check test eval demo r1b verify-page

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest
	@command -v gitleaks >/dev/null 2>&1 || (echo "error: gitleaks not found on PATH; install it, never skip this step" >&2; exit 1)
	gitleaks git --redact

test:
	uv run pytest

EVAL_FILES = evals/hello.py evals/briefing_gate.py evals/glimmer_facts.py evals/proposal_gate.py

eval:
	mkdir -p logs
	# Keep Inspect's state inside the repo (sandbox-friendly, harmless elsewhere).
	XDG_DATA_HOME=$(CURDIR)/logs/.xdg XDG_CACHE_HOME=$(CURDIR)/logs/.xdg/cache INSPECT_TRACE_FILE=$(CURDIR)/logs/trace.log \
	uv run python evals/run_tasks.py --log-dir logs $(EVAL_FILES)

demo:
	@uv run python evals/demo_rejection.py

r1b:
	uv run python -m evals.r1b --all $(R1B_ARGS)

verify-page:
	uv run python -m framework.verify.page_bundle
