"""FR-S11 direction accuracy sweep over RS-485. Drive PA2 across the range
with M2K W1 and, because the ADC is ratiometric, take the expectation from the
MEASURED W1/VDD ratio (M2K scope 1+ on W1, 2+ on VDD) rather than the
commanded voltage — the M2K's absolute-voltage accuracy is unusable
(testReport 4.4), but its measured ratio is fine, the same technique wd_check.py
uses at the driver phase.

At each of 5 levels the reported 30001 must be within ±10 LSB firmware +
~2 LSB measurement of the angle implied by the measured ratio (FR-S11); a
fixed mid level must be stable to <= 3 raw-ADC counts over N reads
(FR-S10/S28). The offset (40001) is set to 0 for the sweep.

The accuracy-of-record for a release is still the DMM-measured resistor
divider (testReport 4.4); this M2K-measured-ratio sweep is the automatable
in-suite approximation.

Reads 30001 (angle) and 30005/30013 (raw ADC) over Modbus via the tester API;
drives + measures with libm2k. Wiring (same as wd_check.py): W1 -> DUT PA2 and
-> M2K 1+;  M2K 2+ -> DUT VDD;  grounds common.

Run:  .venv-m2k\\Scripts\\python.exe wd_divider_sweep.py
      [--base http://windmeter-tester.local] [--slave 31] [--build direction]
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import libm2k
from m2k_signal_check import open_calibrated, ain_mean

RESULTS = []
LEVELS = (0.30, 0.825, 1.65, 2.475, 3.00)  # same spread as wd_check.py
ACC_TOL = 12   # ±10 LSB firmware (FR-S11) + ~2 LSB M2K-ratio measurement
STAB_TOL = 3   # raw ADC counts (FR-S10/S28)


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def api(base, body, timeout=8.0):
    req = urllib.request.Request(
        base + "/api/v1/modbus", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "status": f"http_error:{e}"}


def read_reg(base, S, fc, reg):
    r = api(base, {"slave": S, "function": fc, "register": reg, "count": 1})
    return r["registers"][0] if r.get("ok") else None


def poller(base, path, body):
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}), timeout=6)
    except Exception:
        pass


def expected_angle(v_applied, vdd):
    """Firmware math for an ideal ratiometric 10-bit ADC, offset 0 (0.1 deg)."""
    ratio = max(0.0, min(1.0, v_applied / vdd))
    code = min(1023, int(ratio * 1024))
    raw16 = code * 16
    return ((raw16 * 3600 + 8192) >> 14) % 3600


def circ_dev(a, b):
    d = abs(a - b) % 3600
    return min(d, 3600 - d)


def stimulated(volts, body):
    """One fresh M2K context per analog level (bench quirk), kept OPEN while
    `body` runs so W1 stays driven; measures the applied W1 voltage and VDD.
    Returns (v_w1, v_dd, body_result)."""
    c = open_calibrated()
    try:
        ain, aout = c.getAnalogIn(), c.getAnalogOut()
        for ch in (0, 1):
            ain.enableChannel(ch, True)
            ain.setRange(ch, libm2k.PLUS_MINUS_25V)
        ain.setSampleRate(1_000_000)
        aout.enableChannel(0, True)
        aout.setVoltage(0, volts)
        time.sleep(0.4)
        v_w1 = ain_mean(ain, 0)
        v_dd = ain_mean(ain, 1)
        result = body()
    finally:
        libm2k.contextClose(c)
    return v_w1, v_dd, result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--slave", type=int, default=31)
    ap.add_argument("--build", default="direction",
                    choices=["direction", "combined"])
    ap.add_argument("--reads", type=int, default=8,
                    help="reads per level (accuracy) / at mid (stability)")
    args = ap.parse_args()
    base, S = args.base, args.slave
    # Direction raw-ADC diagnostic: 30005 (raw 0x0004) on a direction build,
    # 30013 (raw 0x000C) on a combined build (TDS §2.7).
    adc_reg = 0x000C if args.build == "combined" else 0x0004

    if read_reg(base, S, 4, 6) is None:
        print(f"DUT not responding at {S}")
        return 1
    poller(base, "/wind/stop", {})
    api(base, {"slave": S, "function": 6, "register": 0, "values": [0]})  # offset 0

    def read_angles(n):
        out = []
        for _ in range(n):
            a = read_reg(base, S, 4, 0)
            if a is not None:
                out.append(a)
        return out

    def read_adc(n):
        out = []
        for _ in range(n):
            a = read_reg(base, S, 4, adc_reg)
            if a is not None:
                out.append(a)
        return out

    print("\n-- accuracy at 5 levels (expectation from measured W1/VDD) --")
    for volts in LEVELS:
        v_w1, v_dd, angs = stimulated(volts, lambda: read_angles(args.reads))
        if not 2.5 <= v_dd <= 3.6:
            record(f"accuracy {volts:.3f}V", False,
                   f"VDD measures {v_dd:.3f}V — is M2K 2+ on the DUT VDD pin?")
            continue
        if not angs:
            record(f"accuracy {volts:.3f}V", False, "no angle reads")
            continue
        exp = expected_angle(v_w1, v_dd)
        devs = [circ_dev(a, exp) for a in angs]
        record(f"accuracy {volts:.3f}V", max(devs) <= ACC_TOL,
               f"W1={v_w1:.4f}V VDD={v_dd:.4f}V expect~{exp} got {angs} "
               f"(worst dev {max(devs)} x0.1deg, tol {ACC_TOL})")

    print("\n-- stability at mid level (FR-S10/S28) --")
    _, v_dd, raws = stimulated(1.65, lambda: read_adc(max(8, args.reads)))
    span = (max(raws) - min(raws)) if raws else 9999
    record("raw-ADC stability span <= 3 counts", len(raws) >= 8 and span <= STAB_TOL,
           f"n={len(raws)} raw-ADC span={span} (tol {STAB_TOL})")

    poller(base, "/wind/start",
           {"type": "direction", "addr": S, "interval_ms": 3000})

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("WD DIVIDER " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
