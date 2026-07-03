"""Stage-D HIL check: measurement services on the product firmware.

Speed build (M2K W2 -> PC1 pulses, AWG runs independently of the Modbus
master on DIO0): count accuracy at 10/100 Hz with the FR-S06 formula
cross-checked ATOMICALLY against the same response's raw count (which is
FR-S24's consistency rule), the FR-S07 cut-off branch, FR-S30
window-change take-effect, and FR-S27 saturation at 100 kHz.

Direction build (9.92k/9.88k divider on PA2): live angle vs the divider
ratio, FR-S12 offset application and wrap, fault bit clear.

Run:  .venv-m2k\\Scripts\\python.exe meas_check.py --build speed|direction
"""

import argparse
import sys
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc
from mb_check import Bus, frame, transact
from m2k_signal_check import open_calibrated

C_SCALED = 980
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def formula(count, window_ms, cutoff):
    if count == 65535:
        return 65535
    v = (count * C_SCALED * 10) // window_ms
    v = min(v, 65535)
    return 0 if v < cutoff else v


class Rig:
    """Fresh M2K context per stimulus configuration (bench quirk) with the
    Modbus master rebuilt on the same context."""

    def __init__(self, url, channel):
        self.url = url
        self.channel = channel
        self.ctx = None
        self.bus = None

    def stimulus(self, freq_hz):
        self.close()
        self.ctx = open_calibrated()
        self.bus = Bus(self.ctx)
        if freq_hz:
            aout = self.ctx.getAnalogOut()
            aout.enableChannel(1, True)
            # AWG rate ladder: pick sr = freq * samples_per_period.
            for spp in (750, 75):
                sr = freq_hz * spp
                if sr in (750, 7500, 75000, 750000, 7500000, 75000000):
                    break
            aout.setCyclic(True)
            aout.setSampleRate(1, sr)
            half = spp // 2
            aout.push(1, [3.3] * half + [0.0] * (spp - half))
        time.sleep(0.3)

    def tx(self, req):
        resp, _ = transact(self.url, self.bus, self.channel, req)
        return resp

    def close(self):
        if self.ctx:
            libm2k.contextClose(self.ctx)
            self.ctx = None


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
                            "clientInfo": {"name": "meas-check", "version": "0.1"}})
    rig = Rig(url, args.saleae_channel)

    def read_block():
        """Atomic FC04 of 0x0000..0x0005: dir, speed, dir_avg, speed_avg,
        raw, status — one response = one coherent snapshot (FR-S24)."""
        r = rig.tx(frame(bytes([slave, 0x04, 0, 0, 0, 6])))
        if r and len(r) == 17 and r[1] == 0x04:
            return [(r[3 + 2 * i] << 8) | r[4 + 2 * i] for i in range(6)]
        return None

    def write_reg(addr, val, name):
        req = frame(bytes([slave, 0x06, addr >> 8, addr & 0xFF,
                           val >> 8, val & 0xFF]))
        r = rig.tx(req)
        ok = r == req
        if not ok:
            record(f"setup write {name}", False, r.hex() if r else "none")
        return ok

    try:
        if args.build == "speed":
            # Baseline: no stimulus.
            rig.stimulus(0)
            time.sleep(2.5)
            b = read_block()
            record("baseline: count 0, speed 0", b is not None and
                   b[4] == 0 and b[1] == 0, f"{b}")

            # Count + formula consistency at 10 and 100 Hz (default window
            # 1000 ms, cutoff 4). The formula check against the SAME
            # response's count is FR-S24's rule.
            for f in (10, 100):
                rig.stimulus(f)
                time.sleep(2.8)  # ≥2 full windows under stimulus
                b = read_block()
                if b is None:
                    record(f"{f} Hz block read", False, "no reply")
                    continue
                count, inst = b[4], b[1]
                ok_c = abs(count - f) <= 2
                ok_f = inst == formula(count, 1000, 4)
                record(f"{f} Hz: count (FR-S05)", ok_c, f"count={count} expect {f}±2")
                record(f"{f} Hz: 30002==formula(30005) (FR-S06/S24)", ok_f,
                       f"inst={inst} formula={formula(count, 1000, 4)}")

            # FR-S07 cut-off branch: raise 40004 to 50 (5.0 m/s); at 1 Hz,
            # v = 1*9.8 = 9 (0.1 m/s units) < 50 -> 30002 = 0, count kept.
            rig.stimulus(1)
            if write_reg(3, 50, "cutoff=50"):
                time.sleep(3.5)
                b = read_block()
                ok = b and b[4] >= 1 and b[1] == 0
                record("cut-off: 30002=0, 30005 kept (FR-S07/S24)", ok,
                       f"count={b[4] if b else '?'} inst={b[1] if b else '?'}")
                write_reg(3, 4, "cutoff=4 restore")

            # FR-S30: window change takes effect (new duration counts).
            rig.stimulus(10)
            if write_reg(1, 3000, "window=3000"):
                time.sleep(7.0)  # ≥2 full 3 s windows
                b = read_block()
                count, inst = (b[4], b[1]) if b else (None, None)
                ok_c = count is not None and abs(count - 30) <= 3
                ok_f = count is not None and inst == formula(count, 3000, 4)
                record("window 3000: count ~30 (FR-S30/S05)", ok_c,
                       f"count={count} expect 30±3")
                record("window 3000: formula holds", ok_f,
                       f"inst={inst} formula={formula(count, 3000, 4) if count is not None else '?'}")
                write_reg(1, 1000, "window=1000 restore")
                time.sleep(2.5)

            # FR-S27: 100 kHz x 1 s = 100k edges -> saturation.
            rig.stimulus(100000)
            time.sleep(2.8)
            b = read_block()
            record("saturation: 30005=65535, 30002=65535 (FR-S27)",
                   b is not None and b[4] == 65535 and b[1] == 65535,
                   f"count={b[4] if b else '?'} inst={b[1] if b else '?'}")

        else:  # direction build — divider on PA2, no AWG stimulus needed
            rig.stimulus(0)
            time.sleep(1.5)
            b = read_block()
            if b is None:
                record("block read", False, "no reply")
                return 1
            raw10, inst, status = b[4], b[0], b[5]
            expect = ((raw10 * 16 * 3600 + 8192) >> 14) % 3600
            record("divider angle vs raw (FR-S28/S12 offset=0)",
                   abs(inst - expect) <= 2 and 1750 <= inst <= 1850,
                   f"raw10={raw10} inst={inst} expect~{expect}")
            record("fault bit clear (FR-S38)", (status & 4) == 0,
                   f"status=0x{status:04X}")

            # FR-S12: offset applied + wrap.
            for off, name in ((900, "offset 900"), (2000, "offset 2000 (wrap)")):
                if write_reg(0, off, name):
                    time.sleep(0.6)
                    b2 = read_block()
                    want = (expect + off) % 3600
                    got = b2[0] if b2 else None
                    dev = min(abs(got - want), 3600 - abs(got - want)) if got is not None else 9999
                    record(f"FR-S12 {name}", dev <= 15,
                           f"inst={got} expect~{want}")
            write_reg(0, 0, "offset restore")
    finally:
        rig.close()

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("MEAS CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
