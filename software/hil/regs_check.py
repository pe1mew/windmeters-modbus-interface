"""Stage-C HIL check: the full TDS §2.7/§2.8 register image on the product
firmware (integrationPlan.md stage C exit; seed of the stage-F acceptance
suite).

Verifies per build: the 12-register map sweep (FR-MB27 — no exception
inside the map, per-build zeros), map edge (FR-MB13), identification
(FR-S32), live uptime (FR-S34), served/CRC counters (FR-S35), pulse-age
(FR-S36, speed build), status bits (FR-S33 stage-C subset), and the §2
protocol vectors against the real map (writes, no-clamp, atomic FC16,
FR-S31, exceptions, silence rows).

Run:  .venv-m2k\\Scripts\\python.exe regs_check.py --build speed|direction
"""

import argparse
import sys
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc
from mb_check import Bus, frame, transact

RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, default=8)
    ap.add_argument("--build", choices=["speed", "direction"], default="speed")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"
    speed = args.build == "speed"
    slave = 30 if speed else 31  # jumper open
    ident = 0x0101 if speed else 0x0201

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "regs-check", "version": "0.1"}})
    ctx = libm2k.m2kOpen()
    if ctx is None:
        print("FAIL — no M2K context")
        return 1
    bus = Bus(ctx)

    def tx(req):
        resp, _ = transact(url, bus, args.saleae_channel, req)
        return resp

    def read_regs(addr, qty):
        r = tx(frame(bytes([slave, 0x04, addr >> 8, addr & 0xFF, 0, qty])))
        if r and len(r) == 5 + 2 * qty and r[1] == 0x04:
            return [(r[3 + 2 * i] << 8) | r[4 + 2 * i] for i in range(qty)]
        return None

    try:
        # Full-map sweep: one FC04 covering all 12 registers (FR-MB27).
        regs = read_regs(0x0000, 12)
        record("map sweep qty 12 (FR-MB27)", regs is not None,
               f"{regs}" if regs else "no/short reply")
        if regs is None:
            return 1

        # Map edge: 0x000C must be exception 02 (FR-MB13).
        r = tx(frame(bytes([slave, 0x04, 0, 0x0C, 0, 1])))
        record("map edge 0x000C -> exc 02 (FR-MB13)",
               r == frame(bytes([slave, 0x84, 0x02])),
               r.hex() if r else "none")

        # Identification.
        record("identification (FR-S32)", regs[6] == ident,
               f"0x{regs[6]:04X} expect 0x{ident:04X}")

        # Per-build zeros (FR-MB27) + stage-D/E placeholders.
        if speed:
            zeros = {0: "30001 dir inst", 2: "30003 dir avg"}
        else:
            zeros = {1: "30002 speed inst", 3: "30004 speed avg",
                     10: "30011 pulse age", 11: "30012 gust"}
        for idx, name in zeros.items():
            record(f"absent-sensor zero: {name}", regs[idx] == 0,
                   f"{regs[idx]}")

        # Status (FR-S33): bit0 clear once the first window completed;
        # bit1 set only while the averaging span is still filling (stage
        # E); bit2 only on a direction build with a floating wiper.
        st = regs[5]
        allowed = (0x0000, 0x0002) if speed else (0x0000, 0x0002, 0x0004, 0x0006)
        record("status bits (FR-S33)", st in allowed,
               f"0x{st:04X} allowed {[hex(a) for a in allowed]}")

        if not speed:
            # Floating PA2 -> fault sentinel on 30001/30003 when bit2 set.
            if st & 0x0004:
                record("dir fault sentinel (FR-S38)",
                       regs[0] == 65535 and regs[2] == 65535,
                       f"30001={regs[0]} 30003={regs[2]} (expect 65535)")

        # Live counters: uptime & pulse-age advance; served increments
        # per served request (our own reads are the stimulus).
        up1 = read_regs(0x0007, 3)  # uptime, crc, served
        time.sleep(2.2)
        up2 = read_regs(0x0007, 3)
        record("uptime advances (FR-S34)",
               up1 and up2 and 1 <= up2[0] - up1[0] <= 4,
               f"{up1[0] if up1 else '?'} -> {up2[0] if up2 else '?'}")
        record("served counts requests (FR-S35)",
               up1 and up2 and up2[2] == up1[2] + 1,
               f"{up1[2] if up1 else '?'} -> {up2[2] if up2 else '?'} (expect +1)")
        if speed:
            a1 = read_regs(0x000A, 1)
            time.sleep(2.2)
            a2 = read_regs(0x000A, 1)
            record("pulse age advances, no pulses (FR-S36)",
                   a1 and a2 and 1 <= a2[0] - a1[0] <= 4,
                   f"{a1[0] if a1 else '?'} -> {a2[0] if a2 else '?'}")

        # CRC counter: deliberate bad-CRC frame -> +1, silent (FR-MB02).
        c1 = read_regs(0x0008, 1)
        bad = frame(bytes([slave, 0x04, 0, 0, 0, 1]))[:-1] + b"\x00"
        r = tx(bad)
        c2 = read_regs(0x0008, 1)
        record("bad CRC: silent + counter +1 (FR-MB02)",
               r == b"" and c1 and c2 and c2[0] == c1[0] + 1,
               f"reply={'none' if not r else r.hex()}, "
               f"crc {c1[0] if c1 else '?'} -> {c2[0] if c2 else '?'}")

        # Protocol vectors against the real holding map.
        vec = [
            ("defaults (FR-S21/§2.8)",
             frame(bytes([slave, 0x03, 0, 0, 0, 4])),
             frame(bytes([slave, 0x03, 8, 0, 0, 0x03, 0xE8, 0, 10, 0, 4]))),
            ("write offset 100 + echo (FR-MB30)",
             frame(bytes([slave, 0x06, 0, 0, 0, 100])),
             frame(bytes([slave, 0x06, 0, 0, 0, 100]))),
            ("offset readback (FR-MB10)",
             frame(bytes([slave, 0x03, 0, 0, 0, 1])),
             frame(bytes([slave, 0x03, 2, 0, 100]))),
            ("write 3600 -> exc 03, no clamp (FR-MB19)",
             frame(bytes([slave, 0x06, 0, 0, 0x0E, 0x10])),
             frame(bytes([slave, 0x86, 0x03]))),
            ("FC16 atomic reject (FR-MB22)",
             frame(bytes([slave, 0x10, 0, 0, 0, 2, 4, 0, 200, 0xFD, 0xE8])),
             frame(bytes([slave, 0x90, 0x03]))),
            ("unchanged after atomic reject",
             frame(bytes([slave, 0x03, 0, 0, 0, 2])),
             frame(bytes([slave, 0x03, 4, 0, 100, 0x03, 0xE8]))),
            ("FR-S31 violating write -> exc 03",
             frame(bytes([slave, 0x06, 0, 1, 0xEA, 0x60])),
             frame(bytes([slave, 0x86, 0x03]))),
            ("FR-S31 paired write accepted",
             frame(bytes([slave, 0x10, 0, 1, 0, 2, 4, 0xEA, 0x60, 0, 60])),
             frame(bytes([slave, 0x10, 0, 1, 0, 2]))),
            ("qty 0 -> exc 03 (FR-MB28)",
             frame(bytes([slave, 0x04, 0, 0, 0, 0])),
             frame(bytes([slave, 0x84, 0x03]))),
            ("FC01 -> exc 01 (FR-MB12)",
             frame(bytes([slave, 0x01, 0, 0, 0, 1])),
             frame(bytes([slave, 0x81, 0x01]))),
            ("restore defaults (FC16)",
             frame(bytes([slave, 0x10, 0, 0, 0, 4, 8, 0, 0, 0x03, 0xE8, 0, 10, 0, 4])),
             frame(bytes([slave, 0x10, 0, 0, 0, 4]))),
        ]
        for name, req, want in vec:
            r = tx(req)
            record(name, r == want,
                   f"{r.hex() if r else 'none'}")

        # Silence row.
        r = tx(frame(bytes([247, 0x04, 0, 0, 0, 1])))
        record("wrong address silent (FR-MB05)", r == b"",
               "none" if r == b"" else (r.hex() if r else "not seen"))
    finally:
        libm2k.contextClose(ctx)

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("REGS CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
