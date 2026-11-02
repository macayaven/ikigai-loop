"""Ticket 15b Step 3 — R2 privacy receipt (offline, no model, no network).

I plant distinct synthetic canaries in every inventoried free-text field of
a replayed raw stream, run whole slots (facts, proposal, card) against
adversarial fakes, and scan every recorded outbound body for them.

Nothing here touches the network or a model: local fakes answer in
process, the Wonder runners return scripted completed streams, the Meta
transport is a recorder, and Telegram goes through the real client over
the ``_open_url`` seam. A socket guard fails the run if anything tries.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from framework.proposal.muse_client import RunResult

MADRID = ZoneInfo("Europe/Madrid")

SLOT = datetime(2026, 11, 3, 15, 30, tzinfo=MADRID)
SUBJECT = "subject-r2"

CONTROL_PHRASE = "Zorpaline harbor light"
CONTROL_WORD = "zorpaline"

DENY_WORD = "wumblen"
DENY_PHRASE = "wumblen"

USAGE_MODEL_PATH = "vault/runnexal/synthrunner"

CHANNELS = (
    "wonder_prompt",
    "meta_body",
    "telegram",
    "why_reply",
    "trace",
    "chart_input",
    "card_stored",
    "stored_outbound",
    "stdout_stderr",
)

BY_DESIGN_LINES = {
    "feed-topic": "feed text as a short topic of at most 6 words",
    "public-repo": "public repo names on public-tier rows",
    "hand-tag": "hand tags written literally in a title",
    "metric-label": "metric labels that go out as metric ids",
}

FINDING_CHANNELS_NOTE = (
    "anything found outbound that is not one of the four by-design lines"
)

Canary = dict[str, Any]

CANARIES: tuple[Canary, ...] = (
    {
        "id": "cal-summary",
        "word": "flimbrel",
        "phrase": "Flimbrel morning drift",
        "type": "calendar.event.created",
        "field": "SUMMARY",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "cal-summary-tag",
        "word": "grundvik",
        "phrase": "Weekly review iki-grundvik",
        "type": "calendar.event.created",
        "field": "SUMMARY",
        "disposition": "planted-via-collector",
        "by_design": "hand-tag",
        "plant": "collector",
    },
    {
        "id": "cal-care",
        "word": "iki-care",
        "phrase": "Flurble iki-care trundle",
        "type": "calendar.event.created",
        "field": "SUMMARY",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "cal-location",
        "word": "hallovex",
        "phrase": "Hallovex annex",
        "type": "calendar.event.created",
        "field": "LOCATION",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "cal-category",
        "word": "zindralk",
        "phrase": "zindralk",
        "type": "calendar.event.created",
        "field": "category",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "envelope-source-id",
        "word": "sourcixa",
        "phrase": "ical-sourcixa-aa",
        "type": "envelope",
        "field": "source_id",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "envelope-collector-version",
        "word": "verplaqo",
        "phrase": "verplaqo",
        "type": "envelope",
        "field": "collector_version",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "label-target",
        "word": "targovex",
        "phrase": "targovex-aa",
        "type": "calendar.label",
        "field": "target_event_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "label-model",
        "word": "modelvexa",
        "phrase": "modelvexa-aa",
        "type": "calendar.label",
        "field": "model_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "gh-push-repo",
        "word": "dremblor",
        "phrase": "quarnkeep/dremblor",
        "type": "github.push",
        "field": "repo",
        "disposition": "planted-via-collector",
        "by_design": "public-repo",
        "plant": "collector",
    },
    {
        "id": "gh-pr-repo",
        "word": "plorvint",
        "phrase": "quarnkeep/plorvint",
        "type": "github.pr",
        "field": "repo",
        "disposition": "planted-via-collector",
        "by_design": "public-repo",
        "plant": "collector",
    },
    {
        "id": "gh-issue-repo",
        "word": "skindrel",
        "phrase": "quarnkeep/skindrel",
        "type": "github.issue",
        "field": "repo",
        "disposition": "planted-via-collector",
        "by_design": "public-repo",
        "plant": "collector",
    },
    {
        "id": "gh-release-repo",
        "word": "troblequ",
        "phrase": "quarnkeep/troblequ",
        "type": "github.release",
        "field": "repo",
        "disposition": "planted-via-collector",
        "by_design": "public-repo",
        "plant": "collector",
    },
    {
        "id": "gh-commit-message",
        "word": "commivex",
        "phrase": "Commivex release notes",
        "type": "github.push",
        "field": "commit-message",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "gh-counts-key",
        "word": "keyvraxo",
        "phrase": "keyvraxo",
        "type": "github.push",
        "field": "counts",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "gh-private-repo",
        "word": "wumblenpriv",
        "phrase": "quarnkeep/wumblenpriv",
        "type": "github.push",
        "field": "repo",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "deny-term",
        "word": "wumblen",
        "phrase": "wumblen",
        "type": "private_terms",
        "field": "deny-terms.txt",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "terms",
    },
    {
        "id": "feed-title",
        "word": "yemblora",
        "phrase": "Yemblora meadow drift",
        "type": "feed.item",
        "field": "title",
        "disposition": "planted-via-collector",
        "by_design": "feed-topic",
        "plant": "collector",
    },
    {
        "id": "feed-url",
        "word": "zorphelu",
        "phrase": "https://example.invalid/zorphelu",
        "type": "feed.item",
        "field": "url",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "feed-source",
        "word": "sorsplaq",
        "phrase": "sorsplaq",
        "type": "feed.item",
        "field": "source",
        "disposition": "planted-via-store",
        "by_design": "metric-label",
        "plant": "store",
    },
    {
        "id": "music-track",
        "word": "melpraxo",
        "phrase": "Melpraxo evening song",
        "type": "music.play",
        "field": "track",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "music-artist",
        "word": "artovexa",
        "phrase": "Artovexa ensemble",
        "type": "music.play",
        "field": "artist",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "screen-category",
        "word": "catovrex",
        "phrase": "catovrex",
        "type": "screen.hour",
        "field": "minutes_by_category",
        "disposition": "planted-via-store",
        "by_design": "metric-label",
        "plant": "store",
    },
    {
        "id": "screen-app",
        "word": "flumjexa",
        "phrase": "Flumjexa",
        "type": "screen.hour",
        "field": "app",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "screen-title",
        "word": "titrevox",
        "phrase": "Titrevox quarterly review",
        "type": "screen.hour",
        "field": "title",
        "disposition": "planted-via-collector",
        "by_design": None,
        "plant": "collector",
    },
    {
        "id": "editor-project",
        "word": "projexil",
        "phrase": "Projexil",
        "type": "editor.hour",
        "field": "project",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "editor-language",
        "word": "langzorq",
        "phrase": "Langzorq",
        "type": "editor.hour",
        "field": "language",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "view-block",
        "word": "blorvixa",
        "phrase": "blorvixa",
        "type": "app.view",
        "field": "block_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "view-screen",
        "word": "screnvix",
        "phrase": "screnvix",
        "type": "app.view",
        "field": "screen",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "tap-block",
        "word": "tapvexil",
        "phrase": "tapvexil",
        "type": "app.tap",
        "field": "block_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "tap-target",
        "word": "targvelt",
        "phrase": "targvelt",
        "type": "app.tap",
        "field": "target",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "thumb-block",
        "word": "thumbvex",
        "phrase": "thumbvex",
        "type": "app.thumb",
        "field": "block_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "rating-block",
        "word": "ratevexo",
        "phrase": "ratevexo",
        "type": "app.rating",
        "field": "block_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "approve-manifest",
        "word": "manvexil",
        "phrase": "manvexil",
        "type": "app.approve",
        "field": "manifest_version",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "approve-card",
        "word": "cardvexo",
        "phrase": "cardvexo",
        "type": "app.approve",
        "field": "card_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "reject-manifest",
        "word": "manvecto",
        "phrase": "manvecto",
        "type": "app.reject",
        "field": "manifest_version",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "reject-card",
        "word": "cardvecto",
        "phrase": "cardvecto",
        "type": "app.reject",
        "field": "card_id",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "journal-text",
        "word": "journvex",
        "phrase": "Journvex quiet note lines",
        "type": "app.journal",
        "field": "text",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "store",
    },
    {
        "id": "usage-model",
        "word": "runnexal",
        "phrase": "vault/runnexal/synthrunner",
        "type": "usage-row",
        "field": "model",
        "disposition": "planted-via-store",
        "by_design": None,
        "plant": "runner",
    },
)

N_PLANTED = len(CANARIES)

# Every free-text field the schemas admit, with its disposition. A new
# field without a line here fails the inventory test.
INVENTORY: dict[tuple[str, str], dict[str, str]] = {
    ("envelope", "source_id"): {
        "disposition": "planted-via-collector",
        "reason": "ICS UID; stored, prompts use aliases never ids",
    },
    ("envelope", "collector_version"): {
        "disposition": "planted-via-store",
        "reason": "direct journal row; stored, never prompted",
    },
    ("calendar.event.created", "category"): {
        "disposition": "planted-via-collector",
        "reason": "canary collector name; stored, reaches the local prompt",
    },
    ("calendar.event.created", "tags"): {
        "disposition": "planted-via-collector",
        "reason": "tag-shaped canary and iki-care from raw titles",
    },
    ("calendar.event.created", "SUMMARY"): {
        "disposition": "planted-via-collector",
        "reason": "raw text dropped by the collector before storing",
    },
    ("calendar.event.created", "LOCATION"): {
        "disposition": "planted-via-collector",
        "reason": "never read by the collector",
    },
    ("calendar.event.updated", "category"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.updated", "tags"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.updated", "SUMMARY"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.updated", "LOCATION"): {
        "disposition": "planted-via-collector",
        "reason": "never read by the collector",
    },
    ("calendar.event.cancelled", "category"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.cancelled", "tags"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.cancelled", "SUMMARY"): {
        "disposition": "planted-via-collector",
        "reason": "same shape as created; covered by the created rows",
    },
    ("calendar.event.cancelled", "LOCATION"): {
        "disposition": "planted-via-collector",
        "reason": "never read by the collector",
    },
    ("calendar.label", "target_event_id"): {
        "disposition": "planted-via-store",
        "reason": "overlay reads the label only; ids stay stored",
    },
    ("calendar.label", "model_id"): {
        "disposition": "planted-via-store",
        "reason": "overlay reads the label only; ids stay stored",
    },
    ("calendar.label", "label"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("calendar.label", "label_source"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("github.push", "repo"): {
        "disposition": "planted-via-collector",
        "reason": "public rows by design; one private-tier row via store",
    },
    ("github.push", "commit-message"): {
        "disposition": "planted-via-collector",
        "reason": "fake payload text the collector never parses",
    },
    ("github.push", "counts"): {
        "disposition": "planted-via-store",
        "reason": "canary counts key on a direct row",
    },
    ("github.pr", "repo"): {
        "disposition": "planted-via-collector",
        "reason": "public rows by design",
    },
    ("github.pr", "counts"): {
        "disposition": "no-free-text",
        "reason": "integer counts under fixed keys; key shape covered by push",
    },
    ("github.issue", "repo"): {
        "disposition": "planted-via-collector",
        "reason": "public rows by design",
    },
    ("github.issue", "counts"): {
        "disposition": "no-free-text",
        "reason": "integer counts under fixed keys; key shape covered by push",
    },
    ("github.release", "repo"): {
        "disposition": "planted-via-collector",
        "reason": "public rows by design",
    },
    ("github.release", "counts"): {
        "disposition": "no-free-text",
        "reason": "integer counts under fixed keys; key shape covered by push",
    },
    ("feed.item", "title"): {
        "disposition": "planted-via-collector",
        "reason": "public; short topic is the designed path",
    },
    ("feed.item", "url"): {
        "disposition": "planted-via-collector",
        "reason": "outbound would be a finding",
    },
    ("feed.item", "source"): {
        "disposition": "planted-via-store",
        "reason": "canary source on a direct row; metric-id suffix by design",
    },
    ("music.play", "track"): {
        "disposition": "planted-via-collector",
        "reason": "stored; type outside ALLOWED_TYPES, dropped before facts",
    },
    ("music.play", "artist"): {
        "disposition": "planted-via-collector",
        "reason": "stored; type outside ALLOWED_TYPES, dropped before facts",
    },
    ("health.daily", "none"): {
        "disposition": "no-free-text",
        "reason": "all numeric; sensitive tier proves sensitive rows never enter facts",
    },
    ("screen.hour", "minutes_by_category"): {
        "disposition": "planted-via-store",
        "reason": "canary category key on a direct row; metric id by design",
    },
    ("screen.hour", "app"): {
        "disposition": "planted-via-collector",
        "reason": "raw watcher text dropped before storing",
    },
    ("screen.hour", "title"): {
        "disposition": "planted-via-collector",
        "reason": "raw watcher text dropped before storing",
    },
    ("screen.hour", "device"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("editor.hour", "project"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("editor.hour", "language"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("jobs.snapshot", "none"): {
        "disposition": "no-free-text",
        "reason": "integer stage counts; dropped type",
    },
    ("app.view", "block_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.view", "screen"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.tap", "block_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.tap", "target"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.thumb", "block_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.rating", "block_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.approve", "manifest_version"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.approve", "card_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.reject", "manifest_version"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.reject", "card_id"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type",
    },
    ("app.checkin", "none"): {
        "disposition": "no-free-text",
        "reason": "one integer; dropped type",
    },
    ("app.journal", "text"): {
        "disposition": "planted-via-store",
        "reason": "stored; dropped type plus sensitive tier",
    },
    ("app.correction", "commitment_id"): {
        "disposition": "controlled",
        "reason": "validated against the known commitment ids; still searched for",
    },
    ("app.correction", "operation"): {
        "disposition": "controlled",
        "reason": "closed operation vocabulary; still searched for",
    },
    ("app.correction", "until"): {
        "disposition": "controlled",
        "reason": "closed until vocabulary; still searched for",
    },
    ("app.correction", "reported_by"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("app.fact_dispute", "fact_id"): {
        "disposition": "controlled",
        "reason": "product fact ids disputed from the stored card; still searched for",
    },
    ("app.fact_dispute", "metric_id"): {
        "disposition": "controlled",
        "reason": "product metric ids disputed from the stored card; still searched for",
    },
    ("app.fact_dispute", "cycle_id"): {
        "disposition": "controlled",
        "reason": "product cycle ids disputed from the stored card; still searched for",
    },
    ("app.fact_dispute", "card_id"): {
        "disposition": "controlled",
        "reason": "product card ids disputed from the stored card; still searched for",
    },
    ("app.fact_dispute", "reported_by"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("app.voice_note", "outcome"): {
        "disposition": "controlled",
        "reason": "closed outcome codes set by code; still searched for",
    },
    ("app.voice_note", "operation"): {
        "disposition": "controlled",
        "reason": "compiled operation from the closed set; still searched for",
    },
    ("app.voice_note", "commitment_id"): {
        "disposition": "controlled",
        "reason": "validated against the known commitment ids; still searched for",
    },
    ("app.voice_note", "until"): {
        "disposition": "controlled",
        "reason": "compiled until from the closed set; still searched for",
    },
    ("app.voice_note", "old_card_id"): {
        "disposition": "controlled",
        "reason": "product card ids; still searched for",
    },
    ("app.voice_note", "new_card_id"): {
        "disposition": "controlled",
        "reason": "product card ids; still searched for",
    },
    ("app.voice_note", "step_seconds"): {
        "disposition": "controlled",
        "reason": "code-defined step names with numeric values; still searched for",
    },
    ("app.voice_note", "compile_model"): {
        "disposition": "controlled",
        "reason": "product config values; still searched for",
    },
    ("app.voice_note", "compile_effort"): {
        "disposition": "controlled",
        "reason": "product config values; still searched for",
    },
    ("app.voice_note", "muse_version"): {
        "disposition": "controlled",
        "reason": "transport version probe; still searched for",
    },
    ("app.voice_note", "validation_codes"): {
        "disposition": "controlled",
        "reason": "closed validation codes; still searched for",
    },
    ("app.voice_note", "reported_by"): {
        "disposition": "controlled",
        "reason": "Literal vocabulary; still searched for",
    },
    ("usage-row", "model"): {
        "disposition": "planted-via-store",
        "reason": "fake runner stream; sanitised to the last path part",
    },
    ("private_terms", "deny-terms.txt"): {
        "disposition": "planted-via-store",
        "reason": "scratch deny list; exercised not assumed",
    },
    ("Fact", "statement"): {
        "disposition": "planted-via-store",
        "reason": "derived, never planted directly; scanned as stored outbound-side",
    },
    ("Fact", "evidence"): {
        "disposition": "planted-via-store",
        "reason": "derived, never planted directly; scanned as stored outbound-side",
    },
    ("Profile", "label"): {
        "disposition": "not-in-slot-path",
        "reason": "nothing in run_slot loads profile text",
    },
    ("Criterion", "text"): {
        "disposition": "not-in-slot-path",
        "reason": "nothing in run_slot loads criterion text",
    },
    ("manifest", "blocks"): {
        "disposition": "not-in-slot-path",
        "reason": "legacy blocks manifest; one table line asserted present",
    },
}


_WS_RE = re.compile(r"\s+")
_UNICODE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _normalise(text: str) -> str:
    out = text.casefold()
    for _ in range(2):
        try:
            out = urllib.parse.unquote(out)
        except Exception:  # noqa: BLE001 -- keep scanning on odd input
            break

    def _uni(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    out = _UNICODE_RE.sub(_uni, out)
    out = out.replace('\\"', '"').replace("\\\\", "\\")
    out = _WS_RE.sub(" ", out)
    return out.strip()


def corpus_holds(corpus: str, phrase: str, word: str) -> bool:
    """One canary found in one channel corpus under any normalisation."""
    normed = _normalise(corpus)
    phrase_hit = bool(_normalise(phrase)) and _normalise(phrase) in normed
    word_hit = bool(_normalise(word)) and _normalise(word) in normed
    return phrase_hit or word_hit


def _norm_contains(corpus: str, needle: str) -> bool:
    """One normalised string found in one normalised corpus."""
    return bool(_normalise(needle)) and _normalise(needle) in _normalise(corpus)


def _is_escape(channels: Sequence[str]) -> bool:
    """A hit only in stored_outbound never left the machine: not an escape."""
    return any(ch != "stored_outbound" for ch in channels)


@contextmanager
def capture_fds() -> Iterator[tuple[Any, Any]]:
    """Capture fds 1 and 2 plus sys.stdout/sys.stderr for one run."""
    first = tempfile.SpooledTemporaryFile(max_size=1 << 20)  # noqa: SIM115 -- read after yield
    second = tempfile.SpooledTemporaryFile(max_size=1 << 20)  # noqa: SIM115 -- read after yield
    sys.stdout.flush()
    sys.stderr.flush()
    saved_out = os.dup(1)
    saved_err = os.dup(2)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    os.dup2(first.fileno(), 1)
    os.dup2(second.fileno(), 2)
    sys.stdout = os.fdopen(os.dup(1), "w")  # type: ignore[assignment]
    sys.stderr = os.fdopen(os.dup(2), "w")  # type: ignore[assignment]
    try:
        yield (first, second)
    finally:
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001, S110 -- restore must not fail
            pass
        try:
            sys.stderr.flush()
        except Exception:  # noqa: BLE001, S110 -- restore must not fail
            pass
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001, S110 -- close the dup, never fd 1
            pass
        try:
            sys.stderr.close()
        except Exception:  # noqa: BLE001, S110 -- close the dup, never fd 2
            pass
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        sys.stdout, sys.stderr = old_stdout, old_stderr
        first.seek(0)
        second.seek(0)


@contextmanager
def no_sockets() -> Iterator[None]:
    """Fail any socket connect, connect_ex or bind inside the scope."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_bind = socket.socket.bind

    def _deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no sockets in r2 worlds")

    socket.socket.connect = _deny  # type: ignore[method-assign]
    socket.socket.connect_ex = _deny  # type: ignore[method-assign]
    socket.socket.bind = _deny  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.socket.bind = real_bind  # type: ignore[method-assign]


def _stream_line(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "stream": {"kind": "session", "id": "s"},
            "record_type": "event",
            "payload": payload,
        }
    )


def _usage_payload() -> dict[str, Any]:
    return {
        "kind": "run_usage",
        "models": [
            {
                "model": USAGE_MODEL_PATH,
                "input_tokens": 11,
                "cached_tokens": 0,
                "output_tokens": 7,
                "reasoning_tokens": 0,
            }
        ],
        "calls": 1,
        "completed_calls": 1,
        "failed_calls": 0,
        "allowance": {"window": {"used_percent": 11}},
    }


def _lifecycle_payload(model: str) -> dict[str, Any]:
    return {
        "kind": "task_lifecycle",
        "event": {
            "kind": "status",
            "details": {
                "phase": "stream_succeeded",
                "facets": [
                    {
                        "kind": "producer",
                        "detail": {
                            "kind": "provider",
                            "model": model,
                            "provider": "meta",
                        },
                    }
                ],
            },
        },
    }


def _terminal_payload(text: str, terminal: str = "completed") -> dict[str, Any]:
    return {"kind": "run_terminal", "terminal": terminal, "text": text, "reason": None}


class _BehaviourRunner:
    """Read the prompt and schema temp files, return a scripted stream."""

    def _version_result(self) -> RunResult:
        return RunResult(0, b"muse-synthetic-version\n", False)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        raise NotImplementedError

    def __init__(self, model: str = "muse-wonder-1.0") -> None:
        self.prompts: list[str] = []
        self.schemas: list[str] = []
        self.calls = 0
        self._model = model

    def _read_argv(self, argv: Sequence[str]) -> tuple[str, dict[str, Any], str]:
        prompt_path = ""
        schema_path = ""
        model = self._model
        for index, token in enumerate(argv):
            if token == "--prompt-file" and index + 1 < len(argv):
                prompt_path = argv[index + 1]
            if token == "--output-schema" and index + 1 < len(argv):
                schema_path = argv[index + 1]
            if token == "--model" and index + 1 < len(argv):
                model = argv[index + 1]
        prompt = Path(prompt_path).read_text(encoding="utf-8") if prompt_path else ""
        schema: dict[str, Any] = (
            json.loads(Path(schema_path).read_text(encoding="utf-8"))
            if schema_path
            else {}
        )
        self.prompts.append(prompt)
        self.schemas.append(json.dumps(schema, sort_keys=True))
        return prompt, schema, model

    def _stdout(self, draft: str, model: str) -> bytes:
        lines = [
            _stream_line(_usage_payload()),
            _stream_line(_lifecycle_payload(model)),
            _stream_line(_terminal_payload(draft)),
        ]
        return ("\n".join(lines) + "\n").encode()

    def _result(self, stdout: bytes) -> RunResult:
        return RunResult(0, stdout, False)


def _schema_ids(schema: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    props = schema.get("properties", {})
    commitments: list[str] = []
    facts: list[str] = []
    metrics: list[str] = []
    node = props.get("commitment_id", {})
    if isinstance(node.get("enum"), list):
        commitments = [str(v) for v in node["enum"]]
    claim = props.get("overall_state", {}).get("items", {})
    claim_props = claim.get("properties", {})
    node = claim_props.get("fact_ids", {})
    if isinstance(node.get("enum"), list):
        facts = [str(v) for v in node["enum"]]
    node = claim_props.get("metric_refs", {})
    if isinstance(node.get("enum"), list):
        metrics = [str(v) for v in node["enum"]]
    return commitments, facts, metrics


def _prompt_facts(prompt: str) -> list[dict[str, str]]:
    """Parse the prompt's fact JSON lines back into id/statement pairs."""
    out: list[dict[str, str]] = []
    for line in prompt.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped.startswith('{"id"'):
            continue
        try:
            item = json.loads(stripped)
        except ValueError:
            continue
        if (
            isinstance(item, dict)
            and set(item.keys()) == {"id", "statement"}
            and isinstance(item["id"], str)
            and isinstance(item["statement"], str)
        ):
            out.append({"id": item["id"], "statement": item["statement"]})
    return out


_DIGIT_TOKEN_RE = re.compile(r"\S*\d\S*")


def strip_digit_tokens(text: str) -> str:
    """Drop every whitespace-separated token holding a digit."""
    return _WS_RE.sub(" ", _DIGIT_TOKEN_RE.sub("", text)).strip()


class EchoRunner(_BehaviourRunner):
    """Copy prompt slices into claims; the gate, not the parser, stops it."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        if len(argv) > 1 and argv[1] == "--version":
            return self._version_result()
        prompt, schema, model = self._read_argv(argv)
        self.calls += 1
        commitments, facts, metrics = _schema_ids(schema)
        commitment = commitments[0] if commitments else "b-r2-one"
        fact_ref = [facts[0]] if facts else []
        metric_ref = [metrics[0]] if metrics else []
        slices = [prompt[i : i + 300] for i in range(0, len(prompt), 300)][:3]
        if not slices:
            slices = ["quiet steady state"]
        claims = [
            {"text": piece, "fact_ids": fact_ref, "metric_refs": metric_ref}
            for piece in slices
        ]
        draft = json.dumps(
            {
                "commitment_id": commitment,
                "overall_state": claims,
                "working": claims,
                "not_working": claims,
                "since_last": [],
            }
        )
        return self._result(self._stdout(draft, model))


def _ics_bytes() -> bytes:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//r2//offline//EN",
    ]
    vevents = [
        ("ical-flimbrel-aa", "Flimbrel morning drift", None),
        ("ical-grundvik-aa", "Weekly review iki-grundvik", None),
        ("ical-trundle-aa", "Flurble iki-care trundle", None),
        ("ical-sourcixa-aa", "Quiet planning block", "Hallovex annex"),
    ]
    for uid, summary, location in vevents:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append("DTSTART:20261102T100000")
        lines.append("DTEND:20261102T110000")
        lines.append("TRANSP:TRANSPARENT")
        lines.append(f"SUMMARY:{summary}")
        if location is not None:
            lines.append(f"LOCATION:{location}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode()


def _now_fn() -> datetime:
    return SLOT - timedelta(minutes=25)


def _poll_now() -> datetime:
    """Inside the facts window: event times must sit under the floored hour.

    Facts keep a winner only when its stamp touches
    ``[window_start, floor_hour(as_of))``, and the store reads
    ``[start, end)``, so a collector stamping its rows at ``as_of`` would
    plant events no prompt ever loads. Seventy minutes back clears both.
    """
    return _now_fn() - timedelta(minutes=70)


def _http_ok(body: bytes) -> Any:
    from framework.collectors.common import HttpResponse

    return HttpResponse(status=200, headers={}, body=body)


def _github_entries(now: datetime) -> list[dict[str, Any]]:
    stamp = (now - timedelta(days=1)).isoformat()
    commits = [{"message": "Commivex release notes"}]
    return [
        {
            "id": "r2-push-aa",
            "type": "PushEvent",
            "repo": {"name": "quarnkeep/dremblor"},
            "payload": {"size": 2, "commits": commits},
            "created_at": stamp,
        },
        {
            "id": "r2-pr-aa",
            "type": "PullRequestEvent",
            "repo": {"name": "quarnkeep/plorvint"},
            "payload": {"action": "opened", "pull_request": {"merged": False}},
            "created_at": stamp,
        },
        {
            "id": "r2-issue-aa",
            "type": "IssuesEvent",
            "repo": {"name": "quarnkeep/skindrel"},
            "payload": {"action": "opened"},
            "created_at": stamp,
        },
        {
            "id": "r2-release-aa",
            "type": "ReleaseEvent",
            "repo": {"name": "quarnkeep/troblequ"},
            "payload": {"action": "published"},
            "created_at": stamp,
        },
    ]


def _feed_get_factory() -> Any:
    from framework.collectors import build_feed as feed_module

    hn_list = feed_module.HN_LIST_URL
    hn_item = feed_module.HN_ITEM_URL.format(item_id=9001)

    def fake(url: str, headers: dict[str, str]) -> Any:
        if url == hn_list:
            return _http_ok(b"[9001]")
        if url == hn_item:
            return _http_ok(
                json.dumps(
                    {
                        "id": 9001,
                        "title": "Yemblora meadow drift",
                        "url": "https://example.invalid/zorphelu",
                        "score": 7,
                    }
                ).encode()
            )
        if url == feed_module.HF_URL:
            return _http_ok(b"[]")
        return _http_ok(b'{"items": []}')

    return fake


def _spotify_get_factory() -> Any:
    played = (SLOT - timedelta(days=1)).isoformat()

    def fake(url: str, headers: dict[str, str]) -> Any:
        return _http_ok(
            json.dumps(
                {
                    "items": [
                        {
                            "track": {
                                "id": "trk-r2-aa",
                                "name": "Melpraxo evening song",
                                "artists": [{"name": "Artovexa ensemble"}],
                            },
                            "played_at": played,
                        }
                    ]
                }
            ).encode()
        )

    return fake


def _spotify_post_factory() -> Any:
    def fake(url: str, headers: dict[str, str], body: bytes) -> Any:
        return _http_ok(b'{"access_token": "r2-synthetic-token"}')

    return fake


def _activitywatch_get_factory() -> Any:
    start = SLOT - timedelta(days=1)
    window_event = {
        "timestamp": start.isoformat(),
        "duration": 3600.0,
        "data": {"app": "Flumjexa", "title": "Titrevox quarterly review"},
    }
    afk_event = {
        "timestamp": (start - timedelta(hours=1)).isoformat(),
        "duration": 7200.0,
        "data": {"status": "not-afk"},
    }

    def fake(url: str, headers: dict[str, str]) -> Any:
        if url.endswith("/api/0/buckets/"):
            return _http_ok(
                json.dumps(
                    {"aw-watcher-window_mac": {}, "aw-watcher-afk_mac": {}}
                ).encode()
            )
        if "aw-watcher-afk" in url:
            return _http_ok(json.dumps([afk_event]).encode())
        return _http_ok(json.dumps([window_event]).encode())

    return fake


def _collect_collector_events() -> list[Any]:
    """Run the real collectors against fake transports, in process."""
    from framework.collectors.activitywatch import ActivityWatchCollector
    from framework.collectors.build_feed import BuildFeedCollector
    from framework.collectors.calendar_ics import CalendarIcsCollector
    from framework.collectors.github_events import GitHubEventsCollector
    from framework.collectors.spotify import SpotifyCollector

    events: list[Any] = []
    cal = CalendarIcsCollector(
        http_get=lambda url, headers: _http_ok(_ics_bytes()),
        now_fn=_poll_now,
        label="zindralk",
    )
    cal_events, _ = cal.poll(None)
    events.extend(cal_events)
    github = GitHubEventsCollector(
        http_get=lambda url, headers: _http_ok(
            json.dumps(_github_entries(_poll_now())).encode()
        ),
        now_fn=_poll_now,
    )
    github_events, _ = github.poll(None)
    events.extend(github_events)
    feed = BuildFeedCollector(http_get=_feed_get_factory(), now_fn=_poll_now)
    feed_events, _ = feed.poll(None)
    events.extend(feed_events)
    spotify = SpotifyCollector(
        http_get=_spotify_get_factory(),
        http_post=_spotify_post_factory(),
        now_fn=_poll_now,
    )
    spotify_events, _ = spotify.poll(None)
    events.extend(spotify_events)
    aw_collector = ActivityWatchCollector(
        http_get=_activitywatch_get_factory(),
        http_post=lambda url, headers, body: _http_ok(b"{}"),
        now_fn=_poll_now,
    )
    events.extend(aw_collector.collect(now=_poll_now()))
    return events


def _direct_events(as_of: datetime, stamp: datetime) -> list[Any]:
    """Rows no collector module produces, appended straight to the store."""
    from framework.schemas.events import Event

    def _event(
        eid: str,
        etype: str,
        source: str,
        data: dict[str, Any],
        tier: str,
        version: str,
    ) -> Any:
        return Event.model_validate(
            {
                "id": eid,
                "subject_id": SUBJECT,
                "source": source,
                "type": etype,
                "time": stamp.isoformat(),
                "source_id": f"{eid}-src",
                "data": {**data, "type": etype},
                "tier": tier,
                "collected_at": as_of.isoformat(),
                "collector_version": version,
            }
        )

    return [
        _event(
            "evt-r2-journal-aa",
            "app.journal",
            "journal",
            {"text": "Journvex quiet note lines"},
            "sensitive",
            "verplaqo",
        ),
        _event(
            "evt-r2-label-aa",
            "calendar.label",
            "calendar-label",
            {
                "target_event_id": "targovex-aa",
                "label": "iki-deep",
                "label_source": "local_model",
                "model_id": "modelvexa-aa",
                "valid": True,
            },
            "private",
            "label@0.1.0",
        ),
        _event(
            "evt-r2-screen-cat-aa",
            "screen.hour",
            "activitywatch",
            {"device": "mac", "minutes_by_category": {"catovrex": 30.0}},
            "private",
            "activitywatch@0.2.0",
        ),
        _event(
            "evt-r2-feed-src-aa",
            "feed.item",
            "feed",
            {
                "title": "Quiet market notes",
                "url": "https://example.invalid/quiet",
                "source": "sorsplaq",
                "score": 1.0,
            },
            "public",
            "feed@0.1.0",
        ),
        _event(
            "evt-r2-counts-aa",
            "github.push",
            "github",
            {"repo": "quarnkeep/dremblor", "counts": {"keyvraxo": 2}},
            "public",
            "github@0.1.0",
        ),
        _event(
            "evt-r2-private-aa",
            "github.push",
            "github",
            {"repo": "quarnkeep/wumblenpriv", "counts": {"commits": 1}},
            "private",
            "github@0.1.0",
        ),
        _event(
            "evt-r2-editor-aa",
            "editor.hour",
            "editor",
            {"project": "Projexil", "language": "Langzorq", "minutes": 30.0},
            "private",
            "editor@0.1.0",
        ),
        _event(
            "evt-r2-health-aa",
            "health.daily",
            "health",
            {"sleep_h": 7.0, "steps": 4000},
            "sensitive",
            "health@0.1.0",
        ),
        _event(
            "evt-r2-jobs-aa",
            "jobs.snapshot",
            "jobs",
            {
                "counts": {
                    "applied": 1,
                    "screen": 0,
                    "interview": 0,
                    "offer": 0,
                }
            },
            "private",
            "jobs@0.1.0",
        ),
        _event(
            "evt-r2-view-aa",
            "app.view",
            "telegram",
            {"block_id": "blorvixa", "screen": "screnvix"},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-tap-aa",
            "app.tap",
            "telegram",
            {"block_id": "tapvexil", "target": "targvelt"},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-thumb-aa",
            "app.thumb",
            "telegram",
            {"block_id": "thumbvex", "value": 1},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-rating-aa",
            "app.rating",
            "telegram",
            {"block_id": "ratevexo", "value": 4.0},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-approve-aa",
            "app.approve",
            "telegram",
            {"manifest_version": "manvexil", "card_id": "cardvexo"},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-reject-aa",
            "app.reject",
            "telegram",
            {"manifest_version": "manvecto", "card_id": "cardvecto"},
            "private",
            "app@0.1.0",
        ),
        _event(
            "evt-r2-checkin-aa",
            "app.checkin",
            "telegram",
            {"energy": 4},
            "private",
            "app@0.1.0",
        ),
    ]


class GateRunner(_BehaviourRunner):
    """Turn received facts into passing claims: canary facts first, max 3."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        timeout_s: float,
        cwd: str | None,
    ) -> RunResult:
        if len(argv) > 1 and argv[1] == "--version":
            return self._version_result()
        prompt, schema, model = self._read_argv(argv)
        self.calls += 1
        commitments, fact_ids, _metrics = _schema_ids(schema)
        commitment = commitments[0] if commitments else "b-r2-one"
        received = _prompt_facts(prompt)
        canary_words = {c["word"] for c in CANARIES}
        canary_phrases = {c["phrase"] for c in CANARIES}

        def _holds_canary(statement: str) -> bool:
            lowered = statement.casefold()
            return any(w in lowered for w in canary_words) or any(
                p.casefold() in lowered for p in canary_phrases
            )

        received.sort(
            key=lambda item: (not _holds_canary(item["statement"]), item["id"])
        )
        claims: list[dict[str, Any]] = []
        for item in received[:3]:
            text = strip_digit_tokens(item["statement"])
            if not re.search(r"[A-Za-z]", text):
                text = "Steady state holds for this goal"
            claims.append({"text": text, "fact_ids": [item["id"]], "metric_refs": []})
        if not claims:
            cite = [fact_ids[0]] if fact_ids else []
            claims = [
                {
                    "text": "Steady state holds for this goal",
                    "fact_ids": cite,
                    "metric_refs": [],
                }
            ]
        draft = json.dumps(
            {
                "commitment_id": commitment,
                "overall_state": claims,
                "working": [],
                "not_working": [],
                "since_last": [],
            }
        )
        return self._result(self._stdout(draft, model))


_ALIAS_RE = re.compile(r'"alias"\s*:\s*"([^"]+)"')


def _prompt_aliases(prompt: str) -> list[str]:
    return _ALIAS_RE.findall(prompt)


def _alias_holding(prompt: str, phrase: str, word: str) -> str | None:
    lowered_phrase = phrase.casefold()
    lowered_word = word.casefold()
    first: str | None = None
    for line in prompt.splitlines():
        match = _ALIAS_RE.search(line)
        if not match:
            continue
        if first is None:
            first = match.group(1)
        lowered = line.casefold()
        if lowered_phrase in lowered or lowered_word in lowered:
            return match.group(1)
    return first


class _CopyingLocal:
    """The brief's copying fake: whole-prompt statements, first alias."""

    def __init__(self) -> None:
        self.personal_prompts: list[str] = []
        self.feed_prompts: list[str] = []
        self.calls = 0
        self.world_dropped: list[dict[str, str]] = []
        self.world_facts: list[dict[str, str]] = []

    def complete(self, prompt: str) -> Any:
        from framework.glimmer.facts import LLMResponse

        self.calls += 1
        aliases = _prompt_aliases(prompt) or ["e1"]
        if "FEED_DATA" in prompt:
            self.feed_prompts.append(prompt)
            body = {"topics": [{"evidence": [aliases[0]], "topic": prompt}]}
        else:
            self.personal_prompts.append(prompt)
            body = {
                "facts": [{"statement": prompt, "evidence": [aliases[0]]}],
            }
        return LLMResponse(
            text=json.dumps(body),
            model_id="synthetic-local",
            latency_ms=1,
            finish_reason="stop",
            completion_tokens=10,
        )


class _TargetedLocal:
    """Copy only what the prompt shows: the phrase, else the word, else nothing."""

    def __init__(self, phrase: str, word: str) -> None:
        self.phrase = phrase
        self.word = word
        self.personal_prompts: list[str] = []
        self.feed_prompts: list[str] = []
        self.calls = 0
        self.world_dropped: list[dict[str, str]] = []
        self.world_facts: list[dict[str, str]] = []

    def complete(self, prompt: str) -> Any:
        from framework.glimmer.facts import LLMResponse

        self.calls += 1
        if _norm_contains(prompt, self.phrase):
            seen: str | None = self.phrase
        elif _norm_contains(prompt, self.word):
            seen = self.word
        else:
            seen = None
        if "FEED_DATA" in prompt:
            self.feed_prompts.append(prompt)
            if seen is None:
                body: dict[str, Any] = {"topics": []}
            else:
                alias = _alias_holding(prompt, self.phrase, self.word) or "f1"
                body = {"topics": [{"evidence": [alias], "topic": seen}]}
        else:
            self.personal_prompts.append(prompt)
            if seen is None:
                body = {"facts": []}
            else:
                alias = _alias_holding(prompt, self.phrase, self.word) or "e1"
                body = {"facts": [{"statement": seen, "evidence": [alias]}]}
        return LLMResponse(
            text=json.dumps(body),
            model_id="synthetic-local",
            latency_ms=1,
            finish_reason="stop",
            completion_tokens=10,
        )


def _commitments_payload(
    labels: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    titles = (
        list(labels)
        if labels is not None
        else [
            f"{CONTROL_PHRASE} pages",
            f"{CONTROL_PHRASE} notes",
            f"{CONTROL_PHRASE} stroll",
            f"{CONTROL_PHRASE} tea",
        ]
    )

    def _titled(cid: str, profile: str, kind: str, title: str) -> dict[str, Any]:
        return {
            "id": cid,
            "profile_id": profile,
            "title": title,
            "kind": kind,
            "dimension": "love",
            "evidence": "github_push",
        }

    return [
        _titled("b-r2-one", "builder", "build", titles[0]),
        _titled("b-r2-two", "builder", "build", titles[1]),
        _titled("d-r2-one", "disconnect", "rest", titles[2]),
        _titled("d-r2-two", "disconnect", "rest", titles[3]),
    ]


class _TelegramRecorder:
    """Real-client bytes at the seam: method, headers, body only."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        body = bytes(request.data) if request.data is not None else b""
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        method = request.full_url.rsplit("/", 1)[-1]
        self.records.append(
            {
                "method": method,
                "headers": headers,
                "body": body.decode("utf-8", "replace"),
            }
        )

        class _FakeResponse:
            status = 200
            headers: ClassVar[dict[str, str]] = {}

            def read(self) -> bytes:
                return json.dumps({"ok": True, "result": {"message_id": 11}}).encode()

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        return _FakeResponse()


class _WonderTap:
    """Record the literals and terms the real scan path computed with."""

    def __init__(self) -> None:
        self.literals: list[str] = []
        self.terms: list[str] = []
        self.calls = 0

    def wrap(self, client: Any) -> Any:
        tap = self
        real_complete = client.complete

        def _complete(request: Any) -> Any:
            tap.calls += 1
            tap.literals = [str(v) for v in (request.forbidden_raw_literals or ())]
            tap.terms = [str(v) for v in (client._private_terms or ())]
            return real_complete(request)

        client.complete = _complete  # type: ignore[method-assign]
        return client


@contextmanager
def _world_env(root: Path, labels: Sequence[str] | None = None) -> Iterator[None]:
    """Scratch-only environment for one world; the caller env is restored."""
    saved = dict(os.environ)
    terms_dir = root / "terms"
    terms_dir.mkdir(parents=True, exist_ok=True)
    (terms_dir / "deny-terms.txt").write_text(DENY_PHRASE + "\n", encoding="utf-8")
    (root / "commitments.json").write_text(
        json.dumps(_commitments_payload(labels)), encoding="utf-8"
    )
    xdg = root / "xdg"
    xdg.mkdir(parents=True, exist_ok=True)
    (root / "home").mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(root / "home")
    os.environ["HIDDEN_CRITERIA_DIR"] = str(terms_dir)
    os.environ["IKIGAI_COMMITMENTS_FILE"] = str(root / "commitments.json")
    os.environ["TELEGRAM_CHAT_ID"] = "424242"
    os.environ["TELEGRAM_BOT_TOKEN"] = "424242:R2MadeUpTokenForOfflineUseOnly"
    os.environ.pop("META_API_KEY", None)
    os.environ.pop("IKIGAI_KILL_FILE", None)
    os.environ["XDG_CONFIG_HOME"] = str(xdg)
    os.environ["IKIGAI_SUBJECT_ID"] = SUBJECT
    os.environ["GITHUB_USER"] = "quarnkeep"
    os.environ.pop("GITHUB_TOKEN", None)
    os.environ["SPOTIFY_CLIENT_ID"] = "r2-synthetic-id"
    os.environ["SPOTIFY_CLIENT_SECRET"] = "r2-synthetic-secret"
    os.environ["SPOTIFY_REFRESH_TOKEN"] = "r2-synthetic-refresh"
    os.environ["ICAL_URL_ZINDRALK"] = "https://example.invalid/r2-calendar"
    os.environ["AW_BASE_URL"] = "https://example.invalid/r2-aw"
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _plant_events(db: Path) -> None:
    from framework.store.store import EventStore

    as_of = _now_fn()
    stamp = SLOT - timedelta(days=1)
    events = _collect_collector_events()
    events.extend(_direct_events(as_of, stamp))
    store = EventStore(db_path=db)
    try:
        store.append_events(events)
    finally:
        store.close()


def _table_text(db: Path, table: str) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            columns = [
                d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description
            ]
        except sqlite3.OperationalError:
            return ""
    finally:
        conn.close()
    parts: list[str] = []
    for row in rows:
        for name, value in zip(columns, row):
            if isinstance(value, (bytes, bytearray)):
                value = bytes(value).decode("utf-8", "replace")
            if isinstance(value, str) and value:
                parts.append(f"{name}={value}")
    return "\n".join(parts)


def _channel_corpora(
    db: Path,
    telegram: _TelegramRecorder,
    runner: _BehaviourRunner,
    trace_text: str,
    stdout_text: str,
) -> dict[str, str]:
    from framework.telegram.models import Card, split_messages, why_reply_pieces

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        try:
            payload = conn.execute(
                "SELECT card_json, chart_json FROM slot_card_payloads LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            payload = None
        try:
            card_rows = conn.execute("SELECT card_id FROM slot_cards").fetchall()
        except sqlite3.OperationalError:
            card_rows = []
    finally:
        conn.close()
    card_id = str(card_rows[0][0]) if card_rows else ""
    why_text = ""
    if payload is not None:
        card = Card.model_validate_json(str(payload[0]))
        why_text = "\n".join(split_messages(why_reply_pieces(card)))
        chart_text = str(payload[1])
        card_text = str(payload[0])
    else:
        chart_text = ""
        card_text = ""
    telegram_text = "\n".join(
        f"{r['method']}\n{r['headers']}\n{r['body']}" for r in telegram.records
    )
    wonder_text = "\n".join(runner.prompts + runner.schemas)
    stored_outbound = "\n".join(
        _table_text(db, table)
        for table in (
            "facts",
            "cycles",
            "proposal_results",
            "slot_cards",
            "slot_ledger",
            "learner_states",
            "local_start_retries",
        )
    )
    return {
        "wonder_prompt": wonder_text,
        "meta_body": "",
        "telegram": telegram_text,
        "why_reply": why_text,
        "trace": trace_text,
        "chart_input": chart_text,
        "card_stored": card_text,
        "stored_outbound": stored_outbound,
        "stdout_stderr": stdout_text,
        "card_id": card_id,
    }


def _stored_local_text(db: Path) -> str:
    return "\n".join(
        _table_text(db, table)
        for table in ("cycle_responses", "proposal_attempts", "cycles")
    )


def _events_text(db: Path) -> str:
    return _table_text(db, "events")


class _HarnessError(Exception):
    pass


def run_world(
    root: Path,
    *,
    local: Any,
    runner: _BehaviourRunner,
    labels: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Run one whole slot offline; return corpora plus run evidence."""
    from framework.cycle import run_cycle
    from framework.cycle.orchestrator import (
        DeadlineWonderClient,
        FactsChildResult,
        Seams,
        run_slot,
    )
    from framework.cycle.trace import trace
    from framework.store.fact_store import FactStore
    from framework.store.store import EventStore

    started = time.monotonic()
    root.mkdir(parents=True, exist_ok=True)
    db = root / "cycle.db"
    tap = _WonderTap()
    telegram = _TelegramRecorder()
    frozen = SLOT - timedelta(minutes=25)

    def _clock() -> datetime:
        return frozen

    def _facts(**kwargs: Any) -> Any:
        store = EventStore(db_path=Path(str(kwargs["db_path"])))
        try:
            fact_store = FactStore(db_path=store.db_path)
            try:
                result, run = run_cycle(
                    kwargs["as_of"], kwargs["subject_id"], store, fact_store, local
                )
                local.world_dropped = [
                    {"code": d.code, "statement_hash": d.statement_hash}
                    for d in result.dropped
                ]
                local.world_facts = [
                    {"id": f.id, "statement": f.statement} for f in result.facts
                ]
                return FactsChildResult("ok", result.cycle_id, run)
            finally:
                fact_store.close()
        finally:
            store.close()

    def _wonder(terms: Any, deadline: datetime) -> Any:
        from framework.proposal.muse_client import MuseExecClient

        client = MuseExecClient(
            private_terms=terms.terms,
            private_terms_available=terms.available,
            timeout_s=120.0,
            runner=runner,
        )
        tap.wrap(client)
        return DeadlineWonderClient(
            make_client=lambda t: client, deadline=deadline, clock=_clock
        )

    outcome: dict[str, Any] = {}
    with _world_env(root, labels):
        _plant_events(db)
        import framework.telegram.client as telegram_client

        real_open = telegram_client._open_url
        telegram_client._open_url = telegram  # type: ignore[method-assign]
        try:
            with no_sockets(), capture_fds() as (first, second):
                code = run_slot(
                    slot=SLOT,
                    subject_id=SUBJECT,
                    db_path=db,
                    no_wait=True,
                    seams=Seams(
                        facts=_facts,
                        wonder=_wonder,
                        telegram=__import__(
                            "framework.telegram.client", fromlist=["TelegramClient"]
                        ).TelegramClient(),
                        clock=_clock,
                        sleep=lambda s: None,
                        home=root / "home",
                        ledger_sleep=lambda s: None,
                    ),
                )
                print(f"r2-stdout-{CONTROL_WORD}")
                os.write(1, f"r2-fdout-{CONTROL_WORD}\n".encode())
                print(f"r2-stderr-{CONTROL_WORD}", file=sys.stderr)
                os.write(2, f"r2-fderr-{CONTROL_WORD}\n".encode())
                sys.stdout.flush()
                sys.stderr.flush()
        finally:
            telegram_client._open_url = real_open  # type: ignore[method-assign]
        first_bytes = first.read()
        second_bytes = second.read()
        stdout_text = first_bytes.decode("utf-8", "replace") + second_bytes.decode(
            "utf-8", "replace"
        )
        with capture_fds() as (trace_first, trace_second):
            corpora_card = _channel_corpora(db, telegram, runner, "", "")["card_id"]
            if corpora_card:
                trace(card_id=corpora_card, db_path=db)
        trace_bytes = trace_first.read() + trace_second.read()
        trace_text = trace_bytes.decode("utf-8", "replace")
    outcome = {
        "corpora": _channel_corpora(db, telegram, runner, trace_text, stdout_text),
        "run_slot_exit": code,
        "runner_calls": runner.calls,
        "literals": tap.literals,
        "terms": tap.terms,
        "facts_calls": local.calls,
        "personal_prompts": list(local.personal_prompts),
        "feed_prompts": list(local.feed_prompts),
        "dropped": list(getattr(local, "world_dropped", [])),
        "kept_facts": list(getattr(local, "world_facts", [])),
        "db": str(db),
        "seconds": time.monotonic() - started,
    }
    return outcome


class _MetaRecorder:
    """Capture the Meta request; answer with an OpenAI-shaped echo draft."""

    def __init__(self, draft: str) -> None:
        self.draft = draft
        self.records: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float) -> Any:
        body = bytes(request.data) if request.data is not None else b""
        raw_headers = {str(k): str(v) for k, v in request.header_items()}
        auth = ""
        for key, value in raw_headers.items():
            if key.casefold() == "authorization":
                auth = value
        assert auth == "Bearer r2-synthetic-key", (
            f"unexpected authorization value {auth!r}"
        )
        recorded = {
            key: ("Bearer [REDACTED]" if key.casefold() == "authorization" else value)
            for key, value in raw_headers.items()
        }
        payload = json.loads(body.decode("utf-8"))
        self.records.append(
            {
                "url": str(request.full_url),
                "headers": recorded,
                "body": payload,
                "prompt": str(payload["messages"][0]["content"]),
            }
        )
        draft = self.draft

        class _FakeResponse:
            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"content": draft},
                                "finish_reason": "stop",
                            }
                        ],
                        "model": "muse-wonder-1.0",
                    }
                ).encode()

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: object) -> None:
                return None

        return _FakeResponse()


def run_meta_arm(db: Path) -> dict[str, Any]:
    """Replay both profiles on a DB copy through the recording Meta transport."""
    from framework.briefing.context import PrivateTerms
    from framework.briefing.schemas import Commitment
    from framework.cycle import run_proposals
    from framework.cycle.orchestrator import (
        SLOT_LIMITS,
        EligibilityState,
        eligible_commitments,
    )
    from framework.proposal.client import MetaClient
    from framework.proposal.core import ModelParams
    from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL
    from framework.store.fact_store import FactStore
    from framework.store.proposal_store import ProposalStore
    from framework.store.store import EventStore

    copy = db.parent / "meta.db"
    source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    as_of = _now_fn()
    recorder = _MetaRecorder(draft="quiet steady state")
    client = MetaClient(
        api_key="r2-synthetic-key",
        private_terms=(DENY_WORD,),
        private_terms_available=True,
        transport=recorder,
    )
    store = EventStore(db_path=copy)
    fact_store = FactStore(db_path=store.db_path)
    proposal_store = ProposalStore(db_path=store.db_path)
    with store, fact_store, proposal_store:
        terms = PrivateTerms(terms=(DENY_WORD,), available=True)
        commitments = [
            Commitment.model_validate(item) for item in _commitments_payload()
        ]
        eligible = {
            profile: eligible_commitments(
                commitments,
                profile_id=profile,
                slot_local=SLOT,
                state=EligibilityState(
                    disconnect_sent_today=0,
                    now_local=SLOT,
                    hour_start_local=SLOT,
                ),
            )
            for profile in ("builder", "disconnect")
        }
        run_proposals(
            as_of=as_of,
            slot=SLOT,
            subject_id=SUBJECT,
            profiles=("builder", "disconnect"),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=terms,
            eligible_by_profile=eligible,
            limits=SLOT_LIMITS,
            models=ModelParams(
                first_model=DEFAULT_MODEL,
                first_effort=DEFAULT_EFFORT,
                retry_model=DEFAULT_MODEL,
                retry_effort=DEFAULT_EFFORT,
            ),
            stale_after_s=12 * 3600.0,
            policy_by_profile=None,
            parents=None,
        )
    bodies: list[str] = []
    for record in recorder.records:
        bodies.append(record["url"])
        bodies.append(json.dumps(record["headers"], sort_keys=True))
        bodies.append(json.dumps(record["body"], sort_keys=True))
        for key, value in record["headers"].items():
            if key.casefold() == "authorization":
                assert value == "Bearer [REDACTED]"
    return {"meta_body": "\n".join(bodies), "calls": len(recorder.records)}


def _scan_world(
    corpora: dict[str, str], channels: Sequence[str]
) -> dict[str, dict[str, bool]]:
    """Per canary, per channel: found or not."""
    found: dict[str, dict[str, bool]] = {}
    for canary in CANARIES:
        per_channel: dict[str, bool] = {}
        for channel in channels:
            per_channel[channel] = corpus_holds(
                corpora.get(channel, ""), canary["phrase"], canary["word"]
            )
        found[canary["id"]] = per_channel
    return found


COPYING_CHANNELS = [c for c in CHANNELS if c != "meta_body"]
META_CHANNELS = ["meta_body"]


def _prompt_visible(main: dict[str, Any]) -> list[Canary]:
    prompts = "\n".join(main["personal_prompts"] + main["feed_prompts"])
    return [c for c in CANARIES if corpus_holds(prompts, c["phrase"], c["word"])]


def _run_r2_inner(scratch_root: Path) -> dict[str, Any]:
    """Run the copying world, one targeted world per visible canary, and Meta."""
    overall_started = time.monotonic()
    scratch_root.mkdir(parents=True, exist_ok=True)

    main_local = _CopyingLocal()
    main_local.world_dropped = []
    main_local.world_facts = []
    main = run_world(scratch_root / "main", local=main_local, runner=EchoRunner())
    main_db = Path(main["db"])
    if not main["corpora"]["card_id"]:
        raise _HarnessError("main world stored no card; recording is blind")

    meta = run_meta_arm(main_db)
    main["corpora"]["meta_body"] = meta["meta_body"]

    required = ["wonder_prompt", "meta_body", "telegram", "card_stored", "trace"]
    missing = [
        channel
        for channel in required
        if not corpus_holds(main["corpora"][channel], CONTROL_PHRASE, CONTROL_WORD)
    ]
    if missing:
        raise _HarnessError(f"control canary missing from {','.join(missing)}")
    if not any("iki-care" in c["phrase"] for c in CANARIES):
        raise _HarnessError("internal label canary left the inventory")
    if DENY_WORD not in main["terms"]:
        raise _HarnessError("deny term never reached the client")
    if "iki-care" not in sorted(main["literals"]):
        raise _HarnessError("iki-care not among the computed literals")

    visible = _prompt_visible(main)
    visible_ids = sorted(c["id"] for c in visible)
    targeted_worlds: dict[str, dict[str, Any]] = {}
    for canary in visible:
        local = _TargetedLocal(canary["phrase"], canary["word"])
        local.world_dropped = []
        local.world_facts = []
        world = run_world(
            scratch_root / f"target-{canary['id']}",
            local=local,
            runner=GateRunner(),
        )
        targeted_worlds[canary["id"]] = world

    copying_found = _scan_world(main["corpora"], COPYING_CHANNELS)
    meta_found = _scan_world(main["corpora"], META_CHANNELS)
    targeted_found: dict[str, dict[str, list[str]]] = {}
    for cid, world in targeted_worlds.items():
        scan = _scan_world(world["corpora"], COPYING_CHANNELS)
        targeted_found[cid] = {
            channel: [cid] for channel in COPYING_CHANNELS if scan[cid][channel]
        }

    def _escape_ids(
        found: Mapping[str, Mapping[str, bool]],
    ) -> list[str]:
        return [
            cid
            for cid, per_channel in found.items()
            if _is_escape([ch for ch, hit in per_channel.items() if hit])
        ]

    copying_hit = {c["id"]: copying_found[c["id"]] for c in CANARIES}
    meta_hit = {c["id"]: meta_found[c["id"]] for c in CANARIES}
    targeted_hit = {
        cid: {ch: (ch in targeted_found.get(cid, {})) for ch in COPYING_CHANNELS}
        for cid in targeted_worlds
    }
    copying_k = len(_escape_ids(copying_hit))
    meta_k = len(_escape_ids(meta_hit))
    targeted_k = len(_escape_ids(targeted_hit))
    arms = {
        "copying": {
            "escaped": copying_k,
            "headline": f"{copying_k} of {N_PLANTED} tested canaries escaped",
        },
        "targeted": {
            "escaped": targeted_k,
            "headline": f"{targeted_k} of {N_PLANTED} tested canaries escaped",
            "worlds": len(targeted_worlds),
        },
        "meta": {
            "escaped": meta_k,
            "headline": f"{meta_k} of {N_PLANTED} tested canaries escaped",
        },
    }

    def _split(escaped_ids: list[str]) -> dict[str, int]:
        by_design = sum(
            1 for c in CANARIES if c["id"] in escaped_ids and c["by_design"] is not None
        )
        return {
            "by_design_escaped": by_design,
            "finding_escaped": len(escaped_ids) - by_design,
        }

    copying_ids = _escape_ids(copying_hit)
    meta_ids = _escape_ids(meta_hit)
    targeted_ids = _escape_ids(targeted_hit)
    arms["copying"].update(_split(copying_ids))
    arms["targeted"].update(_split(targeted_ids))
    arms["meta"].update(_split(meta_ids))
    order = ("copying", "targeted", "meta")
    worse = "copying"
    for name in order:
        if (arms[name]["escaped"], arms[name]["finding_escaped"]) > (
            arms[worse]["escaped"],
            arms[worse]["finding_escaped"],
        ):
            worse = name
    worst_k = int(arms[worse]["escaped"])
    headline_ids = {"copying": copying_ids, "targeted": targeted_ids, "meta": meta_ids}[
        worse
    ]
    headline_split = _split(headline_ids)

    events_text = _events_text(main_db)
    facts_text = json.dumps(main["kept_facts"], sort_keys=True)
    by_field: list[dict[str, Any]] = []
    never_reached_local: list[str] = []
    for canary in CANARIES:
        cid = canary["id"]
        escaped = cid in copying_ids or cid in meta_ids or cid in targeted_ids
        stored_only = any(
            found[cid].get("stored_outbound") for found in (copying_found, meta_found)
        ) or (
            cid in targeted_worlds and targeted_found[cid].keys() == {"stored_outbound"}
        )
        in_events = corpus_holds(events_text, canary["phrase"], canary["word"])
        in_facts = corpus_holds(facts_text, canary["phrase"], canary["word"])
        own_drops = targeted_worlds.get(cid, {}).get("dropped", [])
        if escaped:
            stage = "escaped"
        elif stored_only or in_facts or own_drops:
            stage = "stored-then-stopped"
        elif cid == "usage-model" or in_events:
            stage = "stored"
        else:
            stage = "dropped-by-collector"
        if cid not in visible_ids:
            never_reached_local.append(cid)
        by_field.append(
            {
                "canary_id": cid,
                "type": canary["type"],
                "field": canary["field"],
                "disposition": canary["disposition"],
                "by_design": canary["by_design"],
                "stage_reached": stage,
                "found_in": {
                    "copying": sorted(
                        ch for ch in COPYING_CHANNELS if copying_found[cid].get(ch)
                    ),
                    "targeted": sorted(targeted_found.get(cid, {}).keys()),
                    "meta": sorted(
                        ch for ch in META_CHANNELS if meta_found[cid].get(ch)
                    ),
                },
            }
        )

    stored_local = _stored_local_text(main_db)
    stored_local_hits = sorted(
        c["id"] for c in CANARIES if corpus_holds(stored_local, c["phrase"], c["word"])
    )
    conn = sqlite3.connect(f"file:{main_db}?mode=ro", uri=True)
    try:
        try:
            kind_rows = conn.execute(
                "SELECT profile_id, kind FROM slot_cards"
            ).fetchall()
        except sqlite3.OperationalError:
            kind_rows = []
        try:
            proposal_rows = conn.execute(
                "SELECT profile_id, kind, reason_codes FROM proposal_results"
            ).fetchall()
        except sqlite3.OperationalError:
            proposal_rows = []
    finally:
        conn.close()
    slot_kinds = sorted(f"{row[0]}:{row[1]}" for row in kind_rows)
    proposal_kinds = sorted(f"{row[0]}:{row[1]}:{row[2]}" for row in proposal_rows)

    control_found = sorted(
        channel
        for channel in CHANNELS
        if corpus_holds(main["corpora"][channel], CONTROL_PHRASE, CONTROL_WORD)
    )
    report = {
        "planted": N_PLANTED,
        "arms": arms,
        "headline": f"{worst_k} of {N_PLANTED} tested canaries escaped",
        "headline_arm": worse,
        "by_design_escaped": headline_split["by_design_escaped"],
        "finding_escaped": headline_split["finding_escaped"],
        "prediction": "0 escape",
        "prediction_held": worst_k == 0,
        "by_field": by_field,
        "channels_scanned": list(CHANNELS),
        "control_found_in": control_found,
        "gaps": [
            "chart pixels (no OCR)",
            "voice-note audio to Meta for transcription",
            "voice reply texts to Telegram (they echo the transcript)",
            "corrected cards from the voice worker",
            "the Nov 3 11:30 extra slot's limits/profile branch (same sends, narrower allowed hours)",
            "anything not planted",
        ],
        "stored_local_hits": stored_local_hits,
        "never_reached_local_model": sorted(never_reached_local),
        "prompt_visible": visible_ids,
        "run_slot_exit": main["run_slot_exit"],
        "slot_kinds": slot_kinds,
        "proposal_kinds": proposal_kinds,
    }
    total_seconds = time.monotonic() - overall_started
    return {
        "report": report,
        "main": main,
        "targeted": targeted_worlds,
        "seconds": total_seconds,
    }


def run_r2(scratch_root: Path) -> dict[str, Any]:
    """Whole receipt under the socket guard: worlds, trace and Meta arm."""
    with no_sockets():
        return _run_r2_inner(scratch_root)


BY_DESIGN_REASONS = {
    "feed-topic": (
        "I treat feed text as public by source, and I let it out "
        "only as a topic of at most 6 words."
    ),
    "public-repo": (
        "I count public repo names as by design: the collector tiers GitHub "
        "rows public. With no token the collector reads public events only. "
        "A token belonging to the same user would also return that user's "
        "private events stamped public, and a token is what would change "
        "this line. I run with no token."
    ),
    "hand-tag": (
        "I count this hand tag as by design: docs/PRIVACY.md says a literal "
        "tag in a title counts as a hand tag."
    ),
    "metric-label": (
        "I send metric labels out on purpose as metric ids: screen category "
        "keys and feed source names go out as metric ids, the collectors' "
        "closed tables keep them closed, and my direct rows are a row no "
        "real collector writes."
    ),
}


def _plain_field(row: dict[str, Any]) -> str:
    """One canary named by field, in words a stranger follows."""
    return f"the {row['field']} field on {row['type']} rows ({row['canary_id']})"


def render_r2_md(report: dict[str, Any]) -> str:
    """First person, plain words; counts and field names only, never values."""
    arms = report["arms"]
    findings = [
        row
        for row in report["by_field"]
        if row["stage_reached"] == "escaped" and row["by_design"] is None
    ]
    stopped = [
        row
        for row in report["by_field"]
        if row["stage_reached"] == "stored-then-stopped"
    ]
    by_design_rows = [
        row
        for row in report["by_field"]
        if row["stage_reached"] == "escaped" and row["by_design"] is not None
    ]
    lines = ["# R2 privacy receipt", ""]
    lines.append(f"I ran R2 offline: {report['headline']}.")
    lines.append("")
    lines.append(f"The worse arm was {report['headline_arm']}.")
    lines.append("")
    for name in ("copying", "targeted", "meta"):
        arm = arms[name]
        extra = f", worlds {arm['worlds']}" if "worlds" in arm else ""
        lines.append(
            f"- {name}: {arm['headline']}{extra}; by design "
            f"{arm['by_design_escaped']}, findings {arm['finding_escaped']}."
        )
    lines.append("")
    lines.append(
        f"Of those, {report['by_design_escaped']} got out by design and "
        f"{report['finding_escaped']} are findings."
    )
    lines.append("")
    if by_design_rows:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in by_design_rows:
            groups.setdefault(str(row["by_design"]), []).append(row)
        for key, members in groups.items():
            ids = ", ".join(row["canary_id"] for row in members)
            fields = ", ".join(f"{row['type']}.{row['field']}" for row in members)
            lines.append(f"- {ids} ({fields}): {BY_DESIGN_REASONS[key]}")
    else:
        lines.append("None of those got out by design.")
    lines.append("")
    if stopped:
        lines.append("Stopped before any send:")
        for row in stopped:
            if row["type"] == "private_terms":
                name = f"the entry in my private terms list ({row['canary_id']})"
            else:
                name = _plain_field(row)
            if any(
                channel for channels in row["found_in"].values() for channel in channels
            ):
                lines.append(
                    f"- {name}: it became a stored fact, then the "
                    f"outbound scan blocked the prompt carrying it before "
                    f"any send."
                )
            else:
                lines.append(
                    f"- {name}: the fact layer's leak check dropped it "
                    f"before it became a fact, so it never reached a prompt."
                )
        lines.append("The internal-only label reached no outbound channel.")
    else:
        lines.append("No canary sat only in stored outbound-side rows.")
    lines.append("")
    if findings:
        names = "; ".join(_plain_field(row) for row in findings)
        lines.append(
            "What the findings mean: a local model that misbehaves can copy "
            "any digit-free word it sees in its prompt into a fact, because "
            "the fact layer checks statements for aliases, digits, whole "
            "private values and feed headlines, not against these fields. "
            "What it did not see that way: calendar titles and locations, "
            f"commit text, and window and app titles. The findings are {names}."
        )
    else:
        lines.append(
            "No canary got out that is not by design. What the local model "
            "never saw that way: calendar titles and locations, commit text, "
            "and window and app titles."
        )
    lines.append("")
    never = report["never_reached_local_model"]
    lines.append(
        f"{len(never)} planted canaries never reached the local model at all: "
        + (", ".join(never) if never else "none")
        + "."
    )
    lines.append("")
    lines.append(
        f'Prediction "{report["prediction"]}": '
        + ("held." if report["prediction_held"] else "not held.")
    )
    lines.append("")
    lines.append(
        "What this receipt cannot show: canaries cover only what was planted, "
        "so anything nobody planted stays out of view."
    )
    lines.append("")
    lines.append("## Per-field table")
    lines.append("")
    lines.append("| canary | type.field | disposition | by-design | stage | found in |")
    lines.append("|---|---|---|---|---|---|")
    for row in report["by_field"]:
        found = "; ".join(
            f"{arm}:{','.join(channels)}"
            for arm, channels in row["found_in"].items()
            if channels
        )
        lines.append(
            f"| {row['canary_id']} | {row['type']}.{row['field']} | "
            f"{row['disposition']} | {row['by_design'] or '-'} | "
            f"{row['stage_reached']} | {found or '-'} |"
        )
    lines.append("")
    lines.append("## Channels, controls, gaps")
    lines.append("")
    lines.append(f"Channels scanned: {', '.join(report['channels_scanned'])}.")
    lines.append(f"Control canary found in: {', '.join(report['control_found_in'])}.")
    lines.append(f"Gaps: {'; '.join(report['gaps'])}.")
    lines.append(
        f"Stored-local hits (kept on machine by design, never counted): "
        f"{', '.join(report['stored_local_hits']) or 'none'}."
    )
    lines.append(
        f"Slot exit: {report['run_slot_exit']}; kinds: {', '.join(report['slot_kinds'])}."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="r2-"))
    try:
        outcome = run_r2(scratch)
    except _HarnessError as exc:
        print(f"r2 harness error: {type(exc).__name__}")
        return 1
    report = outcome["report"]
    root = Path.cwd()
    results_dir = root / "evals" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "r2.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (root / "docs" / "r2.md").write_text(render_r2_md(report), encoding="utf-8")
    print(report["headline"])
    for name in ("copying", "targeted", "meta"):
        print(f"{name}: {report['arms'][name]['headline']}")
    print(
        f"by design {report['by_design_escaped']}, findings {report['finding_escaped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
