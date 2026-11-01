"""The founding deposit.

The museum does not start empty: four accessions establish three lineages, one
dormant technique and the first citations. They are checked by the same validator
as every later artifact - seeding is not a privileged path into the catalog.
"""

from __future__ import annotations

from .schema import Artifact, ArtifactDraft, draft_to_artifact
from .validator import validate_draft

SEED_LLM = "seed/founding-deposit"
SEED_TIMESTAMP = "2026-01-01T00:00:00Z"

_SEED_DRAFTS: list[dict] = [
    {
        "id": "savra-lempeng-tangga",
        "title": "Lempeng Tangga Langit",
        "year_fictional": 212,
        "lineage": "savra",
        "form": "lempeng",
        "function": "arsip",
        "materials": ["kapur-putih", "garam-kristal"],
        "motifs": ["tangga-langit", "parut-tujuh"],
        "refs": [],
        "inscription": "Tujuh anak tangga, tujuh kali gagal panen. Yang kedelapan tidak pernah dipahat.",
        "provenance_note": (
            "Lempeng fondasi. Ditemukan tanpa konteks, dianggap sebagai akta pertama "
            "Orang Savra; semua aksesi berikutnya menyebutnya."
        ),
        "visual": {
            "form": "lempeng",
            "palette": "garam",
            "motif": "tangga-langit",
            "symmetry": "translation",
            "density": 0.52,
            "strata": 4,
        },
    },
    {
        "id": "savra-guci-parut",
        "title": "Guci Parut Tujuh",
        "year_fictional": 240,
        "lineage": "savra",
        "form": "guci",
        "function": "ritual",
        "materials": ["kapur-putih", "serat-pandan"],
        "motifs": ["parut-tujuh"],
        "refs": [
            {
                "id": "savra-lempeng-tangga",
                "relation": "turunan",
                "note": "Membawa kapur putih yang sama dengan Lempeng Tangga Langit; teknik parutnya diulang.",
            }
        ],
        "inscription": "Bila garam mengering, isi guci dengan nama yang tidak boleh disebut.",
        "provenance_note": (
            "Guci kurban dari lapisan garam kedua. Permukaannya memakai kapur yang sama "
            "dengan lempeng fondasi, sehingga dianggap turunan langsung."
        ),
        "visual": {
            "form": "guci",
            "palette": "garam",
            "motif": "parut-tujuh",
            "symmetry": "mirror-x",
            "density": 0.61,
            "strata": 5,
        },
    },
    {
        "id": "ulmen-alat-musik-gelombang",
        "title": "Alat Musik Gelombang Diam",
        "year_fictional": 268,
        "lineage": "ulmen",
        "form": "alat-musik",
        "function": "hiburan",
        "materials": ["kayu-cendana", "perunggu-timah"],
        "motifs": ["gelombang-diam", "spiral-terbuka"],
        "refs": [
            {
                "id": "savra-lempeng-tangga",
                "relation": "kutipan",
                "note": "Mengutip hitungan tujuh anak tangga sebagai tangga nada, tanpa memakai bahan Savra.",
            },
            {
                "id": "savra-guci-parut",
                "relation": "patahan",
                "note": "Menolak guci sebagai wadah: bunyi tidak boleh disimpan, hanya dilepaskan.",
            },
        ],
        "inscription": "Tujuh lubang, empat nada. Nada kelima disimpan untuk musim yang tidak datang.",
        "provenance_note": (
            "Instrumen tiup dari lembah kabut. Bukti pertama kontak antar-lembah: "
            "hitungan Savra dipinjam sebagai sistem nada Ulmen."
        ),
        "visual": {
            "form": "alat-musik",
            "palette": "kabut",
            "motif": "gelombang-diam",
            "symmetry": "spiral",
            "density": 0.44,
            "strata": 4,
        },
    },
    {
        "id": "karrun-topeng-mata",
        "title": "Topeng Mata Ganda",
        "year_fictional": 301,
        "lineage": "karrun",
        "form": "topeng",
        "function": "penjaga-ambang",
        "materials": ["obsidian", "tulang-paus"],
        "motifs": ["mata-ganda"],
        "refs": [
            {
                "id": "ulmen-alat-musik-gelombang",
                "relation": "patahan",
                "note": "Menolak nada Ulmen: topeng ini tidak boleh dibunyikan, hanya ditatap dari satu sisi.",
            },
            {
                "id": "savra-guci-parut",
                "relation": "kutipan",
                "note": "Mengambil alih larangan menyebut nama dari guci, tetapi memindahkannya ke wajah penjaga.",
            },
        ],
        "inscription": "Dua mata untuk dua arah: yang datang, dan yang pura-pura pergi.",
        "provenance_note": (
            "Topeng ambang dari pesisir arang. Kelahiran garis Karrun terjadi dengan "
            "menolak Ulmen sekaligus mencuri larangan Savra."
        ),
        "visual": {
            "form": "topeng",
            "palette": "arang",
            "motif": "mata-ganda",
            "symmetry": "radial",
            "density": 0.7,
            "strata": 6,
        },
    },
]


def seed_catalog() -> list[Artifact]:
    """Validate and materialise the founding deposit."""
    catalog: list[Artifact] = []
    for raw in _SEED_DRAFTS:
        report = validate_draft(raw, catalog)
        if not report.ok:
            raise AssertionError(f"seed artifact rejected: {raw['id']}: {report.to_dict()}")
        draft = ArtifactDraft.model_validate(raw)
        catalog.append(
            draft_to_artifact(
                draft,
                iteration=0,
                created_at=SEED_TIMESTAMP,
                llm=SEED_LLM,
                attempt=0,
            )
        )
    return catalog


SEED_ARTIFACTS: tuple[Artifact, ...] = tuple(seed_catalog())
