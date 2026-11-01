"""Read-only catalog server.

It reads the projection produced by the graph (``catalog.json``, ``renders/``) and
never opens the SQLite checkpoint while the curator might be writing to it. One
writer (the graph), many readers (the catalog).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..render import render_svg, render_to_file
from ..schema import Artifact
from ..store import MuseumPaths, load_catalog_payload, read_json

STATIC_DIR = Path(__file__).parent / "static"

EMPTY_PAYLOAD: dict[str, Any] = {
    "museum": "Museum Peradaban yang Tidak Pernah Ada",
    "iteration": 0,
    "status": "belum-dimulai",
    "llm": None,
    "generated_at": None,
    "counts": {"artifacts": 0, "lineages": 0, "materials": 0, "motifs": 0, "rejections": 0},
    "span": {"first_year": None, "last_year": None},
    "lineage_counts": {},
    "material_counts": {},
    "motif_counts": {},
    "most_cited": [],
    "artifacts": [],
    "graph": {"nodes": [], "edges": []},
}


def create_app(root: str | Path | None = None) -> FastAPI:
    paths = MuseumPaths.create(root)
    app = FastAPI(title="Museum Peradaban yang Tidak Pernah Ada", version="0.1.0")
    app.state.paths = paths

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def payload() -> dict[str, Any]:
        return load_catalog_payload(paths) or dict(EMPTY_PAYLOAD)

    def artifacts_by_id() -> dict[str, Artifact]:
        data = payload()
        return {a["id"]: Artifact.model_validate(a) for a in data.get("artifacts", [])}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        index_file = STATIC_DIR / "index.html"
        if not index_file.exists():
            raise HTTPException(500, "catalog UI missing")
        return FileResponse(index_file)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/api/catalog")
    def api_catalog() -> JSONResponse:
        data = payload()
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    def api_status() -> JSONResponse:
        data = payload()
        return JSONResponse(
            {
                "iteration": data.get("iteration", 0),
                "status": data.get("status"),
                "llm": data.get("llm"),
                "generated_at": data.get("generated_at"),
                "counts": data.get("counts", {}),
                "span": data.get("span", {}),
                "most_cited": data.get("most_cited", []),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/graph")
    def api_graph() -> JSONResponse:
        return JSONResponse(payload().get("graph", {"nodes": [], "edges": []}))

    @app.get("/api/artifacts/{artifact_id}")
    def api_artifact(artifact_id: str) -> JSONResponse:
        catalog = artifacts_by_id()
        artifact = catalog.get(artifact_id)
        if artifact is None:
            raise HTTPException(404, f"artefak '{artifact_id}' tidak ada dalam katalog")
        outgoing = [
            {
                "id": ref.id,
                "relation": ref.relation,
                "note": ref.note,
                "target": catalog[ref.id].canonical() if ref.id in catalog else None,
            }
            for ref in artifact.refs
        ]
        incoming = [
            {
                "id": other.id,
                "title": other.title,
                "year": other.year_fictional,
                "relation": ref.relation,
                "note": ref.note,
            }
            for other in catalog.values()
            for ref in other.refs
            if ref.id == artifact_id
        ]
        return JSONResponse(
            {
                "artifact": artifact.canonical(),
                "refs": outgoing,
                "cited_by": incoming,
                "svg_url": f"/api/artifacts/{artifact.id}/svg",
            }
        )

    @app.get("/api/artifacts/{artifact_id}/svg")
    def api_svg(artifact_id: str, refresh: bool = Query(default=False)) -> Response:
        catalog = artifacts_by_id()
        artifact = catalog.get(artifact_id)
        if artifact is None:
            raise HTTPException(404, f"artefak '{artifact_id}' tidak ada dalam katalog")
        target = paths.renders / f"{artifact.id}.svg"
        if refresh or not target.exists():
            try:
                render_to_file(artifact, paths.renders)
            except OSError:
                pass
        svg = target.read_text(encoding="utf-8") if target.exists() else render_svg(artifact)
        return Response(
            content=svg,
            media_type="image/svg+xml; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/api/meta")
    def api_meta() -> JSONResponse:
        return JSONResponse(read_json(paths.meta_json, {}) or {})

    return app
