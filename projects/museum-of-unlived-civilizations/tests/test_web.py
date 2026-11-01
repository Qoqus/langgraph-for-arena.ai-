"""The catalog server reads projections and never writes the checkpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from museum.llm.mock import MockCurator
from museum.runner import Museum
from museum.web.app import create_app


def build_catalog(tmp_path, iterations: int = 3):
    museum = Museum(tmp_path / "state", llm=MockCurator(chaos="off"))
    museum.run(iterations=iterations)
    return museum


def test_catalog_endpoint_lists_artifacts_in_chronological_order(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        payload = client.get("/api/catalog").json()
        assert payload["counts"]["artifacts"] == len(museum.catalog())
        years = [a["year_fictional"] for a in payload["artifacts"]]
        assert years == sorted(years)
        assert payload["graph"]["edges"]
        assert payload["span"]["last_year"] == max(years)
    finally:
        museum.close()


def test_artifact_detail_resolves_cross_references(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        target = next(a for a in museum.catalog() if a.refs)
        detail = client.get(f"/api/artifacts/{target.id}").json()
        assert detail["artifact"]["id"] == target.id
        assert len(detail["refs"]) == len(target.refs)
        for ref in detail["refs"]:
            assert ref["target"] is not None
            assert ref["note"]
        assert detail["svg_url"].endswith("/svg")
    finally:
        museum.close()


def test_cited_by_is_derived_from_the_catalog(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        oldest = museum.catalog()[0]
        detail = client.get(f"/api/artifacts/{oldest.id}").json()
        expected = sum(1 for a in museum.catalog() for r in a.refs if r.id == oldest.id)
        assert len(detail["cited_by"]) == expected
    finally:
        museum.close()


def test_svg_endpoint_returns_an_image(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        artifact = museum.catalog()[1]
        response = client.get(f"/api/artifacts/{artifact.id}/svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.text.startswith("<svg")
        assert artifact.title in response.text
    finally:
        museum.close()


def test_unknown_artifact_is_404(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        assert client.get("/api/artifacts/tidak-ada").status_code == 404
        assert client.get("/api/artifacts/tidak-ada/svg").status_code == 404
    finally:
        museum.close()


def test_status_and_graph_endpoints(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        status = client.get("/api/status").json()
        assert status["counts"]["artifacts"] == len(museum.catalog())
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) == len(museum.catalog())
        assert all(edge["relation"] for edge in graph["edges"])
    finally:
        museum.close()


def test_ui_and_static_assets_are_served(tmp_path):
    museum = build_catalog(tmp_path)
    try:
        client = TestClient(create_app(museum.paths.root))
        index = client.get("/")
        assert index.status_code == 200
        assert "Peradaban yang Tidak Pernah Ada" in index.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/healthz").json()["ok"] == "true"
    finally:
        museum.close()


def test_empty_museum_still_serves_the_catalog(tmp_path):
    client = TestClient(create_app(tmp_path / "empty"))
    payload = client.get("/api/catalog").json()
    assert payload["artifacts"] == []
    assert payload["status"] == "belum-dimulai"
    assert client.get("/api/artifacts/x").status_code == 404
