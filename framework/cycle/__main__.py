"""Ticket 9: ``python -m framework.cycle facts`` CLI (counts/codes only)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from framework.cycle import run_cycle
from framework.glimmer.facts import FactResult, LLMClient, LLMResponse
from framework.glimmer.llm import OpenAICompatibleClient, load_llm_config
from framework.store.fact_store import FactStore
from framework.store.store import EventStore


def _build_llm() -> LLMClient:
    config = load_llm_config()
    return OpenAICompatibleClient(
        base_url=config.base_url, model=config.model, api_key=config.api_key
    )


def _format_pass(
    kept: int, reason: str | None, latency_ms: int, finish: str | None
) -> str:
    return f"{kept}:{reason or '-'}:{latency_ms / 1000:.1f}s:{finish or '-'}"


class _NeverCalledStub:
    """LLM stand-in for code-only cycles; any call is a bug."""

    def complete(self, prompt: str) -> LLMResponse:
        raise AssertionError("model pass skipped: the stub must never be called")


def _format_line(result: FactResult, run: int) -> str:
    personal, feed = result.passes
    codes = ",".join(d.code for d in result.dropped) or "-"
    code = len(result.code_fact_ids)
    return (
        f"cycle={result.cycle_id} run={run} kept={len(result.facts)}"
        f" code={code} model={len(result.facts) - code}"
        f" dropped={len(result.dropped)} noop={result.noop_reason or '-'}"
        f" personal={_format_pass(personal.kept, personal.noop_reason, personal.latency_ms, personal.finish_reason)}"
        f" feed={_format_pass(feed.kept, feed.noop_reason, feed.latency_ms, feed.finish_reason)}"
        f" codes={codes}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m framework.cycle")
    sub = parser.add_subparsers(dest="command", required=True)
    facts = sub.add_parser("facts")
    facts.add_argument("--as-of", required=True)
    facts.add_argument("--subject-id", default=None)
    facts.add_argument("--db", default=None)
    facts.add_argument("--no-personal-pass", action="store_true")
    facts.add_argument("--no-feed-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        as_of = datetime.fromisoformat(args.as_of)
    except ValueError:
        print("error: --as-of must be an ISO-8601 datetime", file=sys.stderr)
        return 2
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        print("error: --as-of must carry a UTC offset", file=sys.stderr)
        return 2
    subject_id = args.subject_id or os.environ.get("IKIGAI_SUBJECT_ID", "")
    if not subject_id:
        print(
            "error: set --subject-id or IKIGAI_SUBJECT_ID",
            file=sys.stderr,
        )
        return 2
    db_path = Path(args.db) if args.db else None
    skip_personal = bool(args.no_personal_pass)
    skip_feed = bool(args.no_feed_pass)
    if skip_personal and skip_feed:
        llm: LLMClient = _NeverCalledStub()
    else:
        llm = _build_llm()
    try:
        store = EventStore(db_path=db_path)
        try:
            fact_store = FactStore(db_path=store.db_path)
            try:
                result, run = run_cycle(
                    as_of,
                    subject_id,
                    store,
                    fact_store,
                    llm,
                    personal_pass=not skip_personal,
                    feed_pass=not skip_feed,
                )
            finally:
                fact_store.close()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001 -- the CLI maps every failure to one line
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(_format_line(result, run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
