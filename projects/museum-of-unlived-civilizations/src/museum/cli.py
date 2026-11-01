"""Command line entry point for the museum."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from .export import DEFAULT_OUT, ExportError, export_site
from .llm import load_curator
from .render import render_to_file
from .runner import Museum, MuseumError, MuseumPaused, Scheduler
from .store import MuseumPaths

DEFAULT_ROOT = Path(os.environ.get("MUSEUM_HOME", "museum-state"))


def _default_llm_spec() -> str:
    return os.environ.get("MUSEUM_LLM", "mock")


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llm",
        default=_default_llm_spec(),
        help="'mock' atau 'openai:<model>' (default: env MUSEUM_LLM atau mock)",
    )
    parser.add_argument(
        "--chaos",
        choices=("off", "sometimes", "always"),
        default="sometimes",
        help="seberapa sering mock sengaja melanggar aturan (default: sometimes)",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=3, help="anggaran perbaikan per iterasi"
    )
    parser.add_argument(
        "--review", action="store_true", help="aktifkan interrupt human-in-the-loop"
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="direktori state museum")
    parser.add_argument("--thread", default="museum-main", help="thread_id checkpointer")


def _make_museum(args: argparse.Namespace) -> Museum:
    spec = args.llm
    kwargs: dict[str, Any] = {}
    if spec == "mock" or spec.startswith("mock:"):
        kwargs["chaos"] = args.chaos
    llm = load_curator(spec, **kwargs)
    return Museum(
        args.root,
        llm=llm,
        thread_id=args.thread,
        max_attempts=args.max_attempts,
        human_review=args.review,
    )


def _printer(prefix: str = "  ") -> Any:
    def on_update(node: str, update: dict[str, Any]) -> None:
        for line in (update.get("log") or [])[-1:]:
            print(f"{prefix}{node:<15} {line}")

    return on_update


def _print_run_summary(museum: Museum) -> None:
    snapshot = museum.snapshot()
    catalog = museum.catalog()
    print(
        f"\niterasi {snapshot.get('iteration', 0)} · {len(catalog)} artefak · "
        f"{len(snapshot.get('rejections') or [])} penolakan"
    )
    if museum.pending_interrupt():
        print("  ⏸  menunggu keputusan manusia: museum review --decision approve")


def cmd_seed(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        museum.ensure_seeded()
        snapshot = museum.snapshot()
        print(
            f"seed selesai · {len(museum.catalog())} artefak fondasi · "
            f"iterasi {snapshot.get('iteration', 0)}"
        )
        print(f"state: {museum.paths.root}")
        for art in museum.catalog():
            print(f"  {art.year_fictional}  {art.id:<32} {art.title}")
    finally:
        museum.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        if args.interval and args.interval > 0:
            scheduler = Scheduler(
                museum,
                interval_seconds=args.interval,
                iterations_per_tick=1,
                max_iterations=(museum.iteration() + args.iterations) if args.iterations else None,
                on_tick=lambda tick, _state: print(f"  tick {tick:03d} selesai"),
                logger=lambda msg: print(f"  {msg}"),
            )
            print(
                f"scheduler: tiap {args.interval:g}s, batas {museum.iteration() + args.iterations} iterasi"
            )
            try:
                scheduler.run_forever()
            except KeyboardInterrupt:
                scheduler.stop()
                print("\nscheduler dihentikan; state tersimpan di checkpoint")
        else:
            museum.run(
                iterations=args.iterations,
                target=args.target,
                on_update=_printer(),
            )
        _print_run_summary(museum)
    finally:
        museum.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    _make_museum(args).close()  # ensures directories + schema exist
    import uvicorn

    from .web.app import create_app

    scheduler: Scheduler | None = None
    if args.schedule:
        museum = _make_museum(args)
        budget = museum.iteration() + args.iterations if args.iterations else None
        scheduler = Scheduler(
            museum,
            interval_seconds=args.schedule,
            max_iterations=budget,
            on_tick=lambda tick, state: print(
                f"scheduler tick {tick}: iterasi {state.get('iteration')} · "
                f"{len(state.get('catalog') or [])} artefak"
            ),
        )

        def loop() -> None:
            try:
                scheduler.run_forever()
            except Exception as exc:
                print(f"scheduler berhenti: {exc}")

        threading.Thread(target=loop, name="museum-scheduler", daemon=True).start()

    app = create_app(args.root)
    print(f"katalog: http://{args.host}:{args.port}  (state: {args.root})")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    finally:
        if scheduler:
            scheduler.stop()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        snapshot = museum.snapshot()
        catalog = museum.catalog()
        if not snapshot:
            print("belum ada checkpoint. jalankan: museum seed")
            return 1
        print(f"state       : {museum.paths.root}")
        print(f"thread      : {museum.thread_id}")
        print(f"iterasi     : {snapshot.get('iteration', 0)}")
        print(f"status      : {snapshot.get('status')}")
        print(f"artefak     : {len(catalog)}")
        print(f"penolakan   : {len(snapshot.get('rejections') or [])}")
        print(f"llm         : {getattr(museum.llm, 'name', '?')}")
        pending = museum.pending_interrupt()
        print(f"interrupt   : {pending['node'] if pending else '-'}")
        print(f"langkah next: {list(museum.graph.get_state(museum.config).next or ())}")
        if catalog:
            first, last = catalog[0], catalog[-1]
            print(f"rentang     : {first.year_fictional} – {last.year_fictional}")
            print("\n5 aksesi terakhir:")
            for art in sorted(catalog, key=lambda a: (a.year_fictional, a.iteration))[-5:]:
                print(
                    f"  {art.year_fictional}  {art.id:<32} "
                    f"{art.lineage:<8} {art.title}  ({len(art.refs)} rujukan)"
                )
        report = museum.verify()
        print(f"integritas  : {'OK' if report['ok'] else 'MASALAH'}")
        for problem in report["problems"]:
            print(f"  ! {problem}")
        return 0 if report["ok"] else 2
    finally:
        museum.close()


def cmd_verify(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        report = museum.verify()
        print(json.dumps({k: v for k, v in report.items() if k != "problems"}, ensure_ascii=False))
        if report["ok"]:
            print("katalog valid: id unik, rujukan utuh, tahun tidak mundur, kosakata terkontrol")
            return 0
        for problem in report["problems"]:
            print(f"  ! {problem}")
        return 2
    finally:
        museum.close()


def cmd_rebuild(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        result = museum.rebuild()
        print(
            f"proyeksi dibangun ulang: {result['artifacts']} artefak, {result['rendered']} plakat"
        )
        print(f"  {result['path']}")
    finally:
        museum.close()
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        count = 0
        for art in museum.catalog():
            path = render_to_file(art, museum.paths.renders)
            count += 1
            print(f"  {path.name}")
        print(f"{count} plakat deterministik ditulis ke {museum.paths.renders}")
    finally:
        museum.close()
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        drawing = museum.graph.get_graph()
        mermaid = drawing.draw_mermaid()
        if args.output:
            Path(args.output).write_text(mermaid, encoding="utf-8")
            print(f"mermaid ditulis ke {args.output}")
        else:
            print(mermaid)
    finally:
        museum.close()
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        rows = museum.history(limit=args.limit)
        print(f"{len(rows)} checkpoint (terbaru dulu)")
        for row in rows:
            print(
                f"  {str(row['created_at'])[:19]:<20} iter {row['iteration']!s:<4} "
                f"{row['status']!s:<18} next={','.join(row['next']) or '-'} "
                f"artefak={row['artifacts']} draf={row['pending_draft'] or '-'}"
            )
            print(f"    checkpoint_id={row['checkpoint_id']}")
    finally:
        museum.close()
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        pending = museum.pending_interrupt()
        if pending is None:
            print("tidak ada interrupt yang menunggu")
            return 1
        value = pending.get("value") or {}
        print(json.dumps(value, ensure_ascii=False, indent=2)[:4000])
        if args.decision is None:
            return 0
        decision: dict[str, Any] = {"decision": args.decision, "note": args.note}
        if args.decision == "edit":
            if not args.file:
                print("--decision edit membutuhkan --file <artefak.json>")
                return 2
            decision["artifact"] = json.loads(Path(args.file).read_text(encoding="utf-8"))
        museum.resume(decision)
        print(f"keputusan '{args.decision}' diterapkan")
        _print_run_summary(museum)
        if args.continue_iterations:
            museum.run(iterations=args.continue_iterations, on_update=_printer())
            _print_run_summary(museum)
        return 0
    except MuseumPaused as exc:
        print(f"museum berhenti: {exc}")
        return 1
    finally:
        museum.close()


def cmd_export(args: argparse.Namespace) -> int:
    museum = _make_museum(args)
    try:
        report = museum.verify()
        if not report["ok"]:
            print("katalog tidak valid; ekspor dibatalkan")
            for problem in report["problems"]:
                print(f"  ! {problem}")
            return 2
        if not museum.catalog() and not args.allow_empty:
            print("katalog kosong — jalankan `museum seed` lalu `museum run --iterations 20`")
            print("  (atau ekspor katalog kosong dengan --allow-empty)")
            return 1
        if museum.has_checkpoint():
            rebuilt = museum.rebuild()
            print(
                f"proyeksi disegarkan: {rebuilt['artifacts']} artefak, {rebuilt['rendered']} plakat"
            )
        result = export_site(args.root, args.out, force=args.force, allow_empty=args.allow_empty)
        print(f"situs statis siap: {result.out}")
        print(
            f"  {result.files} berkas · {result.artifacts} artefak · {result.bytes / 1024:.0f} kB"
        )
        print("  unggah folder itu ke https://app.netlify.com/drop")
        print(f"  atau: netlify deploy --dir={args.out} --prod")
        return 0
    except ExportError as exc:
        print(f"ekspor gagal: {exc}")
        return 2
    finally:
        museum.close()


def cmd_reset(args: argparse.Namespace) -> int:
    paths = MuseumPaths.create(args.root)
    if not paths.root.exists():
        print("tidak ada state untuk dihapus")
        return 0
    if not args.yes:
        print(f"ini akan menghapus {paths.root}. ulangi dengan --yes")
        return 2
    shutil.rmtree(paths.root)
    print(f"dihapus: {paths.root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="museum",
        description="Museum Peradaban yang Tidak Pernah Ada — satu kurator, satu katalog, satu artefak per iterasi.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="tulis deposit fondasi ke checkpoint")
    _add_llm_args(seed)
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("run", help="jalankan siklus kurasi")
    _add_llm_args(run)
    run.add_argument("--iterations", type=int, default=1, help="jumlah iterasi (default: 1)")
    run.add_argument("--target", type=int, default=None, help="iterasi tujuan absolut")
    run.add_argument(
        "--interval", type=float, default=None, help="detik antar iterasi (mode scheduler)"
    )
    run.set_defaults(func=cmd_run)

    serve = sub.add_parser("serve", help="jalankan katalog web")
    _add_llm_args(serve)
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--schedule", type=float, default=None, help="detik antar iterasi otomatis")
    serve.add_argument(
        "--iterations", type=int, default=0, help="batas iterasi tambahan untuk scheduler"
    )
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    status = sub.add_parser("status", help="ringkasan state + pemeriksaan integritas")
    _add_llm_args(status)
    status.set_defaults(func=cmd_status)

    verify = sub.add_parser("verify", help="verifikasi seluruh invarian katalog")
    _add_llm_args(verify)
    verify.set_defaults(func=cmd_verify)

    rebuild = sub.add_parser("rebuild", help="bangun ulang proyeksi + render dari checkpoint")
    _add_llm_args(rebuild)
    rebuild.set_defaults(func=cmd_rebuild)

    render = sub.add_parser("render", help="render semua plakat SVG")
    _add_llm_args(render)
    render.set_defaults(func=cmd_render)

    graph = sub.add_parser("graph", help="cetak graf kurasi sebagai mermaid")
    _add_llm_args(graph)
    graph.add_argument("--output", default=None)
    graph.set_defaults(func=cmd_graph)

    history = sub.add_parser("history", help="lihat checkpoint (time travel)")
    _add_llm_args(history)
    history.add_argument("--limit", type=int, default=12)
    history.set_defaults(func=cmd_history)

    review = sub.add_parser("review", help="lihat/selesaikan interrupt human-in-the-loop")
    _add_llm_args(review)
    review.add_argument("--decision", choices=("approve", "reject", "edit"), default=None)
    review.add_argument("--file", default=None, help="JSON artefak untuk --decision edit")
    review.add_argument("--note", default=None)
    review.add_argument("--continue-iterations", type=int, default=0)
    review.set_defaults(func=cmd_review)

    export = sub.add_parser("export", help="ekspor katalog jadi situs statis (Netlify)")
    _add_llm_args(export)
    export.add_argument(
        "--out", default=DEFAULT_OUT, help=f"direktori keluaran (default: {DEFAULT_OUT})"
    )
    export.add_argument(
        "--force", action="store_true", help="timpa direktori tujuan yang bukan hasil ekspor"
    )
    export.add_argument(
        "--allow-empty", action="store_true", help="izinkan ekspor saat katalog masih kosong"
    )
    export.set_defaults(func=cmd_export)

    reset = sub.add_parser("reset", help="hapus state museum")
    reset.add_argument("--root", default=str(DEFAULT_ROOT))
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except MuseumError as exc:
        print(f"museum: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ndihentikan; state aman di checkpoint", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
