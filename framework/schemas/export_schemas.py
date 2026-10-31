"""Export JSON Schema for every core model to schemas/*.json."""

import json
from pathlib import Path

from pydantic import BaseModel

from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
)
from framework.briefing.schemas import Action, Briefing, Claim, MetricRef, Section
from framework.schemas.core import Criterion, Fact, FactWindow, IkigaiWeights, Profile
from framework.schemas.events import (
    AppApproveData,
    AppCheckinData,
    AppJournalData,
    AppRatingData,
    AppRejectData,
    AppTapData,
    AppThumbData,
    AppViewData,
    CalendarEventCancelledData,
    CalendarEventCreatedData,
    CalendarEventUpdatedData,
    EditorHourData,
    Event,
    FeedItemData,
    GitHubIssueData,
    GitHubPrData,
    GitHubPushData,
    GitHubReleaseData,
    HealthDailyData,
    JobsSnapshotData,
    JobStageCounts,
    MusicPlayData,
    ScreenHourData,
)
from framework.schemas.manifest import (
    BlockConfig,
    ChangelogEntry,
    Decision,
    Manifest,
    ManifestDiff,
)

EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    Event,
    CalendarEventCreatedData,
    CalendarEventUpdatedData,
    CalendarEventCancelledData,
    GitHubPushData,
    GitHubPrData,
    GitHubIssueData,
    GitHubReleaseData,
    FeedItemData,
    MusicPlayData,
    HealthDailyData,
    ScreenHourData,
    EditorHourData,
    JobStageCounts,
    JobsSnapshotData,
    AppViewData,
    AppTapData,
    AppThumbData,
    AppRatingData,
    AppApproveData,
    AppRejectData,
    AppCheckinData,
    AppJournalData,
    FactWindow,
    Fact,
    IkigaiWeights,
    Profile,
    Criterion,
    BlockConfig,
    ChangelogEntry,
    Manifest,
    ManifestDiff,
    Decision,
    Briefing,
    Section,
    Claim,
    Action,
    MetricRef,
    MetricSnapshot,
    TimeInterval,
    ProfileLimits,
    GateContext,
)

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schemas(out_dir: Path = SCHEMAS_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in EXPORTED_MODELS:
        path = out_dir / f"{model.__name__}.json"
        path.write_text(schema_text(model), encoding="utf-8")
        written.append(path)
    return written


def find_drift(schema_dir: Path = SCHEMAS_DIR) -> list[str]:
    drifted: list[str] = []
    for model in EXPORTED_MODELS:
        path = schema_dir / f"{model.__name__}.json"
        if not path.exists() or path.read_text(encoding="utf-8") != schema_text(model):
            drifted.append(model.__name__)
    return drifted


def main() -> None:
    for path in export_schemas():
        print(path)


if __name__ == "__main__":
    main()
