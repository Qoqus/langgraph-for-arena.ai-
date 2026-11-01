"""The curator's brief.

Every iteration the deterministic side of the museum reads the *whole* catalog
and writes down what it sees: which lineages are alive, which materials have gone
quiet, which motifs are unresolved, which works are being cited. Out of that it
derives one **curation directive** — the dramaturgy of the next accession.

The LLM is handed this brief. It decides the content; the brief decides the
pacing. That division is what keeps a twenty-iteration history from collapsing
into twenty unrelated objects.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .schema import Artifact
from .vocabulary import (
    FORMS,
    FUNCTIONS,
    LINEAGE_ORDER,
    LINEAGES,
    MATERIALS,
    MOTIFS,
    PALETTES,
    RELATIONS,
    SYMMETRIES,
    VOCAB_HINT,
)

#: A five-beat narrative loop, repeated as the catalog grows.
DIRECTIVE_CYCLE: tuple[str, ...] = (
    "kelanjutan",  # extend the living lineage
    "pemulihan",  # wake a material that has gone quiet
    "persilangan",  # cross two lineages
    "monumen",  # make a large work about the most-cited ancestor
    "patahan",  # break: birth of a new lineage
)

DIRECTIVE_SPAN = {
    "kelanjutan": 6,
    "pemulihan": 14,
    "persilangan": 20,
    "monumen": 40,
    "patahan": 32,
}

DIRECTIVE_TEXT = {
    "kelanjutan": "teruskan garis keturunan yang sedang hidup",
    "pemulihan": "hidupkan kembali bahan yang sudah lama tidak dipakai",
    "persilangan": "silangkan dua garis keturunan yang berbeda",
    "monumen": "buat karya besar tentang leluhur yang paling sering dirujuk",
    "patahan": "patahkan sejarah: lahirkan garis keturunan baru dari dua karya lama",
}


def _dominant(values: Sequence[str], limit: int = 3) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return [v for v, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def ledger(catalog: Sequence[Artifact]) -> dict[str, Any]:
    """Deterministic reading of the accumulated material history."""
    lineages: dict[str, dict[str, Any]] = {}
    materials: dict[str, dict[str, Any]] = {}
    motifs: dict[str, dict[str, Any]] = {}
    citations: dict[str, int] = defaultdict(int)
    backrefs: dict[str, list[str]] = defaultdict(list)

    for art in catalog:
        entry = lineages.setdefault(
            art.lineage,
            {
                "count": 0,
                "first_year": art.year_fictional,
                "last_year": art.year_fictional,
                "last_iteration": art.iteration,
                "materials": [],
                "motifs": [],
                "forms": [],
                "functions": [],
            },
        )
        entry["count"] += 1
        entry["first_year"] = min(entry["first_year"], art.year_fictional)
        entry["last_year"] = max(entry["last_year"], art.year_fictional)
        entry["last_iteration"] = max(entry["last_iteration"], art.iteration)
        entry["materials"].extend(art.materials)
        entry["motifs"].extend(art.motifs)
        entry["forms"].append(art.form)
        entry["functions"].append(art.function)

        for material in art.materials:
            m = materials.setdefault(
                material,
                {"uses": 0, "last_year": art.year_fictional, "last_iteration": art.iteration},
            )
            m["uses"] += 1
            m["last_year"] = max(m["last_year"], art.year_fictional)
            m["last_iteration"] = max(m["last_iteration"], art.iteration)
        for motif in art.motifs:
            k = motifs.setdefault(
                motif, {"uses": 0, "last_year": art.year_fictional, "last_iteration": art.iteration}
            )
            k["uses"] += 1
            k["last_year"] = max(k["last_year"], art.year_fictional)
            k["last_iteration"] = max(k["last_iteration"], art.iteration)
        for ref in art.refs:
            citations[ref.id] += 1
            backrefs[ref.id].append(art.id)

    for entry in lineages.values():
        entry["materials"] = _dominant(entry["materials"])
        entry["motifs"] = _dominant(entry["motifs"])
        entry["forms"] = _dominant(entry["forms"], 2)
        entry["functions"] = _dominant(entry["functions"], 2)
    return {
        "lineages": lineages,
        "materials": dict(sorted(materials.items())),
        "motifs": dict(sorted(motifs.items())),
        "citations": dict(sorted(citations.items(), key=lambda kv: (-kv[1], kv[0]))),
        "backrefs": dict(backrefs),
    }


def _latest(catalog: Sequence[Artifact]) -> Artifact:
    return max(catalog, key=lambda a: (a.year_fictional, a.iteration, a.id))


def _dormant_materials(state: dict[str, Any], iteration: int) -> list[tuple[str, int]]:
    """Materials that have not appeared for a while, stalest first."""
    dormant: list[tuple[str, int]] = []
    for material, info in state["materials"].items():
        gap = iteration - int(info["last_iteration"])
        threshold = MATERIALS[material].dormancy
        if gap >= threshold:
            dormant.append((material, gap))
    dormant.sort(key=lambda item: (-item[1], item[0]))
    return dormant


def _pick_second_lineage(catalog: Sequence[Artifact], focus: str) -> str | None:
    others = [
        lineage
        for lineage in LINEAGE_ORDER
        if lineage != focus and any(a.lineage == lineage for a in catalog)
    ]
    if not others:
        return None
    # least recently active among existing lineages: the one most in need of a bridge
    scored = []
    for lineage in others:
        arts = [a for a in catalog if a.lineage == lineage]
        scored.append((max(a.iteration for a in arts), lineage))
    scored.sort()
    return scored[0][1]


def ref_candidates(catalog: Sequence[Artifact], pool: Sequence[str]) -> list[dict[str, Any]]:
    by_id = {a.id: a for a in catalog}
    ordered: list[str] = []
    for candidate in pool:
        if candidate in by_id and candidate not in ordered:
            ordered.append(candidate)
    return [
        {"id": rid, "title": by_id[rid].title, "year": by_id[rid].year_fictional}
        for rid in ordered[:4]
    ]


def choose_directive(catalog: Sequence[Artifact], iteration: int) -> dict[str, Any]:
    """Deterministic dramaturgy for iteration ``iteration`` (1-based)."""
    if not catalog:
        # A museum without a founding deposit: the first artifact may cite nothing.
        lineage = LINEAGE_ORDER[0]
        return {
            "kind": "kelanjutan",
            "text": DIRECTIVE_TEXT["kelanjutan"],
            "notes": ["katalog kosong; aksesi pertama tidak dapat merujuk apa pun"],
            "focus_lineage": lineage,
            "partner_lineage": None,
            "focus_materials": list(LINEAGES[lineage].signature_materials),
            "focus_motifs": list(LINEAGES[lineage].signature_motifs),
            "lineage_style": {
                "name": LINEAGES[lineage].name,
                "landscape": LINEAGES[lineage].landscape,
                "temperament": LINEAGES[lineage].temperament,
            },
            "year_floor": 0,
            "year_span": 40,
            "ref_candidates": [],
        }

    state = ledger(catalog)
    latest = _latest(catalog)
    kind = DIRECTIVE_CYCLE[(iteration - 1) % len(DIRECTIVE_CYCLE)]
    notes: list[str] = []

    dormant = _dormant_materials(state, iteration)
    existing_lineages = {a.lineage for a in catalog}
    unused_lineages = [lineage for lineage in LINEAGE_ORDER if lineage not in existing_lineages]

    if kind == "pemulihan" and not dormant:
        kind = "kelanjutan"
        notes.append("belum ada bahan yang cukup lama tidur; lanjutkan saja garis yang hidup")
    if kind == "persilangan" and len(existing_lineages) < 2:
        kind = "kelanjutan"
        notes.append("baru satu garis keturunan; belum ada yang bisa disilangkan")
    if kind == "patahan" and not unused_lineages:
        kind = "persilangan"
        notes.append("semua garis keturunan sudah lahir; patahan menjadi persilangan")
    if kind == "monumen" and len(catalog) < 3:
        kind = "kelanjutan"
        notes.append("terlalu sedikit leluhur untuk dimonumentalkan")
    if kind == "persilangan" and _pick_second_lineage(catalog, latest.lineage) is None:
        kind = "kelanjutan"
        notes.append("tidak ada garis kedua yang tersedia")

    focus_lineage = latest.lineage
    partner_lineage: str | None = None
    focus_materials: list[str] = []
    focus_motifs: list[str] = []
    candidate_pool: list[str] = []

    if kind == "kelanjutan":
        focus_lineage = latest.lineage
        candidate_pool = [latest.id]
        same_lineage = sorted(
            [a for a in catalog if a.lineage == focus_lineage and a.id != latest.id],
            key=lambda a: (-a.year_fictional, -a.iteration),
        )
        candidate_pool += [a.id for a in same_lineage[:2]]
        focus_materials = list(LINEAGES[focus_lineage].signature_materials)
        focus_materials.append(latest.materials[0])
        focus_motifs = list(LINEAGES[focus_lineage].signature_motifs)

    elif kind == "pemulihan":
        material, gap = dormant[0]
        focus_lineage = latest.lineage
        users = [a for a in catalog if material in a.materials]
        users.sort(key=lambda a: (a.year_fictional, a.iteration))
        candidate_pool = [users[0].id] if users else []
        candidate_pool.append(latest.id)
        focus_materials = [material, *LINEAGES[focus_lineage].signature_materials]
        focus_motifs = list(LINEAGES[focus_lineage].signature_motifs)
        if users:
            focus_motifs.append(users[0].motifs[0])
        notes.append(f"bahan '{material}' telah tidur {gap} iterasi")

    elif kind == "persilangan":
        partner_lineage = _pick_second_lineage(catalog, latest.lineage)
        focus_lineage = latest.lineage
        partner_arts = sorted(
            [a for a in catalog if a.lineage == partner_lineage],
            key=lambda a: (-a.year_fictional, -a.iteration),
        )
        candidate_pool = [latest.id, partner_arts[0].id]
        focus_materials = [
            LINEAGES[focus_lineage].signature_materials[0],
            LINEAGES[partner_lineage].signature_materials[0],
        ]
        focus_motifs = [
            LINEAGES[focus_lineage].signature_motifs[0],
            LINEAGES[partner_lineage].signature_motifs[0],
        ]
        notes.append(
            f"menyilangkan {LINEAGES[focus_lineage].name} dengan {LINEAGES[partner_lineage].name}"
        )

    elif kind == "patahan":
        focus_lineage = unused_lineages[0]
        ranked = state["citations"]
        top = [rid for rid in ranked if rid in {a.id for a in catalog}]
        candidate_pool = [latest.id, *top][:3]
        focus_materials = list(LINEAGES[focus_lineage].signature_materials)
        focus_motifs = list(LINEAGES[focus_lineage].signature_motifs)
        notes.append(f"garis '{focus_lineage}' belum pernah ada; ia harus lahir dari karya lama")

    else:  # monumen
        ranked = state["citations"]
        top_id = next((rid for rid in ranked if rid in {a.id for a in catalog}), latest.id)
        top = next(a for a in catalog if a.id == top_id)
        focus_lineage = top.lineage
        candidate_pool = [top.id, latest.id]
        focus_materials = list(LINEAGES[focus_lineage].signature_materials)
        focus_motifs = list(top.motifs)
        notes.append(f"leluhur '{top.id}' sudah dirujuk {ranked.get(top_id, 0)} kali")

    directive: dict[str, Any] = {
        "kind": kind,
        "text": DIRECTIVE_TEXT[kind],
        "notes": notes,
        "focus_lineage": focus_lineage,
        "partner_lineage": partner_lineage,
        "focus_materials": list(dict.fromkeys(focus_materials)),
        "focus_motifs": list(dict.fromkeys(focus_motifs)),
        "lineage_style": {
            "name": LINEAGES[focus_lineage].name,
            "landscape": LINEAGES[focus_lineage].landscape,
            "temperament": LINEAGES[focus_lineage].temperament,
        },
        "year_floor": latest.year_fictional,
        "year_span": DIRECTIVE_SPAN[kind],
    }
    directive["ref_candidates"] = ref_candidates(catalog, list(dict.fromkeys(candidate_pool)))
    return directive


def build_context(
    catalog: Sequence[Artifact],
    *,
    iteration: int,
    max_attempts: int,
    feedback: str | None = None,
) -> dict[str, Any]:
    """The full brief handed to the curator LLM, plus the directive."""
    state = ledger(catalog)
    directive = choose_directive(catalog, iteration)
    compact = [
        {
            "id": a.id,
            "title": a.title,
            "year": a.year_fictional,
            "lineage": a.lineage,
            "form": a.form,
            "function": a.function,
            "materials": list(a.materials),
            "motifs": list(a.motifs),
            "refs": [r.id for r in a.refs],
        }
        for a in sorted(catalog, key=lambda a: (a.year_fictional, a.iteration, a.id))
    ]
    recent = compact[-6:]
    return {
        "iteration": iteration,
        "catalog_size": len(catalog),
        "directive": directive,
        "chronology": {
            "last_year": max((a.year_fictional for a in catalog), default=None),
            "first_year": min((a.year_fictional for a in catalog), default=None),
            "year_floor": directive["year_floor"],
            "year_window": [
                directive["year_floor"],
                directive["year_floor"] + directive["year_span"],
            ],
        },
        "ledger": state,
        "recent_artifacts": recent,
        "registry": compact,
        "vocabulary": {
            "hint": VOCAB_HINT,
            "lineage": [
                {
                    "id": lineage,
                    "name": LINEAGES[lineage].name,
                    "landscape": LINEAGES[lineage].landscape,
                    "temperament": LINEAGES[lineage].temperament,
                    "signature_materials": list(LINEAGES[lineage].signature_materials),
                    "signature_motifs": list(LINEAGES[lineage].signature_motifs),
                }
                for lineage in LINEAGE_ORDER
            ],
            "materials": [
                {
                    "id": m,
                    "label": MATERIALS[m].label,
                    "origin": MATERIALS[m].origin,
                    "texture": MATERIALS[m].texture,
                    "dormancy": MATERIALS[m].dormancy,
                }
                for m in MATERIALS
            ],
            "motifs": [
                {"id": m, "label": MOTIFS[m].label, "meaning": MOTIFS[m].meaning} for m in MOTIFS
            ],
            "forms": [{"id": f, "label": FORMS[f].label, "scale": FORMS[f].scale} for f in FORMS],
            "functions": list(FUNCTIONS),
            "palettes": [{"id": p, "label": PALETTES[p].label} for p in PALETTES],
            "relations": list(RELATIONS),
            "symmetries": list(SYMMETRIES),
        },
        "attempt": 0,
        "max_attempts": max_attempts,
        "feedback": feedback,
    }
