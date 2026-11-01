"""The artifact contract.

Two layers of checking, on purpose:

* ``*Draft`` models check *shape* (types, ranges, list lengths, id syntax).
* :mod:`museum.validator` checks *world rules* (does this reference exist? does
  the year move forward? is the material in the controlled vocabulary?).

Only a draft that passes both becomes an :class:`Artifact`, and the artifact
model itself is frozen: once committed, the past cannot be edited.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+){1,5}$"


class RefLink(BaseModel):
    """A named relationship to an older artifact. The only permitted way to
    reinterpret the past."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=48)
    relation: str
    note: str = Field(min_length=12, max_length=400)


class VisualSpec(BaseModel):
    """Everything the deterministic renderer needs. No image model involved."""

    model_config = ConfigDict(extra="forbid")

    form: str
    palette: str
    motif: str
    symmetry: str
    density: float = Field(ge=0.15, le=0.95)
    strata: int = Field(ge=2, le=9)


class ArtifactDraft(BaseModel):
    """Exactly one of these per curator iteration."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=4, max_length=90)
    year_fictional: int = Field(ge=0, le=9999)
    lineage: str = Field(min_length=2, max_length=32)
    form: str = Field(min_length=2, max_length=32)
    function: str = Field(min_length=2, max_length=32)
    materials: list[str] = Field(min_length=1, max_length=4)
    motifs: list[str] = Field(min_length=1, max_length=3)
    refs: list[RefLink] = Field(min_length=0, max_length=4)
    inscription: str = Field(min_length=8, max_length=400)
    provenance_note: str = Field(min_length=20, max_length=800)
    visual: VisualSpec


class Artifact(BaseModel):
    """An immutable accession. ``iteration`` and ``created_at`` are stamped by
    deterministic code, never by the model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    year_fictional: int
    lineage: str
    form: str
    function: str
    materials: tuple[str, ...]
    motifs: tuple[str, ...]
    refs: tuple[RefLink, ...]
    inscription: str
    provenance_note: str
    visual: VisualSpec
    iteration: int = Field(ge=0)
    created_at: str
    llm: str
    attempt: int = Field(ge=0)
    draft_digest: str

    def canonical(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def digest(self) -> str:
        return digest_json(self.canonical())

    def to_json(self) -> str:
        return json.dumps(self.canonical(), ensure_ascii=False, sort_keys=True)


def digest_json(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def draft_to_artifact(
    draft: ArtifactDraft,
    *,
    iteration: int,
    created_at: str,
    llm: str,
    attempt: int,
) -> Artifact:
    return Artifact(
        **draft.model_dump(),
        iteration=iteration,
        created_at=created_at,
        llm=llm,
        attempt=attempt,
        draft_digest=digest_json(draft.model_dump()),
    )
