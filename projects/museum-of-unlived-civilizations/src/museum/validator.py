"""Deterministic rule engine.

The validator is the museum's conscience: it is the only authority on whether a
draft may enter the catalog. It never mutates anything, so a rejected draft
leaves no trace in the store.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from .schema import ID_PATTERN, Artifact, ArtifactDraft
from .vocabulary import (
    FORMS,
    FUNCTIONS,
    LINEAGES,
    MATERIAL_BEARING_RELATIONS,
    MATERIALS,
    MOTIF_BEARING_RELATIONS,
    MOTIFS,
    PALETTES,
    RELATIONS,
    SYMMETRIES,
)

MAX_YEAR_JUMP = 120


@dataclass(frozen=True)
class Violation:
    code: str
    field: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationReport:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    draft_id: str | None = None

    def codes(self) -> list[str]:
        return [v.code for v in self.violations if v.severity == "error"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "draft_id": self.draft_id,
            "violations": [v.to_dict() for v in self.violations],
        }

    def feedback(self, limit: int = 6) -> str:
        errors = [v for v in self.violations if v.severity == "error"][:limit]
        return "\n".join(f"- [{v.code}] {v.field}: {v.message}" for v in errors)


def _report(violations: Iterable[Violation], draft_id: str | None) -> ValidationReport:
    items = list(violations)
    return ValidationReport(
        ok=not any(v.severity == "error" for v in items),
        violations=items,
        draft_id=draft_id,
    )


def parse_draft(raw: Any) -> tuple[ArtifactDraft | None, list[Violation]]:
    """Shape check. Returns the parsed draft (or ``None``) and shape violations."""
    if isinstance(raw, ArtifactDraft):
        return raw, []
    if isinstance(raw, Artifact):
        return ArtifactDraft(
            **raw.model_dump(exclude={"iteration", "created_at", "llm", "attempt", "draft_digest"})
        ), []
    if not isinstance(raw, dict):
        return None, [Violation("SCHEMA", "$", "draft is not a JSON object")]
    try:
        return ArtifactDraft.model_validate(raw), []
    except ValidationError as exc:
        violations = []
        for err in exc.errors()[:8]:
            loc = ".".join(str(p) for p in err.get("loc", ())) or "$"
            violations.append(Violation("SCHEMA", loc, str(err.get("msg", "invalid"))))
        return None, violations


def validate_draft(
    raw: Any,
    catalog: Sequence[Artifact],
    *,
    year_floor: int | None = None,
) -> ValidationReport:
    """Run every world rule against ``raw`` in the context of ``catalog``."""
    draft, shape_violations = parse_draft(raw)
    if draft is None:
        return _report(shape_violations, None)

    violations: list[Violation] = list(shape_violations)
    by_id: dict[str, Artifact] = {a.id: a for a in catalog}
    last_year = max((a.year_fictional for a in catalog), default=None)
    floor = year_floor if year_floor is not None else last_year

    # --- identity -----------------------------------------------------------
    if not re.match(ID_PATTERN, draft.id):
        violations.append(
            Violation("ID_PATTERN", "id", f"'{draft.id}' tidak mengikuti pola aksesi museum")
        )
    if draft.id in by_id:
        violations.append(
            Violation("ID_DUPLICATE", "id", f"id '{draft.id}' sudah dipakai artefak lain")
        )
    if any(a.title.strip().lower() == draft.title.strip().lower() for a in catalog):
        violations.append(
            Violation("TITLE_DUPLICATE", "title", f"judul '{draft.title}' sudah ada di katalog")
        )

    # --- chronology ---------------------------------------------------------
    if floor is not None:
        if draft.year_fictional < floor:
            violations.append(
                Violation(
                    "YEAR_REGRESSION",
                    "year_fictional",
                    f"tahun {draft.year_fictional} mundur dari tahun terakhir katalog {floor}",
                )
            )
        elif draft.year_fictional - floor > MAX_YEAR_JUMP:
            violations.append(
                Violation(
                    "YEAR_JUMP",
                    "year_fictional",
                    f"lompatan {draft.year_fictional - floor} tahun terlalu jauh (maks {MAX_YEAR_JUMP})",
                )
            )

    # --- controlled vocabulary ---------------------------------------------
    if draft.lineage not in LINEAGES:
        violations.append(
            Violation(
                "LINEAGE_UNKNOWN", "lineage", f"lineage '{draft.lineage}' tidak ada dalam kosakata"
            )
        )
    if draft.form not in FORMS:
        violations.append(
            Violation("FORM_UNKNOWN", "form", f"form '{draft.form}' tidak ada dalam kosakata")
        )
    if draft.function not in FUNCTIONS:
        violations.append(
            Violation(
                "FUNCTION_UNKNOWN",
                "function",
                f"fungsi '{draft.function}' tidak ada dalam kosakata",
            )
        )
    for material in draft.materials:
        if material not in MATERIALS:
            violations.append(
                Violation(
                    "MATERIAL_UNKNOWN", "materials", f"bahan '{material}' tidak ada dalam kosakata"
                )
            )
    for motif in draft.motifs:
        if motif not in MOTIFS:
            violations.append(
                Violation("MOTIF_UNKNOWN", "motifs", f"motif '{motif}' tidak ada dalam kosakata")
            )
    if draft.visual.palette not in PALETTES:
        violations.append(
            Violation(
                "PALETTE_UNKNOWN", "visual.palette", f"palet '{draft.visual.palette}' tidak ada"
            )
        )
    if draft.visual.symmetry not in SYMMETRIES:
        violations.append(
            Violation(
                "SYMMETRY_UNKNOWN",
                "visual.symmetry",
                f"simetri '{draft.visual.symmetry}' tidak ada",
            )
        )
    for attr in ("materials", "motifs"):
        values = getattr(draft, attr)
        if len(set(values)) != len(values):
            violations.append(Violation("DUPLICATE_ENTRY", attr, f"{attr} mengandung duplikat"))

    # --- material identity of the lineage ----------------------------------
    if draft.lineage in LINEAGES and catalog:
        own = set(MATERIALS) & set(LINEAGES[draft.lineage].signature_materials)
        own |= {m for m, spec in MATERIALS.items() if spec.origin == draft.lineage}
        if own and not own & set(draft.materials):
            violations.append(
                Violation(
                    "LINEAGE_MATERIAL_MISMATCH",
                    "materials",
                    f"tidak ada bahan khas {LINEAGES[draft.lineage].name} dalam artefak",
                )
            )

    # --- references: the only way to touch the past ------------------------
    ref_ids = [r.id for r in draft.refs]
    if catalog and not ref_ids:
        violations.append(
            Violation("REFS_EMPTY", "refs", "artefak baru wajib merujuk minimal satu artefak lama")
        )
    if len(set(ref_ids)) != len(ref_ids):
        violations.append(Violation("REF_DUPLICATE", "refs", "ada id rujukan yang berulang"))
    notes = [r.note.strip().lower() for r in draft.refs]
    if len(notes) > 1 and len(set(notes)) != len(notes):
        violations.append(
            Violation("REF_NOTE_GENERIC", "refs", "catatan rujukan tidak boleh disalin")
        )
    for ref in draft.refs:
        target = by_id.get(ref.id)
        if ref.id == draft.id:
            violations.append(
                Violation("REF_SELF", "refs", "artefak tidak boleh merujuk dirinya sendiri")
            )
            continue
        if target is None:
            violations.append(
                Violation("REF_MISSING", "refs", f"rujukan '{ref.id}' tidak ada di katalog")
            )
            continue
        if ref.relation not in RELATIONS:
            violations.append(
                Violation(
                    "RELATION_UNKNOWN", "refs", f"relasi '{ref.relation}' tidak ada dalam kosakata"
                )
            )
        if target.year_fictional > draft.year_fictional:
            violations.append(
                Violation(
                    "REF_FUTURE",
                    "refs",
                    f"merujuk '{ref.id}' ({target.year_fictional}) yang lebih muda dari dirinya",
                )
            )
        if ref.relation in MATERIAL_BEARING_RELATIONS and not set(target.materials) & set(
            draft.materials
        ):
            violations.append(
                Violation(
                    "REF_UNJUSTIFIED_MATERIAL",
                    "refs",
                    f"relasi '{ref.relation}' ke '{ref.id}' tidak membawa bahan dari artefak itu",
                )
            )
        if ref.relation in MOTIF_BEARING_RELATIONS and not set(target.motifs) & set(draft.motifs):
            violations.append(
                Violation(
                    "REF_UNJUSTIFIED_MOTIF",
                    "refs",
                    f"relasi '{ref.relation}' ke '{ref.id}' tidak berbagi motif apa pun",
                )
            )

    # --- lineage birth control ---------------------------------------------
    known_lineages = {a.lineage for a in catalog}
    if catalog and draft.lineage not in known_lineages and len(draft.refs) < 2:
        violations.append(
            Violation(
                "NEW_LINEAGE_UNDERJUSTIFIED",
                "lineage",
                "lineage baru harus menyitir minimal dua artefak lama sebagai asal-usulnya",
            )
        )

    # --- visual must describe this artifact, not another --------------------
    if draft.visual.form != draft.form:
        violations.append(
            Violation("VISUAL_FORM_MISMATCH", "visual.form", "visual.form harus sama dengan form")
        )
    if draft.visual.motif not in draft.motifs:
        violations.append(
            Violation(
                "VISUAL_MOTIF_MISMATCH", "visual.motif", "motif utama visual harus ada di motifs"
            )
        )

    return _report(violations, draft.id)


def verify_catalog(catalog: Sequence[Artifact]) -> list[str]:
    """Global invariants, replayable over the whole history.

    Used by ``museum verify`` and by the test suite as a second, independent
    reading of the same rules.
    """
    problems: list[str] = []
    all_ids = {a.id for a in catalog}
    seen: set[str] = set()
    titles: set[str] = set()
    last_year = -1
    for art in sorted(catalog, key=lambda a: (a.iteration, a.year_fictional)):
        if art.id in seen:
            problems.append(f"ID_DUPLICATE: {art.id}")
        if art.title.strip().lower() in titles:
            problems.append(f"TITLE_DUPLICATE: {art.id}")
        if art.year_fictional < last_year:
            problems.append(f"YEAR_REGRESSION: {art.id} ({art.year_fictional} < {last_year})")
        for ref in art.refs:
            if ref.id not in all_ids:
                problems.append(f"REF_MISSING: {art.id} -> {ref.id}")
            elif ref.id not in seen:
                problems.append(f"REF_NOT_PRIOR: {art.id} -> {ref.id}")
        seen.add(art.id)
        titles.add(art.title.strip().lower())
        last_year = max(last_year, art.year_fictional)
        for material in art.materials:
            if material not in MATERIALS:
                problems.append(f"MATERIAL_UNKNOWN: {art.id} -> {material}")
        for motif in art.motifs:
            if motif not in MOTIFS:
                problems.append(f"MOTIF_UNKNOWN: {art.id} -> {motif}")
        if art.form not in FORMS:
            problems.append(f"FORM_UNKNOWN: {art.id} -> {art.form}")
        if art.function not in FUNCTIONS:
            problems.append(f"FUNCTION_UNKNOWN: {art.id} -> {art.function}")
        if art.lineage not in LINEAGES:
            problems.append(f"LINEAGE_UNKNOWN: {art.id} -> {art.lineage}")
        if art.visual.palette not in PALETTES:
            problems.append(f"PALETTE_UNKNOWN: {art.id} -> {art.visual.palette}")
    return problems
