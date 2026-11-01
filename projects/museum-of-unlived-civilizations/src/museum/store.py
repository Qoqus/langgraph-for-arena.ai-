"""Projections and append-only exports.

The checkpoint is the source of truth; the files here are *projections* that the
web catalog and external tools can read without touching SQLite. If they are ever
lost, ``museum rebuild`` regenerates them from the checkpoint.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import Artifact


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MuseumPaths:
    root: Path

    @classmethod
    def create(cls, root: str | Path | None = None) -> MuseumPaths:
        base = Path(root or os.environ.get("MUSEUM_HOME") or Path.cwd() / "museum-state")
        return cls(base)

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def renders(self) -> Path:
        return self.root / "renders"

    @property
    def db(self) -> Path:
        return self.root / "checkpoints.sqlite"

    @property
    def catalog_json(self) -> Path:
        return self.data / "catalog.json"

    @property
    def ledger_jsonl(self) -> Path:
        return self.data / "ledger.jsonl"

    @property
    def meta_json(self) -> Path:
        return self.data / "meta.json"

    @property
    def reviews_json(self) -> Path:
        return self.data / "reviews.json"

    def ensure(self) -> MuseumPaths:
        self.data.mkdir(parents=True, exist_ok=True)
        self.renders.mkdir(parents=True, exist_ok=True)
        return self


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def provenance_graph(catalog: Sequence[Artifact]) -> dict[str, list[dict[str, Any]]]:
    nodes = [
        {
            "id": a.id,
            "title": a.title,
            "year": a.year_fictional,
            "lineage": a.lineage,
            "iteration": a.iteration,
        }
        for a in sorted(catalog, key=lambda a: (a.year_fictional, a.iteration, a.id))
    ]
    edges = [
        {
            "source": ref.id,
            "target": a.id,
            "relation": ref.relation,
            "note": ref.note,
        }
        for a in catalog
        for ref in a.refs
    ]
    return {"nodes": nodes, "edges": edges}


def catalog_payload(
    catalog: Sequence[Artifact],
    *,
    iteration: int,
    status: str,
    llm: str | None = None,
    thread_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(catalog, key=lambda a: (a.year_fictional, a.iteration, a.id))
    lineage_counts: dict[str, int] = {}
    material_counts: dict[str, int] = {}
    motif_counts: dict[str, int] = {}
    for art in ordered:
        lineage_counts[art.lineage] = lineage_counts.get(art.lineage, 0) + 1
        for m in art.materials:
            material_counts[m] = material_counts.get(m, 0) + 1
        for m in art.motifs:
            motif_counts[m] = motif_counts.get(m, 0) + 1
    cited = {ref.id for art in ordered for ref in art.refs}
    payload: dict[str, Any] = {
        "museum": "Museum Peradaban yang Tidak Pernah Ada",
        "iteration": iteration,
        "status": status,
        "thread_id": thread_id,
        "llm": llm,
        "generated_at": utc_now(),
        "counts": {
            "artifacts": len(ordered),
            "lineages": len(lineage_counts),
            "materials": len(material_counts),
            "motifs": len(motif_counts),
            "rejections": (extra or {}).get("rejections", 0),
        },
        "span": {
            "first_year": ordered[0].year_fictional if ordered else None,
            "last_year": ordered[-1].year_fictional if ordered else None,
        },
        "lineage_counts": dict(sorted(lineage_counts.items())),
        "material_counts": dict(sorted(material_counts.items())),
        "motif_counts": dict(sorted(motif_counts.items())),
        "most_cited": sorted(
            [
                {"id": rid, "count": sum(1 for a in ordered if any(r.id == rid for r in a.refs))}
                for rid in cited
            ],
            key=lambda item: (-item["count"], item["id"]),
        )[:5],
        "artifacts": [art.canonical() for art in ordered],
        "graph": provenance_graph(ordered),
    }
    if extra:
        payload.update(extra)
    return payload


def project(
    paths: MuseumPaths,
    catalog: Sequence[Artifact],
    *,
    iteration: int,
    status: str,
    llm: str | None = None,
    thread_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths.ensure()
    payload = catalog_payload(
        catalog,
        iteration=iteration,
        status=status,
        llm=llm,
        thread_id=thread_id,
        extra=extra,
    )
    write_json_atomic(paths.catalog_json, payload)
    write_json_atomic(
        paths.meta_json,
        {
            "iteration": iteration,
            "status": status,
            "llm": llm,
            "thread_id": thread_id,
            "artifacts": len(catalog),
            "updated_at": payload["generated_at"],
        },
    )
    return payload


def known_ledger_ids(paths: MuseumPaths) -> set[str]:
    ids: set[str] = set()
    try:
        with paths.ledger_jsonl.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    except FileNotFoundError:
        return ids
    return ids


def append_ledger(paths: MuseumPaths, artifacts: Iterable[Artifact]) -> list[str]:
    """Append-only commit log. Idempotent: replaying the same commits is safe."""
    paths.ensure()
    existing = known_ledger_ids(paths)
    added: list[str] = []
    with paths.ledger_jsonl.open("a", encoding="utf-8") as handle:
        for art in artifacts:
            if art.id in existing:
                continue
            record = {
                "entry": "commit",
                "id": art.id,
                "iteration": art.iteration,
                "year": art.year_fictional,
                "committed_at": art.created_at,
                "digest": art.digest(),
                "artifact": art.canonical(),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing.add(art.id)
            added.append(art.id)
        handle.flush()
        os.fsync(handle.fileno())
    return added


def read_ledger(paths: MuseumPaths) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with paths.ledger_jsonl.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def load_catalog_payload(paths: MuseumPaths) -> dict[str, Any] | None:
    return read_json(paths.catalog_json)


def rebuild_from_artifacts(
    paths: MuseumPaths, artifacts: Sequence[Artifact], iteration: int
) -> dict[str, Any]:
    """Rewrite the ledger from scratch (used by ``museum rebuild``)."""
    if paths.ledger_jsonl.exists():
        paths.ledger_jsonl.unlink()
    append_ledger(paths, sorted(artifacts, key=lambda a: (a.iteration, a.year_fictional)))
    return project(paths, artifacts, iteration=iteration, status="rebuilt")
