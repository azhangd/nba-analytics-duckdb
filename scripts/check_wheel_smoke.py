"""Install the built wheel into a clean venv and run the public smoke path."""

from __future__ import annotations

import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _run(command: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def _venv_bin(venv_dir: Path, executable: str) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / executable


def _latest_wheel() -> Path:
    wheels = sorted(
        Path("dist").glob("nba_analytics_duckdb-*.whl"),
        key=lambda path: path.stat().st_mtime,
    )
    if not wheels:
        raise SystemExit("No wheel found under dist/. Run `uv build` first.")
    return wheels[-1]


def main() -> None:
    wheel = _latest_wheel().resolve()
    with tempfile.TemporaryDirectory(prefix="nba-duckdb-wheel-smoke-") as raw_tmp:
        tmp = Path(raw_tmp)
        venv_dir = tmp / "venv"
        fixtures_dir = tmp / "fixtures"
        warehouse_path = tmp / "warehouse" / "nba.duckdb"

        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = _venv_bin(venv_dir, "python")
        nba_duckdb = _venv_bin(venv_dir, "nba-duckdb")
        env = {
            **os.environ,
            "NBA_DUCKDB_PATH": str(warehouse_path),
            "NBA_DUCKDB_LOG_LEVEL": "WARNING",
        }

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                f"{wheel}[full]",
            ],
            env=env,
        )
        _run([str(nba_duckdb), "--help"], env=env)
        _run([str(nba_duckdb), "init"], env=env)
        _run(
            [str(nba_duckdb), "generate-test-fixtures", "--fixtures-dir", str(fixtures_dir)],
            env=env,
        )
        _run(
            [str(nba_duckdb), "run-smoke", "--fixtures-dir", str(fixtures_dir)],
            env=env,
        )
        _run([str(nba_duckdb), "quality"], env=env)
        _run([str(nba_duckdb), "datasets", "list"], env=env)

    print(f"wheel smoke passed: {wheel.name}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
