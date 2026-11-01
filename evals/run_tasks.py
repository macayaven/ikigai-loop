"""Run Inspect task files on the mock model and fail loudly on any miss.

``inspect eval`` exits 0 even when a sample scores INCORRECT (measured on
inspect_ai 0.3.285), so this wrapper walks the returned logs instead: it
exits 1 unless every task log has status ``success``, every log holds at
least one sample, and every score on every sample is CORRECT. A sample
with no scores counts as failed. Mock model only, no network.

Each file runs in its own ``inspect_eval`` call, in the order given:
measured that one call over several files silently drops a file with a
syntax error or no tasks when it sits beside a good file, exiting 0 as
if nothing were wrong. One call per file makes a broken file raise (or
return no logs) where it names itself, so every problem shows up.
"""

from __future__ import annotations

import argparse
import sys

from inspect_ai import eval as inspect_eval
from inspect_ai.scorer import CORRECT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Inspect task files and exit 1 unless all pass."
    )
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    if not args.files:
        print("run_tasks: no task files given", file=sys.stderr)
        return 2
    failed = False
    for task_file in args.files:
        try:
            logs = inspect_eval(
                [task_file],
                model="mockllm/model",
                log_dir=args.log_dir,
                display="plain",
            )
        except Exception as exc:  # noqa: BLE001 - every failure must name its file
            print(
                f"FAIL {task_file}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            failed = True
            continue
        if not logs:
            print(f"FAIL {task_file}: no tasks ran", file=sys.stderr)
            failed = True
            continue
        for log in logs:
            task_name = log.eval.task
            status = str(log.status)
            samples = log.samples or []
            correct = 0
            for sample in samples:
                scores = sample.scores or {}
                if not scores:
                    print(
                        f"FAIL {task_name} sample {sample.id}: no scores",
                        file=sys.stderr,
                    )
                    failed = True
                    continue
                bad = [name for name, score in scores.items() if score.value != CORRECT]
                if bad:
                    print(
                        f"FAIL {task_name} sample {sample.id}: "
                        f"non-correct score in {', '.join(sorted(bad))}",
                        file=sys.stderr,
                    )
                    failed = True
                else:
                    correct += 1
            print(f"{task_name}: {correct}/{len(samples)} correct (status={status})")
            if status != "success":
                print(
                    f"FAIL {task_name}: log status is {status}, not success",
                    file=sys.stderr,
                )
                failed = True
            if not samples:
                print(f"FAIL {task_name}: log has no samples", file=sys.stderr)
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
