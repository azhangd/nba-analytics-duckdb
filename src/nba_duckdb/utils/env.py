"""Environment parsing helpers."""

from __future__ import annotations

import os


def positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    value = int(raw) if raw else default
    if value < 1:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


def positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    value = float(raw) if raw else default
    if value <= 0:
        raise ValueError(f"{name} must be a positive number, got {raw!r}")
    return value
