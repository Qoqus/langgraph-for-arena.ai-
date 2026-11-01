"""The curator graph.

Shape of one loop (``STATE`` = accumulated catalog + working memory):

    START
      │
      ▼
    open_iteration ──► curate ──► validate ──(valid)──► human_review? ──► commit ──► render
       ▲                  ▲            │                    │                          │
       │                  │            │                    └─(reject)─┐                │
       │                  │            │                               ▼                │
       │                  │            └──(invalid, budget left)──► repair              │
       │                  │                                            │                │
       │                  │◄───────────────────────────────────────────┘                │
       │                  │                                                             │
       │                  └────────────(invalid, budget spent)──► reject ───────────────┤
       │                                                                                │
       │                                                    advance ◄───────────────────┘
       │                                                       │
       └───────────(iteration < target)───────────────────────┤
                                                               └──(done)──► finalize ──► END

Why these nodes and not one big node:

* ``curate`` is the only place a model is called. It has no side effects, so it is
  safe to retry (transport errors) and safe to replay.
* ``validate`` is pure and deterministic. Keeping it separate is what makes the
  repair edge expressible: the graph, not a ``while`` loop inside a node, owns
  the retry budget.
* ``commit`` is the single write to the catalog. The catalog channel uses an
  ``operator.add`` reducer, so the only possible update is an append. Each entry
  is a frozen canonical dict: the past cannot be edited, only cited.
* ``render`` is a pure function of committed JSON, kept outside the commit so a
  renderer failure can never lose an accession (and can be replayed).
* ``advance`` projects state to disk and decides whether the cycle continues.
  The cycle is an explicit edge back to ``open_iteration``.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from .context import build_context, choose_directive
from .llm import CuratorLLM
from .parsing import extract_json
from .render import render_svg, render_to_file
from .schema import Artifact, ArtifactDraft, draft_to_artifact
from .store import MuseumPaths, append_ledger, project, utc_now
from .validator import validate_draft

DEFAULT_THREAD = "museum-main"


class MuseumState(TypedDict, total=False):
    # -- execution state (per run) ------------------------------------------
    iteration: int
    target_iterations: int
    attempt: int
    max_attempts: int
    status: str
    # -- working memory (per iteration, overwritten) ------------------------
    brief: dict[str, Any]
    pending_draft: dict[str, Any] | None
    validation: dict[str, Any] | None
    repair_feedback: list[str] | None
    review_decision: dict[str, Any] | None
    review_approved: bool
    last_committed: dict[str, Any] | None
    stats: dict[str, Any]
    # -- domain state (append-only, reducer) --------------------------------
    catalog: Annotated[list[dict[str, Any]], operator.add]
    rejections: Annotated[list[dict[str, Any]], operator.add]
    renders: Annotated[list[dict[str, Any]], operator.add]
    timeline: Annotated[list[dict[str, Any]], operator.add]
    log: Annotated[list[str], operator.add]


@dataclass
class MuseumDeps:
    llm: CuratorLLM
    paths: MuseumPaths
    thread_id: str = DEFAULT_THREAD
    max_attempts: int = 3
    human_review: bool = False
    render: bool = True
    clock: Callable[[], str] = field(default=utc_now)


def _catalog(state: MuseumState) -> list[Artifact]:
    return [Artifact.model_validate(item) for item in state.get("catalog") or []]


def _last_committed_artifact(state: MuseumState) -> Artifact | None:
    record = state.get("last_committed") or {}
    for item in reversed(state.get("catalog") or []):
        if not record or item["id"] == record.get("id"):
            return Artifact.model_validate(item)
    return None


def _event(name: str, *, iteration: int, at: str, **detail: Any) -> dict[str, Any]:
    return {"event": name, "iteration": iteration, "at": at, **detail}


def build_graph(deps: MuseumDeps, checkpointer: BaseCheckpointSaver | None = None):
    """Compile the cyclical curator graph."""
    clock = deps.clock
    paths = deps.paths

    # -- nodes --------------------------------------------------------------
    def open_iteration(state: MuseumState) -> dict[str, Any]:
        """Read the whole catalog and decide the shape of the next accession.

        Only the *brief* (a few hundred bytes) is kept in the state; the verbose
        prompt context is rebuilt on demand, so checkpoints do not pay for it.
        """
        iteration = int(state.get("iteration", 0)) + 1
        catalog = _catalog(state)
        directive = choose_directive(catalog, iteration)
        return {
            "iteration": iteration,
            "attempt": 0,
            "max_attempts": deps.max_attempts,
            "brief": directive,
            "pending_draft": None,
            "validation": None,
            "repair_feedback": None,
            "review_decision": None,
            "review_approved": False,
            "status": "curating",
            "timeline": [
                _event(
                    "brief",
                    iteration=iteration,
                    at=clock(),
                    directive=directive["kind"],
                    lineage=directive["focus_lineage"],
                    notes=directive["notes"],
                    year_floor=directive["year_floor"],
                )
            ],
            "log": [
                f"iterasi {iteration}: direktif {directive['kind']} — {directive['text']} "
                f"(garis {directive['focus_lineage']}, lantai tahun {directive['year_floor']})"
            ],
        }

    def curate(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        attempt = int(state.get("attempt", 0))
        context = build_context(
            _catalog(state), iteration=iteration, max_attempts=deps.max_attempts
        )
        context["attempt"] = attempt
        feedback = "\n".join(state.get("repair_feedback") or [])
        context["feedback"] = feedback or None
        raw = deps.llm.propose(context)
        parsed, error = extract_json(raw)
        draft_id = (parsed or {}).get("id") if isinstance(parsed, dict) else None
        return {
            "pending_draft": {
                "raw": raw if len(raw) <= 2000 else raw[:2000],
                "parsed": parsed,
                "parse_error": error,
                "llm": getattr(deps.llm, "name", "unknown"),
            },
            "status": "validating",
            "timeline": [
                _event(
                    "draft",
                    iteration=iteration,
                    at=clock(),
                    attempt=attempt + 1,
                    draft_id=draft_id,
                    parse_error=error,
                )
            ],
            "log": [
                f"iterasi {iteration} percobaan {attempt + 1}: draf {draft_id or '(tidak terbaca)'}"
                + (f" — {error}" if error else "")
            ],
        }

    def validate(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        catalog = _catalog(state)
        pending = state.get("pending_draft") or {}
        report = validate_draft(pending.get("parsed"), catalog)
        payload = report.to_dict()
        feedback = [] if report.ok else [report.feedback()]
        return {
            "validation": payload,
            "repair_feedback": feedback,
            "status": "accepted" if report.ok else "rejected",
            "timeline": [
                _event(
                    "validate",
                    iteration=iteration,
                    at=clock(),
                    ok=report.ok,
                    codes=report.codes(),
                )
            ],
            "log": [
                f"iterasi {iteration}: validasi {'lolos' if report.ok else 'gagal'}"
                + ("" if report.ok else f" ({', '.join(report.codes())})")
            ],
        }

    def repair(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        attempt = int(state.get("attempt", 0)) + 1
        codes = (state.get("validation") or {}).get("violations", [])
        return {
            "attempt": attempt,
            "status": "repairing",
            "timeline": [
                _event(
                    "repair",
                    iteration=iteration,
                    at=clock(),
                    attempt=attempt,
                    codes=[v.get("code") for v in codes],
                )
            ],
            "log": [f"iterasi {iteration}: perbaikan ke-{attempt} atas draf yang ditolak"],
        }

    def human_review(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        pending = state.get("pending_draft") or {}
        payload = {
            "question": "Setujui draf ini masuk katalog?",
            "options": ["approve", "reject", "edit"],
            "iteration": iteration,
            "directive": state.get("brief") or {},
            "draft": pending.get("parsed"),
            "validation": state.get("validation"),
        }
        decision = interrupt(payload)
        if isinstance(decision, str):
            decision = {"decision": decision}
        decision = decision or {}
        kind = str(decision.get("decision", "approve")).lower()
        if kind not in ("approve", "reject", "edit"):
            kind = "reject"
        draft = decision.get("artifact") if kind == "edit" else pending.get("parsed")
        if kind == "edit" and not isinstance(draft, dict):
            kind = "reject"
        return {
            "review_decision": {"decision": kind, "at": clock(), "note": decision.get("note")},
            "pending_draft": {**pending, "parsed": draft, "edited": kind == "edit"},
            "review_approved": kind in ("approve", "edit"),
            "status": f"review-{kind}",
            "timeline": [_event("human_review", iteration=iteration, at=clock(), decision=kind)],
            "log": [f"iterasi {iteration}: kurator manusia memilih '{kind}'"],
        }

    def commit(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        attempt = int(state.get("attempt", 0))
        pending = state.get("pending_draft") or {}
        catalog = _catalog(state)
        # Defence in depth: never write on the strength of an earlier verdict.
        report = validate_draft(pending.get("parsed"), catalog)
        if not report.ok:
            return {
                "validation": report.to_dict(),
                "repair_feedback": [report.feedback()],
                "status": "rejected",
                "timeline": [
                    _event(
                        "commit-blocked",
                        iteration=iteration,
                        at=clock(),
                        codes=report.codes(),
                    )
                ],
                "log": [f"iterasi {iteration}: commit dibatalkan oleh validator"],
            }
        draft = ArtifactDraft.model_validate(pending["parsed"])
        artifact = draft_to_artifact(
            draft,
            iteration=iteration,
            created_at=clock(),
            llm=pending.get("llm") or getattr(deps.llm, "name", "unknown"),
            attempt=attempt,
        )
        appended = append_ledger(paths, [artifact])
        return {
            "catalog": [artifact.canonical()],
            "last_committed": {
                "id": artifact.id,
                "title": artifact.title,
                "year": artifact.year_fictional,
                "iteration": iteration,
                "digest": artifact.digest(),
                "ledger_appended": bool(appended),
            },
            "status": "committed",
            "timeline": [
                _event(
                    "commit",
                    iteration=iteration,
                    at=clock(),
                    id=artifact.id,
                    year=artifact.year_fictional,
                    lineage=artifact.lineage,
                )
            ],
            "log": [
                f"iterasi {iteration}: '{artifact.id}' masuk katalog ({artifact.year_fictional})"
            ],
        }

    def render(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        artifact = _last_committed_artifact(state)
        if artifact is None:
            return {
                "status": "render-skipped",
                "log": [f"iterasi {iteration}: tidak ada karya untuk dirender"],
            }
        svg = render_svg(artifact)
        entry = {"id": artifact.id, "bytes": len(svg.encode("utf-8"))}
        if deps.render:
            path = render_to_file(artifact, paths.renders)
            entry["path"] = str(path)
        return {
            "renders": [entry],
            "status": "rendered",
            "timeline": [_event("render", iteration=iteration, at=clock(), id=artifact.id)],
            "log": [
                f"iterasi {iteration}: plakat deterministik {entry['bytes']} byte untuk {artifact.id}"
            ],
        }

    def reject(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        pending = state.get("pending_draft") or {}
        validation = state.get("validation") or {}
        draft = pending.get("parsed")
        record = {
            "iteration": iteration,
            "at": clock(),
            "attempt": int(state.get("attempt", 0)) + 1,
            "draft_id": (draft or {}).get("id") if isinstance(draft, dict) else None,
            "parse_error": pending.get("parse_error"),
            "codes": [v.get("code") for v in validation.get("violations", [])],
            "violations": validation.get("violations", []),
            "draft": draft,
        }
        return {
            "rejections": [record],
            "last_committed": None,
            "status": "abstained",
            "timeline": [
                _event(
                    "reject",
                    iteration=iteration,
                    at=clock(),
                    codes=record["codes"],
                )
            ],
            "log": [
                f"iterasi {iteration}: tidak ada aksesi — {', '.join(record['codes']) or 'ditolak'}"
            ],
        }

    def advance(state: MuseumState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        catalog = _catalog(state)
        rejections = state.get("rejections") or []
        project(
            paths,
            catalog,
            iteration=iteration,
            status="curating",
            llm=getattr(deps.llm, "name", None),
            thread_id=deps.thread_id,
            extra={"rejections": len(rejections)},
        )
        stats = {
            "artifacts": len(catalog),
            "rejections": len(rejections),
            "lineages": len({a.lineage for a in catalog}),
            "materials": len({m for a in catalog for m in a.materials}),
            "motifs": len({m for a in catalog for m in a.motifs}),
            "revision": len(state.get("timeline") or []),
        }
        return {
            "stats": stats,
            "status": "iteration-complete",
            "timeline": [
                _event(
                    "advance",
                    iteration=iteration,
                    at=clock(),
                    artifacts=stats["artifacts"],
                    rejections=stats["rejections"],
                )
            ],
        }

    def finalize(state: MuseumState) -> dict[str, Any]:
        iteration = int(state.get("iteration", 0))
        catalog = _catalog(state)
        payload = project(
            paths,
            catalog,
            iteration=iteration,
            status="complete",
            llm=getattr(deps.llm, "name", None),
            thread_id=deps.thread_id,
            extra={"rejections": len(state.get("rejections") or [])},
        )
        return {
            "status": "complete",
            "timeline": [
                _event(
                    "finalize",
                    iteration=iteration,
                    at=clock(),
                    artifacts=len(catalog),
                    generated_at=payload["generated_at"],
                )
            ],
            "log": [
                f"selesai: {len(catalog)} artefak, {len(state.get('rejections') or [])} penolakan, "
                f"{iteration} iterasi"
            ],
        }

    # -- routing ------------------------------------------------------------
    def after_validation(state: MuseumState) -> str:
        ok = bool((state.get("validation") or {}).get("ok"))
        if state.get("review_approved"):
            return "commit" if ok else "reject"
        if ok:
            return "human_review" if deps.human_review else "commit"
        if int(state.get("attempt", 0)) + 1 < int(state.get("max_attempts", deps.max_attempts)):
            return "repair"
        return "reject"

    def after_review(state: MuseumState) -> str:
        decision = (state.get("review_decision") or {}).get("decision", "reject")
        if decision == "approve":
            return "commit"
        if decision == "edit":
            return "validate"
        return "reject"

    def after_advance(state: MuseumState) -> str:
        if int(state.get("iteration", 0)) < int(state.get("target_iterations", 0)):
            return "continue"
        return "finish"

    # -- wiring -------------------------------------------------------------
    builder = StateGraph(MuseumState)
    builder.add_node("open_iteration", open_iteration)
    builder.add_node("curate", curate, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("validate", validate)
    builder.add_node("repair", repair)
    builder.add_node("human_review", human_review)
    builder.add_node("commit", commit)
    builder.add_node("render", render)
    builder.add_node("reject", reject)
    builder.add_node("advance", advance)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "open_iteration")
    builder.add_edge("open_iteration", "curate")
    builder.add_edge("curate", "validate")
    builder.add_conditional_edges(
        "validate",
        after_validation,
        {
            "human_review": "human_review",
            "commit": "commit",
            "repair": "repair",
            "reject": "reject",
        },
    )
    builder.add_edge("repair", "curate")  # the repair cycle, inside the graph
    builder.add_conditional_edges(
        "human_review",
        after_review,
        {"commit": "commit", "validate": "validate", "reject": "reject"},
    )
    builder.add_edge("commit", "render")
    builder.add_edge("render", "advance")
    builder.add_edge("reject", "advance")
    builder.add_conditional_edges(
        "advance",
        after_advance,
        {"continue": "open_iteration", "finish": "finalize"},  # the curation cycle
    )
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def thread_config(thread_id: str = DEFAULT_THREAD, *, recursion_limit: int = 200) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}


def state_catalog(state_values: dict[str, Any] | None) -> list[Artifact]:
    if not state_values:
        return []
    return [Artifact.model_validate(item) for item in state_values.get("catalog") or []]
