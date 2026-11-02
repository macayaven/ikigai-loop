"""The fixed limit sentences, shared by the CLI and the comparison code."""

from __future__ import annotations

LIMITS = {
    "LIMIT_ONE_FAMILY_ONE_SOURCE": "I audit one number family against one public source. Every other "
    "number on the card is unchecked by this run.",
    "LIMIT_FEED_WINDOW": "I read at most 300 events from the past 30 days, "
    "and an event can take up to 6 hours to appear in the feed. On Nov 1 "
    "the feed showed no push for 17 merges and 17 new branches that the "
    "repo's activity list did show, so a covered window can still miss "
    "rows the feed never showed.",
    "LIMIT_PUSHES_FEED_ONLY": "Pushes have no independent public source here. For pushes I audit "
    "only the path from the feed to the card, not the count against "
    "the world.",
    "LIMIT_OTHER_REPOS_FEED_ONLY": "Only the named repo gets the pull list and the activity rows. "
    "Every other repo in the count comes from the feed alone.",
    "LIMIT_DELTA_NOT_AUDITED": "Claims that state a change since the parent card are deltas. "
    "I count them and do not audit them.",
    "LIMIT_EVIDENCE_AND_DIRECTION": "Fact evidence lists and direction words are not audited. A "
    "statement can cite the wrong rows, or say rose for fell, and this "
    "run will not catch it.",
    "LIMIT_OTHER_FAMILIES_NOT_TOUCHED": "Screen and calendar numbers are not touched by this run.",
    "LIMIT_UNPARSED_NEEDS_HUMAN": "A paraphrase my parser cannot read is unavailable, not wrong. "
    "It needs a human reader.",
    "LIMIT_FEED_MAY_SETTLE": "This snapshot was taken under 6 hours after the window closed. A "
    "feed row that has not appeared yet can make this run a mismatch "
    "that clears on a later re-run.",
}
