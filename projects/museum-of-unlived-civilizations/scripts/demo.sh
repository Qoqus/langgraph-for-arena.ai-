#!/usr/bin/env bash
# Demo end-to-end: seed, 20 iterasi, verifikasi, dan ringkasan katalog.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="${MUSEUM_HOME:-museum-state}"
MUSEUM=".venv/bin/museum"

if [[ ! -x "$MUSEUM" ]]; then
  echo "jalankan 'make install' dulu (atau python3 -m venv .venv && .venv/bin/pip install -e \".[dev]\")"
  exit 1
fi

echo "== reset state =="
"$MUSEUM" reset --root "$ROOT" --yes >/dev/null 2>&1 || true

echo
echo "== seed: deposit fondasi =="
"$MUSEUM" seed --root "$ROOT"

echo
echo "== 20 iterasi kurasi (mock: chaos sometimes) =="
"$MUSEUM" run --root "$ROOT" --iterations 20 | sed -e 's/^/  /'

echo
echo "== verifikasi invarian =="
"$MUSEUM" verify --root "$ROOT"

echo
echo "== status =="
"$MUSEUM" status --root "$ROOT"

echo
echo "== selesai =="
echo "katalog web : make serve ROOT=$ROOT"
echo "detail satu artefak: museum-state/data/catalog.json"
echo "plakat SVG  : museum-state/renders/"
