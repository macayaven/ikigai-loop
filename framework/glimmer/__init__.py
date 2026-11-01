"""Ticket 9: Glimmer fact layer (pure core plus CLI-edge client)."""

from framework.briefing.context import MetricSnapshot
from framework.glimmer.checks import check_fact, highest_tier, resolve_aliases
from framework.glimmer.facts import (
    ALLOWED_TYPES,
    MAX_FACTS,
    MAX_FEED_PER_SOURCE,
    MAX_PROMPT_EVENTS,
    AttemptRecord,
    DroppedFact,
    FactResult,
    LLMClient,
    LLMResponse,
    LLMUnavailableError,
    PassResult,
    extract_facts,
)
from framework.glimmer.llm import (
    MODEL_MAX_TOKENS,
    MODEL_TIMEOUT_S,
    LLMConfig,
    OpenAICompatibleClient,
    load_llm_config,
    sanitise_model_id,
)
from framework.glimmer.metrics import (
    WINDOW,
    build_metric_snapshot,
    build_period_rollup,
    select_winners,
)
from framework.glimmer.prompt import (
    REPAIR_SUFFIX,
    build_feed_prompt,
    build_personal_prompt,
    strip_feed_title,
)
from framework.glimmer.schemas import (
    FactDraft,
    FactDraftBatch,
    FeedTopicBatch,
    FeedTopicDraft,
)

__all__ = [
    "ALLOWED_TYPES",
    "MAX_FACTS",
    "MAX_FEED_PER_SOURCE",
    "MAX_PROMPT_EVENTS",
    "MODEL_MAX_TOKENS",
    "MODEL_TIMEOUT_S",
    "REPAIR_SUFFIX",
    "WINDOW",
    "AttemptRecord",
    "DroppedFact",
    "FactDraft",
    "FactDraftBatch",
    "FactResult",
    "FeedTopicBatch",
    "FeedTopicDraft",
    "LLMClient",
    "LLMConfig",
    "LLMResponse",
    "LLMUnavailableError",
    "MetricSnapshot",
    "OpenAICompatibleClient",
    "PassResult",
    "build_feed_prompt",
    "build_metric_snapshot",
    "build_period_rollup",
    "build_personal_prompt",
    "check_fact",
    "extract_facts",
    "highest_tier",
    "load_llm_config",
    "resolve_aliases",
    "sanitise_model_id",
    "select_winners",
    "strip_feed_title",
]
