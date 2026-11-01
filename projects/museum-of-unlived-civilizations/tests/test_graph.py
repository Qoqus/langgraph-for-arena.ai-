"""The graph itself: nodes, cycles, reducers, threads."""

from __future__ import annotations

from langgraph.types import Command

from museum.graph import MuseumState, thread_config
from museum.llm.mock import MockCurator
from museum.runner import Museum


def edges(museum: Museum) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in museum.graph.get_graph().edges}


def test_graph_contains_the_expected_nodes(museum):
    nodes = set(museum.graph.get_graph().nodes)
    expected = {
        "__start__",
        "open_iteration",
        "curate",
        "validate",
        "repair",
        "human_review",
        "commit",
        "render",
        "reject",
        "advance",
        "finalize",
        "__end__",
    }
    assert expected == nodes


def test_curation_loop_is_an_explicit_cycle(museum):
    graph_edges = edges(museum)
    # the outer cycle: an iteration can only continue through advance
    assert ("advance", "open_iteration") in graph_edges
    assert ("advance", "finalize") in graph_edges
    # the repair cycle inside an iteration
    assert ("validate", "repair") in graph_edges
    assert ("repair", "curate") in graph_edges
    # the happy path has no shortcut from generation to commit
    assert ("curate", "commit") not in graph_edges
    assert ("curate", "validate") in graph_edges
    assert ("validate", "commit") in graph_edges
    assert ("commit", "render") in graph_edges


def test_mermaid_rendering_mentions_the_cycles(museum):
    mermaid = museum.graph.get_graph().draw_mermaid()
    assert "open_iteration" in mermaid
    assert "-->" in mermaid
    assert "advance" in mermaid


def test_catalog_channel_is_append_only():
    from typing import get_type_hints

    annotation = get_type_hints(MuseumState, include_extras=True)["catalog"]
    # Annotated[list[dict], operator.add] - the reducer can only extend history
    assert getattr(annotation, "__metadata__", None)
    reducer = annotation.__metadata__[0]
    assert reducer(("a",), ("b",)) == ("a", "b")


def test_threads_are_isolated(tmp_path):
    root = tmp_path / "state"
    a = Museum(root, llm=MockCurator(chaos="off"), thread_id="koleksi-a")
    b = Museum(root, llm=MockCurator(chaos="off"), thread_id="koleksi-b")
    try:
        a.run(iterations=2)
        b.run(iterations=1)
        assert a.iteration() == 2
        assert b.iteration() == 1
        assert len(a.catalog()) == len(b.catalog()) + 1
    finally:
        a.close()
        b.close()


def test_thread_config_keeps_a_stable_thread_id(museum):
    config = thread_config("museum-main", recursion_limit=321)
    assert config["configurable"]["thread_id"] == "museum-main"
    assert config["recursion_limit"] == 321
    assert museum.thread_id == "museum-main"


def test_graph_pauses_only_when_review_is_enabled(tmp_path):
    plain = Museum(tmp_path / "plain", llm=MockCurator(chaos="off"))
    review = Museum(tmp_path / "review", llm=MockCurator(chaos="off"), human_review=True)
    try:
        plain.run(iterations=1)
        review.run(iterations=1)
        assert plain.pending_interrupt() is None
        assert review.pending_interrupt() is not None
    finally:
        plain.close()
        review.close()


def test_resume_with_command_shape(museum):
    """The resume payload is a plain dict, so a human decision is JSON-safe."""
    payload = {"decision": "approve", "note": "ok", "artifact": {"id": "x"}}
    command = Command(resume=payload)
    assert command.resume == payload
