"""The mock is a model stand-in: same context in, same JSON out."""

from __future__ import annotations

import json

import pytest

from museum.context import build_context
from museum.llm import load_curator
from museum.llm.mock import MockCurator
from museum.seed import SEED_ARTIFACTS
from museum.validator import validate_draft


def context(iteration: int = 1, attempt: int = 0) -> dict:
    ctx = build_context(list(SEED_ARTIFACTS), iteration=iteration, max_attempts=3)
    ctx["attempt"] = attempt
    return ctx


def test_mock_is_deterministic():
    a = MockCurator(chaos="off").propose(context(3))
    b = MockCurator(chaos="off").propose(context(3))
    assert a == b
    assert json.loads(a) == json.loads(b)


def test_mock_output_passes_the_validator():
    for iteration in range(1, 31):
        draft = json.loads(MockCurator(chaos="off").propose(context(iteration)))
        report = validate_draft(draft, list(SEED_ARTIFACTS))
        assert report.ok, (iteration, report.to_dict())


def test_mock_chaos_produces_rejections():
    draft = json.loads(MockCurator(chaos="always").propose(context(4)))
    report = validate_draft(draft, list(SEED_ARTIFACTS))
    assert not report.ok


def test_mock_chaos_sometimes_only_on_first_attempt():
    chaotic = MockCurator(chaos="sometimes")
    first = json.loads(chaotic.propose(context(8, attempt=0)))
    second = json.loads(chaotic.propose(context(8, attempt=1)))
    assert not validate_draft(first, list(SEED_ARTIFACTS)).ok
    assert validate_draft(second, list(SEED_ARTIFACTS)).ok


def test_mock_respects_the_directive():
    ctx = context(5)
    draft = json.loads(MockCurator(chaos="off").propose(ctx))
    assert draft["lineage"] == ctx["directive"]["focus_lineage"]
    floor = ctx["chronology"]["year_floor"]
    assert floor < draft["year_fictional"] <= floor + ctx["directive"]["year_span"]


def test_mock_rejects_unknown_chaos():
    with pytest.raises(ValueError):
        MockCurator(chaos="kadang-kadang")


def test_load_curator_switches_implementations(monkeypatch):
    monkeypatch.delenv("MUSEUM_LLM", raising=False)
    assert isinstance(load_curator("mock"), MockCurator)
    assert isinstance(load_curator("mock:abc"), MockCurator)
    with pytest.raises(ValueError):
        load_curator("swarm:7")
