"""FR-S21 reset matrix over RS-485: after a reset the DUT re-enters its
defined state — holding registers restored from flash (FR-S39, the last
committed set, not the §2.8 defaults) and all measurement accumulators
cleared (status bit 1 set, 30008 uptime back near 0).

The watchdog source is exercised over the wire on a *_test build via the
FR-S20 hang hook (holding 0x00FF := 0xDEAD -> stop feeding -> IWDG reset), so
no power cycle or extra rig is needed; the persistence + defined-state code is
identical in the release build. The power-on and brown-out sources are
electrically identical from the firmware's point of view but need a
programmable supply — they stay §9.2 (real-PCB) and are reported here as
NOT RUN, not failed.

Sequence (FR-S21/FR-S39), via the tester machine API at the DUT address:
  1. write a non-default, FR-S31-legal 6-register set via FC16, let it persist
  2. record uptime as a baseline
  3. trigger the watchdog reset; wait for recovery
  4. assert the DEFINED STATE: holdings == the written set (restored from
     flash, not defaults), uptime went backwards and is low, and the
     averaging accumulator is cleared (status bit 1 set; FR-S23/S33)
  5. restore defaults, reset again, assert the defaults now persist (proves
     the ping-pong store handles successive saves)

Run:  .venv-m2k\\Scripts\\python.exe reset_matrix_check.py
      [--base http://windmeter-tester.local] [--slave 32] [--build combined]
"""

import argparse
import json
import sys
import time
import urllib.request

RESULTS = []
DEFAULTS = [0, 1000, 10, 4, 980, 1]         # TDS §2.8 (six holdings)
NONDEFAULT = [900, 2000, 20, 10, 1200, 2]   # FR-S31-legal (avg*1000 >= window)
HANG_REG = 0x00FF
HANG_MAGIC = 0xDEAD
STATUS_AVG_NOT_FILLED = 0x0002  # bit 1 (FR-S33) — set while accumulator refills


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


def read_regs(base, S, fc, reg, count):
    r = api(base, {"slave": S, "function": fc, "register": reg, "count": count})
    return r["registers"] if r.get("ok") else None


def read_holdings(base, S):
    return read_regs(base, S, 3, 0, 6)


def read_uptime(base, S):
    v = read_regs(base, S, 4, 7, 1)
    return v[0] if v else None


def read_status(base, S):
    v = read_regs(base, S, 4, 5, 1)
    return v[0] if v else None


def write_holdings(base, S, vals):
    return api(base, {"slave": S, "function": 16, "register": 0, "values": vals})


def watchdog_reset(base, S, tag):
    """Fire the *_test hang hook, then wait for the IWDG reset + reboot."""
    up_before = read_uptime(base, S)
    api(base, {"slave": S, "function": 6, "register": HANG_REG,
               "values": [HANG_MAGIC]})   # DUT echoes, then hangs
    time.sleep(0.3)
    # While hung, reads time out; after the IWDG reset (~1–2.5 s) + reboot and
    # the FR-S19 bus re-sync, they succeed again with a low uptime.
    t0 = time.time()
    back = None
    while time.time() - t0 < 12:
        up = read_uptime(base, S)
        if up is not None and (up_before is None or up <= up_before):
            back = up
            break
        time.sleep(0.4)
    record(f"[{tag}] watchdog reset + recovery (FR-S20)", back is not None,
           f"uptime {up_before} -> {back} s")
    return up_before, back


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--slave", type=int, default=32)
    ap.add_argument("--build", default="combined",
                    choices=["speed", "direction", "combined"])
    args = ap.parse_args()
    base, S = args.base, args.slave

    ident = read_regs(base, S, 4, 6, 1)
    if ident is None:
        print(f"DUT not responding at {S}")
        return 1
    print(f"DUT @ {S}: ident 0x{ident[0]:04X} ({args.build})")

    # *_test build gate: 0x00FF must be writable (the hang hook). A write of 0
    # is harmless (only 0xDEAD arms the hang); a release build returns exc 02.
    probe = api(base, {"slave": S, "function": 6, "register": HANG_REG,
                       "values": [0]})
    if probe.get("status") == "exception":
        print("!! 0x00FF unmapped — this is a RELEASE build. Flash the *_test "
              "build for the watchdog-hang hook. The power-on/brown-out reset "
              "sources need a programmable supply (integrationPlan §9.2).")
        return 1

    # Quiet the tester poller so its traffic doesn't collide with the resets.
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + "/wind/stop", data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=6)
    except Exception:
        pass
    time.sleep(0.4)

    print(f"\ninitial holdings: {read_holdings(base, S)}")

    # ---- 1: write a non-default set, let it persist ------------------------
    print("\n-- write non-default 6-register set + persist --")
    write_holdings(base, S, NONDEFAULT)
    time.sleep(0.6)  # main-loop persist_service commits after the reply
    rb = read_holdings(base, S)
    record("non-default set written", rb == NONDEFAULT,
           f"{rb} (want {NONDEFAULT})")

    # ---- 2+3+4: watchdog reset, assert the FR-S21 defined state ------------
    print("\n-- watchdog reset -> assert FR-S21 defined state --")
    up_before, up_after = watchdog_reset(base, S, "wdt")
    survived = read_holdings(base, S)
    record("holdings restored from flash (== written, not defaults; "
           "FR-S39/S21)", survived == NONDEFAULT,
           f"{survived} (want {NONDEFAULT}, defaults would be {DEFAULTS})")
    record("uptime went backwards — a real reset occurred (FR-S34)",
           up_before is not None and up_after is not None
           and up_after < up_before, f"{up_before} -> {up_after} s")
    record("uptime low after reset (fresh boot)",
           up_after is not None and up_after <= 3, f"{up_after} s")
    # Bit 1 (averaging not filled) stays set for the whole averaging span
    # after a reset, so it is the robust "accumulators cleared" signal; bit 0
    # (no completed window) can already have cleared after the first window.
    st = read_status(base, S)
    record("averaging accumulator cleared after reset — status bit 1 set "
           "(FR-S21/S23/S33)",
           st is not None and (st & STATUS_AVG_NOT_FILLED) != 0,
           f"status 0x{st:04X} (bit0={'set' if st and st & 1 else 'clear'})"
           if st is not None else "no status")

    # ---- 5: restore defaults, reset again, assert defaults persist ---------
    print("\n-- restore defaults, reset again, assert defaults persist --")
    write_holdings(base, S, DEFAULTS)
    time.sleep(0.6)
    record("defaults restored", read_holdings(base, S) == DEFAULTS,
           f"{read_holdings(base, S)}")
    watchdog_reset(base, S, "wdt-2")
    after2 = read_holdings(base, S)
    record("restored defaults persist across a second reset (ping-pong)",
           after2 == DEFAULTS, f"{after2}")

    print("\n-- power-on / brown-out sources (FR-S21/S22): NOT RUN — need a "
          "programmable supply (integrationPlan §9.2, real-PCB) --")

    # Leave the bench as found: the tester poller running against this DUT.
    poller_type = "speed" if args.build == "speed" else "direction"
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + "/wind/start",
            data=json.dumps({"type": poller_type, "addr": S,
                             "interval_ms": 3000}).encode(),
            headers={"Content-Type": "application/json"}), timeout=6)
    except Exception:
        pass

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("RESET MATRIX " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
