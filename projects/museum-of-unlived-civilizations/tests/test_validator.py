from __future__ import annotations

import copy
import json

import pytest
from conftest import drafts_for

from museum.seed import SEED_ARTIFACTS
from museum.validator import validate_draft, verify_catalog


@pytest.fixture()
def catalog():
    return list(SEED_ARTIFACTS)


@pytest.fixture()
def draft(catalog):
    return drafts_for(catalog, iteration=1)


def codes(report) -> set[str]:
    return set(report.codes())


def test_seed_catalog_is_valid():
    assert verify_catalog(list(SEED_ARTIFACTS)) == []
    assert len({a.id for a in SEED_ARTIFACTS}) == len(SEED_ARTIFACTS)


def test_valid_draft_accepted(catalog, draft):
    report = validate_draft(draft, catalog)
    assert report.ok, report.to_dict()


def test_duplicate_id_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["id"] = catalog[1].id
    report = validate_draft(bad, catalog)
    assert not report.ok
    assert "ID_DUPLICATE" in codes(report)


def test_missing_reference_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["refs"] = [{"id": "tidak-pernah-ada", "relation": "kutipan", "note": "mengarang rujukan"}]
    report = validate_draft(bad, catalog)
    assert not report.ok
    assert "REF_MISSING" in codes(report)


def test_year_regression_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["year_fictional"] = max(a.year_fictional for a in catalog) - 12
    report = validate_draft(bad, catalog)
    assert not report.ok
    assert "YEAR_REGRESSION" in codes(report)


def test_year_jump_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["year_fictional"] = max(a.year_fictional for a in catalog) + 400
    assert "YEAR_JUMP" in codes(validate_draft(bad, catalog))


def test_unknown_material_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["materials"] = ["batu-bulan", *bad["materials"][:1]]
    assert "MATERIAL_UNKNOWN" in codes(validate_draft(bad, catalog))


def test_unknown_motif_and_palette_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["motifs"] = ["motif-karangan"]
    bad["visual"]["motif"] = "motif-karangan"
    bad["visual"]["palette"] = "pelangi"
    found = codes(validate_draft(bad, catalog))
    assert {"MOTIF_UNKNOWN", "PALETTE_UNKNOWN"} <= found


def test_unknown_lineage_form_function_rejected(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["lineage"] = "atlantis"
    bad["form"] = "pesawat"
    bad["function"] = "hiburan-massal"
    bad["visual"]["form"] = "pesawat"
    found = codes(validate_draft(bad, catalog))
    assert {"LINEAGE_UNKNOWN", "FORM_UNKNOWN", "FUNCTION_UNKNOWN"} <= found


def test_reference_ordering_and_self_reference(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["refs"] = [
        {"id": bad["id"], "relation": "kutipan", "note": "merujuk dirinya sendiri, tidak sah"},
        {
            "id": catalog[-1].id,
            "relation": "kutipan",
            "note": "catatan berbeda untuk rujukan kedua",
        },
    ]
    found = codes(validate_draft(bad, catalog))
    assert "REF_SELF" in found


def test_material_bearing_relation_must_share_material(catalog, draft):
    target = next(a for a in catalog if a.lineage != draft["lineage"])
    bad = copy.deepcopy(draft)
    bad["materials"] = [m for m in bad["materials"] if m not in target.materials]
    bad["refs"] = [
        {"id": target.id, "relation": "turunan", "note": "mengaku turunan tanpa membawa bahannya"}
    ]
    assert "REF_UNJUSTIFIED_MATERIAL" in codes(validate_draft(bad, catalog))


def test_resonance_must_share_motif(catalog, draft):
    target = next(a for a in catalog if not set(a.motifs) & set(draft["motifs"]))
    bad = copy.deepcopy(draft)
    bad["refs"] = [
        {"id": target.id, "relation": "resonansi", "note": "mengaku resonansi tanpa motif bersama"}
    ]
    assert "REF_UNJUSTIFIED_MOTIF" in codes(validate_draft(bad, catalog))


def test_refs_required_once_catalog_exists(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["refs"] = []
    assert "REFS_EMPTY" in codes(validate_draft(bad, catalog))


def test_new_lineage_needs_two_ancestors(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["lineage"] = "tirsa"  # not yet in the seeded catalog
    bad["materials"] = ["gipsum-berlapis"]
    bad["refs"] = [
        {"id": catalog[0].id, "relation": "kutipan", "note": "satu leluhur saja tidak cukup"}
    ]
    report = validate_draft(bad, catalog)
    assert "NEW_LINEAGE_UNDERJUSTIFIED" in codes(report)


def test_lineage_material_identity(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["materials"] = [m for m in bad["materials"] if m not in ("obsidian", "tulang-paus")] or [
        "serat-pandan"
    ]
    assert "LINEAGE_MATERIAL_MISMATCH" in codes(validate_draft(bad, catalog))


def test_visual_must_match_artifact(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["visual"]["form"] = "monolit" if bad["form"] != "monolit" else "guci"
    bad["visual"]["motif"] = (
        next(m for m in bad["motifs"] if m != bad["visual"]["motif"])
        if len(bad["motifs"]) > 1
        else "simpul-tiga"
    )
    found = codes(validate_draft(bad, catalog))
    assert "VISUAL_FORM_MISMATCH" in found


def test_schema_violations_are_reported_not_raised(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["year_fictional"] = "tahun lama"
    bad["unknown_field"] = True
    bad["visual"]["density"] = 12
    report = validate_draft(bad, catalog)
    assert not report.ok
    assert "SCHEMA" in codes(report)


def test_garbage_input_is_rejected_cleanly(catalog):
    for payload in (None, "not json", [], {"id": 5}, 42):
        report = validate_draft(payload, catalog)
        assert not report.ok
        assert report.violations


def test_validator_does_not_mutate_catalog(catalog, draft):
    before = [a.model_dump_json() for a in catalog]
    bad = copy.deepcopy(draft)
    bad["year_fictional"] = 1
    validate_draft(bad, catalog)
    assert before == [a.model_dump_json() for a in catalog]


def test_report_serialises_for_state(catalog, draft):
    bad = copy.deepcopy(draft)
    bad["id"] = catalog[0].id
    payload = validate_draft(bad, catalog).to_dict()
    json.dumps(payload)  # must be checkpoint-safe
    assert payload["ok"] is False
    assert payload["violations"][0]["code"]
