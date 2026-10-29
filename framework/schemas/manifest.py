"""Manifest, BlockConfig base and Decision schemas (SPEC section 3)."""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr


class BlockConfig(SchemaModel):
    type: NonEmptyStr
    dimension: Dimension
    config: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class ChangelogEntry(SchemaModel):
    from_version: str | None = Field(default=None, alias="from")
    change: str
    why: str
    evidence: Annotated[list[NonEmptyStr], Field(min_length=1)]


class Manifest(SchemaModel):
    version: NonEmptyStr
    parent: str | None
    layout: list[str]
    blocks: dict[str, BlockConfig]
    changelog: list[ChangelogEntry]


class ManifestDiff(SchemaModel):
    base_version: NonEmptyStr
    candidate: Manifest


DecisionKind = Literal["noop", "evolve", "recalibrate", "refine_objective"]


class Decision(SchemaModel):
    kind: DecisionKind
    rationale: str
    evidence: list[NonEmptyStr]
    manifest_diff: ManifestDiff | None = None

    @model_validator(mode="after")
    def _kind_rules(self) -> "Decision":
        if self.kind == "evolve":
            if self.manifest_diff is None:
                raise ValueError("evolve decisions require manifest_diff")
            if self.manifest_diff.candidate.parent != self.manifest_diff.base_version:
                raise ValueError(
                    "manifest_diff candidate parent must equal base_version"
                )
        elif self.manifest_diff is not None:
            raise ValueError("manifest_diff is only allowed for evolve decisions")
        if self.kind != "noop":
            if not self.rationale.strip():
                raise ValueError("non-noop decisions require a rationale")
            if not self.evidence:
                raise ValueError("non-noop decisions require evidence")
        return self
