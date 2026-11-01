"""Ekspor katalog menjadi situs statis yang siap diunggah ke Netlify.

Katalog hanya butuh berkas: satu ``index.html``, aset statis, satu snapshot JSON,
dan plakat SVG. Tidak ada server, tidak ada API, tidak ada SQLite — sehingga
seluruh museum bisa hidup di hosting statis.

Bentuk ekspor sengaja meniru lapisan baca web:

===========================  ==================================================
``data/catalog.json``        payload yang sama dengan ``GET /api/catalog``
``data/artefak/<id>.json``   padanan ``GET /api/artifacts/{id}``
``renders/<id>.svg``         padanan ``GET /api/artifacts/{id}/svg``
===========================  ==================================================

``app.js`` mengenali mode ``static`` lewat ``window.MUSEUM_CONFIG`` yang
disuntikkan ke ``index.html``; dalam mode itu ia membaca snapshot, tidak
melakukan polling, dan menyusun rujukan silang dari katalog yang sudah dimuat.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .render import render_svg
from .schema import Artifact
from .store import MuseumPaths, catalog_payload, load_catalog_payload, utc_now, write_json_atomic

STATIC_DIR = Path(__file__).parent / "web" / "static"
MARKER = ".museum-export"
DEFAULT_OUT = "dist"

ASSETS = ("style.css", "app.js", "icon.svg")


class ExportError(RuntimeError):
    """Ekspor tidak bisa dijalankan dengan state atau tujuan yang diberikan."""


@dataclass(frozen=True)
class ExportReport:
    """Hasil satu ekspor."""

    out: Path
    files: int
    artifacts: int
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "out": str(self.out),
            "files": self.files,
            "artifacts": self.artifacts,
            "bytes": self.bytes,
        }


def _guard_target(out: Path, root: Path, *, force: bool) -> None:
    resolved = out.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if resolved == Path(root).resolve() or resolved == Path(root).resolve().parent:
        raise ExportError(f"tujuan ekspor '{out}' menimpa direktori state/induknya")
    if resolved in forbidden:
        raise ExportError(f"tujuan ekspor '{out}' terlalu berbahaya untuk dihapus")
    if not out.exists():
        return
    if not out.is_dir():
        raise ExportError(f"tujuan ekspor '{out}' ada dan bukan direktori")
    contents = list(out.iterdir())
    if not contents:
        return
    if (out / MARKER).exists():
        return
    if not force:
        raise ExportError(
            f"'{out}' sudah berisi berkas lain. Ulangi dengan --force bila memang ingin menimpanya."
        )


def _layout(out: Path) -> None:
    for relative in ("assets", "data/artefak", "renders"):
        (out / relative).mkdir(parents=True, exist_ok=True)


def _index_html() -> str:
    source = STATIC_DIR / "index.html"
    if not source.exists():
        raise ExportError("template katalog tidak ditemukan di paket museum.web.static")
    html = source.read_text(encoding="utf-8")
    html = html.replace('"/static/', '"./assets/')
    html = html.replace("<!-- MUSEUM_META -->", _head_meta())
    html = html.replace("<!-- MUSEUM_CONFIG -->", _config_script())
    leftovers = [token for token in ('"/static/', "<!-- MUSEUM_", "/api/") if token in html]
    if leftovers:
        raise ExportError(f"template masih menyisakan penanda absolut: {leftovers}")
    return html


def _head_meta() -> str:
    return "\n".join(
        [
            '<link rel="manifest" href="./manifest.webmanifest" />',
            '<meta property="og:type" content="website" />',
            '<meta property="og:title" content="Museum Peradaban yang Tidak Pernah Ada" />',
            '<meta property="og:description" content="Katalog kronologis 24 artefak dari satu kurator tunggal, dirender deterministik dari data." />',
        ]
    )


def _config_script() -> str:
    return (
        "<script>\n"
        "  window.MUSEUM_CONFIG = {\n"
        '    mode: "static",\n'
        '    catalogUrl: "./data/catalog.json",\n'
        '    artifactUrl: (id) => "./data/artefak/" + encodeURIComponent(id) + ".json",\n'
        '    svgUrl: (id) => "./renders/" + encodeURIComponent(id) + ".svg",\n'
        "    pollMs: 0\n"
        "  };\n"
        "</script>"
    )


def _target(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    keys = ("id", "title", "year_fictional", "lineage", "form", "function")
    return {key: artifact.get(key) for key in keys}


def artifact_detail(payload: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    """Padanan bentuk JSON ``GET /api/artifacts/{id}``."""
    by_id = {a["id"]: a for a in payload.get("artifacts", [])}
    artifact = by_id.get(artifact_id)
    if artifact is None:
        raise ExportError(f"artefak '{artifact_id}' tidak ada di payload")
    outgoing = [
        {
            "id": ref["id"],
            "relation": ref.get("relation"),
            "note": ref.get("note"),
            "target": _target(by_id.get(ref["id"])),
        }
        for ref in artifact.get("refs", [])
    ]
    incoming = [
        {
            "id": other["id"],
            "title": other.get("title"),
            "year": other.get("year_fictional"),
            "relation": ref.get("relation"),
            "note": ref.get("note"),
        }
        for other in payload.get("artifacts", [])
        for ref in other.get("refs", [])
        if ref.get("id") == artifact_id
    ]
    return {
        "artifact": artifact,
        "refs": outgoing,
        "cited_by": incoming,
        "svg_url": f"./renders/{artifact_id}.svg",
    }


def _manifest(title: str) -> dict[str, Any]:
    return {
        "name": title,
        "short_name": "Museum",
        "description": (
            "Katalog kronologis artefak dari sejarah material yang dibangun "
            "satu agen kurator LangGraph."
        ),
        "lang": "id",
        "dir": "ltr",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#08080a",
        "theme_color": "#08080a",
        "categories": ["education", "books"],
        "icons": [
            {
                "src": "./assets/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            },
            {
                "src": "./assets/icon.svg",
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "maskable",
            },
        ],
    }


NETLIFY_TOML = """\
# Ikut terunggah bersama situs. Netlify membacanya bila folder ini dipakai
# sebagai root proyek (drag & drop folder, atau `netlify deploy --dir=.`).

[build]
  publish = "."

[[redirects]]
  from = "/katalog"
  to = "/"
  status = 301

[[headers]]
  for = "/*"
  [headers.values]
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"
    Permissions-Policy = "geolocation=(), microphone=(), camera=()"

[[headers]]
  for = "/assets/*"
  [headers.values]
    Cache-Control = "public, max-age=3600"

[[headers]]
  for = "/data/*"
  [headers.values]
    Cache-Control = "public, max-age=60, must-revalidate"

[[headers]]
  for = "/renders/*"
  [headers.values]
    Cache-Control = "public, max-age=86400"
"""

HEADERS_FILE = """\
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  Cache-Control: public, max-age=0, must-revalidate

/assets/*
  Cache-Control: public, max-age=3600

/data/*
  Cache-Control: public, max-age=60, must-revalidate

/renders/*
  Cache-Control: public, max-age=86400
"""

ROBOTS_TXT = "User-agent: *\nAllow: /\n"

NOT_FOUND_HTML = """\
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Tidak ditemukan — Museum Peradaban yang Tidak Pernah Ada</title>
<meta name="theme-color" content="#08080a" />
<style>
  html, body { margin: 0; height: 100%; background: #08080a; color: #ece7db; }
  body {
    display: grid;
    place-items: center;
    padding: 24px;
    font-family: "Iowan Old Style", Palatino, Georgia, serif;
    text-align: center;
  }
  p.eyebrow {
    margin: 0 0 10px;
    color: #c8a24a;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
  }
  h1 { margin: 0 0 12px; font-size: clamp(26px, 7vw, 38px); font-weight: 500; }
  p.deck { margin: 0 0 22px; max-width: 34ch; color: #8b8578; font-size: 15px; line-height: 1.6; }
  a {
    display: inline-block;
    min-height: 44px;
    padding: 12px 22px;
    border: 1px solid rgba(236, 231, 219, 0.22);
    border-radius: 999px;
    color: #ece7db;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 11px;
    letter-spacing: 0.16em;
    text-decoration: none;
    text-transform: uppercase;
  }
</style>
</head>
<body>
  <main>
    <p class="eyebrow">404 / galeri kosong</p>
    <h1>Ruang ini tidak ada dalam denah.</h1>
    <p class="deck">Artefak yang Anda cari tidak pernah diaksesikan. Kembali ke katalog untuk melihat kronologi yang benar-benar dibangun kurator.</p>
    <a href="./">Kembali ke katalog</a>
  </main>
</body>
</html>
"""

DEPLOY_README = """\
# Museum — folder siap unggah

Folder ini adalah ekspor statis dari katalog museum. Tidak ada server, basis data,
maupun kunci API di dalamnya: hanya HTML, CSS, JavaScript, JSON, dan plakat SVG.

## Cara tercepat: Netlify Drop

1. Buka <https://app.netlify.com/drop>.
2. Seret **folder ini** (`dist/`) ke jendela peramban.
3. Selesai — Netlify memberi URL `*.netlify.app` dalam beberapa detik.

## Netlify CLI

```bash
npm i -g netlify-cli
netlify deploy --dir=dist            # pratinjau
netlify deploy --dir=dist --prod     # produksi
```

## Hosting statis lain

Folder ini juga jalan di GitHub Pages, Cloudflare Pages, Vercel (static), S3,
atau `python3 -m http.server -d dist`. Tidak ada routing sisi server yang
dibutuhkan: seluruh navigasi memakai hash (`#/artefak/<id>`), jadi tautan dalam
tetap bisa dibagikan tanpa aturan rewrite.

## Isi folder

| Berkas | Isi |
| --- | --- |
| `index.html` | katalog; `window.MUSEUM_CONFIG` menandainya sebagai mode statis |
| `assets/` | `style.css`, `app.js`, `icon.svg` |
| `data/catalog.json` | snapshot katalog (padanan `GET /api/catalog`) |
| `data/artefak/<id>.json` | detail per artefak (padanan `GET /api/artifacts/{id}`) |
| `renders/<id>.svg` | plakat deterministik per artefak |
| `manifest.webmanifest` | metadata PWA (bisa dipasang ke layar utama) |
| `_headers`, `netlify.toml` | cache + header keamanan untuk Netlify |

## Memperbarui

```bash
make run ITERATIONS=1     # satu aksesi baru
make export               # tulis ulang dist/
```

Unggah ulang folder `dist/` (atau `netlify deploy --dir=dist --prod`).
Mode statis sengaja tidak melakukan polling: snapshot tidak bisa berubah di
tengah jalan, jadi tidak ada permintaan berulang ke hosting.
"""


def export_site(
    root: str | Path = "museum-state",
    out: str | Path = DEFAULT_OUT,
    *,
    payload: dict[str, Any] | None = None,
    allow_empty: bool = False,
    force: bool = False,
) -> ExportReport:
    """Tulis situs statis lengkap ke ``out`` dan kembalikan ringkasannya."""
    paths = MuseumPaths.create(root)
    data = payload if payload is not None else load_catalog_payload(paths)
    artifacts_raw = list((data or {}).get("artifacts") or [])

    if not artifacts_raw:
        if not allow_empty:
            raise ExportError(
                "katalog masih kosong — jalankan `museum seed` lalu `museum run --iterations 20`"
            )
        data = catalog_payload([], iteration=0, status="belum-dimulai")

    assert data is not None
    artifacts = [Artifact.model_validate(item) for item in artifacts_raw]

    target = Path(out).expanduser()
    _guard_target(target, Path(root), force=force)
    if target.exists():
        shutil.rmtree(target)
    _layout(target)

    written: list[Path] = []

    def emit(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)

    def emit_json(path: Path, value: Any) -> None:
        write_json_atomic(path, value)
        written.append(path)

    for asset in ASSETS:
        source = STATIC_DIR / asset
        if not source.exists():
            raise ExportError(f"aset katalog hilang: {source.name}")
        destination = target / "assets" / asset
        shutil.copyfile(source, destination)
        written.append(destination)

    emit(target / "index.html", _index_html())
    emit_json(target / "data" / "catalog.json", data)
    emit_json(target / "data" / "graph.json", data.get("graph", {"nodes": [], "edges": []}))

    for artifact in artifacts:
        emit_json(
            target / "data" / "artefak" / f"{artifact.id}.json", artifact_detail(data, artifact.id)
        )
        emit(target / "renders" / f"{artifact.id}.svg", render_svg(artifact))

    title = data.get("museum") or "Museum Peradaban yang Tidak Pernah Ada"
    emit_json(target / "manifest.webmanifest", _manifest(title))
    emit(target / "404.html", NOT_FOUND_HTML)
    emit(target / "robots.txt", ROBOTS_TXT)
    emit(target / "_headers", HEADERS_FILE)
    emit(target / "netlify.toml", NETLIFY_TOML)
    emit(target / "BACA-INI.md", DEPLOY_README)
    emit_json(
        target / MARKER,
        {
            "generator": "museum export",
            "exported_at": utc_now(),
            "artifacts": len(artifacts),
            "iteration": data.get("iteration"),
        },
    )

    total = sum(path.stat().st_size for path in written)
    return ExportReport(
        out=target.resolve(), files=len(written), artifacts=len(artifacts), bytes=total
    )
