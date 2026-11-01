"""Deterministic mock curator.

It is a *stand-in for the model*, not a shortcut around the graph: it receives
the same context object a real model receives and returns the same kind of raw
JSON string. Its decisions are derived from the directive and the catalog, so a
20-iteration run produces a history with real continuity.

``chaos`` injects malformed drafts on purpose so the validator, the repair edge
and the rejection path are exercised for real rather than in theory.
"""

from __future__ import annotations

import json
import random

from ..vocabulary import (
    FORMS,
    FUNCTIONS,
    LINEAGES,
    MATERIALS,
    MOTIFS,
    PALETTES,
    SYMMETRIES,
)

PLACES = (
    "musim tanpa hujan",
    "ambang yang dijaga",
    "sungai yang berbalik",
    "malam tanpa gema",
    "gudang garam",
    "tangga yang patah",
    "kebun yang lupa dituai",
    "batas kabut",
)

QUALIFIERS = (
    "yang menahan air",
    "tanpa penutup",
    "dari tangan kedua",
    "yang tidak selesai",
    "untuk yang belum lahir",
    "dengan satu sisi gelap",
    "berisi hitungan yang salah",
)

TITLE_TEMPLATES = (
    "{form} {motif}",
    "{form} {motif} dari {place}",
    "{form} {qualifier}",
    "{form} untuk {function}",
    "{form} {motif}, tahun {year}",
)

INSCRIPTIONS = (
    "Di sini {material} berhenti menjadi bahan dan mulai menjadi saksi: {meaning}.",
    "Dipahat sembilan kali, ditolak tujuh kali; yang tersisa hanya {meaning}.",
    "Tidak ada yang membacanya utuh. Yang tersisa adalah {meaning} dan lapisan {material}.",
    "Catatan penuh: {meaning}. Bahan: {material}. Sisanya sengaja dihilangkan.",
    "Benda ini menolak disebut pusaka. Ia hanya menandai {meaning}.",
    "Seorang penjaga menulis: 'jangan pindahkan {material}, ia sedang menghitung.'",
)

PROVENANCE = (
    "Ditemukan pada lapisan {year}; diajukan sebagai {kind} pada iterasi {iteration} untuk garis {lineage}. "
    "Kekerabatan materialnya ditarik dari {refs}.",
    "Masuk katalog lewat jalur {kind} (iterasi {iteration}). Permukaannya menahan jejak {material}; "
    "kurator menautkannya ke {refs} karena kesamaan proses, bukan kesamaan bentuk.",
    "Tercatat tanpa konteks kubur, tahun {year}. Ditempatkan dalam garis {lineage} setelah dibandingkan dengan {refs}.",
)

LINEAGE_PALETTE = {
    "savra": "garam",
    "ulmen": "kabut",
    "karrun": "arang",
    "heska": "kaca",
    "oroba": "rawa",
    "tirsa": "puncak",
}

FORM_BY_KIND = {
    "monumen": ("monolit", "tenun", "arca"),
    "patahan": ("monolit", "topeng", "alat-musik", "arca"),
    "pemulihan": ("guci", "relikuari", "lampu", "lempeng"),
    "persilangan": ("topeng", "tenun", "alat-musik", "relikuari"),
    "kelanjutan": ("guci", "lempeng", "cincin", "lampu", "tenun"),
}

SYMMETRY_BY_KIND = {
    "monumen": "radial",
    "patahan": "spiral",
    "persilangan": "mirror-x",
    "pemulihan": "translation",
    "kelanjutan": "mirror-x",
}

_SHORT_WORDS = ("sigil", "jejak", "ambang", "simpul", "sisa", "catat", "lubang", "tanda")


def _dedupe(values) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


class MockCurator:
    name = "mock-curator/1"

    def __init__(self, chaos: str = "sometimes", salt: str = "museum") -> None:
        if chaos not in ("off", "sometimes", "always"):
            raise ValueError("chaos must be one of: off, sometimes, always")
        self.chaos = chaos
        self.salt = salt

    # -- public -------------------------------------------------------------
    def propose(self, context: dict) -> str:
        rnd = random.Random(f"{self.salt}|{context['iteration']}|{context['attempt']}")
        draft = self._valid_draft(context, rnd)
        if self._should_break(context):
            draft = self._break(context, draft, rnd)
        return json.dumps(draft, ensure_ascii=False)

    # -- internals ----------------------------------------------------------
    def _should_break(self, context: dict) -> bool:
        if self.chaos == "always":
            return True
        if self.chaos == "sometimes":
            return context["attempt"] == 0 and context["iteration"] % 4 == 0
        return False

    def _valid_draft(self, context: dict, rnd: random.Random) -> dict:
        directive = context["directive"]
        registry = context["registry"]
        by_id = {a["id"]: a for a in registry}
        kind = directive["kind"]
        lineage = directive["focus_lineage"]
        floor = context["chronology"]["year_floor"]
        year = floor + rnd.randint(1, max(1, directive["year_span"]))

        # materials: focus + one material that belongs to the lineage
        own = [
            m
            for m in MATERIALS
            if MATERIALS[m].origin == lineage or m in LINEAGES[lineage].signature_materials
        ]
        materials = _dedupe(directive["focus_materials"])[:3]
        if not set(materials) & set(own):
            materials.insert(0, rnd.choice(own))
        materials = _dedupe([*materials, rnd.choice(own)])[:4]

        motifs = _dedupe(directive["focus_motifs"])[:2]
        motifs = _dedupe([*motifs, rnd.choice(list(MOTIFS))])[:3]

        form = rnd.choice(FORM_BY_KIND.get(kind, tuple(FORMS)))
        function = rnd.choice(FUNCTIONS)
        if kind == "monumen" and rnd.random() < 0.6:
            function = "kronik"

        # references, with a relation that survives the justification rules
        pool = [c["id"] for c in directive["ref_candidates"] if c["id"] in by_id]
        if not pool and registry:
            pool = [max(registry, key=lambda a: (a["year"], a["id"]))["id"]]
        required = 2 if (registry and lineage not in {a["lineage"] for a in registry}) else 1
        want = min(len(pool), max(required, rnd.randint(1, 3)))
        chosen = pool[:want]
        if registry and len(chosen) < required:
            for art in sorted(registry, key=lambda a: -a["year"]):
                if art["id"] not in chosen:
                    chosen.append(art["id"])
                if len(chosen) >= required:
                    break

        refs = []
        for ref_id in chosen:
            target = by_id[ref_id]
            shared_materials = set(target["materials"]) & set(materials)
            shared_motifs = set(target["motifs"]) & set(motifs)
            if kind == "patahan":
                relation = "patahan"
            elif shared_materials:
                relation = "pemulihan" if kind == "pemulihan" else "turunan"
            elif shared_motifs:
                relation = "resonansi"
            else:
                relation = "kutipan"
            if relation in ("turunan", "pemulihan") and not shared_materials:
                relation = "resonansi" if shared_motifs else "kutipan"
            if relation == "resonansi" and not shared_motifs:
                relation = "kutipan"
            if shared_materials:
                note = (
                    f"membawa bahan {', '.join(sorted(shared_materials))} dari {target['title']} "
                    f"({target['year']}), tekniknya diulang lalu dibelokkan"
                )
            elif shared_motifs:
                note = (
                    f"mengutip motif {', '.join(sorted(shared_motifs))} dari {target['title']} "
                    f"({target['year']}) tanpa mewarisi bahannya"
                )
            else:
                note = (
                    f"menyebut {target['title']} ({target['year']}) sebagai leluhur yang ditolak, "
                    f"bukan sebagai sumber bahan"
                )
            refs.append({"id": ref_id, "relation": relation, "note": note[:400]})

        artifact_id = self._unique_id(lineage, form, rnd, by_id)
        title = self._unique_title(form, motifs, function, year, rnd, registry)
        material_labels = ", ".join(MATERIALS[m].label for m in materials)
        template = INSCRIPTIONS[rnd.randrange(len(INSCRIPTIONS))]
        inscription = template.format(
            material=MATERIALS[materials[0]].label,
            meaning=MOTIFS[motifs[0]].meaning,
            year=year,
        )
        ref_titles = (
            ", ".join(by_id[r["id"]]["title"] for r in refs) or "tidak ada karya sebelumnya"
        )
        provenance = PROVENANCE[rnd.randrange(len(PROVENANCE))].format(
            year=year,
            kind=directive["text"],
            iteration=context["iteration"],
            lineage=LINEAGES[lineage].name,
            material=material_labels,
            refs=ref_titles,
        )

        return {
            "id": artifact_id,
            "title": title,
            "year_fictional": year,
            "lineage": lineage,
            "form": form,
            "function": function,
            "materials": materials,
            "motifs": motifs,
            "refs": refs,
            "inscription": inscription,
            "provenance_note": provenance,
            "visual": {
                "form": form,
                "palette": LINEAGE_PALETTE.get(lineage, rnd.choice(list(PALETTES))),
                "motif": motifs[0],
                "symmetry": SYMMETRY_BY_KIND.get(kind, rnd.choice(list(SYMMETRIES))),
                "density": round(rnd.uniform(0.32, 0.86), 2),
                "strata": rnd.randint(3, 7),
            },
        }

    def _unique_id(self, lineage: str, form: str, rnd: random.Random, by_id: dict) -> str:
        word = _SHORT_WORDS[rnd.randrange(len(_SHORT_WORDS))]
        base = f"{lineage}-{form}-{word}"
        candidate = base
        index = 2
        while candidate in by_id:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _unique_title(self, form, motifs, function, year, rnd, registry) -> str:
        taken = {a["title"].lower() for a in registry}
        place = PLACES[rnd.randrange(len(PLACES))]
        qualifier = QUALIFIERS[rnd.randrange(len(QUALIFIERS))]
        template = TITLE_TEMPLATES[rnd.randrange(len(TITLE_TEMPLATES))]
        for offset in range(len(TITLE_TEMPLATES)):
            body = TITLE_TEMPLATES[
                (TITLE_TEMPLATES.index(template) + offset) % len(TITLE_TEMPLATES)
            ].format(
                form=FORMS[form].label.capitalize(),
                motif=MOTIFS[motifs[0]].label,
                place=place,
                qualifier=qualifier,
                function=function,
                year=year,
            )
            if body.lower() not in taken:
                return body
        return f"{FORMS[form].label.capitalize()} {MOTIFS[motifs[0]].label} ({year})"

    def _break(self, context: dict, draft: dict, rnd: random.Random) -> dict:
        """Return a draft that must be rejected, cycling through the rule set."""
        mode = context["iteration"] % 4
        broken = dict(draft)
        if mode == 0:
            if context["registry"]:
                broken["id"] = context["registry"][0]["id"]
            else:
                broken["id"] = "museum-tanpa-katalog"
        elif mode == 1:
            broken["refs"] = [
                *broken["refs"],
                {
                    "id": "artefak-yang-hilang",
                    "relation": "kutipan",
                    "note": "dirujuk dari ingatan yang ternyata tidak pernah dicatat",
                },
            ]
        elif mode == 2:
            broken["year_fictional"] = max(0, context["chronology"]["year_floor"] - 7)
        else:
            broken["materials"] = ["batu-bulan", *list(broken["materials"])[1:]]
        return broken
