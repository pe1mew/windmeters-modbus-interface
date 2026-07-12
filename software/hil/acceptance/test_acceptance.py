"""Stage-F acceptance suite: one pytest per verified check group
(integrationPlan.md §4-F; NFR-TST01's automated core).

Order matters loosely: the register/protocol checks leave the DUT at
defaults; the measurement and averaging groups restore what they change.
"""

from conftest import run_check


def test_version_chain(build, mcp_port, dut_addr):
    """FR-S32: version.h <-> RELEASES.md <-> flashed DUT."""
    rc, out = run_check("version_check.py", "--address", str(dut_addr),
                        "--port", str(mcp_port))
    assert rc == 0, "version chain mismatch — see log"


def test_register_image_and_protocol(build, mcp_port):
    """Stage C: full §2.7/§2.8 map + §2 protocol vectors (FR-MB rows)."""
    rc, out = run_check("regs_check.py", "--build", build,
                        "--port", str(mcp_port))
    assert rc == 0 and "REGS CHECK PASS" in out


def test_measurement_services(build, mcp_port):
    """Stage D: FR-S05/S06/S07/S12/S24/S27/S30 measurement rows."""
    rc, out = run_check("meas_check.py", "--build", build,
                        "--port", str(mcp_port))
    assert rc == 0 and "MEAS CHECK PASS" in out


def test_averaging_engine(build, mcp_port):
    """Stage E: FR-S13/S14/S23/S30/S31/S33/S37 averaging rows."""
    rc, out = run_check("avg_check.py", "--build", build,
                        "--port", str(mcp_port))
    assert rc == 0 and "AVG CHECK PASS" in out
