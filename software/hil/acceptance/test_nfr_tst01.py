"""NFR-TST01 backlog — pytest stubs for the HIL rows not yet in the default
green suite (testReport.md "Pending / not yet run").

Each row needs a specific bench rig, so it is SKIPPED unless its ``--run-*``
gate is passed. A stub whose underlying check script is not written yet
XFAILs when its gate IS passed, so the intent stays collected and the row
lights up the moment the rig and the script both exist. Nothing here runs in
a plain ``pytest .`` invocation, so the default acceptance run stays green.

Enable a row explicitly, e.g.:

    ..\\.venv-m2k\\Scripts\\python.exe -m pytest test_nfr_tst01.py \\
        --build direction --run-m2k -v

Wired to real scripts already:
  - FR-MB20/21 latency  -> rs485_raw_check.py --group latency
  - VDD ratiometric     -> m2k_vplus_check.py
To be written (XFAIL until then):
  - reset_matrix_check.py   (FR-S21/S39)
  - wd_altstim_check.py     (FR-S14 on-target alternating stimulus)
  - wd_divider_sweep.py     (FR-S11 5-ratio accuracy sweep)
"""

import pytest

from conftest import HIL, run_check


def _require_script(name):
    """XFAIL (not error) when an as-yet-unwritten stub script is enabled, so a
    turned-on gate reads 'to be written' rather than a raw FileNotFoundError.
    """
    if not (HIL / name).exists():
        pytest.xfail(f"{name} not yet written (NFR-TST01 stub)")


def test_reset_matrix(build, dut_addr, base, run_reset_matrix):
    """FR-S21/FR-S39: after a reset the DUT re-enters its defined state within
    1 s — holding registers restored from flash (the last committed set, not
    the §2.8 defaults) and the averaging accumulator cleared (status bit 1
    set, 30008 uptime back near 0).

    The watchdog source is reachable over the wire on a ``*_test`` hang-hook
    build (write TEST_HOOKS 0x00FF, wait for recovery); the power-on and
    brown-out sources need a programmable supply (integrationPlan.md §9.2).
    """
    if not run_reset_matrix:
        pytest.skip("needs --run-reset-matrix (a *_test hang-hook build; the "
                    "power-on/brown-out sources need a programmable supply)")
    _require_script("reset_matrix_check.py")
    rc, out = run_check("reset_matrix_check.py", "--build", build,
                        "--base", base, "--slave", str(dut_addr))
    assert rc == 0 and "RESET MATRIX PASS" in out


def test_latency_histogram(build, mcp_port, run_raw_master):
    """FR-MB20/21: 1000-request latency histogram through the MAX3485 —
    1000/1000 answered, every request-end -> response-start gap within
    [t3.5, 100 ms], and the median < 15 ms.

    Wraps the existing rs485_raw_check.py latency group (testReport.md
    R485-LAT-10D: 4.07/4.12/4.17/4.44 ms min/med/p99/max); needs the
    second-MAX3485 M2K raw master on the DIO lines.
    """
    if not run_raw_master:
        pytest.skip("needs --run-raw-master (second MAX3485 on the M2K DIO)")
    rc, out = run_check("rs485_raw_check.py", "--group", "latency",
                        "--build", build, "--port", str(mcp_port))
    assert rc == 0, "latency histogram failed — see log"


def test_direction_circular_mean(build, dut_addr, base, run_m2k):
    """FR-S14: on-target circular mean. Drive PA2 with an M2K W1 stimulus
    alternating 350.0 deg and 10.0 deg at equal dwell; after one averaging
    window 30003 reads within 0.0 deg +/- 1.0 deg ([3590..3599] u [0..10])
    and NEVER lands in the ~180 deg naive-linear-mean failure band
    [1700..1900].
    """
    if build == "speed":
        pytest.skip("direction/combined build only (no vane on a speed build)")
    if not run_m2k:
        pytest.skip("needs --run-m2k (M2K W1 driving the PA2 divider)")
    _require_script("wd_altstim_check.py")
    rc, out = run_check("wd_altstim_check.py", "--build", build,
                        "--base", base, "--slave", str(dut_addr))
    assert rc == 0 and "PASS" in out


def test_direction_divider_sweep(build, dut_addr, base, run_m2k):
    """FR-S11: 5-ratio divider accuracy sweep. At each of 5 known divider
    ratios the reported 30001 is within +/-10 LSB (+/-1.0 deg) of the
    expected angle, and 100 reads over 60 s at a fixed ratio span <= 3 counts.
    Accuracy of record is the DMM-measured resistor divider, not the M2K AWG
    (testReport.md 4.4).
    """
    if build == "speed":
        pytest.skip("direction/combined build only")
    if not run_m2k:
        pytest.skip("needs --run-m2k (divider ladder on PA2)")
    _require_script("wd_divider_sweep.py")
    rc, out = run_check("wd_divider_sweep.py", "--build", build,
                        "--base", base, "--slave", str(dut_addr))
    assert rc == 0 and "PASS" in out


def test_vdd_ratiometric_sweep(build, dut_addr, base, run_m2k):
    """FR-S09/FR-S11: ratiometric-ADC VDD sweep. With PA2 fed from a divider
    off VDD, sweep VDD with the M2K V+ (the LinkE 3V3 lifted off the rail)
    and confirm the reported angle stays put — the ratiometric connection
    cancels rail changes, so no external reference is used.

    Wraps the existing m2k_vplus_check.py. The direction raw-ADC diagnostic
    is at 30005 (0x0004) on a direction build and 30013 (0x000C) on a
    combined build (TDS 2.7).
    """
    if build == "speed":
        pytest.skip("direction/combined build only")
    if not run_m2k:
        pytest.skip("needs --run-m2k (M2K V+ powering the DUT, LinkE 3V3 off)")
    adc_reg = 0x000C if build == "combined" else 0x0004
    rc, out = run_check("m2k_vplus_check.py", "--base", base,
                        "--slave", str(dut_addr), "--adc-reg", str(adc_reg))
    assert rc == 0, "VDD ratiometric sweep failed — see log"
