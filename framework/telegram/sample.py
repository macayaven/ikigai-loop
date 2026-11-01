"""Sample card and chart: invented values, never stored."""

from datetime import UTC, datetime

from framework.telegram.models import Card, ChartData

SLOT = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
START = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
END = datetime(2026, 11, 2, 17, 25, tzinfo=UTC)

SAMPLE_CARD = Card.model_validate(
    {
        "slot": SLOT,
        "since_line": "Since 15:30: sample card, synthetic values.",
        "proposals": [
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": "Write-up draft",
                "start": START,
                "end": END,
            },
            {
                "letter": "B",
                "kind": "proposal",
                "profile": "Disconnect",
                "title": "Family call",
                "start": START,
                "end": END,
            },
        ],
        "statements": ["Sample statement, synthetic values."],
    }
)

SAMPLE_CHART = ChartData.model_validate(
    {
        "period_labels": ["earlier", "prior", "last"],
        "screen": [
            {"label": "code", "earlier": 4.0, "prior": 6.0, "last": 8.0},
            {"label": "comms", "earlier": 1.0, "prior": 2.0, "last": 3.0},
            {"label": "feed", "earlier": 0.0, "prior": 1.0, "last": 2.0},
        ],
        "pushes": {"label": "pushes", "earlier": 0.0, "prior": 1.0, "last": 2.0},
        "tally": [
            {"label": "Builder", "count": 3},
            {"label": "Disconnect", "count": 1},
            {"label": "Neither", "count": 0},
        ],
    }
)
