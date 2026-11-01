"""Runtime around the graph: seeding, bounded runs, resume, verification.

The checkpoint (SQLite) is the source of truth. Everything else - ``catalog.json``,
``ledger.jsonl``, ``renders/*.svg`` - is a projection that can be rebuilt from it.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .graph import (
    DEFAULT_THREAD,
    MuseumDeps,
    build_graph,
    state_catalog,
    thread_config,
)
from .llm import CuratorLLM, load_curator
from .render import render_to_file
from .schema import Artifact
from .seed import SEED_ARTIFACTS
from .store import (
    MuseumPaths,
    append_ledger,
    project,
    read_ledger,
    utc_now,
)
from .validator import verify_catalog


class MuseumError(RuntimeError):
    pass


class MuseumPaused(MuseumError):
    """The graph is waiting for a human decision."""


class Museum:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        llm: CuratorLLM | None = None,
        llm_spec: str | None = None,
        thread_id: str = DEFAULT_THREAD,
        max_attempts: int = 3,
        human_review: bool = False,
        render: bool = True,
        seed: bool = True,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.paths = MuseumPaths.create(root).ensure()
        self.thread_id = thread_id
        self.llm = llm or load_curator(llm_spec)
        self.seed_enabled = seed
        self._conn = sqlite3.connect(self.paths.db, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._saver = SqliteSaver(self._conn)
        self._saver.setup()
        self.deps = MuseumDeps(
            llm=self.llm,
            paths=self.paths,
            thread_id=thread_id,
            max_attempts=max_attempts,
            human_review=human_review,
            render=render,
            clock=clock,
        )
        self.graph = build_graph(self.deps, self._saver)
        self.config = thread_config(thread_id, recursion_limit=400)

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> Museum:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- state --------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        return dict(self.graph.get_state(self.config).values or {})

    def catalog(self) -> list[Artifact]:
        return state_catalog(self.snapshot())

    def iteration(self) -> int:
        return int(self.snapshot().get("iteration", 0) or 0)

    def has_checkpoint(self) -> bool:
        return bool(self.snapshot())

    def pending_interrupt(self) -> dict[str, Any] | None:
        snapshot = self.graph.get_state(self.config)
        for task in getattr(snapshot, "tasks", ()) or ():
            for item in getattr(task, "interrupts", ()) or ():
                return {
                    "value": item.value,
                    "id": getattr(item, "id", None),
                    "node": getattr(task, "name", None),
                }
        return None

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for snap in self.graph.get_state_history(self.config, limit=limit):
            values = snap.values or {}
            rows.append(
                {
                    "checkpoint_id": snap.config.get("configurable", {}).get("checkpoint_id"),
                    "created_at": snap.created_at,
                    "next": list(snap.next or ()),
                    "iteration": values.get("iteration"),
                    "status": values.get("status"),
                    "artifacts": len(values.get("catalog") or []),
                    "pending_draft": ((values.get("pending_draft") or {}).get("parsed") or {}).get(
                        "id"
                    ),
                }
            )
        return rows

    # -- seeding ------------------------------------------------------------
    def ensure_seeded(self) -> None:
        if self.has_checkpoint() or not self.seed_enabled:
            return
        seed_catalog = [a.canonical() for a in SEED_ARTIFACTS]
        append_ledger(self.paths, SEED_ARTIFACTS)
        for artifact in SEED_ARTIFACTS:
            render_to_file(artifact, self.paths.renders)
        project(
            self.paths,
            list(SEED_ARTIFACTS),
            iteration=0,
            status="seeded",
            llm="seed/founding-deposit",
            thread_id=self.thread_id,
        )
        # Write the seed into the checkpoint without advancing the cycle: the
        # first real invoke starts at open_iteration with iteration=0.
        self.graph.update_state(
            self.config,
            {"catalog": seed_catalog, "iteration": 0, "status": "seeded"},
            as_node="finalize",
        )

    # -- running ------------------------------------------------------------
    def target(self, iterations: int | None = None, *, target: int | None = None) -> int:
        current = self.iteration()
        if target is not None:
            if target < current:
                raise MuseumError(
                    f"target {target} lebih kecil dari iterasi sekarang {current}; museum tidak mundur"
                )
            return target
        return current + int(iterations or 0)

    def run(
        self,
        iterations: int | None = None,
        *,
        target: int | None = None,
        on_update: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Advance the museum by ``iterations`` cycles in one graph invocation."""
        self.ensure_seeded()
        if self.pending_interrupt():
            raise MuseumPaused("graph sedang menunggu keputusan manusia; panggil resume() dulu")
        desired = self.target(iterations, target=target)
        current = self.iteration()
        if desired <= current:
            return self.snapshot()

        config = thread_config(
            self.thread_id,
            recursion_limit=max(200, 40 + (desired - current) * 20),
        )
        for _ in self._stream({"target_iterations": desired}, config, on_update):
            pass
        return self.snapshot()

    def run_once(
        self, on_update: Callable[[str, dict[str, Any]], None] | None = None
    ) -> dict[str, Any]:
        return self.run(iterations=1, on_update=on_update)

    def _stream(
        self,
        payload: dict[str, Any],
        config: dict[str, Any],
        on_update: Callable[[str, dict[str, Any]], None] | None,
    ) -> Iterator[dict[str, Any]]:
        for chunk in self.graph.stream(
            payload,
            config,
            stream_mode="updates",
            durability="sync",
        ):
            if not isinstance(chunk, dict):
                continue
            for node, update in chunk.items():
                if on_update and isinstance(update, dict):
                    on_update(node, update)
            yield chunk

    def resume(
        self,
        decision: dict[str, Any] | str,
        *,
        on_update: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if isinstance(decision, str):
            decision = {"decision": decision}
        if not self.pending_interrupt():
            raise MuseumPaused("tidak ada interrupt yang menunggu")
        for _ in self.graph.stream(
            Command(resume=decision), self.config, stream_mode="updates", durability="sync"
        ):
            pass
        return self.snapshot()

    # -- derived views ------------------------------------------------------
    def verify(self) -> dict[str, Any]:
        catalog = self.catalog()
        base_problems = verify_catalog(catalog)
        ledger_ids = {row.get("id") for row in read_ledger(self.paths)}
        catalog_ids = {a.id for a in catalog}
        projection = self.paths.catalog_json
        projection_ids: set[str] = set()
        if projection.exists():
            payload = json.loads(projection.read_text(encoding="utf-8"))
            projection_ids = {a["id"] for a in payload.get("artifacts", [])}
        problems = list(base_problems)
        if ledger_ids != catalog_ids:
            problems.append(
                f"LEDGER_DRIFT: ledger={len(ledger_ids)} catalog={len(catalog_ids)} "
                f"(hilang: {sorted(catalog_ids - ledger_ids)}, yatim: {sorted(ledger_ids - catalog_ids)})"
            )
        if projection_ids and projection_ids != catalog_ids:
            problems.append("PROJECTION_DRIFT: catalog.json tidak sama dengan checkpoint")
        return {
            "ok": not problems,
            "problems": problems,
            "artifacts": len(catalog),
            "iteration": self.iteration(),
            "rejections": len(self.snapshot().get("rejections") or []),
        }

    def rebuild(self) -> dict[str, Any]:
        catalog = self.catalog()
        from .store import rebuild_from_artifacts

        snapshot = self.snapshot()
        rebuild_from_artifacts(
            self.paths,
            catalog,
            self.iteration(),
            status=snapshot.get("status") or "rebuilt",
            llm=getattr(self.llm, "name", None),
            extra={"rejections": len(snapshot.get("rejections") or [])},
        )
        for art in catalog:
            render_to_file(art, self.paths.renders)
        return {
            "artifacts": len(catalog),
            "rendered": len(catalog),
            "path": str(self.paths.catalog_json),
        }


# ---------------------------------------------------------------------------
# periodic curation
# ---------------------------------------------------------------------------


class Scheduler:
    """Runs one curator iteration per tick.

    Every iteration is a separate graph invocation, so a stop between ticks loses
    nothing; and because checkpoints are written synchronously inside a tick, a
    stop *during* a tick resumes at the last completed node.
    """

    def __init__(
        self,
        museum: Museum,
        *,
        interval_seconds: float = 60.0,
        iterations_per_tick: int = 1,
        max_iterations: int | None = None,
        on_tick: Callable[[int, dict[str, Any]], None] | None = None,
        logger: Callable[[str], None] = print,
    ) -> None:
        self.museum = museum
        self.interval = max(0.1, float(interval_seconds))
        self.iterations_per_tick = max(1, int(iterations_per_tick))
        self.max_iterations = max_iterations
        self.on_tick = on_tick
        self.log = logger
        self.stop_event = threading.Event()
        self.ticks = 0
        self._lock_path = museum.paths.root / "scheduler.lock"

    # -- single-writer lock -------------------------------------------------
    def acquire(self) -> bool:
        pid = str(os.getpid())
        try:
            fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                other = int(self._lock_path.read_text().strip() or 0)
            except (ValueError, OSError):
                other = 0
            if other and _pid_alive(other):
                return False
            self._lock_path.unlink(missing_ok=True)
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        os.write(fd, pid.encode())
        os.close(fd)
        return True

    def release(self) -> None:
        self._lock_path.unlink(missing_ok=True)

    # -- loop ---------------------------------------------------------------
    def run_forever(self) -> None:
        if not self.acquire():
            raise MuseumError("scheduler lain sedang memegang lock museum")
        try:
            while not self.stop_event.is_set():
                if (
                    self.max_iterations is not None
                    and self.museum.iteration() >= self.max_iterations
                ):
                    self.log(f"scheduler: batas {self.max_iterations} iterasi tercapai")
                    break
                if self.museum.pending_interrupt():
                    self.log("scheduler: menunggu keputusan manusia, berhenti")
                    break
                try:
                    state = self.museum.run_once()
                except Exception as exc:  # keep the museum alive between ticks
                    self.log(f"scheduler: iterasi gagal ({exc}); mencoba lagi pada tick berikutnya")
                    if self.stop_event.wait(self.interval):
                        break
                    continue
                self.ticks += 1
                if self.on_tick:
                    self.on_tick(self.ticks, state)
                if self.stop_event.wait(self.interval):
                    break
        finally:
            self.release()

    def stop(self) -> None:
        self.stop_event.set()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
