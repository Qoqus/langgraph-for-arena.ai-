"""Prompts for a real curator model.

The prompt is only half of the contract: the validator is the other half, and it
is the half that cannot be talked out of anything.
"""

from __future__ import annotations

import json
from typing import Any

from .schema import ArtifactDraft

SYSTEM_PROMPT = """Kamu adalah kurator tunggal Museum Peradaban yang Tidak Pernah Ada.

Setiap iterasi kamu membaca SELURUH katalog yang pernah kamu buat, lalu menambahkan
TEPAT SATU artefak baru. Katalog itu adalah satu-satunya dunia yang ada: tidak ada
peradaban lain di luar sana, tidak ada referensi dunia nyata, tidak ada dewa penulis.
Apa pun yang tidak kamu catat tidak pernah terjadi.

Hukum museum (ditegakkan kode, bukan kesepakatan):
1. Keluarkan SATU objek JSON saja, tanpa penjelasan, tanpa pagar kode.
2. `id` unik, huruf kecil, dipisah tanda hubung, 2-6 segmen (contoh: `savra-guci-parut`).
3. `year_fictional` bilangan bulat, TIDAK BOLEH lebih kecil dari `chronology.year_floor`.
   Ikuti `chronology.year_window` yang diberikan.
4. `lineage`, `form`, `function`, `materials`, `motifs`, `visual.palette`,
   `visual.symmetry` WAJIB dari kosakata terkontrol pada konteks. Jangan mengarang id baru.
5. `refs` berisi 1-4 artefak lama yang benar-benar ada di `registry`, dengan `relation`
   dari kosakata. Setiap `note` minimal 12 karakter dan menjelaskan hubungannya secara
   spesifik. Wajib ada minimal satu rujukan bila katalog tidak kosong.
   - `turunan` dan `pemulihan` harus membawa salah satu bahan artefak yang dirujuk.
   - `resonansi` harus berbagi salah satu motif artefak yang dirujuk.
   - `patahan` dan `kutipan` tidak menuntut kesamaan bahan/motif.
6. Bahan khas garis keturunannya harus muncul di `materials` (lihat `signature_materials`).
   Jika kamu memperkenalkan lineage baru, sitir minimal DUA karya lama.
7. `visual.form` harus sama dengan `form`; `visual.motif` harus salah satu isi `motifs`.
   `visual` hanya parameter prosedural, bukan deskripsi gambar.
8. Jangan pernah menulis ulang, mengoreksi, atau "menafsirkan ulang" masa lalu dengan
   mengubah artefak lama. Satu-satunya cara menyentuh masa lalu adalah `refs`.
9. Hormati direktif kurasi: jenis, garis fokus, bahan fokus, motif fokus, dan tahun.
10. Bahasa Indonesia untuk `title`, `inscription`, `provenance_note`, `refs[].note`.
    Nada: katalog museum yang kering, spesifik, tanpa keajaiban.

Skema keluaran (semua field wajib):
{schema}
"""

USER_TEMPLATE = """ITERASI {iteration} dari museum.

DIREKTIF: {directive_kind} — {directive_text}
CATATAN DIREKTIF: {notes}
GARIS FOKUS: {focus_lineage} ({lineage_name})
BAHAN FOKUS: {focus_materials}
MOTIF FOKUS: {focus_motifs}
JENDELA TAHUN: {year_window}
KANDIDAT RUJUKAN: {candidates}

LEDGER MATERIAL (pemakaian / iterasi terakhir):
{material_ledger}

LEDGER MOTIF:
{motif_ledger}

GARIS KETURUNAN:
{lineage_ledger}

KARYA TERAKHIR:
{recent}

REGISTRY LENGKAP (id | tahun | lineage | bahan | motif | form | fungsi):
{registry}

{failure_feedback}
Tulis tepat satu objek JSON sekarang."""


def _schema_text() -> str:
    schema = ArtifactDraft.model_json_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2)


def _lineage_ledger(context: dict[str, Any]) -> str:
    rows = []
    for lineage, info in sorted(context["ledger"]["lineages"].items()):
        rows.append(
            f"- {lineage}: {info['count']} karya, tahun {info['first_year']}-{info['last_year']}, "
            f"iterasi terakhir {info['last_iteration']}, bahan {info['materials']}, motif {info['motifs']}"
        )
    return "\n".join(rows) or "- (kosong)"


def _material_ledger(context: dict[str, Any]) -> str:
    rows = []
    for material, info in context["ledger"]["materials"].items():
        rows.append(f"- {material}: {info['uses']}x, iterasi terakhir {info['last_iteration']}")
    return "\n".join(rows) or "- (kosong)"


def _motif_ledger(context: dict[str, Any]) -> str:
    rows = []
    for motif, info in context["ledger"]["motifs"].items():
        rows.append(f"- {motif}: {info['uses']}x, iterasi terakhir {info['last_iteration']}")
    return "\n".join(rows) or "- (kosong)"


def _recent(context: dict[str, Any]) -> str:
    rows = []
    for art in context["recent_artifacts"]:
        rows.append(
            f"- {art['id']} ({art['year']}, {art['lineage']}): {art['title']} — "
            f"{', '.join(art['materials'])}; motif {', '.join(art['motifs'])}; rujukan {art['refs']}"
        )
    return "\n".join(rows) or "- (kosong)"


def _registry(context: dict[str, Any]) -> str:
    rows = [
        f"- {a['id']} | {a['year']} | {a['lineage']} | {','.join(a['materials'])} | "
        f"{','.join(a['motifs'])} | {a['form']} | {a['function']}"
        for a in context["registry"]
    ]
    return "\n".join(rows) or "- (kosong)"


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    directive = context["directive"]
    candidates = ", ".join(f"{c['id']} ({c['title']})" for c in directive["ref_candidates"])
    feedback = ""
    if context.get("feedback"):
        feedback = (
            "DRAF SEBELUMNYA DITOLAK. Perbaiki pelanggaran berikut, jangan mengulanginya:\n"
            f"{context['feedback']}\n\n"
        )
    user = USER_TEMPLATE.format(
        iteration=context["iteration"],
        directive_kind=directive["kind"],
        directive_text=directive["text"],
        notes="; ".join(directive["notes"]) or "-",
        focus_lineage=directive["focus_lineage"],
        lineage_name=directive["lineage_style"]["name"],
        focus_materials=", ".join(directive["focus_materials"]) or "-",
        focus_motifs=", ".join(directive["focus_motifs"]) or "-",
        year_window=f"{context['chronology']['year_window'][0]}..{context['chronology']['year_window'][1]}",
        candidates=candidates or "-",
        material_ledger=_material_ledger(context),
        motif_ledger=_motif_ledger(context),
        lineage_ledger=_lineage_ledger(context),
        recent=_recent(context),
        registry=_registry(context),
        failure_feedback=feedback,
    )
    system = SYSTEM_PROMPT.replace("{schema}", _schema_text())
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": user + "\n\nKOSAKATA TERKONTROL:\n" + context["vocabulary"]["hint"],
        },
    ]
