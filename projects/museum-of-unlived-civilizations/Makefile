VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
MUSEUM := $(VENV)/bin/museum
ROOT ?= museum-state
ITERATIONS ?= 20
PORT ?= 8000
STATIC_PORT ?= 8090
EXPORT_DIR ?= dist
SCHEDULE ?= 30

.PHONY: help install seed run serve schedule export static test lint format verify graph history demo acceptance reset clean

help:
	@echo "make install                  buat venv + pasang paket (editable + dev)"
	@echo "make seed                     deposit fondasi museum"
	@echo "make run ITERATIONS=20        jalankan siklus kurasi"
	@echo "make serve PORT=8000          katalog web (baca proyeksi)"
	@echo "make export                   ekspor situs statis ke dist/ (siap Netlify)"
	@echo "make static STATIC_PORT=8090  sajikan dist/ tanpa server museum"
	@echo "make schedule SCHEDULE=30     web + kurasi periodik tiap 30 detik"
	@echo "make test | lint | format     kualitas kode"
	@echo "make verify | graph | history status museum"
	@echo "make demo                     seed + 20 iterasi + verify, sekali jalan"
	@echo "make acceptance               buktikan 7 kriteria sukses di state sementara"
	@echo "make reset                    hapus museum-state (destruktif)"

install:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

seed:
	$(MUSEUM) seed --root $(ROOT)

run:
	$(MUSEUM) run --root $(ROOT) --iterations $(ITERATIONS)

serve:
	$(MUSEUM) serve --root $(ROOT) --port $(PORT)

schedule:
	$(MUSEUM) serve --root $(ROOT) --port $(PORT) --schedule $(SCHEDULE)

export:
	$(MUSEUM) export --root $(ROOT) --out $(EXPORT_DIR)

static:
	$(PY) -m http.server --bind 0.0.0.0 --directory $(EXPORT_DIR) $(STATIC_PORT)

test:
	$(PY) -m pytest

lint:
	$(RUFF) check src tests scripts

format:
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

verify:
	$(MUSEUM) verify --root $(ROOT)

graph:
	$(MUSEUM) graph --root $(ROOT)

history:
	$(MUSEUM) history --root $(ROOT) --limit 20

demo: install
	bash scripts/demo.sh

acceptance:
	$(PY) scripts/acceptance.py

reset:
	$(MUSEUM) reset --root $(ROOT) --yes

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
	@echo "state museum tidak dihapus; gunakan 'make reset' bila memang ingin."
