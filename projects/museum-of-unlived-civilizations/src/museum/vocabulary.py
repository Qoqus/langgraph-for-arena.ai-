"""Controlled vocabulary of the museum.

Facts live in code. The LLM never invents a material, a motif, a form, a
function, a lineage or a palette: it only chooses among these ids. That is what
keeps the world's material history closed and checkable across iterations.

Nothing here is random; the vocabulary is the museum's constitution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Lineage:
    id: str
    name: str
    landscape: str
    temperament: str
    signature_materials: tuple[str, ...]
    signature_motifs: tuple[str, ...]


@dataclass(frozen=True)
class Material:
    id: str
    label: str
    origin: str
    texture: str
    #: how many curator iterations of silence count as "dormant" (revival cue)
    dormancy: int = 5


@dataclass(frozen=True)
class Motif:
    id: str
    label: str
    geometry: Literal["spiral", "ladder", "eye", "net", "scar", "ring", "root", "wave"]
    meaning: str


@dataclass(frozen=True)
class Form:
    id: str
    label: str
    #: silhouette template used by the procedural renderer
    silhouette: Literal[
        "vessel",
        "tablet",
        "mask",
        "figure",
        "textile",
        "instrument",
        "reliquary",
        "monolith",
        "ring",
        "lamp",
    ]
    scale: Literal["kecil", "sedang", "besar"]


@dataclass(frozen=True)
class Palette:
    id: str
    label: str
    ground: str
    ink: str
    accents: tuple[str, ...]


LINEAGES: dict[str, Lineage] = {
    "savra": Lineage(
        id="savra",
        name="Orang Savra",
        landscape="dataran garam yang membeku setiap malam",
        temperament="menyimpan ingatan dengan menggores, bukan menulis",
        signature_materials=("kapur-putih", "serat-pandan"),
        signature_motifs=("parut-tujuh", "tangga-langit"),
    ),
    "ulmen": Lineage(
        id="ulmen",
        name="Ulmen",
        landscape="lembah kabut yang tidak pernah melihat matahari penuh",
        temperament="mengukur dunia dengan bunyi dan gema",
        signature_materials=("kayu-cendana", "perunggu-timah"),
        signature_motifs=("spiral-terbuka", "gelombang-diam"),
    ),
    "karrun": Lineage(
        id="karrun",
        name="Karrun",
        landscape="pesisir arang tempat bangkai paus menjadi kuil",
        temperament="berdagang dengan orang mati sebelum berdagang dengan orang hidup",
        signature_materials=("obsidian", "tulang-paus"),
        signature_motifs=("mata-ganda", "jala-bintang"),
    ),
    "heska": Lineage(
        id="heska",
        name="Heska",
        landscape="kota kaca di cekungan vulkanik",
        temperament="percaya bahwa cahaya adalah bentuk tertua dari kesaksian",
        signature_materials=("kaca-vulkanik", "tembaga-hijau"),
        signature_motifs=("cincin-berputar", "mata-ganda"),
    ),
    "oroba": Lineage(
        id="oroba",
        name="Oroba",
        landscape="rawa resapan yang menelan segala sesuatu dalam tujuh hari",
        temperament="menanam kata-kata di lumpur dan memanennya sebagai hukum",
        signature_materials=("tanah-liat", "resin-jernih"),
        signature_motifs=("akar-terbalik", "gelombang-diam"),
    ),
    "tirsa": Lineage(
        id="tirsa",
        name="Tirsa",
        landscape="punggung pegunungan yang bernapas tipis",
        temperament="menganggap ketinggian sebagai bentuk kesabaran",
        signature_materials=("gipsum-berlapis", "benang-perak"),
        signature_motifs=("jala-bintang", "tangga-langit"),
    ),
}

MATERIALS: dict[str, Material] = {
    "kapur-putih": Material("kapur-putih", "kapur putih", "savra", "berbutir, menyerap cahaya"),
    "serat-pandan": Material("serat-pandan", "serat pandan", "savra", "berserat, kenyal"),
    "kayu-cendana": Material("kayu-cendana", "kayu cendana", "ulmen", "beraroma, mudah diukir"),
    "perunggu-timah": Material("perunggu-timah", "perunggu timah", "ulmen", "berdering, berat"),
    "obsidian": Material("obsidian", "obsidian", "karrun", "licin seperti air beku"),
    "tulang-paus": Material("tulang-paus", "tulang paus", "karrun", "berpori, berkapur"),
    "kaca-vulkanik": Material("kaca-vulkanik", "kaca vulkanik", "heska", "tembus cahaya, getas"),
    "tembaga-hijau": Material("tembaga-hijau", "tembaga hijau", "heska", "teroksidasi, hangat"),
    "tanah-liat": Material("tanah-liat", "tanah liat", "oroba", "lembap, mudah dibentuk"),
    "resin-jernih": Material("resin-jernih", "resin jernih", "oroba", "lengket, mengawetkan"),
    "gipsum-berlapis": Material("gipsum-berlapis", "gipsum berlapis", "tirsa", "berlapis, rapuh"),
    "benang-perak": Material("benang-perak", "benang perak", "tirsa", "tipis, memantulkan dingin"),
    "batu-sungai": Material("batu-sungai", "batu sungai", "savra", "licin, padat", dormancy=7),
    "garam-kristal": Material(
        "garam-kristal", "garam kristal", "savra", "berkilau, larut", dormancy=7
    ),
}

MOTIFS: dict[str, Motif] = {
    "spiral-terbuka": Motif(
        "spiral-terbuka", "spiral terbuka", "spiral", "waktu yang tidak menutup"
    ),
    "tangga-langit": Motif(
        "tangga-langit", "tangga langit", "ladder", "akses ke yang lebih tinggi"
    ),
    "mata-ganda": Motif("mata-ganda", "mata ganda", "eye", "kesaksian yang tidak bisa dibohongi"),
    "jala-bintang": Motif("jala-bintang", "jala bintang", "net", "ikatan antara yang jauh"),
    "parut-tujuh": Motif("parut-tujuh", "parut tujuh", "scar", "tujuh musim kelaparan"),
    "cincin-berputar": Motif("cincin-berputar", "cincin berputar", "ring", "siklus yang dirayakan"),
    "akar-terbalik": Motif("akar-terbalik", "akar terbalik", "root", "hukum yang tumbuh ke bawah"),
    "gelombang-diam": Motif("gelombang-diam", "gelombang diam", "wave", "gerak yang ditahan"),
    "bara-pecah": Motif("bara-pecah", "bara pecah", "scar", "kehilangan yang disengaja"),
    "simpul-tiga": Motif("simpul-tiga", "simpul tiga", "net", "perjanjian tiga pihak"),
}

FORMS: dict[str, Form] = {
    "guci": Form("guci", "guci", "vessel", "sedang"),
    "lempeng": Form("lempeng", "lempeng", "tablet", "kecil"),
    "topeng": Form("topeng", "topeng", "mask", "sedang"),
    "tenun": Form("tenun", "tenun", "textile", "besar"),
    "alat-musik": Form("alat-musik", "alat musik", "instrument", "sedang"),
    "relikuari": Form("relikuari", "relikuari", "reliquary", "kecil"),
    "monolit": Form("monolit", "monolit", "monolith", "besar"),
    "cincin": Form("cincin", "cincin", "ring", "kecil"),
    "lampu": Form("lampu", "lampu", "lamp", "kecil"),
    "arca": Form("arca", "arca", "figure", "besar"),
}

FUNCTIONS: tuple[str, ...] = (
    "ritual",
    "arsip",
    "penanda-makam",
    "alat-ukur",
    "hiburan",
    "perdagangan",
    "penjaga-ambang",
    "kronik",
    "persembahan",
    "perlindungan",
)

PALETTES: dict[str, Palette] = {
    "garam": Palette("garam", "garam", "#14181a", "#f2ead8", ("#c9a227", "#3f7d78", "#b4553b")),
    "kabut": Palette("kabut", "kabut", "#101418", "#e8e4da", ("#8fae8b", "#b98b7f", "#5c6b8a")),
    "arang": Palette("arang", "arang", "#0d0c0b", "#efe6d6", ("#c25b32", "#8a6f4e", "#d9a441")),
    "kaca": Palette("kaca", "kaca", "#0b1020", "#e6eefc", ("#5fc8d8", "#c8a03c", "#7a5fc8")),
    "rawa": Palette("rawa", "rawa", "#0f1410", "#e9e6cf", ("#7f9c4a", "#b5842f", "#5a4632")),
    "puncak": Palette("puncak", "puncak", "#0e1116", "#eef0f6", ("#9dc6e0", "#c9cdd6", "#8b6fae")),
}

RELATIONS: tuple[str, ...] = (
    "turunan",  # a direct descendant: carries material and technique forward
    "pemulihan",  # revival of a dormant material
    "resonansi",  # shares a motif without direct descent
    "kutipan",  # quotes an inscription/measure
    "patahan",  # a break: acknowledges the ancestor by refusing it
)

SYMMETRIES: tuple[str, ...] = ("mirror-x", "radial", "translation", "spiral")

#: Lineages may only be introduced in this order. A new lineage enters the
#: catalog through a ``patahan`` artifact that cites at least two older works.
LINEAGE_ORDER: tuple[str, ...] = ("savra", "ulmen", "karrun", "heska", "oroba", "tirsa")

#: Relations that must materially or iconographically justify themselves.
MATERIAL_BEARING_RELATIONS: tuple[str, ...] = ("turunan", "pemulihan")
MOTIF_BEARING_RELATIONS: tuple[str, ...] = ("resonansi",)

VOCAB = {
    "lineage": tuple(LINEAGES),
    "material": tuple(MATERIALS),
    "motif": tuple(MOTIFS),
    "form": tuple(FORMS),
    "function": FUNCTIONS,
    "palette": tuple(PALETTES),
    "relation": RELATIONS,
    "symmetry": SYMMETRIES,
}

#: Human-readable vocabulary blocks injected into the LLM prompt.
VOCAB_HINT = "\n".join(
    [
        "lineage: " + ", ".join(f"{k} ({v.name})" for k, v in LINEAGES.items()),
        "material: " + ", ".join(MATERIALS),
        "motif: " + ", ".join(f"{k} ({v.meaning})" for k, v in MOTIFS.items()),
        "form: " + ", ".join(FORMS),
        "function: " + ", ".join(FUNCTIONS),
        "palette: " + ", ".join(PALETTES),
        "relation: " + ", ".join(RELATIONS),
        "symmetry: " + ", ".join(SYMMETRIES),
    ]
)


def signature_material(lineage: str) -> str:
    """The material a lineage always returns to. Deterministic, no RNG."""
    return LINEAGES[lineage].signature_materials[0]


def lineage_entry_index(lineage: str) -> int:
    return LINEAGE_ORDER.index(lineage) if lineage in LINEAGE_ORDER else -1
