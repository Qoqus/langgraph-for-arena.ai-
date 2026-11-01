from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from museum.render import render_svg, render_to_file, svg_filename
from museum.schema import Artifact
from museum.seed import SEED_ARTIFACTS
from museum.vocabulary import FORMS, PALETTES, SYMMETRIES


def _artifact(
    form: str = "guci",
    palette: str = "garam",
    *,
    artifact_id: str | None = None,
    symmetry: str = "mirror-x",
    density: float = 0.6,
    strata: int = 5,
) -> Artifact:
    base = SEED_ARTIFACTS[1].canonical()
    base["id"] = artifact_id or f"uji-{form}-{palette}"
    base["iteration"] = 1
    base["form"] = form
    base["visual"] = {
        "form": form,
        "palette": palette,
        "motif": base["motifs"][0],
        "symmetry": symmetry,
        "density": density,
        "strata": strata,
    }
    return Artifact.model_validate(base)


def test_render_is_deterministic():
    artifact = _artifact()
    first = render_svg(artifact)
    second = render_svg(artifact)
    assert first == second
    assert len(first) > 1000


def test_render_is_well_formed_xml():
    for artifact in SEED_ARTIFACTS:
        svg = render_svg(artifact)
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        assert root.attrib["viewBox"] == "0 0 520 680"
        assert artifact.title in root.attrib["aria-label"]


def test_every_form_and_palette_renders():
    for form in FORMS:
        for palette in PALETTES:
            artifact = _artifact(form=form, palette=palette, artifact_id=f"uji-{form}-{palette}")
            root = ET.fromstring(render_svg(artifact))
            assert root is not None


def test_every_symmetry_renders():
    for symmetry in SYMMETRIES:
        artifact = _artifact(symmetry=symmetry, artifact_id=f"uji-{symmetry}")
        ET.fromstring(render_svg(artifact))


def test_render_depends_on_visual_parameters():
    a = _artifact(density=0.3, artifact_id="rapat")
    b = _artifact(density=0.9, artifact_id="renggang")
    assert render_svg(a) != render_svg(b)

    left = _artifact(artifact_id="kiri-simetri", symmetry="translation")
    right = _artifact(artifact_id="kanan-simetri", symmetry="radial")
    assert render_svg(left) != render_svg(right)


def test_render_has_no_external_or_scripted_content():
    svg = render_svg(_artifact())
    assert "<script" not in svg
    assert "<image" not in svg
    assert "http://www.w3.org/2000/svg" in svg  # the only namespace, not a fetch
    assert svg.count("http://") == 1
    assert "data:" not in svg


def test_render_to_file_is_byte_identical(tmp_path):
    artifact = _artifact()
    path = render_to_file(artifact, tmp_path)
    assert path.name == svg_filename(artifact)
    first = path.read_bytes()
    render_to_file(artifact, tmp_path)
    assert path.read_bytes() == first
    assert first.decode("utf-8") == render_svg(artifact)


def test_visual_is_not_mutated_by_render():
    artifact = _artifact()
    before = artifact.model_dump_json()
    render_svg(artifact)
    assert artifact.model_dump_json() == before


def test_different_artifacts_differ_visually():
    svgs = {render_svg(artifact) for artifact in SEED_ARTIFACTS}
    assert len(svgs) == len(SEED_ARTIFACTS)


def test_artifact_is_frozen():
    from pydantic import ValidationError

    artifact = _artifact()
    with pytest.raises(ValidationError):
        artifact.title = "judul baru"  # type: ignore[misc]
