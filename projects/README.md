# Projects

Eksplorasi konsep yang dibangun di atas LangGraph, disimpan di dalam checkout monorepo
tetapi **berdiri sendiri** (masing-masing punya `pyproject.toml` dan test suite sendiri;
tidak ada dependensi yang ditambahkan ke library di `libs/`).

| Proyek | Konsep |
|---|---|
| [`museum-of-unlived-civilizations`](./museum-of-unlived-civilizations) | Satu agen kurator tunggal yang membangun sejarah material fiktif secara akumulatif: satu artefak baru per iterasi, dengan `StateGraph` siklik, validasi deterministik, dan persistence `SqliteSaver`. Mulai dari [README-nya](./museum-of-unlived-civilizations/README.md). |

```bash
cd museum-of-unlived-civilizations
make install && make demo && make serve
```
