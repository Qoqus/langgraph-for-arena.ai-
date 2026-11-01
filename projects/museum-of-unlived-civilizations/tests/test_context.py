"""The deterministic brief: pacing, ledgers and feasible references."""

from __future__ import annotations

from museum.context import DIRECTIVE_CYCLE, build_context, choose_directive, ledger
from museum.seed import SEED_ARTIFACTS
from museum.vocabulary import LINEAGES


def test_directive_cycle_covers_every_kind():
    seen = set()
    catalog = list(SEED_ARTIFACTS)
    for iteration in range(1, 21):
        directive = choose_directive(catalog, iteration)
        seen.add(directive["kind"])
    assert set(DIRECTIVE_CYCLE) <= seen
    assert len(DIRECTIVE_CYCLE) == 5


def test_directive_references_always_exist_and_are_not_the_future():
    catalog = list(SEED_ARTIFACTS)
    known = {a.id for a in catalog}
    for iteration in range(1, 12):
        directive = choose_directive(catalog, iteration)
        for candidate in directive["ref_candidates"]:
            assert candidate["id"] in known
            assert candidate["year"] <= directive["year_floor"]
        assert directive["year_span"] > 0


def test_directive_never_asks_for_an_unknown_lineage():
    catalog = list(SEED_ARTIFACTS)
    for iteration in range(1, 30):
        directive = choose_directive(catalog, iteration)
        assert directive["focus_lineage"] in LINEAGES
        if directive["partner_lineage"]:
            assert directive["partner_lineage"] in LINEAGES
            assert directive["partner_lineage"] != directive["focus_lineage"]


def test_directive_focus_materials_are_in_the_vocabulary():
    from museum.vocabulary import MATERIALS

    catalog = list(SEED_ARTIFACTS)
    for iteration in range(1, 14):
        directive = choose_directive(catalog, iteration)
        for material in directive["focus_materials"]:
            assert material in MATERIALS


def test_ledger_reads_the_whole_catalog():
    catalog = list(SEED_ARTIFACTS)
    state = ledger(catalog)
    assert sum(entry["count"] for entry in state["lineages"].values()) == len(catalog)
    assert {a.lineage for a in catalog} == set(state["lineages"])
    assert state["citations"], "seed sudah mengandung rujukan"
    # karrun-topeng-mata dirujuk oleh artefak tirsa pada seed? minimal satu kutipan tercatat
    assert all(isinstance(count, int) for count in state["citations"].values())


def test_context_is_json_serialisable_and_self_contained():
    import json

    catalog = list(SEED_ARTIFACTS)
    context = build_context(catalog, iteration=1, max_attempts=3)
    encoded = json.dumps(context, ensure_ascii=False)
    assert len(encoded) > 2000
    assert context["chronology"]["year_floor"] == max(a.year_fictional for a in catalog)
    assert context["vocabulary"]["hint"]
    for artifact in context["registry"]:
        assert artifact["id"]


def test_dormant_material_produces_a_revival_directive():
    from museum.schema import Artifact

    catalog = list(SEED_ARTIFACTS)
    # fabrication: pretend the museum has been running for a while without obsidian
    long_run = [
        Artifact.model_validate(
            {
                **SEED_ARTIFACTS[0].canonical(),
                "id": f"savra-guci-lama-{i}",
                "title": f"Guci Lama {i}",
                "year_fictional": 400 + i,
                "iteration": i + 1,
            }
        )
        for i in range(6)
    ]
    directive = choose_directive(catalog + long_run, 7)
    assert directive["kind"] == "pemulihan"
    assert directive["focus_materials"][0] in {
        "obsidian",
        "tulang-paus",
        "kayu-cendana",
        "perunggu-timah",
    }


def test_empty_catalog_still_gets_a_directive():
    directive = choose_directive([], 1)
    assert directive["kind"] == "kelanjutan"
    assert directive["ref_candidates"] == []
    assert directive["year_floor"] == 0
    assert directive["focus_lineage"] in LINEAGES


def test_museum_can_start_without_a_seed(tmp_path):
    from museum.llm.mock import MockCurator
    from museum.runner import Museum

    museum = Museum(tmp_path / "state", llm=MockCurator(chaos="off"), seed=False)
    try:
        museum.run(iterations=1)
        catalog = museum.catalog()
        assert len(catalog) == 1
        assert catalog[0].refs == ()
        assert museum.verify()["ok"] is True
    finally:
        museum.close()
