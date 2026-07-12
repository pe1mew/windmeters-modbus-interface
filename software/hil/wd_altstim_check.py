"""FR-S14 on-target circular mean over RS-485. Drive PA2 with an M2K W1
stimulus alternating near 350 deg and near 10 deg at equal dwell; after one
averaging window the boxcar 30003 must read within ~0.0 deg (the [3580..3599]
u [0..20] wrap band) and NEVER the ~180 deg naive-linear-mean failure band
[1700..1900].

This is a relative test — it needs two distinct angles that straddle north,
not absolute accuracy — so the M2K's absolute-voltage inaccuracy (unusable
per testReport 4.4) does not matter here. The two levels are chosen roughly
symmetric about north, so an ideal circular mean lands on 0 deg regardless of
a few-percent level error.

Reads the product register 30003 over Modbus through the tester machine API;
drives the stimulus with libm2k. Wiring: M2K W1 -> DUT PA2 (RJ14 J5 pin 4);
grounds common.

Run:  .venv-m2k\\Scripts\\python.exe wd_altstim_check.py
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
from m2k_signal_check import open_calibrated

W1 = 0  # AnalogOut channel 0

RESULTS = []


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--slave", type=int, default=31)
    ap.add_argument("--build", default="direction",
                    choices=["direction", "combined"])
    ap.add_argument("--vdd", type=float, default=3.3,
                    help="nominal DUT rail for the ratiometric level math")
    ap.add_argument("--period", type=float, default=1.0,
                    help="alternation period s (equal dwell per half)")
    args = ap.parse_args()
    base, S = args.base, args.slave

    if read_reg(base, S, 4, 6) is None:
        print(f"DUT not responding at {S}")
        return 1
    poller(base, "/wind/stop", {})  # it competes for the direction registers

    # The averaging window (40003) sets how long to hold before 30003 settles.
    avg_s = read_reg(base, S, 3, 2) or 10
    hold_s = avg_s + 4

    # Two levels straddling north: ~350 deg (adc 995) and ~10 deg (adc 28).
    v_hi = args.vdd * 995 / 1023
    v_lo = args.vdd * 28 / 1023

    rate = 75000
    half = max(2, int(round(rate * args.period / 2)))
    buf = [v_hi] * half + [v_lo] * half

    avg = None
    ctx = open_calibrated()
    try:
        aout = ctx.getAnalogOut()
        aout.enableChannel(W1, True)
        aout.setSampleRate(W1, rate)
        aout.setCyclic(True)   # repeat the buffer forever
        aout.push(W1, buf)
        print(f"W1 alternating {v_hi:.3f}V/{v_lo:.3f}V, {args.period:.1f}s "
              f"period; holding {hold_s}s (avg window {avg_s}s)")
        # Sanity: the instantaneous 30001 should visit BOTH ends, proving the
        # stimulus actually reaches PA2 (else 30003 near north is meaningless).
        seen_hi = seen_lo = False
        t0 = time.time()
        while time.time() - t0 < hold_s:
            inst = read_reg(base, S, 4, 0)
            if inst is not None and inst != 65535:
                seen_hi = seen_hi or inst >= 3400
                seen_lo = seen_lo or inst <= 200
            time.sleep(0.5)
        record("instantaneous 30001 visits both ends (stimulus reaches PA2)",
               seen_hi and seen_lo, f"saw_hi={seen_hi} saw_lo={seen_lo}")
        avg = read_reg(base, S, 4, 2)  # 30003 dir_avg, sampled while driven
    finally:
        libm2k.contextClose(ctx)
        print("M2K released")

    in_wrap = avg is not None and (avg >= 3580 or avg <= 20)
    in_fail = avg is not None and 1700 <= avg <= 1900
    record("circular mean near north, not 180 (FR-S14)",
           bool(in_wrap) and not in_fail,
           f"30003 = {avg / 10:.1f} deg" if avg is not None else "no read")

    poller(base, "/wind/start",
           {"type": "direction", "addr": S, "interval_ms": 3000})

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("WD ALTSTIM " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
