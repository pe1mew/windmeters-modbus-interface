"""FR-S39 holding-register persistence across reset (over RS-485).

Requires a *_test build (TEST_HOOKS) so the FR-S20 watchdog-hang hook
(holding 0x00FF := 0xDEAD -> stop feeding -> IWDG reset) gives a
controllable reset without a power cycle. The persistence code is identical
in the release build.

Sequence, via the tester machine API at the DUT address:
  1. write non-default settings via FC16, read back
  2. record uptime (30008), then trigger the watchdog hang
  3. wait for the DUT to reset and come back
  4. assert the settings SURVIVED (== what was written, not the defaults)
     and uptime went backwards (a reset really happened)
  5. restore defaults, reset again, assert the defaults now persist
     (proves the ping-pong store handles successive saves)

Run:  .venv-m2k\\Scripts\\python.exe rs485_persist_check.py
      [--slave 32] [--build combined]
"""

import argparse
import json
import sys
import time
import urllib.request

RESULTS = []
DEFAULTS = [0, 1000, 10, 4]      # TDS §2.8
NONDEFAULT = [900, 2000, 20, 10]  # FR-S31-legal (avg*1000 >= window)
HANG_REG = 0x00FF
HANG_MAGIC = 0xDEAD


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


def read_holdings(base, S):
    r = api(base, {"slave": S, "function": 3, "register": 0, "count": 4})
    return r["registers"] if r.get("ok") else None


def read_uptime(base, S):
    r = api(base, {"slave": S, "function": 4, "register": 7, "count": 1})
    return r["registers"][0] if r.get("ok") else None


def write_holdings(base, S, vals):
    return api(base, {"slave": S, "function": 16, "register": 0,
                      "values": vals})


def trigger_reset_and_wait(base, S, tag):
    """Fire the watchdog-hang hook, then wait for the DUT to come back."""
    up_before = read_uptime(base, S)
    api(base, {"slave": S, "function": 6, "register": HANG_REG,
               "values": [HANG_MAGIC]})  # DUT echoes, then hangs
    time.sleep(0.3)
    # while hung, reads time out; after the IWDG reset (~1–2.5 s) + reboot,
    # they succeed again.
    t0 = time.time()
    back = None
    while time.time() - t0 < 12:
        up = read_uptime(base, S)
        if up is not None and (up_before is None or up <= up_before):
            back = up
            break
        time.sleep(0.4)
    record(f"[{tag}] DUT reset and recovered", back is not None,
           f"uptime {up_before} -> {back}")
    return up_before, back


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--slave", type=int, default=32)
    ap.add_argument("--build", default="combined")
    args = ap.parse_args()
    base, S = args.base, args.slave

    st = api(base, {"slave": S, "function": 4, "register": 6, "count": 1})
    if not st.get("ok"):
        print(f"DUT not responding at {S}: {st.get('status')}")
        return 1
    print(f"DUT @ {S}: ident 0x{st['registers'][0]:04X} ({args.build})")
    if api(base, {"slave": S, "function": 6, "register": HANG_REG,
                  "values": [0]}).get("status") == "exception":
        print("!! 0x00FF unmapped — this is a RELEASE build; flash the "
              "*_test build for the watchdog-hang hook.")
        return 1
    # quiet the tester poller so its traffic doesn't collide with the resets
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + "/wind/stop", data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=6)
    except Exception:
        pass

    print(f"\ninitial holdings: {read_holdings(base, S)}")

    # ---- 1: write non-defaults, confirm, let them persist ------------------
    print("\n-- write non-default settings + persist --")
    write_holdings(base, S, NONDEFAULT)
    time.sleep(0.5)  # let the main loop's persist_service commit to flash
    rb = read_holdings(base, S)
    record("non-default settings written", rb == NONDEFAULT,
           f"{rb} (want {NONDEFAULT})")

    # ---- 2+3: reset, assert survival --------------------------------------
    print("\n-- watchdog reset, assert settings SURVIVE --")
    up_before, up_after = trigger_reset_and_wait(base, S, "cycle-1")
    survived = read_holdings(base, S)
    record("settings persisted across reset (== written, not defaults)",
           survived == NONDEFAULT,
           f"{survived} (want {NONDEFAULT}, defaults would be {DEFAULTS})")
    record("uptime went backwards (a real reset occurred)",
           up_before is not None and up_after is not None
           and up_after < up_before,
           f"{up_before} -> {up_after} s")

    # ---- 4+5: restore defaults, reset again, assert defaults persist -------
    print("\n-- restore defaults, reset again, assert defaults persist --")
    write_holdings(base, S, DEFAULTS)
    time.sleep(0.5)
    record("defaults restored", read_holdings(base, S) == DEFAULTS,
           f"{read_holdings(base, S)}")
    trigger_reset_and_wait(base, S, "cycle-2")
    after2 = read_holdings(base, S)
    record("restored defaults persisted across a second reset",
           after2 == DEFAULTS, f"{after2}")

    # leave the poller running again
    try:
        urllib.request.urlopen(urllib.request.Request(
            base + "/wind/start",
            data=json.dumps({"type": "direction", "addr": S,
                             "interval_ms": 3000}).encode(),
            headers={"Content-Type": "application/json"}), timeout=6)
    except Exception:
        pass

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
