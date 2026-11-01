"""``python -m museum`` — same entry point as the ``museum`` script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
