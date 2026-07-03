"""Stage-E HIL check: the averaging engine on the product firmware.

Speed build (M2K W2 pulses): steady-state convergence (FR-S13), status
bit 1 lifecycle (FR-S33), the FR-S23 anti-zero-padding trap after an
accumulator clear, gust capture and decay (FR-S37), step response inside
one averaging window (FR-S13), and the two-stage boxcar at N = 6000
(FR-S31) with the device staying responsive.

Direction build (divider on PA2): steady circular mean == instantaneous,
FR-S30 retain-on-clear, bit lifecycle.

Run:  .venv-m2k\\Scripts\\python.exe avg_check.py --build speed|direction
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc
from mb_check import frame
from meas_check import Rig

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
    slave = 30 if args.build == "speed" else 31

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "avg-check", "version": "0.1"}})
    rig = Rig(url, args.saleae_channel)

    def read_block():
        """[dir, speed, dir_avg, speed_avg, raw, status, ..., gust] 12 regs."""
        r = rig.tx(frame(bytes([slave, 0x04, 0, 0, 0, 12])))
        if r and len(r) == 29 and r[1] == 0x04:
            return [(r[3 + 2 * i] << 8) | r[4 + 2 * i] for i in range(12)]
        return None

    def write_reg(addr, val, name):
        req = frame(bytes([slave, 0x06, addr >> 8, addr & 0xFF,
                           val >> 8, val & 0xFF]))
        r = rig.tx(req)
        if r != req:
            record(f"setup write {name}", False, r.hex() if r else "none")
            return False
        return True

    def restore_defaults():
        req = frame(bytes([slave, 0x10, 0, 1, 0, 2, 4, 0x03, 0xE8, 0, 10]))
        rig.tx(req)  # 40002=1000, 40003=10 in one atomic pair

    try:
        if args.build == "speed":
            # Steady state: 10 Hz -> 98; after >= one avg window (10 s),
            # 30004 == 30002 and bit1 cleared (FR-S13/S33).
            rig.stimulus(10)
            time.sleep(14.5)  # onset windows must slide fully out of the ring
            b = read_block()
            record("steady: 30004==30002 (FR-S13)",
                   b and b[1] == 98 and abs(b[3] - 98) <= 1,
                   f"inst={b[1] if b else '?'} avg={b[3] if b else '?'}")
            record("steady: bit1 cleared (FR-S33)",
                   b and (b[5] & 2) == 0, f"status=0x{b[5]:04X}" if b else "?")
            record("steady: gust==98 (FR-S37)",
                   b and b[11] == 98, f"gust={b[11] if b else '?'}")

            # FR-S23 trap: clear the accumulator (40003 write), read after
            # ~2.5 s: a zero-padded mean would read ~20; the partial mean
            # must read ~98. Bit1 must be set again until 20 windows fill.
            if write_reg(2, 20, "avg=20"):
                b1 = read_block()  # right after the clear (<1 window)
                time.sleep(2.6)
                b2 = read_block()
                record("FR-S30: 30004 retained right after clear",
                       b1 and abs(b1[3] - 98) <= 1, f"avg={b1[3] if b1 else '?'}")
                record("FR-S23: partial mean, no zero-padding",
                       b2 and abs(b2[3] - 98) <= 1,
                       f"avg={b2[3] if b2 else '?'} (zero-padded would be ~25)")
                record("FR-S30: bit1 re-asserted",
                       b2 and (b2[5] & 2) == 2, f"status=0x{b2[5]:04X}" if b2 else "?")
            restore_defaults()
            time.sleep(1.5)

            # Gust: burst 100 Hz for ~2.5 s, back to 10 Hz. Gust jumps to
            # 980 and holds while the mean stays far below; after a full
            # averaging window the burst leaves the boxcar and gust decays.
            rig.stimulus(100)
            time.sleep(2.6)
            rig.stimulus(10)
            time.sleep(2.6)
            b = read_block()
            # Windows straddling the frequency switch legitimately carry
            # ±1 pulse -> gust up to ~989.
            record("gust captured (FR-S37)",
                   b and 965 <= b[11] <= 995 and 98 <= b[3] <= 700,
                   f"gust={b[11] if b else '?'} avg={b[3] if b else '?'}")
            time.sleep(12)
            b = read_block()
            record("gust decays after the window slides",
                   b and b[11] <= 120, f"gust={b[11] if b else '?'}")

            # Step response: to 100 Hz steady; within one averaging window
            # + one measurement window, 30004 reaches 980 (FR-S13).
            rig.stimulus(100)
            time.sleep(11.5)
            b = read_block()
            # The DUT window is HSI-paced (+0.3%): at 100 Hz it alternates
            # 100/101 pulses -> inst 980/989 legitimately (FR-S06 physics).
            record("step settles in one avg window (FR-S13)",
                   b and 980 <= b[1] <= 990 and 978 <= b[3] <= 990,
                   f"inst={b[1] if b else '?'} avg={b[3] if b else '?'}")

            # Two-stage boxcar: 40002=100, 40003=600 -> N=6000, blocks of
            # 94. At 10 Hz each 100 ms window counts 1 -> inst 98. After
            # ~15 s the partial mean must read 98 and the device must stay
            # inside its latency budget (implicit: transactions work).
            rig.stimulus(10)
            if write_reg(2, 600, "avg=600") and write_reg(1, 100, "window=100"):
                time.sleep(15)
                b = read_block()
                record("two-stage N=6000: partial mean 98 (FR-S31/S23)",
                       b and abs(b[3] - 98) <= 1,
                       f"avg={b[3] if b else '?'} inst={b[1] if b else '?'}")
                record("two-stage: bit1 still set (600 s unfilled)",
                       b and (b[5] & 2) == 2, f"status=0x{b[5]:04X}" if b else "?")
            restore_defaults()

        else:  # direction build
            rig.stimulus(0)
            time.sleep(12.5)
            b = read_block()
            record("steady: 30003==30001 (FR-S14)",
                   b and b[0] != 65535 and abs(b[2] - b[0]) <= 1,
                   f"inst={b[0] if b else '?'} avg={b[2] if b else '?'}")
            record("steady: bit1 cleared", b and (b[5] & 2) == 0,
                   f"status=0x{b[5]:04X}" if b else "?")
            if write_reg(2, 20, "avg=20"):
                b1 = read_block()
                record("FR-S30: 30003 retained right after clear",
                       b1 and b1[2] == b[2],
                       f"avg={b1[2] if b1 else '?'} (was {b[2] if b else '?'})")
                b2 = None
                time.sleep(2.6)
                b2 = read_block()
                record("FR-S23: partial circular mean, no dilution",
                       b2 and abs(b2[2] - b[0]) <= 2,
                       f"avg={b2[2] if b2 else '?'}")
            restore_defaults()
    finally:
        rig.close()

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("AVG CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
