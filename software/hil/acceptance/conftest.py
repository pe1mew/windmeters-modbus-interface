"""Acceptance-suite fixtures (integrationPlan.md stage F, NFR-TST01 seed).

Wraps the proven check scripts as pytest runs against a flashed DUT.
Select the build under test with --build (must match the flashed binary):

    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . --build speed -v
    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . --build direction -v
    ..\\.venv-m2k\\Scripts\\python.exe -m pytest . --build combined -v

The suite is intentionally a thin orchestrator: each underlying script
remains runnable standalone for debugging, and its PASS/FAIL contract is
what the tests assert.

The NFR-TST01 backlog rows (test_nfr_tst01.py) each need a specific bench
rig and stay skipped unless enabled with --run-reset-matrix / --run-raw-
master / --run-m2k, so the default `pytest .` run stays green.
"""

import subprocess
import sys
from pathlib import Path

import pytest

HIL = Path(__file__).parent.parent


def pytest_addoption(parser):
    parser.addoption("--build", choices=["speed", "direction", "combined"],
                     default="speed", help="flashed build variant under test")
    parser.addoption("--mcp-port", type=int, default=10530)
    parser.addoption("--base", default="http://windmeter-tester.local",
                     help="windmeter-tester machine-API base URL")
    # NFR-TST01 backlog gates. Each of these rows needs a specific bench rig,
    # so it is skipped unless explicitly enabled — kept out of the default
    # green run (integrationPlan.md §9 / testReport.md "Pending").
    parser.addoption("--run-reset-matrix", action="store_true",
                     help="FR-S21 reset matrix (needs a *_test hang-hook "
                          "build or programmable-supply power control)")
    parser.addoption("--run-raw-master", action="store_true",
                     help="FR-MB20/21 latency histogram (needs the second "
                          "MAX3485 M2K raw master; rs485_raw_check.py)")
    parser.addoption("--run-m2k", action="store_true",
                     help="M2K-stimulus rows: FR-S14 alternating direction, "
                          "FR-S11 5-ratio divider sweep, VDD ratiometric sweep")


@pytest.fixture(scope="session")
def build(request):
    return request.config.getoption("--build")


@pytest.fixture(scope="session")
def mcp_port(request):
    return request.config.getoption("--mcp-port")


@pytest.fixture(scope="session")
def base(request):
    return request.config.getoption("--base")


@pytest.fixture(scope="session")
def dut_addr(build):
    """Jumper-open Modbus address for the build under test (TDS FR-S03)."""
    return {"speed": 30, "direction": 31, "combined": 32}[build]


@pytest.fixture(scope="session")
def run_reset_matrix(request):
    return request.config.getoption("--run-reset-matrix")


@pytest.fixture(scope="session")
def run_raw_master(request):
    return request.config.getoption("--run-raw-master")


@pytest.fixture(scope="session")
def run_m2k(request):
    return request.config.getoption("--run-m2k")


def run_check(script, *args):
    """Run a harness script with the m2k venv python; return (rc, output)."""
    proc = subprocess.run([sys.executable, str(HIL / script), *args],
                          capture_output=True, text=True, timeout=900)
    out = proc.stdout + proc.stderr
    print(out)  # keep the detailed per-row log in the pytest report
    return proc.returncode, out
