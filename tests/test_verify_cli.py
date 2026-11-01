"""Ticket 17a: verify CLI exit codes, output shapes and hostile inputs."""

from __future__ import annotations

import io
import json
import shlex
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from framework.verify import LIMITS_NOTE
from framework.verify.__main__ import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "verify"


def _write(path: Path, data: bytes) -> str:
    path.write_bytes(data)
    return str(path)


@pytest.fixture()
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def _stdin_bytes(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))


def _good_payload() -> dict[str, object]:
    return {
        "claims": [
            {
                "id": "c1",
                "text": "Deploys reached 12 in November",
                "metric_refs": [{"metric_id": "deploys.nov", "value": 12}],
            }
        ],
        "facts": {},
        "metrics": {"deploys.nov": 12},
        "labels": {"deploys.nov": ["deploys", "november"]},
    }


def test_false_number_input_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run([str(EXAMPLES / "input.json")], capsys)
    assert code == 1
    assert err == ""
    assert out.splitlines()[0] == "FAIL"
    assert "L1B_METRIC_VALUE_MISMATCH" in out
    assert LIMITS_NOTE in out


def test_fixed_input_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run([str(EXAMPLES / "input-fixed.json")], capsys)
    assert code == 0
    assert err == ""
    assert out.splitlines()[0] == "PASS"
    assert LIMITS_NOTE in out


def test_worked_readme_pins_real_cli_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _err = _run([str(EXAMPLES / "input.json")], capsys)
    assert code == 1
    readme = (EXAMPLES / "README.md").read_text()
    assert out.strip() in readme
    assert "verify-claims examples/verify/input.json" in readme


def test_json_shape_and_stdin(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(workdir / "in.json", json.dumps(_good_payload()).encode())
    code, out, err = _run([path, "--json"], capsys)
    assert code == 0
    assert err == ""
    body = json.loads(out)
    assert body == {"passed": True, "limits": LIMITS_NOTE, "violations": []}

    _stdin_bytes(monkeypatch, json.dumps(_good_payload()).encode())
    code, out, _err = _run(["-", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["passed"] is True


def test_json_fail_shape(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = _run([str(EXAMPLES / "input.json"), "--json"], capsys)
    assert code == 1
    body = json.loads(out)
    assert body["passed"] is False
    assert body["limits"] == LIMITS_NOTE
    assert body["violations"] == [
        {
            "code": "L1B_METRIC_VALUE_MISMATCH",
            "claim_id": "c1",
            "message": "metric value differs from the snapshot",
        }
    ]


def _hostile_rows() -> list[tuple[str, bytes]]:
    good = _good_payload()
    long_claim = "x" * 2001
    total_over = ["y" * 2000] * 51
    many_claims = [
        {"id": f"c{i}", "text": "The queue looks steady", "fact_ids": ["t1"]}
        for i in range(5001)
    ]
    many_refs = [{"metric_id": f"m{i}", "value": 1} for i in range(101)]
    return [
        ("empty-file", b""),
        ("whitespace-only", b"   \n "),
        ("top-level-list", b"[]"),
        ("missing-claims", json.dumps({"facts": {}, "metrics": {}}).encode()),
        (
            "missing-metrics",
            json.dumps(
                {
                    "claims": [
                        {"id": "c1", "text": "Steady", "fact_ids": ["t1"]},
                    ],
                    "facts": {"t1": "Note filed"},
                }
            ).encode(),
        ),
        (
            "missing-facts",
            json.dumps(
                {
                    "claims": [
                        {"id": "c1", "text": "Steady", "fact_ids": ["t1"]},
                    ],
                    "metrics": {},
                }
            ).encode(),
        ),
        ("nan", b'{"claims": [], "facts": {}, "metrics": {"m": NaN}}'),
        ("infinity", b'{"claims": [], "facts": {}, "metrics": {"m": Infinity}}'),
        ("one-e999", b'{"claims": [], "facts": {}, "metrics": {"m": 1e999}}'),
        (
            "big-int",
            b'{"claims": [], "facts": {}, "metrics": {"m": ' + b"9" * 5000 + b"}}",
        ),
        ("nested", b"[" * 100000),
        ("deep-object", b'{"a":' * 100000),
        ("non-utf8", b'{"claims": ["\xff\xfe"]}'),
        (
            "string-metric-canary",
            json.dumps(
                {
                    "claims": [
                        {"id": "c1", "text": "Steady", "fact_ids": ["t1"]},
                    ],
                    "facts": {"t1": "Note filed"},
                    "metrics": {"canary-row": "12"},
                }
            ).encode(),
        ),
        (
            "unknown-key-canary",
            json.dumps({**good, "canary-row": ["x"]}).encode(),
        ),
        (
            "labels-nonlist-canary",
            json.dumps({**good, "labels": {"canary-row": "deploys"}}).encode(),
        ),
        (
            "label-words-over-cap",
            json.dumps(
                {
                    **good,
                    "labels": {"deploys.nov": [f"w{i}" for i in range(11)]},
                }
            ).encode(),
        ),
        (
            "order-over-cap",
            json.dumps({**good, "order": [[f"m{i}" for i in range(367)]]}).encode(),
        ),
        (
            "string-metric",
            json.dumps({**good, "metrics": {"deploys.nov": "12"}}).encode(),
        ),
        (
            "bool-metric",
            json.dumps({**good, "metrics": {"deploys.nov": True}}).encode(),
        ),
        (
            "null-metric",
            json.dumps({**good, "metrics": {"deploys.nov": None}}).encode(),
        ),
        (
            "dup-ids",
            json.dumps(
                {
                    **good,
                    "claims": [
                        {"id": "c1", "text": "First canary-row"},
                        {"id": "c1", "text": "Second canary-row"},
                    ],
                }
            ).encode(),
        ),
        (
            "dup-keys",
            b'{"claims": [], "claims": [], "facts": {}, "metrics": {}}',
        ),
        (
            "unknown-key",
            json.dumps({**good, "label": ["canary-row"]}).encode(),
        ),
        ("empty-claims", json.dumps({**good, "claims": []}).encode()),
        (
            "blank-deny",
            json.dumps({**good, "deny_terms": ["  ", "canary-row"]}).encode(),
        ),
        (
            "claim-over-cap",
            json.dumps(
                {**good, "claims": [{"id": "c1", "text": long_claim + "canary-row"}]}
            ).encode(),
        ),
        (
            "total-over-cap",
            json.dumps(
                {
                    **good,
                    "claims": [
                        {"id": f"c{i}", "text": t + "canary-row"}
                        for i, t in enumerate(total_over)
                    ],
                }
            ).encode(),
        ),
        (
            "input-over-bytes",
            json.dumps({**good, "facts": {"big": "z" * 10_000_001}}).encode(),
        ),
        ("claims-over-cap", json.dumps({**good, "claims": many_claims}).encode()),
        (
            "refs-over-cap",
            json.dumps(
                {
                    **good,
                    "claims": [
                        {
                            "id": "c1",
                            "text": "canary-row steady",
                            "metric_refs": many_refs,
                        }
                    ],
                }
            ).encode(),
        ),
        (
            "deny-over-cap",
            json.dumps({**good, "deny_terms": ["t"] * 1001}).encode(),
        ),
        (
            "advice-over-cap",
            json.dumps({**good, "advice_words": ["w"] * 1001}).encode(),
        ),
        ("bad-order", json.dumps({**good, "order": [["solo"]]}).encode()),
    ]


@pytest.mark.parametrize(
    "name,data", _hostile_rows(), ids=[n for n, _ in _hostile_rows()]
)
def test_hostile_input_exits_2(
    workdir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    data: bytes,
) -> None:
    if name == "non-utf8":
        _stdin_bytes(monkeypatch, data)
        argv = ["-"]
    else:
        argv = [_write(workdir / "in.json", data)]
    code, out, err = _run(argv, capsys)
    assert code == 2, name
    assert out == "", name
    assert err != "", name
    assert "Traceback" not in err, name
    assert "canary-row" not in err, name


def test_hostile_stdin_text_also_exits_2(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stdin_bytes(monkeypatch, b"not json at all")
    code, out, err = _run(["-"], capsys)
    assert code == 2
    assert out == ""
    assert err != ""
    assert "Traceback" not in err


def test_missing_file_exits_2(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run([str(workdir / "absent.json")], capsys)
    assert code == 2
    assert out == ""
    assert err != ""
    assert "Traceback" not in err


def test_big_int_metric_is_exit_1_not_traceback(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token = "9" * 400
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": f"Deploys reached {token} in November canary-row",
                "metric_refs": [{"metric_id": "deploys.nov", "value": int(token)}],
            }
        ],
        "facts": {},
        "metrics": {"deploys.nov": int(token)},
        "labels": {"deploys.nov": ["deploys", "november"]},
    }
    argv = [_write(workdir / "in.json", json.dumps(payload).encode())]
    code, out, err = _run(argv, capsys)
    assert code == 1
    assert "Traceback" not in err
    assert "canary-row" not in out


def test_28_places_token_backed_by_1_is_exit_1(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    token = "0." + "0" * 27 + "1"
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": f"Share sits at {token} in the log",
                "metric_refs": [{"metric_id": "share", "value": 1}],
                "fact_ids": ["t1"],
            }
        ],
        "facts": {"t1": "Log note filed"},
        "metrics": {"share": 1},
    }
    argv = [_write(workdir / "in.json", json.dumps(payload).encode())]
    code, out, _err = _run(argv, capsys)
    assert code == 1
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in out


def test_hostile_claim_id_escaped_in_both_outputs(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile_id = "c1\ud83d\x07bad"
    payload = {
        "claims": [{"id": hostile_id, "text": "The queue looks steady"}],
        "facts": {},
        "metrics": {},
    }
    argv = [_write(workdir / "in.json", json.dumps(payload).encode())]
    code, out, _ = _run(argv, capsys)
    assert code == 1
    assert hostile_id not in out
    code, out, _ = _run([*argv, "--json"], capsys)
    assert code == 1
    json.loads(out)


def test_big_fact_string_still_passes(
    workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "claims": [{"id": "c1", "text": "The queue looks steady", "fact_ids": ["t1"]}],
        "facts": {"t1": "n" * 5_000_000},
        "metrics": {},
    }
    argv = [_write(workdir / "in.json", json.dumps(payload).encode())]
    code, out, _ = _run(argv, capsys)
    assert code == 0
    assert out.splitlines()[0] == "PASS"


def test_no_network_needed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "socket", _boom)
    for argv, expected in (
        ([str(EXAMPLES / "input.json")], 1),
        ([str(EXAMPLES / "input-fixed.json")], 0),
    ):
        code, _, _ = _run(argv, capsys)
        assert code == expected


def test_dash_flag_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["--help"], ["--nope"]):
        code, out, err = _run(argv, capsys)
        assert code == 2
        assert out == ""
        assert err == "usage: verify-claims [--json] <input.json|->\n"


def test_main_with_replaced_stdout(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(workdir / "in.json", json.dumps(_good_payload()).encode())
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    code = main([path])
    assert code == 0
    assert buffer.getvalue().splitlines()[0] == "PASS"
    assert LIMITS_NOTE in buffer.getvalue()


def test_closed_pipe_keeps_normal_exit_code() -> None:
    import os
    import subprocess

    root = Path(__file__).resolve().parents[1]
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "framework.verify", str(EXAMPLES / "input.json")],
            stdout=write_fd,
            stderr=subprocess.PIPE,
            cwd=root,
            timeout=120,
            check=False,
        )
    finally:
        os.close(write_fd)
    assert proc.returncode == 1
    assert proc.stderr == b""


def test_fixed_input_changes_the_claim_not_the_records() -> None:
    fixed = json.loads((EXAMPLES / "input-fixed.json").read_text())
    broken = json.loads((EXAMPLES / "input.json").read_text())
    assert fixed["metrics"] == broken["metrics"]
    assert fixed["facts"] == broken["facts"]


ROOT = Path(__file__).resolve().parents[1]


def _subprocess_cli(
    argv: list[str], data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "framework.verify", *argv],
        input=data,
        capture_output=True,
        cwd=ROOT,
        timeout=60,
        check=False,
    )


def _shape_file(workdir: Path, name: str, data: bytes) -> str:
    path = workdir / name
    path.write_bytes(data)
    return str(path)


def test_unclosed_string_exits_2(workdir: Path) -> None:
    for data in (b'"' + b'\\"' * 1_000_000, b'"' + b'\\"' * 1_000_000 + b"\\"):
        proc = _subprocess_cli([_shape_file(workdir, "in.json", data)])
        assert proc.returncode == 2
        assert proc.stdout == b""
        assert b"input is not valid JSON" in proc.stderr
        assert b"Traceback" not in proc.stderr


def _million_bad_list_payloads() -> list[tuple[str, bytes, str]]:
    bad_claims = b"[" + b"1," * 999_999 + b"1]"
    refs = b"[" + b"1," * 999_999 + b"1]"
    fact_ids = b"[" + b"1," * 999_999 + b"1]"
    order = b"[" + b"1," * 999_999 + b"1]"
    terms = b"[" + b"1," * 999_999 + b"1]"
    return [
        (
            "claims",
            b'{"claims":' + bad_claims + b',"facts":{},"metrics":{}}',
            "claims.0: must be an object",
        ),
        (
            "metric_refs",
            b'{"claims":[{"id":"c1","text":"Steady","metric_refs":'
            + refs
            + b'}],"facts":{},"metrics":{}}',
            "claims.0.metric_refs.0",
        ),
        (
            "fact_ids",
            b'{"claims":[{"id":"c1","text":"Steady","fact_ids":'
            + fact_ids
            + b'}],"facts":{},"metrics":{}}',
            "claims.0.fact_ids.0",
        ),
        (
            "order",
            b'{"claims":[{"id":"c1","text":"Steady"}]'
            + b',"facts":{},"metrics":{},"order":'
            + order
            + b"}",
            "order.0",
        ),
        (
            "deny_terms",
            b'{"claims":[{"id":"c1","text":"Steady"}]'
            + b',"facts":{},"metrics":{},"deny_terms":'
            + terms
            + b"}",
            "deny_terms.0",
        ),
    ]


@pytest.mark.parametrize(
    "name,data,marker",
    _million_bad_list_payloads(),
    ids=["claims", "metric_refs", "fact_ids", "order", "deny_terms"],
)
def test_million_bad_list_items_stop_at_first(
    workdir: Path, name: str, data: bytes, marker: str
) -> None:
    proc = _subprocess_cli([_shape_file(workdir, "in.json", data)])
    assert proc.returncode == 2, name
    assert proc.stdout == b"", name
    err = proc.stderr.decode("utf-8", "replace")
    assert marker in err, name
    assert "more" not in err, name
    assert "Traceback" not in err, name
    if name == "claims":
        assert err.strip() == "claims.0: must be an object"


def test_half_million_bad_fact_values_is_one_line(workdir: Path) -> None:
    facts = b"{" + b",".join(b'"k%d":0' % i for i in range(500_000)) + b"}"
    data = (
        b'{"claims":[{"id":"c1","text":"Steady"}],"facts":' + facts + b',"metrics":{}}'
    )
    proc = _subprocess_cli([_shape_file(workdir, "in.json", data)])
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"Traceback" not in proc.stderr
    assert proc.stderr.strip().count(b"\n") == 0


def test_half_million_unknown_keys_is_one_line(workdir: Path) -> None:
    extra = b",".join(b'"k%d":0' % i for i in range(500_000))
    data = (
        b'{"claims":[{"id":"c1","text":"Steady","fact_ids":["t1"]}],'
        b'"facts":{"t1":"Note filed"},"metrics":{},' + extra + b"}"
    )
    proc = _subprocess_cli([_shape_file(workdir, "in.json", data)])
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"Traceback" not in proc.stderr
    assert proc.stderr.strip().count(b"\n") == 0


def _letters(n: int) -> str:
    return "".join(chr(97 + (n // 26**k) % 26) for k in range(4))


def test_many_series_against_many_claims(workdir: Path) -> None:
    series = [[f"s{i}a", f"s{i}b"] for i in range(100_000)]
    labels = {f"s{i}a": [f"wa{_letters(i)}"] for i in range(100_000)}
    labels.update({f"s{i}b": [f"wb{_letters(i)}"] for i in range(100_000)})
    first_word = f"wa{_letters(0)}"
    payload = {
        "claims": [
            {"id": f"c{i}", "text": "steady note", "fact_ids": ["t1"]}
            for i in range(5000)
        ],
        "facts": {"t1": "Note filed"},
        "metrics": {"s0a": 5},
        "labels": labels,
        "order": series,
    }
    claims = payload["claims"]
    assert isinstance(claims, list)
    claims[0] = {
        "id": "c0",
        "text": f"{first_word} steady note",
        "fact_ids": ["t1"],
        "metric_refs": [{"metric_id": "s0a", "value": 5}],
    }
    data = json.dumps(payload).encode()
    assert len(data) < 10_000_000
    proc = _subprocess_cli([_shape_file(workdir, "in.json", data)])
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    assert proc.stderr == b""


def test_long_label_words_against_many_claims(workdir: Path) -> None:
    members = [f"m{i}" for i in range(366)]
    labels = {"m0": ["deploys"]}
    for member in members[1:]:
        labels[member] = [(f"{member}x{j}" + "z" * 100)[:100] for j in range(10)]
        assert all(len(word) == 100 for word in labels[member])
    payload = {
        "claims": [
            {
                "id": f"c{i}",
                "text": "Deploys steady note",
                "metric_refs": [{"metric_id": "m0", "value": 5}],
            }
            for i in range(5000)
        ],
        "facts": {},
        "metrics": {"m0": 5},
        "labels": labels,
        "order": [members],
    }
    proc = _subprocess_cli(
        [_shape_file(workdir, "in.json", json.dumps(payload).encode())]
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    assert proc.stderr == b""


def _sh(script: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True,
        cwd=ROOT,
        timeout=60,
        check=False,
    )


def test_closed_streams_have_no_traceback(workdir: Path) -> None:
    good = _shape_file(workdir, "good.json", json.dumps(_good_payload()).encode())
    bad = str(EXAMPLES / "input.json")
    missing = str(workdir / "absent.json")
    python = shlex.quote(sys.executable)

    proc = _sh(f"{python} -m framework.verify - <&-")
    assert proc.returncode == 2
    assert b"Traceback" not in proc.stderr
    assert b"Traceback" not in proc.stdout

    proc = _sh(f"{python} -m framework.verify {shlex.quote(good)} >&-")
    assert proc.returncode == 0
    assert proc.stderr == b""
    assert b"Traceback" not in proc.stdout

    proc = _sh(f"{python} -m framework.verify {shlex.quote(bad)} >&-")
    assert proc.returncode == 1
    assert b"Traceback" not in proc.stderr
    assert b"Traceback" not in proc.stdout

    proc = _sh(f"{python} -m framework.verify {shlex.quote(missing)} 2>&-")
    assert proc.returncode == 2

    subdir = workdir / "somedir"
    subdir.mkdir()
    # A directory as the file argument reaches our reader: exit 2, fixed text.
    proc = _sh(f"{python} -m framework.verify {shlex.quote(str(subdir))}")
    assert proc.returncode == 2
    assert b"input file cannot be read" in proc.stderr
    assert b"Traceback" not in proc.stderr
    # A directory on stdin never reaches our code: CPython refuses to start
    # ("init_sys_streams: <stdin> is a directory") and exits 1 itself.
    proc = _sh(f"{python} -m framework.verify - < {shlex.quote(str(subdir))}")
    assert proc.returncode == 1
    assert b"is a directory" in proc.stderr
    assert b"Traceback" not in proc.stderr


def test_keyboard_interrupt_returns_130(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import framework.verify.__main__ as cli

    def _interrupted(_path: str) -> bytes:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_read_input", _interrupted)
    code, out, err = _run(["-"], capsys)
    assert code == 130
    assert out == ""
    assert err == ""


def test_padded_input_at_the_byte_cap(workdir: Path) -> None:
    raw = json.dumps(_good_payload()).encode()
    assert len(raw) < 10_000_000
    exact = b" " * (10_000_000 - len(raw)) + raw
    assert len(exact) == 10_000_000
    proc = _subprocess_cli([_shape_file(workdir, "exact.json", exact)])
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    proc = _subprocess_cli(["-"], data=exact)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    over = exact + b" "
    proc = _subprocess_cli([_shape_file(workdir, "over.json", over)])
    assert proc.returncode == 2
    assert b"MAX_INPUT_BYTES" in proc.stderr
    assert proc.stdout == b""
    proc = _subprocess_cli(["-"], data=over)
    assert proc.returncode == 2
    assert b"MAX_INPUT_BYTES" in proc.stderr
    assert proc.stdout == b""


def test_positional_count_is_usage_error() -> None:
    for argv in ([], ["a.json", "b.json"]):
        proc = _subprocess_cli(argv)
        assert proc.returncode == 2
        assert proc.stdout == b""
        assert proc.stderr == b"usage: verify-claims [--json] <input.json|->\n"
        assert b"Traceback" not in proc.stderr
