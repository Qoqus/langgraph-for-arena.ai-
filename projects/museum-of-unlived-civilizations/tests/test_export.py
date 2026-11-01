"""Ekspor statis: satu katalog, dua cara menyajikannya (server dan berkas)."""

from __future__ import annotations

import json

import pytest

from museum.export import ExportError, export_site
from museum.llm.mock import MockCurator
from museum.runner import Museum

REQUIRED = (
    "index.html",
    "assets/style.css",
    "assets/app.js",
    "assets/icon.svg",
    "data/catalog.json",
    "manifest.webmanifest",
    "404.html",
    "robots.txt",
    "_headers",
    "netlify.toml",
    "BACA-INI.md",
)


@pytest.fixture()
def museum(tmp_path):
    instance = Museum(tmp_path / "state", llm=MockCurator(chaos="off"))
    instance.run(iterations=3)
    try:
        yield instance
    finally:
        instance.close()


def relative_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_export_writes_a_self_contained_site(museum, tmp_path):
    out = tmp_path / "dist"
    report = export_site(museum.paths.root, out)

    for name in REQUIRED:
        assert (out / name).is_file(), name
    assert (out / ".museum-export").is_file()

    catalog = museum.catalog()
    assert report.artifacts == len(catalog)
    assert len(list((out / "renders").glob("*.svg"))) == len(catalog)
    assert len(list((out / "data" / "artefak").glob("*.json"))) == len(catalog)
    assert report.files == len(relative_files(out))
    assert report.bytes > 0


def test_index_is_rewritten_for_static_hosting(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)
    html = (out / "index.html").read_text(encoding="utf-8")

    assert "/static/" not in html
    assert "/api/" not in html
    assert "<!-- MUSEUM_" not in html
    assert "./assets/style.css" in html
    assert "./assets/app.js" in html
    assert 'href="./manifest.webmanifest"' in html
    assert 'mode: "static"' in html
    assert 'catalogUrl: "./data/catalog.json"' in html
    assert "pollMs: 0" in html
    assert "viewport-fit=cover" in html


def test_snapshot_matches_the_checkpoint(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)
    payload = json.loads((out / "data" / "catalog.json").read_text(encoding="utf-8"))

    catalog = museum.catalog()
    assert [a["id"] for a in payload["artifacts"]] == [a.id for a in catalog]
    expected_edges = sum(len(a.refs) for a in catalog)
    assert len(payload["graph"]["edges"]) == expected_edges
    assert payload["counts"]["artifacts"] == len(catalog)

    graph = json.loads((out / "data" / "graph.json").read_text(encoding="utf-8"))
    assert graph == payload["graph"]


def test_every_artifact_has_detail_json_and_svg(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)

    for artifact in museum.catalog():
        svg = (out / "renders" / f"{artifact.id}.svg").read_text(encoding="utf-8")
        assert svg.startswith("<svg")
        assert artifact.title in svg

        detail = json.loads(
            (out / "data" / "artefak" / f"{artifact.id}.json").read_text(encoding="utf-8")
        )
        assert detail["artifact"]["id"] == artifact.id
        assert len(detail["refs"]) == len(artifact.refs)
        for ref in detail["refs"]:
            assert ref["target"] is not None, ref["id"]
            assert ref["target"]["title"]
        assert detail["svg_url"] == f"./renders/{artifact.id}.svg"


def test_cited_by_is_derived_like_the_api(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)
    oldest = museum.catalog()[0]
    detail = json.loads(
        (out / "data" / "artefak" / f"{oldest.id}.json").read_text(encoding="utf-8")
    )
    expected = sum(1 for a in museum.catalog() for r in a.refs if r.id == oldest.id)
    assert len(detail["cited_by"]) == expected


def test_static_mode_disables_polling(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)
    app = (out / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'mode: "api"' in app  # default untuk `museum serve`
    assert "if (!STATIC && CONFIG.pollMs > 0)" in app
    assert "window.MUSEUM_CONFIG || {}" in app


def test_manifest_and_hosting_metadata(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)

    manifest = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["lang"] == "id"
    assert manifest["start_url"] == "./"
    assert manifest["display"] == "standalone"
    assert manifest["icons"][0]["src"] == "./assets/icon.svg"

    headers = (out / "_headers").read_text(encoding="utf-8")
    assert "X-Content-Type-Options: nosniff" in headers
    assert "/renders/*" in headers

    netlify = (out / "netlify.toml").read_text(encoding="utf-8")
    assert 'publish = "."' in netlify
    assert "/data/*" in netlify

    not_found = (out / "404.html").read_text(encoding="utf-8")
    assert "Kembali ke katalog" in not_found


def test_export_is_repeatable(museum, tmp_path):
    out = tmp_path / "dist"
    export_site(museum.paths.root, out)
    first_files = relative_files(out)
    first_svg = (out / "renders" / "x").parent
    svg_before = {p.name: p.read_bytes() for p in first_svg.glob("*.svg")}

    export_site(museum.paths.root, out)
    assert relative_files(out) == first_files
    assert {p.name: p.read_bytes() for p in first_svg.glob("*.svg")} == svg_before


def test_export_refuses_to_wipe_a_foreign_directory(museum, tmp_path):
    out = tmp_path / "dist"
    out.mkdir()
    (out / "catatan.txt").write_text("jangan dihapus", encoding="utf-8")

    with pytest.raises(ExportError):
        export_site(museum.paths.root, out)
    assert (out / "catatan.txt").exists()

    export_site(museum.paths.root, out, force=True)
    assert not (out / "catatan.txt").exists()
    assert (out / "index.html").is_file()


def test_export_refuses_a_dangerous_target(museum):
    with pytest.raises(ExportError):
        export_site(museum.paths.root, museum.paths.root)
    with pytest.raises(ExportError):
        export_site(museum.paths.root, "/")


def test_empty_museum_needs_an_explicit_opt_in(tmp_path):
    empty = Museum(tmp_path / "empty", llm=MockCurator(chaos="off"))
    try:
        with pytest.raises(ExportError):
            export_site(empty.paths.root, tmp_path / "dist")

        report = export_site(empty.paths.root, tmp_path / "dist", allow_empty=True)
        payload = json.loads((tmp_path / "dist" / "data" / "catalog.json").read_text())
        assert report.artifacts == 0
        assert payload["artifacts"] == []
        assert payload["status"] == "belum-dimulai"
        assert (tmp_path / "dist" / "index.html").is_file()
    finally:
        empty.close()


def test_rebuild_keeps_the_checkpoint_facts(museum):
    before = json.loads(museum.paths.catalog_json.read_text(encoding="utf-8"))
    museum.rebuild()
    after = json.loads(museum.paths.catalog_json.read_text(encoding="utf-8"))

    assert before["status"] == after["status"] == "complete"
    assert after["llm"] == before["llm"]
    assert after["counts"]["rejections"] == before["counts"]["rejections"]
    assert [a["id"] for a in after["artifacts"]] == [a["id"] for a in before["artifacts"]]


def test_cli_export_accepts_an_empty_museum(tmp_path):
    from museum.cli import main

    out = tmp_path / "kosong"
    assert (
        main(["export", "--root", str(tmp_path / "state"), "--out", str(out), "--llm", "mock"]) == 1
    )
    code = main(
        [
            "export",
            "--root",
            str(tmp_path / "state"),
            "--out",
            str(out),
            "--llm",
            "mock",
            "--allow-empty",
        ]
    )
    assert code == 0
    assert (out / "index.html").is_file()


def test_cli_export_command(museum, tmp_path):
    from museum.cli import main

    out = tmp_path / "site"
    code = main(["export", "--root", str(museum.paths.root), "--out", str(out), "--llm", "mock"])
    assert code == 0
    assert (out / "index.html").is_file()
    assert (out / "renders").is_dir()

    payload = json.loads((out / "data" / "catalog.json").read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["llm"]
