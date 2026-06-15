"""Local verification entrypoint for the SC Spire viewer (A13, local part).

Runs the unit suite (test_viewer_units.py) via pytest using the SAME Python
interpreter (sys.executable), reports pass/fail + exit code, and optionally
(with --smoke) runs smoke_test_viewer.py if a server is reachable on 8766.
If no server is reachable, the smoke step is skipped gracefully (not failed).

Stdlib only. Runnable from the tool dir:  python verify.py  [--smoke]
The GitHub Actions workflow is added separately by the controller.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
UNIT_TEST_FILE = "test_viewer_units.py"
SMOKE_FILE = "smoke_test_viewer.py"
SMOKE_HOST = "127.0.0.1"
SMOKE_PORT = 8766


def run_pytest() -> int:
    """Run the unit suite with the current interpreter. Returns its exit code."""
    cmd = [sys.executable, "-m", "pytest", UNIT_TEST_FILE, "-q"]
    print(f"[verify] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(TOOL_DIR))
    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"[verify] pytest {status} (exit code {result.returncode})")
    return result.returncode


def server_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_smoke() -> int:
    """Run the smoke test if a server is reachable; skip gracefully otherwise.

    Returns 0 on success or graceful skip, nonzero only if the smoke test
    actually ran and failed.
    """
    if not server_reachable(SMOKE_HOST, SMOKE_PORT):
        print(
            f"[verify] smoke skipped: no server reachable on "
            f"{SMOKE_HOST}:{SMOKE_PORT}"
        )
        return 0
    cmd = [sys.executable, SMOKE_FILE]
    print(f"[verify] running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(TOOL_DIR))
    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"[verify] smoke {status} (exit code {result.returncode})")
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SC Spire viewer local verify (A13).")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="also run smoke_test_viewer.py if a server is reachable on 8766",
    )
    args = parser.parse_args(argv)

    pytest_rc = run_pytest()

    smoke_rc = 0
    if args.smoke:
        smoke_rc = run_smoke()

    overall = pytest_rc if pytest_rc != 0 else smoke_rc
    print(f"[verify] summary: pytest_exit={pytest_rc} smoke_exit={smoke_rc} overall={overall}")
    return overall


if __name__ == "__main__":
    raise SystemExit(main())
