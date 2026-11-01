"""Deterministic, procedural renderer.

No image model, no network, no ``random`` module state: the same artifact always
renders byte-identical SVG. The drawing is a pure function of the artifact's
JSON — form, palette, primary motif, symmetry, density, stratigraphy and the
chronology implied by its references.

Visual grammar
--------------
* the ground is a museum plaque;
* horizontal strata encode the time between the oldest reference and the piece;
* the silhouette comes from ``form``;
* the tessellation inside it comes from ``motif`` + ``symmetry`` + ``density``.
"""

from __future__ import annotations

import hashlib
import math
import random
from html import escape
from pathlib import Path

from .schema import Artifact
from .vocabulary import FORMS, MOTIFS, PALETTES

VIEW_W = 520
VIEW_H = 680

_SCALE = {"kecil": 0.86, "sedang": 1.04, "besar": 1.2}

_BOX = {
    "vessel": (210, 250),
    "tablet": (185, 245),
    "mask": (200, 250),
    "textile": (210, 255),
    "instrument": (175, 285),
    "reliquary": (195, 205),
    "figure": (190, 300),
    "monolith": (155, 330),
    "ring": (205, 205),
    "lamp": (205, 205),
}


def _seed(artifact: Artifact) -> int:
    raw = f"{artifact.id}|{artifact.visual.model_dump_json()}|{artifact.iteration}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)


def _f(value: float) -> str:
    """Compact, stable float formatting."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _silhouette(silhouette: str, cx: float, cy: float, w: float, h: float) -> list[str]:
    """Primitives describing the object's outline (used as fill and as clip)."""
    if silhouette == "vessel":
        return [
            f'<ellipse cx="{_f(cx)}" cy="{_f(cy + h * 0.10)}" rx="{_f(w * 0.50)}" ry="{_f(h * 0.40)}"/>',
            f'<path d="M {_f(cx - w * 0.17)},{_f(cy - h * 0.26)} L {_f(cx - w * 0.23)},{_f(cy - h * 0.48)} '
            f'L {_f(cx + w * 0.23)},{_f(cy - h * 0.48)} L {_f(cx + w * 0.17)},{_f(cy - h * 0.26)} Z"/>',
            f'<ellipse cx="{_f(cx)}" cy="{_f(cy - h * 0.48)}" rx="{_f(w * 0.27)}" ry="{_f(h * 0.055)}"/>',
        ]
    if silhouette == "tablet":
        return [
            f'<path d="M {_f(cx - w * 0.48)},{_f(cy - h * 0.44)} H {_f(cx + w * 0.34)} '
            f"L {_f(cx + w * 0.48)},{_f(cy - h * 0.28)} V {_f(cy + h * 0.46)} "
            f'H {_f(cx - w * 0.48)} Z"/>'
        ]
    if silhouette == "figure":
        return [
            f'<circle cx="{_f(cx)}" cy="{_f(cy - h * 0.30)}" r="{_f(w * 0.21)}"/>',
            f'<path d="M {_f(cx - w * 0.46)},{_f(cy + h * 0.50)} '
            f"C {_f(cx - w * 0.44)},{_f(cy + h * 0.02)} {_f(cx - w * 0.24)},{_f(cy - h * 0.16)} "
            f"{_f(cx)},{_f(cy - h * 0.16)} "
            f"C {_f(cx + w * 0.24)},{_f(cy - h * 0.16)} {_f(cx + w * 0.44)},{_f(cy + h * 0.02)} "
            f'{_f(cx + w * 0.46)},{_f(cy + h * 0.50)} Z"/>',
        ]
    if silhouette == "mask":
        return [
            f'<path d="M {_f(cx)},{_f(cy - h * 0.47)} C {_f(cx + w * 0.46)},{_f(cy - h * 0.46)} '
            f"{_f(cx + w * 0.48)},{_f(cy - h * 0.02)} {_f(cx + w * 0.34)},{_f(cy + h * 0.24)} "
            f"C {_f(cx + w * 0.20)},{_f(cy + h * 0.55)} {_f(cx - w * 0.20)},{_f(cy + h * 0.55)} "
            f"{_f(cx - w * 0.34)},{_f(cy + h * 0.24)} C {_f(cx - w * 0.48)},{_f(cy - h * 0.02)} "
            f'{_f(cx - w * 0.46)},{_f(cy - h * 0.46)} {_f(cx)},{_f(cy - h * 0.47)} Z"/>'
        ]
    if silhouette == "textile":
        return [
            f'<path d="M {_f(cx - w * 0.48)},{_f(cy - h * 0.40)} H {_f(cx + w * 0.48)} '
            f'V {_f(cy + h * 0.42)} H {_f(cx - w * 0.48)} Z"/>'
        ]
    if silhouette == "instrument":
        return [
            f'<g transform="rotate(-17 {_f(cx)} {_f(cy)})">'
            f'<rect x="{_f(cx - w * 0.50)}" y="{_f(cy - h * 0.20)}" width="{_f(w)}" '
            f'height="{_f(h * 0.32)}" rx="{_f(h * 0.16)}"/>'
            f"</g>",
            f'<path d="M {_f(cx + w * 0.16)},{_f(cy + h * 0.20)} L {_f(cx + w * 0.44)},{_f(cy + h * 0.40)} '
            f'L {_f(cx + w * 0.50)},{_f(cy + h * 0.12)} L {_f(cx + w * 0.26)},{_f(cy + h * 0.02)} Z"/>',
        ]
    if silhouette == "reliquary":
        return [
            f'<rect x="{_f(cx - w * 0.44)}" y="{_f(cy - h * 0.10)}" width="{_f(w * 0.88)}" '
            f'height="{_f(h * 0.52)}" rx="{_f(w * 0.04)}"/>',
            f'<path d="M {_f(cx - w * 0.50)},{_f(cy - h * 0.10)} L {_f(cx)},{_f(cy - h * 0.50)} '
            f'L {_f(cx + w * 0.50)},{_f(cy - h * 0.10)} Z"/>',
        ]
    if silhouette == "monolith":
        return [
            f'<path d="M {_f(cx - w * 0.44)},{_f(cy + h * 0.46)} L {_f(cx - w * 0.50)},{_f(cy - h * 0.34)} '
            f"L {_f(cx - w * 0.10)},{_f(cy - h * 0.48)} L {_f(cx + w * 0.36)},{_f(cy - h * 0.38)} "
            f'L {_f(cx + w * 0.50)},{_f(cy + h * 0.46)} Z"/>'
        ]
    if silhouette == "ring":
        return [
            f'<path fill-rule="evenodd" d="M {_f(cx - w * 0.48)},{_f(cy)} '
            f"a {_f(w * 0.48)},{_f(w * 0.48)} 0 1,0 {_f(w * 0.96)},0 "
            f"a {_f(w * 0.48)},{_f(w * 0.48)} 0 1,0 {_f(-w * 0.96)},0 Z "
            f"M {_f(cx - w * 0.28)},{_f(cy)} "
            f"a {_f(w * 0.28)},{_f(w * 0.28)} 0 1,0 {_f(w * 0.56)},0 "
            f'a {_f(w * 0.28)},{_f(w * 0.28)} 0 1,0 {_f(-w * 0.56)},0 Z"/>'
        ]
    # lamp: shallow bowl with a wick flame
    return [
        f'<path d="M {_f(cx - w * 0.48)},{_f(cy - h * 0.04)} Q {_f(cx)},{_f(cy + h * 0.50)} '
        f'{_f(cx + w * 0.48)},{_f(cy - h * 0.04)} Z"/>',
        f'<path d="M {_f(cx)},{_f(cy - h * 0.40)} '
        f"C {_f(cx + w * 0.13)},{_f(cy - h * 0.24)} {_f(cx + w * 0.11)},{_f(cy - h * 0.06)} "
        f"{_f(cx)},{_f(cy - h * 0.06)} "
        f"C {_f(cx - w * 0.11)},{_f(cy - h * 0.06)} {_f(cx - w * 0.13)},{_f(cy - h * 0.24)} "
        f'{_f(cx)},{_f(cy - h * 0.40)} Z"/>',
    ]


def _motif_cell(motif: str, geometry: str, size: float, color: str, width: float) -> str:
    s = size
    stroke = f'fill="none" stroke="{color}" stroke-width="{_f(width)}" stroke-linecap="round"'
    if geometry == "spiral":
        pts = []
        turns = 2.35
        steps = 44
        for i in range(steps + 1):
            t = turns * 2 * math.pi * i / steps
            r = s * (0.05 + 0.33 * i / steps)
            pts.append(f"{_f(r * math.cos(t))},{_f(r * math.sin(t))}")
        return f'<polyline points="{" ".join(pts)}" {stroke}/>'
    if geometry == "ladder":
        rails = (
            f'<path d="M {_f(-s * 0.24)},{_f(-s * 0.38)} V {_f(s * 0.38)} '
            f'M {_f(s * 0.24)},{_f(-s * 0.38)} V {_f(s * 0.38)}" {stroke}/>'
        )
        rungs = "".join(
            f'<path d="M {_f(-s * 0.24)},{_f(y)} H {_f(s * 0.24)}" {stroke}/>'
            for y in (-s * 0.28, -s * 0.14, 0, s * 0.14, s * 0.28)
        )
        return rails + rungs
    if geometry == "eye":
        return (
            f'<path d="M {_f(-s * 0.36)},0 Q 0,{_f(-s * 0.30)} {_f(s * 0.36)},0 '
            f'Q 0,{_f(s * 0.30)} {_f(-s * 0.36)},0 Z" {stroke}/>'
            f'<circle cx="0" cy="0" r="{_f(s * 0.10)}" fill="{color}"/>'
        )
    if geometry == "net":
        lines = []
        for i in (-2, -1, 0, 1, 2):
            lines.append(
                f'<path d="M {_f(-s * 0.40)},{_f(i * s * 0.13)} L 0,{_f(i * s * 0.13 - s * 0.26)} '
                f'L {_f(s * 0.40)},{_f(i * s * 0.13)} L 0,{_f(i * s * 0.13 + s * 0.26)} Z" {stroke}/>'
            )
        return "".join(lines)
    if geometry == "scar":
        return "".join(
            f'<path d="M {_f(-s * 0.30 + k * s * 0.15)},{_f(-s * 0.30)} '
            f'L {_f(-s * 0.22 + k * s * 0.15)},{_f(s * 0.30)}" {stroke}/>'
            for k in range(5)
        )
    if geometry == "ring":
        return "".join(
            f'<circle cx="0" cy="0" r="{_f(s * r)}" {stroke}/>' for r in (0.13, 0.26, 0.39)
        )
    if geometry == "root":
        return (
            f'<path d="M 0,{_f(-s * 0.40)} V {_f(s * 0.20)} '
            f"M 0,{_f(s * 0.02)} L {_f(-s * 0.26)},{_f(s * 0.30)} "
            f"M 0,{_f(s * 0.02)} L {_f(s * 0.26)},{_f(s * 0.30)} "
            f"M 0,{_f(-s * 0.16)} L {_f(-s * 0.24)},{_f(-s * 0.34)} "
            f'M 0,{_f(-s * 0.16)} L {_f(s * 0.24)},{_f(-s * 0.34)}" {stroke}/>'
        )
    # wave
    return "".join(
        f'<path d="M {_f(-s * 0.40)},{_f(y)} '
        f"Q {_f(-s * 0.20)},{_f(y - s * 0.18)} 0,{_f(y)} "
        f'T {_f(s * 0.40)},{_f(y)}" {stroke}/>'
        for y in (-s * 0.22, 0, s * 0.22)
    )


def _tessellation(
    artifact: Artifact, cx: float, cy: float, w: float, h: float, colors: list[str]
) -> str:
    """Tile the primary motif inside the silhouette.

    The grid is deliberately eroded: some cells are dropped and every cell is
    nudged, rotated and scaled by a seeded generator, so the same artifact always
    produces the same worn pattern - and two artifacts never produce the same one.
    """
    visual = artifact.visual
    geometry = MOTIFS[visual.motif].geometry
    rnd = random.Random(_seed(artifact))
    density = visual.density
    cell = 64 - density * 22
    count = int(5 + density * 26)
    width = 0.85 + density * 0.9
    parts: list[str] = []

    def draw(x: float, y: float, rotation: float, color: str, *, wear: bool = True) -> None:
        if wear and rnd.random() < 0.13:
            return  # a lost cell: the object is old
        scale = rnd.uniform(0.84, 1.06)
        jitter = rnd.uniform(-7.0, 7.0) if wear else 0.0
        body = _motif_cell(visual.motif, geometry, cell, color, width * scale)
        parts.append(
            f'<g transform="translate({_f(x)},{_f(y)}) rotate({_f(rotation + jitter)}) '
            f'scale({_f(scale)})">{body}</g>'
        )

    if visual.symmetry == "translation":
        cols = max(2, int(w / cell) + 1)
        rows = max(2, int(h / cell) + 1)
        for r in range(rows):
            for c in range(cols):
                x = cx - w / 2 + (c + 0.5) * (w / cols) + (r % 2) * cell * 0.18
                y = cy - h / 2 + (r + 0.5) * (h / rows)
                draw(x, y, 0.0, colors[(r + c) % len(colors)])
    elif visual.symmetry == "mirror-x":
        half = max(2, int(count / 2))
        for i in range(half):
            x = cx + w * (0.12 + 0.38 * rnd.random())
            y = cy - h * 0.44 + h * 0.88 * (i + 0.5) / half
            color = colors[i % len(colors)]
            draw(x, y, 0.0, color, wear=False)
            draw(2 * cx - x, y, 0.0, color, wear=False)
    elif visual.symmetry == "radial":
        radius = min(w, h) * 0.30
        for i in range(count):
            angle = 2 * math.pi * i / count
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            draw(x, y, math.degrees(angle) + 90, colors[i % len(colors)], wear=False)
        draw(cx, cy, 0.0, colors[0], wear=False)
    else:  # spiral
        for i in range(count):
            t = i / max(1, count - 1)
            angle = t * 3.1 * 2 * math.pi
            radius = (0.06 + 0.40 * t) * min(w, h) * 1.02
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle) * 0.72
            draw(x, y, math.degrees(angle) + 90, colors[i % len(colors)], wear=False)
    return '<g opacity="0.88">' + "".join(parts) + "</g>"


def _detail(
    artifact: Artifact, silhouette: str, cx: float, cy: float, w: float, h: float, ink: str
) -> str:
    stroke = f'fill="none" stroke="{ink}" stroke-width="1.1" opacity="0.55"'
    if silhouette == "figure":
        return (
            f'<path d="M {_f(cx)},{_f(cy - h * 0.16)} V {_f(cy + h * 0.46)}" {stroke}/>'
            f'<path d="M {_f(cx - w * 0.30)},{_f(cy + h * 0.24)} Q {_f(cx)},{_f(cy + h * 0.32)} '
            f'{_f(cx + w * 0.30)},{_f(cy + h * 0.24)}" {stroke}/>'
        )
    if silhouette == "tablet":
        return (
            f'<path d="M {_f(cx - w * 0.30)},{_f(cy - h * 0.26)} l {_f(w * 0.10)},{_f(h * 0.08)} '
            f'l {_f(-w * 0.04)},{_f(h * 0.12)} l {_f(w * 0.12)},{_f(h * 0.07)}" {stroke}/>'
        )
    if silhouette == "textile":
        fringe = "".join(
            f'<path d="M {_f(cx - w * 0.44 + k * w * 0.08)},{_f(cy + h * 0.42)} v {_f(h * 0.05)}" {stroke}/>'
            for k in range(11)
        )
        return fringe + (
            f'<path d="M {_f(cx - w * 0.48)},{_f(cy - h * 0.40)} H {_f(cx + w * 0.48)}" {stroke}/>'
        )
    if silhouette == "instrument":
        return "".join(
            f'<circle cx="{_f(cx - w * 0.30 + k * w * 0.19)}" cy="{_f(cy - h * 0.02 + k * h * 0.035)}" '
            f'r="{_f(w * 0.033)}" fill="{ink}" opacity="0.5"/>'
            for k in range(4)
        )
    if silhouette == "mask":
        return (
            f'<ellipse cx="{_f(cx - w * 0.19)}" cy="{_f(cy - h * 0.10)}" rx="{_f(w * 0.10)}" '
            f'ry="{_f(h * 0.035)}" fill="{ink}" opacity="0.45"/>'
            f'<ellipse cx="{_f(cx + w * 0.19)}" cy="{_f(cy - h * 0.10)}" rx="{_f(w * 0.10)}" '
            f'ry="{_f(h * 0.035)}" fill="{ink}" opacity="0.45"/>'
            f'<path d="M {_f(cx - w * 0.08)},{_f(cy + h * 0.22)} Q {_f(cx)},{_f(cy + h * 0.28)} '
            f'{_f(cx + w * 0.08)},{_f(cy + h * 0.22)}" {stroke}/>'
        )
    if silhouette == "vessel":
        return (
            f'<path d="M {_f(cx - w * 0.23)},{_f(cy - h * 0.44)} H {_f(cx + w * 0.23)}" {stroke}/>'
        )
    if silhouette == "figure":
        return (
            f'<path d="M {_f(cx)},{_f(cy - h * 0.06)} V {_f(cy + h * 0.46)}" {stroke}/>'
            f'<path d="M {_f(cx - w * 0.30)},{_f(cy + h * 0.24)} Q {_f(cx)},{_f(cy + h * 0.32)} '
            f'{_f(cx + w * 0.30)},{_f(cy + h * 0.24)}" {stroke}/>'
        )
    if silhouette == "ring":
        return f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(min(w, h) * 0.36)}" {stroke}/>'
    return ""


def render_svg(artifact: Artifact) -> str:
    visual = artifact.visual
    palette = PALETTES[visual.palette]
    form = FORMS.get(artifact.form)
    silhouette = form.silhouette if form else "tablet"
    scale = _SCALE[form.scale if form else "sedang"]
    bw, bh = _BOX[silhouette]
    bw, bh = bw * scale, bh * scale
    cx, cy = VIEW_W / 2, 320.0

    rnd = random.Random(_seed(artifact) ^ 0x5EED)
    colors = list(palette.accents)

    strata = visual.strata
    top, bottom = 92.0, 600.0
    band_edges = [top + (bottom - top) * (i / strata) ** 0.94 for i in range(strata + 1)]
    bands = []
    for i in range(strata):
        y0, y1 = band_edges[i], band_edges[i + 1]
        color = colors[i % len(colors)]
        opacity = 0.05 + 0.035 * ((i * 7 + int(visual.density * 10)) % 4)
        bands.append(
            f'<rect x="26" y="{_f(y0)}" width="{VIEW_W - 52}" height="{_f(y1 - y0 + 0.6)}" '
            f'fill="{color}" opacity="{_f(opacity)}"/>'
        )
        bands.append(
            f'<path d="M 26,{_f(y0)} H {VIEW_W - 26}" stroke="{palette.ink}" stroke-width="0.5" '
            f'opacity="0.16"/>'
        )

    # grain
    grain = "".join(
        f'<circle cx="{_f(rnd.uniform(20, VIEW_W - 20))}" cy="{_f(rnd.uniform(70, VIEW_H - 70))}" '
        f'r="{_f(rnd.uniform(0.4, 1.5))}" fill="{palette.ink}" opacity="{_f(rnd.uniform(0.03, 0.13))}"/>'
        for _ in range(150)
    )

    clip_id = "form-clip"
    fill_base = f'<g fill="{palette.ink}" opacity="0.10">'
    outline = f'<g fill="none" stroke="{palette.ink}" stroke-width="1.6" opacity="0.72">'
    prims = _silhouette(silhouette, cx, cy, bw, bh)
    silhouette_fill = fill_base + "".join(prims) + "</g>"
    silhouette_stroke = outline + "".join(prims) + "</g>"
    clip_content = "".join(prims)

    tess = _tessellation(artifact, cx, cy, bw, bh, colors)
    hatch_step = 9.0
    hatch = "".join(
        f'<path d="M {_f(cx - bw * 0.7 + k * hatch_step)},{_f(cy + bh * 0.6)} '
        f'l {_f(bh * 1.2)},{_f(-bh * 1.2)}" stroke="{palette.ink}" stroke-width="0.4" '
        f'opacity="0.10"/>'
        for k in range(int(bw * 1.5 / hatch_step) + int(bh * 1.2 / hatch_step) + 2)
    )
    detail = _detail(artifact, silhouette, cx, cy, bw, bh, palette.ink)

    # archaeological layer numbering: the piece sits in the topmost layer
    ticks = []
    layer_labels = []
    for i in range(strata + 1):
        y = band_edges[i]
        ticks.append(
            f'<path d="M 26,{_f(y)} h 8" stroke="{palette.ink}" stroke-width="0.7" opacity="0.35"/>'
        )
    for i in range(strata):
        y = (band_edges[i] + band_edges[i + 1]) / 2 + 3
        layer_labels.append(
            f'<text x="{VIEW_W - 34}" y="{_f(y)}" text-anchor="end" font-size="7.5" '
            f'fill="{palette.ink}" font-family="ui-monospace, monospace" letter-spacing="1.1" '
            f'opacity="0.34">L{strata - i:02d}</text>'
        )

    # the object rests on a plinth: a soft shadow and a hairline base
    plinth_y = cy + bh * 0.5 + 8
    plinth = (
        f'<ellipse cx="{_f(cx)}" cy="{_f(plinth_y)}" rx="{_f(bw * 0.42)}" ry="9" '
        f'fill="{palette.ink}" opacity="0.10"/>'
        f'<path d="M {_f(cx - bw * 0.52)},{_f(plinth_y)} H {_f(cx + bw * 0.52)}" '
        f'stroke="{palette.ink}" stroke-width="0.5" opacity="0.18"/>'
    )

    # registration marks, as on an archival plate
    marks = "".join(
        f'<path d="M {_f(mx - 4)},{_f(my)} H {_f(mx + 4)} M {_f(mx)},{_f(my - 4)} V {_f(my + 4)}" '
        f'stroke="{palette.ink}" stroke-width="0.6" opacity="0.30"/>'
        for mx, my in ((30, 30), (VIEW_W - 30, 30), (30, VIEW_H - 30), (VIEW_W - 30, VIEW_H - 30))
    )

    accession = escape(artifact.id.upper())
    year_text = f"{artifact.year_fictional:04d}"
    motif_label = escape(artifact.visual.motif)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" width="{VIEW_W}" height="{VIEW_H}" role="img" aria-label="{escape(artifact.title)}">
  <defs>
    <linearGradient id="ground" x1="0" y1="0" x2="0.25" y2="1">
      <stop offset="0" stop-color="{palette.ink}" stop-opacity="0.05"/>
      <stop offset="0.45" stop-color="{palette.ink}" stop-opacity="0"/>
      <stop offset="1" stop-color="{palette.ink}" stop-opacity="0.10"/>
    </linearGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.44" r="0.72">
      <stop offset="0.45" stop-color="#000000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000000" stop-opacity="0.34"/>
    </radialGradient>
    <clipPath id="{clip_id}">{clip_content}</clipPath>
  </defs>
  <rect width="{VIEW_W}" height="{VIEW_H}" fill="{palette.ground}"/>
  <rect width="{VIEW_W}" height="{VIEW_H}" fill="url(#ground)"/>
  <g>{"".join(bands)}</g>
  <g>{"".join(ticks)}</g>
  <g>{"".join(layer_labels)}</g>
  {plinth}
  {silhouette_fill}
  <g clip-path="url(#{clip_id})">{hatch}{tess}</g>
  {silhouette_stroke}
  {detail}
  <g>{grain}</g>
  <rect width="{VIEW_W}" height="{VIEW_H}" fill="url(#vignette)"/>
  {marks}
  <rect x="14.5" y="14.5" width="{VIEW_W - 29}" height="{VIEW_H - 29}" fill="none" stroke="{palette.ink}" stroke-width="0.8" opacity="0.28"/>
  <rect x="20.5" y="20.5" width="{VIEW_W - 41}" height="{VIEW_H - 41}" fill="none" stroke="{palette.ink}" stroke-width="0.4" opacity="0.18"/>
  <g fill="{palette.ink}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">
    <text x="28" y="646" font-size="10" letter-spacing="1.4" opacity="0.62">{accession}</text>
    <text x="{VIEW_W - 28}" y="646" font-size="10" text-anchor="end" letter-spacing="1.4" opacity="0.62">{year_text}</text>
    <text x="28" y="70" font-size="8" letter-spacing="2" opacity="0.42">{motif_label.upper()}</text>
    <text x="{VIEW_W - 28}" y="70" font-size="8" text-anchor="end" letter-spacing="2" opacity="0.42">{escape(palette.label.upper())} / {escape(silhouette.upper())}</text>
  </g>
</svg>
"""


def svg_filename(artifact: Artifact) -> str:
    return f"{artifact.id}.svg"


def render_to_file(artifact: Artifact, directory: str | Path) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / svg_filename(artifact)
    svg = render_svg(artifact)
    # write atomically so a crash never leaves a truncated plaque
    tmp = path.with_suffix(".svg.tmp")
    tmp.write_text(svg, encoding="utf-8")
    tmp.replace(path)
    return path
