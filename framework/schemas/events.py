"""Event envelope (PLAN section 2.2) with typed data per event type."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from framework.schemas.base import SchemaModel, Tier

NonEmptyStr = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class CalendarEventData(SchemaModel):
    start: AwareDatetime
    end: AwareDatetime
    busy: bool
    category: str
    tags: list[str]
    is_new: bool

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "CalendarEventData":
        if self.end < self.start:
            raise ValueError("calendar event end must not be before start")
        return self


class CalendarEventCreatedData(CalendarEventData):
    type: Literal["calendar.event.created"] = "calendar.event.created"


class CalendarEventUpdatedData(CalendarEventData):
    type: Literal["calendar.event.updated"] = "calendar.event.updated"


class CalendarEventCancelledData(CalendarEventData):
    type: Literal["calendar.event.cancelled"] = "calendar.event.cancelled"


class GitHubPushData(SchemaModel):
    type: Literal["github.push"] = "github.push"
    repo: str
    counts: dict[str, NonNegativeInt]


class GitHubPrData(SchemaModel):
    type: Literal["github.pr"] = "github.pr"
    repo: str
    counts: dict[str, NonNegativeInt]


class GitHubIssueData(SchemaModel):
    type: Literal["github.issue"] = "github.issue"
    repo: str
    counts: dict[str, NonNegativeInt]


class GitHubReleaseData(SchemaModel):
    type: Literal["github.release"] = "github.release"
    repo: str
    counts: dict[str, NonNegativeInt]


class FeedItemData(SchemaModel):
    type: Literal["feed.item"] = "feed.item"
    title: str
    url: str
    source: str
    score: NonNegativeFloat


class MusicPlayData(SchemaModel):
    type: Literal["music.play"] = "music.play"
    track: str
    artist: str
    played_at: AwareDatetime


class HealthDailyData(SchemaModel):
    type: Literal["health.daily"] = "health.daily"
    sleep_h: NonNegativeFloat | None = None
    resting_hr: NonNegativeFloat | None = None
    hrv_ms: NonNegativeFloat | None = None
    steps: NonNegativeInt | None = None
    exercise_min: NonNegativeFloat | None = None
    mindful_min: NonNegativeFloat | None = None
    daylight_min: NonNegativeFloat | None = None
    mood_valence: Annotated[float, Field(ge=-1, le=1)] | None = None


class ScreenHourData(SchemaModel):
    type: Literal["screen.hour"] = "screen.hour"
    device: Literal["mac", "iphone"]
    minutes_by_category: dict[str, NonNegativeFloat]


class EditorHourData(SchemaModel):
    type: Literal["editor.hour"] = "editor.hour"
    project: str
    language: str
    minutes: NonNegativeFloat


class JobStageCounts(SchemaModel):
    applied: NonNegativeInt
    screen: NonNegativeInt
    interview: NonNegativeInt
    offer: NonNegativeInt


class JobsSnapshotData(SchemaModel):
    type: Literal["jobs.snapshot"] = "jobs.snapshot"
    counts: JobStageCounts


class AppViewData(SchemaModel):
    type: Literal["app.view"] = "app.view"
    block_id: str
    screen: str | None = None


class AppTapData(SchemaModel):
    type: Literal["app.tap"] = "app.tap"
    block_id: str
    target: str


class AppThumbData(SchemaModel):
    type: Literal["app.thumb"] = "app.thumb"
    block_id: str
    value: Literal[-1, 1]


class AppRatingData(SchemaModel):
    type: Literal["app.rating"] = "app.rating"
    block_id: str | None = None
    value: float


class AppApproveData(SchemaModel):
    type: Literal["app.approve"] = "app.approve"
    manifest_version: str
    card_id: str | None = None


class AppRejectData(SchemaModel):
    type: Literal["app.reject"] = "app.reject"
    manifest_version: str
    card_id: str | None = None


class AppCheckinData(SchemaModel):
    type: Literal["app.checkin"] = "app.checkin"
    energy: Annotated[int, Field(ge=1, le=5)]


class AppJournalData(SchemaModel):
    type: Literal["app.journal"] = "app.journal"
    text: NonEmptyStr


EventData = Annotated[
    CalendarEventCreatedData
    | CalendarEventUpdatedData
    | CalendarEventCancelledData
    | GitHubPushData
    | GitHubPrData
    | GitHubIssueData
    | GitHubReleaseData
    | FeedItemData
    | MusicPlayData
    | HealthDailyData
    | ScreenHourData
    | EditorHourData
    | JobsSnapshotData
    | AppViewData
    | AppTapData
    | AppThumbData
    | AppRatingData
    | AppApproveData
    | AppRejectData
    | AppCheckinData
    | AppJournalData,
    Field(discriminator="type"),
]

EventType = Literal[
    "calendar.event.created",
    "calendar.event.updated",
    "calendar.event.cancelled",
    "github.push",
    "github.pr",
    "github.issue",
    "github.release",
    "feed.item",
    "music.play",
    "health.daily",
    "screen.hour",
    "editor.hour",
    "jobs.snapshot",
    "app.view",
    "app.tap",
    "app.thumb",
    "app.rating",
    "app.approve",
    "app.reject",
    "app.checkin",
    "app.journal",
]

SENSITIVE_TYPES: frozenset[str] = frozenset({"health.daily", "app.journal"})


class Event(SchemaModel):
    id: NonEmptyStr
    subject_id: NonEmptyStr
    source: NonEmptyStr
    type: EventType
    time: AwareDatetime
    source_id: NonEmptyStr
    data: EventData
    tier: Tier
    collected_at: AwareDatetime
    collector_version: NonEmptyStr

    @model_validator(mode="after")
    def _type_and_tier_rules(self) -> "Event":
        if self.type != self.data.type:
            raise ValueError("event type must match data type")
        if self.type in SENSITIVE_TYPES and self.tier != "sensitive":
            raise ValueError(f"{self.type} events must have tier 'sensitive'")
        return self
