"""Curator model adapters. One interface, two implementations."""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class CuratorLLM(Protocol):
    name: str

    def propose(self, context: dict) -> str:
        """Return raw model output (expected: one JSON object)."""
        ...


def load_curator(spec: str | None = None, **kwargs) -> CuratorLLM:
    """Resolve a curator from a spec string or the environment.

    ``mock`` (default) or ``openai:<model>`` / ``openai-compatible:<model>``.
    Environment for the HTTP adapter: ``MUSEUM_LLM_BASE_URL``,
    ``MUSEUM_LLM_API_KEY``, ``MUSEUM_LLM_MODEL``.
    """
    from .mock import MockCurator
    from .openai_compat import OpenAICompatibleCurator

    spec = spec or os.environ.get("MUSEUM_LLM", "mock")
    if spec in ("mock", "mock:", ""):
        return MockCurator(**kwargs)
    if spec.startswith("mock:"):
        return MockCurator(salt=spec.split(":", 1)[1], **kwargs)
    if spec.startswith(("openai:", "openai-compatible:", "http:")):
        model = spec.split(":", 1)[1] if ":" in spec else os.environ.get("MUSEUM_LLM_MODEL", "")
        return OpenAICompatibleCurator(model=model, **kwargs)
    raise ValueError(f"unknown curator spec: {spec!r} (use 'mock' or 'openai:<model>')")


__all__ = ["CuratorLLM", "load_curator"]
