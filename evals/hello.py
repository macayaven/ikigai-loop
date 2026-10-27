"""Ticket 1: hello Inspect task.

Runs offline on Inspect's built-in mock model (`mockllm/model`). The mock
model's completion is deterministic, so the `exact` scorer passes without
any network access or API key.
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

MOCK_COMPLETION = "Default output from mockllm/model"


@task
def hello() -> Task:
    return Task(
        dataset=[Sample(input="Say hello.", target=MOCK_COMPLETION)],
        solver=[generate()],
        scorer=exact(),
    )
