#!/usr/bin/env python3
"""Fail when tracked files violate the public data/artifact policy."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_FILE_BYTES = 1_000_000

ALLOWED_DATA_PREFIXES = (
    "tests/fixtures/generated/",
)

BANNED_DIRECTORY_PREFIXES = (
    "data/",
    "logs/",
    "artifacts/",
    "dist/",
    "build/",
    "target/",
    "dbt/target/",
    "dbt/dbt_packages/",
    "htmlcov/",
)

BANNED_SUFFIXES = (
    ".duckdb",
    ".duckdb.wal",
    ".parquet",
    ".jsonl",
    ".ipynb",
    ".pkl",
    ".pickle",
    ".joblib",
    ".sav",
    ".onnx",
    ".pt",
    ".pth",
    ".h5",
    ".xgb",
)

DATA_SUFFIXES = (
    ".csv",
    ".tsv",
    ".json",
    ".xlsx",
    ".xls",
    ".feather",
    ".arrow",
    ".sqlite",
    ".db",
)


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str

    def format(self) -> str:
        return f"{self.path}: {self.reason}"


def _is_allowed_data_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ALLOWED_DATA_PREFIXES)


def _is_banned_suffix(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in BANNED_SUFFIXES)


def _is_data_suffix(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in DATA_SUFFIXES)


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    raw = result.stdout.decode()
    return [path for path in raw.split("\0") if path]


def check_paths(
    paths: list[str],
    *,
    root: Path,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        normalized = path.replace(os.sep, "/")
        full_path = root / normalized

        if any(normalized.startswith(prefix) for prefix in BANNED_DIRECTORY_PREFIXES):
            violations.append(
                Violation(normalized, "generated output directories must not be tracked")
            )

        if normalized.endswith(".ipynb"):
            violations.append(
                Violation(normalized, "notebooks are not accepted in-repo for v1")
            )
        elif _is_banned_suffix(normalized):
            violations.append(Violation(normalized, "generated data or model artifact"))
        elif _is_data_suffix(normalized) and not _is_allowed_data_path(normalized):
            violations.append(
                Violation(normalized, "data files are only allowed under tests/fixtures/generated/")
            )

        if full_path.exists() and full_path.is_file() and full_path.stat().st_size > max_file_bytes:
            violations.append(
                Violation(
                    normalized,
                    f"file is larger than the {max_file_bytes} byte tracked-file limit",
                )
            )

    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    max_file_bytes = int(os.environ.get("NBA_DUCKDB_MAX_TRACKED_FILE_BYTES", DEFAULT_MAX_FILE_BYTES))
    paths = tracked_files(root)
    violations = check_paths(paths, root=root, max_file_bytes=max_file_bytes)
    if violations:
        print("Artifact policy violations:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation.format()}", file=sys.stderr)
        return 1
    print(f"Artifact check passed: {len(paths)} tracked files scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
