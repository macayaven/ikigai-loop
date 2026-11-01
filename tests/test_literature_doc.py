"""Docs 2: literature links are well formed; PREREG registered text is pinned."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LITERATURE = REPO_ROOT / "docs" / "LITERATURE.md"
PREREG = REPO_ROOT / "docs" / "PREREG.md"

# sha256 of the bytes before "## Deviations" in
# `git show 79c9f3a:docs/PREREG.md`, computed before this ticket's edit.
REGISTERED_SHA256 = "d537e90dd8111aaca21ead9dd0af32471dbb1936f021c1064591c5f847bf90c8"

DOI_RE = re.compile(r"^https://doi\.org/10\.\d{4,9}/\S+$")
PMC_RE = re.compile(r"^https://pmc\.ncbi\.nlm\.nih\.gov/articles/PMC\d+/?$")
ACL_RE = re.compile(r"^https://aclanthology\.org/\S+$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def test_literature_links_well_formed() -> None:
    text = LITERATURE.read_text(encoding="utf-8")
    assert "Nov 1, 2026" in text
    urls = LINK_RE.findall(text)
    dois = [u for u in urls if "doi.org" in u]
    pmcs = [u for u in urls if "pmc.ncbi.nlm.nih.gov" in u]
    acls = [u for u in urls if "aclanthology.org" in u]
    assert dois and pmcs and acls
    for url in dois:
        assert DOI_RE.match(url), url
    for url in pmcs:
        assert PMC_RE.match(url), url
    for url in acls:
        assert ACL_RE.match(url), url


def test_prereg_registered_text_unchanged() -> None:
    raw = PREREG.read_bytes()
    assert raw.count(b"## Deviations") == 1
    prefix = raw.split(b"## Deviations")[0]
    assert hashlib.sha256(prefix).hexdigest() == REGISTERED_SHA256
