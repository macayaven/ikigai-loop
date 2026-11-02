.PHONY: check test eval demo r1b r2 r3-doc r4-doc verify-page try glimmer-proof audit-control metrics

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest
	@command -v gitleaks >/dev/null 2>&1 || (echo "error: gitleaks not found on PATH; install it, never skip this step" >&2; exit 1)
	gitleaks git --redact

test:
	uv run pytest

metrics:
	uv run python -m framework.metrics report $(METRICS_ARGS)

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

r2:
	uv run python -m evals.r2

r3-doc:
	uv run python -m evals.r3 --summary --write-doc

r4-doc:
	uv run python -m evals.r4 --summary --write-doc

try:
	uv run --no-default-groups try-ikigai

glimmer-proof:
	uv run python -m framework.provenance.glimmer_proof

verify-page:
	uv run python -m framework.verify.page_bundle

audit-control:
	uv run python -m source_audit negative-control
