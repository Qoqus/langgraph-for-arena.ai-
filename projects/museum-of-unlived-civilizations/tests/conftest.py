from __future__ import annotations

import json

import pytest

from museum.context import build_context
from museum.llm.mock import MockCurator
from museum.runner import Museum
from museum.schema import Artifact
from museum.seed import SEED_ARTIFACTS


@pytest.fixture()
def state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture()
def museum(state_dir):
    instance = Museum(state_dir, llm=MockCurator(chaos="sometimes"), max_attempts=3)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture()
def seed_catalog() -> list[Artifact]:
    return list(SEED_ARTIFACTS)


def drafts_for(catalog: list[Artifact], iteration: int = 1, attempt: int = 0) -> dict:
    """A clean draft produced by the mock, for tests that need a valid baseline."""
    context = build_context(catalog, iteration=iteration, max_attempts=3)
    context["attempt"] = attempt
    raw = MockCurator(chaos="off").propose(context)
    return json.loads(raw)
