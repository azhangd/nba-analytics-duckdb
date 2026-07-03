"""Environment parsing helpers."""

from __future__ import annotations

import logging
import os


def positive_int(name: str, default: int, *, logger: logging.Logger | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        if logger:
            logger.warning("Ignoring invalid %s=%r; using %d", name, raw, default)
        return default
    return max(1, value)


def positive_float(name: str, default: float, *, logger: logging.Logger | None = None) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        if logger:
            logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
        return default
    return max(0.01, value)
