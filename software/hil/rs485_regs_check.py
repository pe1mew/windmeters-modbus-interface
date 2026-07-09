"""Full register read/write matrix over real RS-485, §9.1 follow-up:
the windmeters-modbus-interface-tester is the bus master, driven through
its machine API (tester manual/api.md): POST /api/v1/modbus executes one
transaction and returns the outcome INCLUDING the raw TX/RX frames, so
every CRC is re-verified here without trusting the tester's decode.

Covers, over the wire (both builds via --build; the holding matrix is
identical on both per FR-MB27, the input-register active/zero map differs):
  - FC04: full 12-register image, every register singly, map-edge and
    straddle reads -> exception 02 (FR-MB13/14), identification/uptime/
    served plausibility; per-build active/zero registers (speed: pulse-
    age tracks uptime; direction: raw ADC in range, no DIR_FAULT)
  - direction only: 40001 offset applied to the reported angle with 3600
    wraparound (FR-S25/S26)
  - FC03: defaults, singles, map edge (FR-MB27, TDS §2.8 defaults)
  - FC06: min/max/mid accepted + byte-exact echo (FR-MB30), out-of-range
    rejected with exception 03 and NO state change (FR-MB19), unmapped ->
    exception 02 (FR-MB15), TEST_HOOKS register absent on release build
  - FC16: block write + read-back, atomic reject on one bad value
    (FR-MB22), atomic reject on FR-S31 cross-rule violation, partial-
    unmapped range rejected
  - FR-S31 cross rule via FC06 (avg*1000 >= window)
  - FR-S30: status bits 0/1 re-assert after a valid 40002/40003 write,
    bit 0 clears after the first window, bit 1 after the averaging fill
  - FR-MB05 address filter: every other candidate address stays silent
  - Consistency: DUT served-counter delta == transactions answered,
    DUT crc_error_count untouched, master-side crc_errors delta == 0

Run:  .venv-m2k\\Scripts\\python.exe rs485_regs_check.py --build speed
      .venv-m2k\\Scripts\\python.exe rs485_regs_check.py --build direction
      [--base http://windmeter-tester.local] [--slave N]

The DUT ends at defaults with the tester's wind poller restarted.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rs485_check import crc16

RESULTS = []
COUNTED = {"served": 0, "multi_attempt": 0}
DUT_SLAVE = None  # set in main(); mb() counts served only for this address


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def api(base, path, body=None, timeout=20.0):
    if body is None:
        req = urllib.request.Request(base + path)
    else:
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def frame_crc_ok(hex_str):
    if not hex_str:
        return False
    d = bytes(int(x, 16) for x in hex_str.split())
    return len(d) >= 4 and crc16(d[:-2]) == d[-2:]


def mb(base, slave, fc, register, count=None, values=None, fmt=None):
    body = {"slave": slave, "function": fc, "register": register}
    if count is not None:
        body["count"] = count
    if values is not None:
        body["values"] = values
    if fmt is not None:
        body["register_format"] = fmt
    r = api(base, "/api/v1/modbus", body)
    # Independent wire check on everything the tester reports it sent/got.
    if r.get("raw_tx") and not frame_crc_ok(r["raw_tx"]):
        record("wire: raw_tx CRC self-check", False, r["raw_tx"])
    if r.get("raw_rx") and not frame_crc_ok(r["raw_rx"]):
        record("wire: raw_rx CRC self-check", False, r["raw_rx"])
    if slave == DUT_SLAVE and r.get("status") in ("ok", "exception"):
        COUNTED["served"] += 1
        if r.get("attempts", 1) > 1:
            COUNTED["multi_attempt"] += 1
            COUNTED["served"] += r["attempts"] - 1  # DUT may have served extras
    return r


def expect_ok(base, name, slave, fc, register, count=None, values=None,
              want=None, fmt=None):
    r = mb(base, slave, fc, register, count=count, values=values, fmt=fmt)
    ok = r.get("ok") and r.get("status") == "ok"
    det = f"status {r.get('status')}"
    if ok and want is not None:
        got = r.get("registers")
        ok = got == want
        det = f"read {got}" + ("" if ok else f" != want {want}")
    if ok and fc == 6:
        # FR-MB30: FC06 response is a byte-exact echo of the request.
        ok = r.get("raw_tx") == r.get("raw_rx")
        det += "; echo byte-exact" if ok else \
               f"; ECHO MISMATCH tx={r.get('raw_tx')} rx={r.get('raw_rx')}"
    record(name, bool(ok), det)
    return r


def expect_exc(base, name, code, slave, fc, register, count=None, values=None):
    r = mb(base, slave, fc, register, count=count, values=values)
    ok = (not r.get("ok") and r.get("status") == "exception"
          and r.get("exception_code") == code)
    record(name, ok,
           f"status {r.get('status')} exc {r.get('exception_code')} "
           f"(want {code})")
    return r


def read_holdings(base, slave):
    r = mb(base, slave, 3, 0, count=4)
    return r.get("registers") if r.get("ok") else None


def read_inputs(base, slave):
    r = mb(base, slave, 4, 0, count=12)
    return r.get("registers") if r.get("ok") else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://windmeter-tester.local")
    ap.add_argument("--build", choices=["speed", "direction", "combined"],
                    default="speed",
                    help="which firmware variant is flashed on the DUT")
    ap.add_argument("--slave", type=int, default=None,
                    help="DUT address (default 30 speed / 31 direction / 32 combined)")
    ap.add_argument("--speed-live", action="store_true",
                    help="assert live speed data (a PC1 pulse source is wired)")
    ap.add_argument("--skip-status-timing", action="store_true",
                    help="skip the ~15 s FR-S30 status-bit timing block")
    args = ap.parse_args()
    global DUT_SLAVE
    build = args.build
    is_dir = build == "direction"
    is_combined = build == "combined"
    has_speed = build in ("speed", "combined")
    has_direction = build in ("direction", "combined")
    S = args.slave if args.slave is not None else {
        "speed": 30, "direction": 31, "combined": 32}[build]
    DUT_SLAVE = S
    base = args.base
    ident_want = {"speed": 0x0101, "direction": 0x0201, "combined": 0x0301}[build]
    # Input map length (TDS §2.7): combined adds the direction raw ADC at
    # 30013 (0x000C), extending the map edge from 0x000C to 0x000D.
    map_len = 13 if is_combined else 12
    adc_idx = 12 if is_combined else 4  # direction raw ADC register index
    # Read-0 addresses per build; none on combined (both sensors live).
    if is_combined:
        zero_regs = set()
    elif is_dir:
        zero_regs = {1, 3, 10, 11}
    else:
        zero_regs = {0, 2}
    print(f"=== register matrix: {build} build, address {S} "
          f"(map {map_len} regs) ===")

    st0 = api(base, "/api/v1/status")
    print(f"tester fw {st0.get('fw_version')}, modbus "
          f"{st0['modbus']['timeout_ms']} ms x{st0['modbus']['retries']} "
          f"retries, master crc_errors {st0['modbus']['crc_errors']}, "
          f"timeouts {st0['modbus']['timeouts']}")
    if st0.get("busy", {}).get("wind_poll_active"):
        api(base, "/wind/stop", {})
        time.sleep(0.5)
        print("wind poller stopped for the matrix")

    # ---- A: input-register image (FC04) ------------------------------------
    print("\n-- FC04 input registers --")
    r = mb(base, S, 4, 0, count=map_len)
    inp = r.get("registers") if r.get("ok") else None
    record(f"FC04 block read 0x0000 x{map_len}",
           inp is not None and len(inp) == map_len, f"{inp}")
    if inp is None:
        return 1
    # inp[9] is the served count BEFORE the baseline read itself (the DUT
    # samples it while handling the frame) — so the baseline transaction,
    # already in COUNTED, is correctly part of the expected delta.
    served_start = inp[9]
    if zero_regs:
        inactive_label = ("speed regs 30002/30004 + pulse-age/gust 30011/30012"
                          if is_dir else "direction regs 30001/30003")
        record(f"inactive-build regs read 0 ({inactive_label})",
               all(inp[i] == 0 for i in zero_regs),
               f"{[inp[i] for i in sorted(zero_regs)]}")
    record(f"30007 identification == 0x{ident_want:04X} "
           f"({build} build, fw v1)",
           inp[6] == ident_want, f"0x{inp[6]:04X}")
    record("30008 uptime plausible (>10 s since flash)",
           inp[7] > 10, f"{inp[7]} s")
    record("30009 DUT crc_error_count == 0", inp[8] == 0, f"{inp[8]}")
    if has_direction:
        record(f"direction raw ADC (300{'13' if is_combined else '05'}) "
               "in range 0..1023 (PA2 driven)",
               0 <= inp[adc_idx] <= 1023, f"{inp[adc_idx]}")
        record("30001 dir_instant valid (0..3599, not 65535 fault)",
               inp[0] <= 3599, f"{inp[0] / 10:.1f} deg")
        record("30006 status has no DIR_FAULT bit (PA2 not floating)",
               not (inp[5] & 0x0004), f"0x{inp[5]:04X}")
    if has_speed:
        # 30011 pulse-age climbs with uptime while no pulses arrive; with a
        # live PC1 stimulus it resets toward 0 instead.
        if args.speed_live:
            record("30002/30005 live speed data (PC1 pulses)",
                   inp[1] > 0 and inp[4] > 0,
                   f"inst {inp[1] / 10:.1f} m/s, count {inp[4]}")
            record("30011 pulse-age low (pulses arriving)",
                   inp[10] <= 3, f"{inp[10]} s")
        else:
            record("30011 pulse-age tracks uptime (no anemometer)",
                   abs(inp[10] - inp[7]) <= 2, f"age {inp[10]} vs uptime {inp[7]}")
    if is_combined:
        record("both sensors present in one image (dir + speed slots)",
               inp[0] != 0 and inp[6] == ident_want,
               f"dir {inp[0] / 10:.1f} deg / speed {inp[1] / 10:.1f} m/s")

    singles = []
    for a in range(map_len):
        rr = mb(base, S, 4, a, count=1)
        singles.append(rr["registers"][0] if rr.get("ok") else None)
    # uptime/served/pulse-age drift; direction inst/avg/adc + live speed
    # jitter, so compare the identity/steady regs exactly, allow the rest.
    drift = {7, 9, 10}
    if has_direction:
        drift |= {0, 2, adc_idx}
    if has_speed and args.speed_live:
        drift |= {1, 3, 4, 11}
    ok = all(singles[i] == inp[i] for i in range(map_len) if i not in drift) \
        and all(singles[i] is not None for i in drift)
    record(f"FC04 single reads x{map_len} consistent with block image", ok,
           f"{singles}")

    edge = map_len  # first unmapped raw address (0x000C or 0x000D)
    if is_combined:
        expect_ok(base, "FC04 read 0x000C (30013 dir-raw, combined-only)",
                  S, 4, 0x000C, count=1)
    expect_exc(base, f"FC04 read 0x{edge:04X} (map edge) -> exc 02 (FR-MB13)",
               2, S, 4, edge, count=1)
    expect_exc(base, f"FC04 read 0x{edge - 5:04X} x6 (straddles edge) "
               "-> exc 02 (FR-MB14)", 2, S, 4, edge - 5, count=6)

    # ---- A2 (direction present): offset -> reported angle, wraparound -------
    if has_direction:
        print("\n-- direction offset applied to angle (FR-S25/S26 wrap) --")
        expect_ok(base, "40001 offset := 0 (baseline)", S, 6, 0, values=[0])
        time.sleep(0.3)
        base_ang = mb(base, S, 4, 0, count=1)["registers"][0]
        print(f"    baseline angle (offset 0): {base_ang / 10:.1f} deg")
        for off in (900, 1800, 3599):
            expect_ok(base, f"40001 offset := {off}", S, 6, 0, values=[off])
            time.sleep(0.3)
            ang = mb(base, S, 4, 0, count=1)["registers"][0]
            up = (base_ang + off) % 3600     # convention-agnostic: try both
            dn = (base_ang - off) % 3600
            d_up = min((ang - up) % 3600, (up - ang) % 3600)
            d_dn = min((ang - dn) % 3600, (dn - ang) % 3600)
            err = min(d_up, d_dn)
            record(f"angle shifts by offset {off / 10:.0f} deg (3600 wrap)",
                   err <= 15,
                   f"base {base_ang / 10:.1f} {'+' if d_up <= d_dn else '-'} "
                   f"{off / 10:.1f} -> {ang / 10:.1f} deg (err {err} LSB)")
        expect_ok(base, "40001 offset := 0 (restore)", S, 6, 0, values=[0])

    # ---- B: holding defaults (FC03) ----------------------------------------
    print("\n-- FC03 holding registers --")
    expect_ok(base, "FC03 block read: TDS §2.8 defaults [0,1000,10,4]",
              S, 3, 0, count=4, want=[0, 1000, 10, 4])
    for a, want in ((0, 0), (1, 1000), (2, 10), (3, 4)):
        expect_ok(base, f"FC03 single 4000{a+1}", S, 3, a, count=1,
                  want=[want])
    expect_exc(base, "FC03 read 0x0004 (map edge) -> exc 02", 2, S, 3, 4,
               count=1)

    # ---- C: FC06 write matrix ----------------------------------------------
    print("\n-- FC06 single writes: range edges, rejects, echo --")
    # 40001 offset [0..3599]
    expect_ok(base, "40001 offset := 3599 (max)", S, 6, 0, values=[3599])
    expect_ok(base, "40001 read-back 3599", S, 3, 0, count=1, want=[3599])
    expect_ok(base, "40001 offset := 1800", S, 6, 0, values=[1800])
    expect_exc(base, "40001 := 3600 -> exc 03, no clamp (FR-MB19)",
               3, S, 6, 0, values=[3600])
    expect_ok(base, "40001 unchanged after reject", S, 3, 0, count=1,
              want=[1800])
    # 40003 averaging to max first so the window max is cross-legal (FR-S31)
    expect_ok(base, "40003 averaging := 600 (max)", S, 6, 2, values=[600])
    # 40002 window [100..60000]
    expect_ok(base, "40002 window := 100 (min)", S, 6, 1, values=[100])
    expect_ok(base, "40002 window := 60000 (max, avg=600 makes it legal)",
              S, 6, 1, values=[60000])
    expect_exc(base, "40002 := 99 -> exc 03", 3, S, 6, 1, values=[99])
    expect_exc(base, "40002 := 60001 -> exc 03", 3, S, 6, 1, values=[60001])
    expect_ok(base, "40002 unchanged after rejects", S, 3, 1, count=1,
              want=[60000])
    # FR-S31 cross-rule via FC06
    expect_exc(base, "40003 := 1 while window=60000 -> exc 03 (FR-S31)",
               3, S, 6, 2, values=[1])
    expect_ok(base, "40003 unchanged after cross reject", S, 3, 2, count=1,
              want=[600])
    expect_ok(base, "40002 window := 1000 (back to sane)", S, 6, 1,
              values=[1000])

    # 40004 cutoff [0..50] — the register whose write coincided with the
    # 2026-07-06 break failure; every accepted write is followed by a full
    # read to prove the DUT keeps serving (the original symptom).
    print("\n-- 40004 low-speed cutoff (incident register) --")
    for v in (0, 50, 4):
        expect_ok(base, f"40004 cutoff := {v}", S, 6, 3, values=[v])
        alive = read_inputs(base, S)
        record(f"DUT serves FC04 after cutoff:={v} (incident regression)",
               alive is not None and alive[6] == ident_want,
               "full image read OK" if alive else "NO RESPONSE")
    expect_exc(base, "40004 := 51 -> exc 03", 3, S, 6, 3, values=[51])
    expect_ok(base, "40004 unchanged after reject", S, 3, 3, count=1,
              want=[4])

    print("\n-- unmapped writes --")
    expect_exc(base, "FC06 0x0004 (unmapped) -> exc 02 (FR-MB15)",
               2, S, 6, 4, values=[1])
    expect_exc(base, "FC06 0x00FF := 0xDEAD -> exc 02 "
               "(TEST_HOOKS absent on release build)",
               2, S, 6, 0x00FF, values=[0xDEAD])
    alive = read_inputs(base, S)
    record("DUT alive after 0x00FF/0xDEAD probe (no hang hook in release)",
           alive is not None, "serves" if alive else "DEAD")

    # ---- D: FC16 ------------------------------------------------------------
    print("\n-- FC16 multiple writes: commit + atomicity --")
    expect_ok(base, "FC16 [40001..40004] := [100,2000,20,10]",
              S, 16, 0, values=[100, 2000, 20, 10])
    expect_ok(base, "read-back all 4", S, 3, 0, count=4,
              want=[100, 2000, 20, 10])
    expect_exc(base, "FC16 with one bad value (cutoff 99) -> exc 03",
               3, S, 16, 0, values=[200, 3000, 30, 99])
    expect_ok(base, "atomic: NOTHING committed (FR-MB22)", S, 3, 0, count=4,
              want=[100, 2000, 20, 10])
    expect_exc(base, "FC16 cross-violation (window 30000, avg 5) -> exc 03",
               3, S, 16, 0, values=[300, 30000, 5, 10])
    expect_ok(base, "atomic: cross reject committed nothing (FR-S31)",
              S, 3, 0, count=4, want=[100, 2000, 20, 10])
    expect_exc(base, "FC16 0x0002 x3 (partially unmapped) -> exc 02",
               2, S, 16, 2, values=[30, 10, 1])
    expect_ok(base, "atomic: unmapped-range reject committed nothing",
              S, 3, 0, count=4, want=[100, 2000, 20, 10])

    print("\n-- Modicon-format addressing through the API --")
    expect_ok(base, "write 40004:=4 via Modicon string \"40004\"",
              S, 6, "40004", values=[4], fmt="modicon")
    expect_ok(base, "read-back (raw 0x0003)", S, 3, 3, count=1, want=[4])

    # ---- E: restore defaults + FR-S30 status-bit dance ---------------------
    print("\n-- restore defaults; FR-S30 averaging-reset status bits --")
    expect_ok(base, "FC16 restore defaults [0,1000,10,4]",
              S, 16, 0, values=[0, 1000, 10, 4])
    expect_ok(base, "defaults read back", S, 3, 0, count=4,
              want=[0, 1000, 10, 4])

    if not args.skip_status_timing:
        r = mb(base, S, 4, 5, count=1)
        s_now = r["registers"][0] if r.get("ok") else None
        record("status bits 0|1 re-assert right after 40002/40003 change "
               "(FR-S30)", s_now == 3, f"status {s_now} at +~0.2 s")
        t0 = time.time()
        bit0_at = bit1_at = None
        while time.time() - t0 < 20:
            r = mb(base, S, 4, 5, count=1)
            if r.get("ok"):
                s = r["registers"][0]
                if bit0_at is None and not (s & 1):
                    bit0_at = time.time() - t0
                if not (s & 2):
                    bit1_at = time.time() - t0
                    break
            time.sleep(0.4)
        record("status bit 0 clears after first window (~1 s)",
               bit0_at is not None and bit0_at < 3.0,
               f"cleared at +{bit0_at:.1f} s" if bit0_at else "never cleared")
        record("status bit 1 clears after averaging fill (~10 s)",
               bit1_at is not None and 8.0 < bit1_at < 16.0,
               f"cleared at +{bit1_at:.1f} s" if bit1_at else "never cleared")

    # ---- F: FR-MB05 address filter over RS-485 ------------------------------
    print("\n-- other addresses stay silent --")
    silent_addrs = [a for a in (30, 31, 32, 35, 36, 37) if a != S]
    for other in silent_addrs:
        r = mb(base, other, 4, 0, count=1)
        record(f"address {other} silent (timeout) (FR-MB05/FR-S03)",
               r.get("status") == "timeout", f"status {r.get('status')}")

    # ---- G: consistency ------------------------------------------------------
    print("\n-- end-to-end consistency --")
    fin = read_inputs(base, S)
    COUNTED["served"] -= 1  # fin[9] was sampled before the final read served
    served_delta = (fin[9] - served_start) & 0xFFFF if fin else -1
    det = (f"served {served_start} -> {fin[9]} (delta {served_delta}, "
           f"expected {COUNTED['served']}"
           + (f", {COUNTED['multi_attempt']} multi-attempt transactions"
              if COUNTED['multi_attempt'] else "") + ")")
    record("DUT served-counter delta == answered transactions",
           fin is not None and served_delta == COUNTED["served"], det)
    record("DUT crc_error_count still 0 after whole matrix",
           fin is not None and fin[8] == 0, f"{fin[8] if fin else '?'}")
    st1 = api(base, "/api/v1/status")
    record("master crc_errors unchanged",
           st1["modbus"]["crc_errors"] == st0["modbus"]["crc_errors"],
           f"{st0['modbus']['crc_errors']} -> {st1['modbus']['crc_errors']}")
    record(f"master timeouts grew by exactly the "
           f"{len(silent_addrs)} silent-address probes",
           st1["modbus"]["timeouts"] - st0["modbus"]["timeouts"]
           == len(silent_addrs),
           f"{st0['modbus']['timeouts']} -> {st1['modbus']['timeouts']}")

    # Leave the bench as found: poller running against this build's DUT.
    # The tester poller polls one quantity; for combined pick direction
    # (reliably live from the divider) — the tester only accepts
    # speed|direction as a poll type.
    poller_type = "direction" if has_direction else "speed"
    api(base, "/wind/start", {"type": poller_type, "addr": S,
                              "interval_ms": 3000})
    print(f"\nwind poller restarted ({poller_type} @ {S}, 3 s)")

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
