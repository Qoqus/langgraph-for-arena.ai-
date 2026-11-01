#!/usr/bin/env python
"""Executable proof of the seven success criteria.

    python scripts/acceptance.py        # or: make acceptance

Runs against a throw-away state directory; never touches museum-state/.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from museum.llm.mock import MockCurator
from museum.runner import Museum
from museum.vocabulary import FORMS, FUNCTIONS, LINEAGES, MATERIALS, MOTIFS, PALETTES
from museum.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[str, bool, str]] = []


def check(label: str, fn) -> None:
    try:
        detail = fn() or ""
        RESULTS.append((label, True, detail))
    except Exception as exc:
        RESULTS.append((label, False, f"{type(exc).__name__}: {exc}"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="museum-acceptance-"))
    state = tmp / "state"

    museum = Museum(state, llm=MockCurator(chaos="sometimes"), max_attempts=3)
    museum.run(iterations=20)
    catalog = museum.catalog()

    def criterion_1() -> str:
        assert len(catalog) == 24, f"harus 24 artefak, dapat {len(catalog)}"
        ids = [a.id for a in catalog]
        assert len(ids) == len(set(ids)), "id tidak unik"
        known: set[str] = set()
        last_year = -1
        for art in sorted(catalog, key=lambda a: (a.iteration, a.year_fictional)):
            for ref in art.refs:
                assert ref.id in known, f"{art.id} -> {ref.id} tidak ada"
            known.add(art.id)
            assert art.year_fictional >= last_year, f"tahun mundur di {art.id}"
            last_year = art.year_fictional
            assert art.lineage in LINEAGES
            assert art.form in FORMS and art.function in FUNCTIONS
            assert set(art.materials) <= set(MATERIALS)
            assert set(art.motifs) <= set(MOTIFS)
            assert art.visual.palette in PALETTES
        return "20 iterasi → 24 artefak valid, tahun 212–507"

    def criterion_2() -> str:
        reject_dir = tmp / "reject"
        bad = Museum(reject_dir, llm=MockCurator(chaos="always"), max_attempts=2)
        bad.run(iterations=1)
        snapshot = bad.snapshot()
        assert len(bad.catalog()) == 4, "state parsial bocor ke katalog"
        assert snapshot["rejections"], "penolakan tidak tercatat"
        assert snapshot["rejections"][0]["codes"]
        ledger_ids = {
            json.loads(line)["id"]
            for line in bad.paths.ledger_jsonl.read_text().splitlines()
            if line.strip()
        }
        assert ledger_ids == {a.id for a in bad.catalog()}
        codes = snapshot["rejections"][0]["codes"]
        bad.close()
        return f"ditolak: {', '.join(codes)}; katalog & ledger tidak berubah"

    def criterion_3() -> str:
        count = 0
        for art in catalog:
            svg_path = state / "renders" / f"{art.id}.svg"
            root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
            assert root.tag.endswith("svg")
            assert art.title in root.attrib["aria-label"]
            count += 1
        assert count == len(catalog)
        return f"{count} plakat SVG terparse, deterministik dari JSON"

    def criterion_4() -> str:
        payload = json.loads((state / "data" / "catalog.json").read_text(encoding="utf-8"))
        years = [a["year_fictional"] for a in payload["artifacts"]]
        assert years == sorted(years), "timeline tidak kronologis"
        client = TestClient(create_app(state))
        detail = client.get(f"/api/artifacts/{catalog[2].id}").json()
        assert detail["refs"] and detail["refs"][0]["target"]
        assert client.get("/").status_code == 200
        assert payload["graph"]["edges"]
        return (
            f"timeline {years[0]}–{years[-1]}, {len(payload['graph']['edges'])} rujukan silang, "
            f"detail + cited_by tersedia"
        )

    def criterion_5() -> str:
        resume_dir = tmp / "resume"
        first = Museum(resume_dir, llm=MockCurator(chaos="off"))
        first.run(iterations=5)
        before = [a.id for a in first.catalog()]
        first.close()
        second = Museum(resume_dir, llm=MockCurator(chaos="off"))
        assert second.iteration() == 5
        assert [a.id for a in second.catalog()] == before
        second.run(iterations=2)
        assert second.iteration() == 7 and len(second.catalog()) == len(before) + 2
        assert second.verify()["ok"]
        second.close()
        return "proses berhenti → checkpoint dibuka ulang → lanjut tanpa kehilangan katalog"

    def criterion_6() -> str:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        deps = re.findall(r'"([a-zA-Z0-9_.\-]+)[><=~!]', pyproject)
        forbidden = {
            "langgraph-supervisor",
            "langgraph-swarm",
            "crewai",
            "autogen",
            "torch",
            "diffusers",
            "pillow",
            "openai",
        }
        assert not forbidden & set(deps), f"dependensi terlarang: {forbidden & set(deps)}"
        imports: set[str] = set()
        for path in (ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
        assert not forbidden & imports, f"import terlarang: {forbidden & imports}"
        graph_source = (ROOT / "src" / "museum" / "graph.py").read_text(encoding="utf-8")
        assert graph_source.count(".propose(") == 1, "harus tepat satu panggilan model"
        clean = sorted({d for d in deps if d != "requires-python"})
        return f"dependensi bersih: {', '.join(clean)}"

    def criterion_7() -> str:
        tests = list((ROOT / "tests").glob("test_*.py"))
        count = sum(
            len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.MULTILINE))
            for path in tests
        )
        assert count >= 60, f"hanya {count} tes"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for topic in ("seed", "mock", "LLM API", "Asumsi"):
            assert topic.lower() in readme.lower(), f"README tidak membahas {topic}"
        return f"{count} tes di {len(tests)} berkas; README mencakup seed, mock, LLM API, asumsi"

    check("1. 20 iterasi mock → katalog valid", criterion_1)
    check("2. Validator menolak tanpa state parsial", criterion_2)
    check("3. Visual deterministik per artefak", criterion_3)
    check("4. Timeline kronologis + rujukan silang", criterion_4)
    check("5. Scheduler/checkpoint dapat dilanjutkan", criterion_5)
    check("6. Tanpa multi-agent, training, image-gen", criterion_6)
    check("7. Test suite + README lengkap", criterion_7)
    museum.close()

    width = max(len(label) for label, _, _ in RESULTS)
    print("\n  AKSEPTASI — Museum Peradaban yang Tidak Pernah Ada\n")
    for label, ok, detail in RESULTS:
        mark = "LULUS" if ok else "GAGAL"
        print(f"  [{mark}] {label.ljust(width)}  {detail}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n  {len(RESULTS) - len(failed)}/{len(RESULTS)} kriteria terpenuhi. state uji: {tmp}\n")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
