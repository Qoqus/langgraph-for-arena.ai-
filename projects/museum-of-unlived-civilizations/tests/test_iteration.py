"""End-to-end behaviour of the cyclical curator, with the mock model."""

from __future__ import annotations

import json

from museum.llm.mock import MockCurator
from museum.runner import Museum, Scheduler
from museum.seed import SEED_ARTIFACTS
from museum.vocabulary import FORMS, FUNCTIONS, LINEAGES, MATERIALS, MOTIFS, PALETTES


class GarbageCurator:
    name = "garbage/0"

    def propose(self, context: dict) -> str:
        return "Saya tidak bisa mematuhi skema hari ini."


def make_museum(path, chaos="sometimes", **kwargs) -> Museum:
    return Museum(
        path, llm=MockCurator(chaos=chaos), max_attempts=kwargs.pop("max_attempts", 3), **kwargs
    )


def test_twenty_iterations_produce_a_valid_chronology(tmp_path):
    museum = make_museum(tmp_path / "state")
    try:
        museum.run(iterations=20)
        snapshot = museum.snapshot()
        catalog = museum.catalog()

        assert snapshot["iteration"] == 20
        assert snapshot["status"] == "complete"
        assert len(catalog) == len(SEED_ARTIFACTS) + 20

        ids = [a.id for a in catalog]
        assert len(ids) == len(set(ids)), "id harus unik"

        known: set[str] = set()
        last_year = -1
        for artifact in sorted(catalog, key=lambda a: (a.iteration, a.year_fictional, a.id)):
            for ref in artifact.refs:
                assert ref.id in known, f"{artifact.id} merujuk {ref.id} yang belum ada"
            known.add(artifact.id)
            assert artifact.year_fictional >= last_year, "tahun tidak boleh mundur"
            last_year = artifact.year_fictional

            assert artifact.lineage in LINEAGES
            assert artifact.form in FORMS
            assert artifact.function in FUNCTIONS
            assert artifact.visual.palette in PALETTES
            assert artifact.visual.motif in artifact.motifs
            assert set(artifact.materials) <= set(MATERIALS)
            assert set(artifact.motifs) <= set(MOTIFS)

        # every accession has its deterministic plaque
        for artifact in catalog:
            svg = museum.paths.renders / f"{artifact.id}.svg"
            assert svg.exists(), f"plakat hilang untuk {artifact.id}"
            assert artifact.title in svg.read_text(
                encoding="utf-8"
            ) or artifact.id.upper() in svg.read_text(encoding="utf-8")

        # projection and ledger agree with the checkpoint
        payload = json.loads(museum.paths.catalog_json.read_text(encoding="utf-8"))
        assert len(payload["artifacts"]) == len(catalog)
        ledger = [json.loads(line) for line in museum.paths.ledger_jsonl.read_text().splitlines()]
        assert {row["id"] for row in ledger} == set(ids)
        assert museum.verify()["ok"] is True

        # the run actually exercised the repair cycle without losing an iteration
        repaired = [a for a in catalog if a.attempt > 0]
        assert repaired, "mock chaos harus memaksa setidaknya satu perbaikan"
        assert snapshot.get("rejections") == []
    finally:
        museum.close()


def test_rejected_draft_writes_nothing(tmp_path):
    museum = make_museum(tmp_path / "state", chaos="always", max_attempts=2)
    try:
        museum.run(iterations=1)
        snapshot = museum.snapshot()
        catalog = museum.catalog()

        assert len(catalog) == len(SEED_ARTIFACTS), "tidak boleh ada state parsial"
        assert snapshot["iteration"] == 1
        assert len(snapshot["rejections"]) == 1
        rejection = snapshot["rejections"][0]
        assert rejection["codes"], "penolakan harus mencatat pelanggaran"
        assert rejection["attempt"] == 2

        ledger_ids = {
            json.loads(line)["id"]
            for line in museum.paths.ledger_jsonl.read_text().splitlines()
            if line.strip()
        }
        assert ledger_ids == {a.id for a in SEED_ARTIFACTS}

        payload = json.loads(museum.paths.catalog_json.read_text(encoding="utf-8"))
        assert payload["counts"]["artifacts"] == len(SEED_ARTIFACTS)
        assert payload["counts"]["rejections"] == 1
        assert museum.verify()["ok"] is True
    finally:
        museum.close()


def test_unparseable_model_output_is_a_rejection_not_a_crash(tmp_path):
    museum = Museum(tmp_path / "state", llm=GarbageCurator(), max_attempts=1)
    try:
        museum.run(iterations=1)
        snapshot = museum.snapshot()
        assert len(museum.catalog()) == len(SEED_ARTIFACTS)
        rejection = snapshot["rejections"][0]
        assert rejection["parse_error"]
        assert "SCHEMA" in rejection["codes"]
    finally:
        museum.close()


def test_state_survives_process_restart(tmp_path):
    root = tmp_path / "state"
    first = make_museum(root)
    first.run(iterations=5)
    catalog_before = [a.canonical() for a in first.catalog()]
    first.close()

    second = make_museum(root)
    try:
        assert second.iteration() == 5
        assert [a.canonical() for a in second.catalog()] == catalog_before
        assert second.verify()["ok"] is True

        second.run(iterations=3)
        assert second.iteration() == 8
        assert len(second.catalog()) == len(catalog_before) + 3
        assert [a.canonical() for a in second.catalog()][: len(catalog_before)] == catalog_before
    finally:
        second.close()


def test_catalog_is_append_only_and_immutable(museum):
    museum.run(iterations=3)
    first_generation = {a.id: a.digest() for a in museum.catalog()}
    museum.run(iterations=3)
    for artifact in museum.catalog():
        if artifact.id in first_generation:
            assert artifact.digest() == first_generation[artifact.id], (
                "artefak lama tidak boleh berubah"
            )


def test_time_travel_history_is_available(museum):
    museum.run(iterations=3)
    rows = museum.history(limit=200)
    assert len(rows) > 5
    artifact_counts = [row["artifacts"] for row in rows]
    assert min(artifact_counts) >= len(SEED_ARTIFACTS)
    assert max(artifact_counts) == len(museum.catalog())
    assert any(row["status"] == "committed" for row in rows)


def test_checkpoint_names_are_replayable(museum):
    museum.run(iterations=1)
    state = museum.graph.get_state(museum.config)
    assert state.values["iteration"] == 1
    assert len(state.values["catalog"]) == len(SEED_ARTIFACTS) + 1
    assert state.values["pending_draft"] is not None


def test_human_in_the_loop_can_approve(tmp_path):
    museum = make_museum(tmp_path / "state", human_review=True)
    try:
        museum.run(iterations=1)
        pending = museum.pending_interrupt()
        assert pending and pending["node"] == "human_review"
        assert len(museum.catalog()) == len(SEED_ARTIFACTS), "belum boleh commit sebelum disetujui"

        museum.resume({"decision": "approve", "note": "disetujui untuk uji"})
        assert len(museum.catalog()) == len(SEED_ARTIFACTS) + 1
        assert museum.snapshot()["review_decision"]["decision"] == "approve"
    finally:
        museum.close()


def test_human_in_the_loop_can_edit_then_reject_invalid_edit(tmp_path):
    museum = make_museum(tmp_path / "state", human_review=True)
    try:
        museum.run(iterations=1)
        draft = dict(museum.pending_interrupt()["value"]["draft"])
        draft["year_fictional"] = 5
        museum.resume({"decision": "edit", "artifact": draft})
        assert len(museum.catalog()) == len(SEED_ARTIFACTS)
        assert museum.snapshot().get("rejections")
        assert "YEAR_REGRESSION" in museum.snapshot()["rejections"][0]["codes"]
    finally:
        museum.close()


def test_scheduler_runs_until_budget(tmp_path):
    museum = make_museum(tmp_path / "state", chaos="off")
    ticks: list[int] = []
    scheduler = Scheduler(
        museum,
        interval_seconds=0.01,
        max_iterations=5,
        on_tick=lambda tick, state: ticks.append(state["iteration"]),
        logger=lambda msg: None,
    )
    try:
        scheduler.run_forever()
        assert museum.iteration() == 5
        assert len(ticks) == 5
        assert museum.verify()["ok"] is True
    finally:
        scheduler.stop()
        museum.close()


def test_scheduler_single_writer_lock(tmp_path):
    museum = make_museum(tmp_path / "state")
    other = make_museum(tmp_path / "state")
    try:
        first = Scheduler(museum, interval_seconds=0.01, logger=lambda msg: None)
        second = Scheduler(other, interval_seconds=0.01, logger=lambda msg: None)
        assert first.acquire() is True
        assert second.acquire() is False
        first.release()
        assert second.acquire() is True
        second.release()
    finally:
        museum.close()
        other.close()


def test_projection_can_be_rebuilt_from_checkpoint(museum):
    museum.run(iterations=3)
    catalog = [a.canonical() for a in museum.catalog()]
    museum.paths.catalog_json.unlink()
    museum.paths.ledger_jsonl.unlink()
    for svg in museum.paths.renders.glob("*.svg"):
        svg.unlink()

    result = museum.rebuild()
    assert result["artifacts"] == len(catalog)
    assert museum.paths.catalog_json.exists()
    assert len(list(museum.paths.renders.glob("*.svg"))) == len(catalog)
    assert museum.verify()["ok"] is True
    assert [a.canonical() for a in museum.catalog()] == catalog
