"""FR-S38 wind-direction float-fault over RS-485 (the last §9.1 row).

With the wiper physically lifted off PA2, the firmware's pull-toggle
detector (wd_wiper_floating) must flag the open input: DIR_FAULT (status
bit 2) set and the dir_instant/dir_avg registers reading the 65535 fault
sentinel. The fault is sticky (FR-S38) and clears only when a real source
re-drives PA2 — run with --expect driven after reconnecting to assert
recovery.

Applies to the direction build (addr 31, dir raw at 30005) and the
combined build (addr 32, dir raw at 30013 — same wd_wiper_floating code
path, gated on HAVE_WIND_DIRECTION).

Run:  .venv-m2k\\Scripts\\python.exe rs485_float_check.py \
          --build combined --expect fault
      (reconnect the divider, then)
      .venv-m2k\\Scripts\\python.exe rs485_float_check.py \
          --build combined --expect driven
"""

import argparse
import json
import sys
import urllib.request

RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def api(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--build", choices=["direction", "combined"],
                    default="combined")
    ap.add_argument("--slave", type=int, default=None)
    ap.add_argument("--expect", choices=["fault", "driven"], default="fault",
                    help="fault = PA2 floating; driven = PA2 re-driven")
    args = ap.parse_args()
    S = args.slave if args.slave is not None else (
        32 if args.build == "combined" else 31)
    adc_idx = 12 if args.build == "combined" else 4  # 30013 vs 30005
    ident_want = 0x0301 if args.build == "combined" else 0x0201

    r = api(args.base, "/api/v1/modbus",
            {"slave": S, "function": 4, "register": 0, "count": adc_idx + 1})
    if not r.get("ok"):
        print(f"read failed: {r.get('status')}")
        return 1
    g = r["registers"]
    inst, avg, status, adc = g[0], g[2], g[5], g[adc_idx]
    fault_bit = bool(status & 0x0004)
    print(f"{args.build} @ {S}: ident 0x{g[6]:04X}, dir_inst {inst}, "
          f"dir_avg {avg}, status 0x{status:04X}, dir_raw {adc}")

    record("identification correct for build", g[6] == ident_want,
           f"0x{g[6]:04X}")
    if args.expect == "fault":
        record("FR-S38: DIR_FAULT status bit set (PA2 floating)",
               fault_bit, f"status 0x{status:04X}")
        record("FR-S38: dir_instant == 65535 fault sentinel", inst == 65535,
               f"{inst}")
        record("FR-S38: dir_avg == 65535 fault sentinel", avg == 65535,
               f"{avg}")
    else:  # driven — recovery
        record("FR-S38 recovery: DIR_FAULT bit clear (PA2 re-driven)",
               not fault_bit, f"status 0x{status:04X}")
        record("FR-S38 recovery: dir_instant is a real angle (0..3599)",
               inst <= 3599, f"{inst / 10:.1f} deg")
        record("dir raw ADC back in range 0..1023", 0 <= adc <= 1023,
               f"{adc}")

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
