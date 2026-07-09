"""Pre-teardown bench checks powered from the M2K V+ supply (DUT 3V3 lead
moved from the WCH-LinkE to M2K V+, LinkE 3V3 lifted, common ground):

  1. Ratiometric ADC (FR-S38 / P2-WD-RATIO) — sweep VDD 3.0..3.6 V and
     confirm the reported wind-direction angle and raw ADC stay constant
     (the divider tracks VDD and the ADC reference is VDD, so the code is
     ratiometric). The one firmware/design property the digital suite can't
     reach; needs the variable supply on the bench.
  2. Persistence across a REAL power cycle (FR-S39) — write non-default
     holdings, cut V+ (true power removal), restore, confirm the settings
     survived and uptime reset. Exercises the cold-boot flash read, not just
     a watchdog reset.

SAFETY: refuses to drive V+ if the DUT already answers (LinkE 3V3 not
lifted) — two supplies on one rail would fight.

Run (direction data must be live — divider on PA2; combined or direction
build at its address):
    .venv-m2k\\Scripts\\python.exe m2k_vplus_check.py [--slave 32]
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

RESULTS = []
DEFAULTS = [0, 1000, 10, 4]
NONDEFAULT = [900, 2000, 20, 10]


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def api(base, body, timeout=6.0):
    req = urllib.request.Request(
        base + "/api/v1/modbus", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "status": f"http:{e}"}


def read(base, S, reg, count=1, retries=4):
    """FC04 read with retries (comms can glitch as V+ moves)."""
    for _ in range(retries):
        r = api(base, {"slave": S, "function": 4, "register": reg,
                       "count": count})
        if r.get("ok"):
            return r["registers"]
        time.sleep(0.25)
    return None


def wait_boot(base, S, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = read(base, S, 6, 1, retries=1)
        if r is not None:
            return r[0]
        time.sleep(0.4)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--slave", type=int, default=32)
    ap.add_argument("--adc-reg", type=int, default=0x000C,
                    help="raw ADC register (30013 combined / 30005 direction)")
    args = ap.parse_args()
    base, S = args.base, args.slave

    # quiet the poller so its traffic doesn't collide with power transients
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + "/wind/stop", data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=5)
    except Exception:
        pass

    # ---- SAFETY: DUT must be unpowered (V+ is about to be the sole rail) ---
    if read(base, S, 6, 1, retries=2) is not None:
        print("ABORT: DUT already responds at %d — the LinkE 3V3 lead is "
              "still on the rail. Lift it so M2K V+ is the sole supply, "
              "then re-run." % S)
        return 2
    print("DUT is unpowered (good) — bringing it up on M2K V+ ...")

    ctx = open_calibrated()
    try:
        ps = ctx.getPowerSupply()
        ps.enableChannel(0, True)
        ps.pushChannel(0, 3.3)
        ident = wait_boot(base, S)
        if ident is None:
            print("ABORT: DUT did not boot on V+ = 3.3 V — check the V+→3V3 "
                  "wiring and common ground.")
            return 1
        print(f"booted on V+: ident 0x{ident:04X} at address {S}\n")

        # ==== 1: ratiometric VDD sweep ====================================
        print("-- ratiometric ADC across VDD 3.0..3.6 V --")
        rows = []
        for v in (3.6, 3.45, 3.3, 3.15, 3.0):
            ps.pushChannel(0, v)
            time.sleep(0.7)
            ang = read(base, S, 0, 1)          # 30001 dir_instant
            adc = read(base, S, args.adc_reg, 1)
            if ang is None or adc is None:
                print(f"    V+={v:.2f} V : no response "
                      f"(MAX3485 marginal near 3.0 V) — skipped")
                continue
            rows.append((v, ang[0], adc[0]))
            print(f"    V+={v:.2f} V : angle {ang[0] / 10:.1f} deg, "
                  f"raw ADC {adc[0]}")
        if len(rows) >= 3:
            angs = [r[1] for r in rows]
            adcs = [r[2] for r in rows]
            a_span = max(angs) - min(angs)
            d_span = max(adcs) - min(adcs)
            record("ratiometric: raw ADC constant across the VDD sweep",
                   d_span <= 15, f"ADC span {d_span} LSB over "
                   f"{rows[0][0]:.2f}..{rows[-1][0]:.2f} V ({len(rows)} pts)")
            record("ratiometric: reported angle constant across the sweep",
                   a_span <= 20, f"angle span {a_span / 10:.1f} deg")
        else:
            record("ratiometric sweep", False,
                   f"only {len(rows)} usable points")

        # ==== 2: persistence across a real power cycle ====================
        print("\n-- persistence across a REAL power cycle (V+ off/on) --")
        ps.pushChannel(0, 3.3)
        time.sleep(0.8)
        api(base, {"slave": S, "function": 16, "register": 0,
                   "values": NONDEFAULT})
        time.sleep(0.6)  # let regs_persist_service commit to flash
        rb = api(base, {"slave": S, "function": 3, "register": 0,
                        "count": 4}).get("registers")
        record("non-default holdings written", rb == NONDEFAULT,
               f"{rb}")
        up_before = read(base, S, 7, 1)
        up_before = up_before[0] if up_before else None

        print("    cutting V+ (power off) ...")
        ps.enableChannel(0, False)
        time.sleep(1.8)                        # drain decoupling
        print("    restoring V+ (power on) ...")
        ps.enableChannel(0, True)
        ps.pushChannel(0, 3.3)
        ident2 = wait_boot(base, S)
        record("DUT rebooted after a true power cycle", ident2 is not None,
               f"ident 0x{ident2:04X}" if ident2 else "did not come back")

        after = api(base, {"slave": S, "function": 3, "register": 0,
                           "count": 4}).get("registers")
        record("holdings persisted across the power cycle (FR-S39)",
               after == NONDEFAULT,
               f"{after} (want {NONDEFAULT}, defaults would be {DEFAULTS})")
        up_after = read(base, S, 7, 1)
        up_after = up_after[0] if up_after else None
        record("uptime reset (a real power cycle occurred)",
               up_before is not None and up_after is not None
               and up_after < up_before, f"{up_before} -> {up_after} s")

        # leave defaults stored
        api(base, {"slave": S, "function": 16, "register": 0,
                   "values": DEFAULTS})
        time.sleep(0.6)
    finally:
        libm2k.contextClose(ctx)  # releases V+ -> DUT powers off
        print("\nM2K released — V+ off, DUT unpowered. Reconnect the LinkE "
              "3V3 to run it again, or proceed to dismantle.")

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
