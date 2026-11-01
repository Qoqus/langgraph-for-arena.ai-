"""Turn whatever the model said into something the validator can judge."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(object, error)``. Never raises: a malformed draft is just a
    rejected draft, not a crashed museum."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "model returned nothing"
    text = raw.strip()
    match = _FENCE.search(text)
    if match:
        text = match.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None, f"no JSON object found ({exc.msg})"
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None, f"invalid JSON ({exc.msg} at char {exc.pos})"
    if not isinstance(value, dict):
        return None, f"expected a JSON object, got {type(value).__name__}"
    for key in ("artifact", "draft"):
        if key in value and isinstance(value[key], dict):
            return value[key], None
    return value, None
