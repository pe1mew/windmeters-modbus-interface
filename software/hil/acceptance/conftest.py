"""Acceptance-suite fixtures (integrationPlan.md stage F, NFR-TST01 seed).

Wraps the proven check scripts as pytest runs against a flashed DUT.
Select the build under test with --build (must match the flashed binary):

    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . --build speed -v
    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . --build direction -v

The suite is intentionally a thin orchestrator: each underlying script
remains runnable standalone for debugging, and its PASS/FAIL contract is
what the tests assert.
"""

import subprocess
import sys
from pathlib import Path

import pytest

HIL = Path(__file__).parent.parent


def pytest_addoption(parser):
    parser.addoption("--build", choices=["speed", "direction"],
                     default="speed", help="flashed build variant under test")
    parser.addoption("--mcp-port", type=int, default=10530)


@pytest.fixture(scope="session")
def build(request):
    return request.config.getoption("--build")


@pytest.fixture(scope="session")
def mcp_port(request):
    return request.config.getoption("--mcp-port")


def run_check(script, *args):
    """Run a harness script with the m2k venv python; return (rc, output)."""
    proc = subprocess.run([sys.executable, str(HIL / script), *args],
                          capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    print(out)  # keep the detailed per-row log in the pytest report
    return proc.returncode, out
