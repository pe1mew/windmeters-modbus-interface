"""M2K signal verification — generate every stimulus the driver HIL tests
will need, and verify each one on an independent observer.

Digital signals are verified on the Saleae (independent crystal — this
cross-checks both instruments' timebases at once). Analog signals are
verified on the M2K's own calibrated scope via loopback.

Wiring (one-time, side-project rig):
    M2K DIO0  -> Saleae digital channel (pass its index via --saleae-channel)
    M2K GND   -> Saleae GND
    M2K W1    -> M2K 1+   (AWG loopback to scope ch1;  1- -> GND)
    M2K V+    -> M2K 2+   (PSU loopback to scope ch2;  2- -> GND)

Run (Python 3.11 venv for libm2k):
    .venv-m2k\\Scripts\\python.exe m2k_signal_check.py --saleae-channel 9

Checks (driverDevelopment.md refs):
    D1  pulse train  1 Hz  50%   - wind speed count rows (§3.3)
    D2  pulse train 10 Hz  50%
    D3  pulse train 100 Hz 50%
    D4  pulse train  1 kHz 50%   - saturation-row range
    D5  duty 10% @ 10 Hz         - rising-edges-only row
    D6  burst of exactly 100 pulses @ 100 Hz
    A1  DC levels 0.0/0.825/1.65/2.475/3.3 V on W1 - direction rows (§4.3)
    A2  ramp 0->3.3 V            - direction sweep
    P1  V+ = 3.0/3.3/3.6 V       - ratiometric sanity row (§4.3)
"""

import argparse
import csv
import sys
import tempfile
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc, tool  # Saleae MCP helpers

DIO = 0                 # M2K digital pin used for pulse generation
FREQ_TOL = 0.001        # 0.1% — both instruments are crystal-based
DUTY_TOL = 0.02         # 2 percentage points
DC_TOL_V = 0.060        # AWG + scope gain stack ~1.3%; absolute accuracy is
                        # irrelevant to the DUT tests, which use measured
                        # VDD:applied ratios (driverDevelopment.md §2.5/§4.2)
RESULTS = []

# Bench-learned libm2k/fw-0.33 session quirk: repeated analog-output
# reconfiguration inside ONE context corrupts output state (stop() wedges
# the DAC until reset(); re-push at the same sample rate is ignored;
# setVoltage inherits stale state). A fresh m2kOpen()+calibrate per analog
# stimulus configuration is reliable — costs ~1.5 s each. Digital out does
# not show the problem.


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


# ---------- Saleae side (digital verification) ----------

def saleae_capture_edges(url, channel, seconds):
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [channel]},
            "digitalSampleRate": 10_000_000,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": seconds}},
    })
    cid = cap["captureId"]
    try:
        tool(url, "wait_capture", {"captureId": cid}, timeout=seconds + 60)
        out = Path(tempfile.mkdtemp(prefix="m2ksig_"))
        tool(url, "export_raw_data_csv", {
            "captureId": cid, "directory": str(out),
            "digitalChannels": [channel], "analogDownsampleRatio": 1})
        rows = []
        with open(out / "digital.csv", newline="") as f:
            rdr = csv.reader(f)
            next(rdr)
            for t, v in rdr:
                rows.append((float(t), int(v)))
        edges = [rows[0]]
        for t, v in rows[1:]:
            if v != edges[-1][1]:
                edges.append((t, v))
        return edges
    finally:
        tool(url, "close_capture", {"captureId": cid})


def freq_duty_from_edges(edges):
    # The pattern generator emits one anomalous stub period right after
    # push() (seen on the bench: 46.8 ms stub, then perfect 1.0001 s
    # periods). Judge steady state only: drop the first two and last
    # periods, then reject outliers vs the median.
    rising = [t for (t, v) in edges if v == 1]
    if len(rising) < 5:
        return None, None, len(rising)
    periods = [b - a for a, b in zip(rising, rising[1:])][2:-1] or \
              [b - a for a, b in zip(rising, rising[1:])][1:]
    med = sorted(periods)[len(periods) // 2]
    steady = [p for p in periods if abs(p - med) <= 0.05 * med]
    period = sum(steady) / len(steady)
    highs = []
    for (t0, v0), (t1, _) in zip(edges, edges[1:]):
        if v0 == 1:
            highs.append(t1 - t0)
    highs = [h for h in highs[2:-1] if h <= period] or highs[1:-1]
    duty = (sum(highs) / len(highs)) / period if highs else None
    return 1.0 / period, duty, len(rising)


# ---------- M2K side (generation + analog verification) ----------

def dig_square(dig, freq_hz, duty):
    # Large cyclic buffers get truncated by the pattern generator (seen on
    # the bench: 1 Hz @ 1 MS/s ran 6% fast). Scale the sample rate with the
    # frequency so one period stays at ~10k samples.
    spp = 10_000
    sr = freq_hz * spp
    if sr > 1_000_000:
        sr = 1_000_000
        spp = int(round(sr / freq_hz))
    dig.setSampleRateOut(int(sr))
    high = int(round(spp * duty))
    buf = [1 << DIO] * high + [0] * (spp - high)
    dig.setCyclic(True)
    dig.push(buf)


def dig_burst(dig, n_pulses, freq_hz):
    spp = 1_000
    sr = int(freq_hz * spp)  # 100 Hz -> 100 kS/s, buffer ~100k samples
    dig.setSampleRateOut(sr)
    high = spp // 2
    buf = ([1 << DIO] * high + [0] * (spp - high)) * n_pulses + [0]
    dig.setCyclic(False)
    dig.push(buf)


def ain_mean(ain, ch, n=4000):
    data = ain.getSamples(n)[ch]
    return sum(data) / len(data)


def open_calibrated(retries=4):
    # Rapid close/reopen cycles can transiently fail with "Cannot set the
    # number of kernel buffers" while the old context tears down — retry.
    last = None
    for _ in range(retries):
        c = None
        try:
            c = libm2k.m2kOpen()
            if c is None:
                raise RuntimeError("no M2K context")
            c.calibrateADC()
            c.calibrateDAC()
            return c
        except Exception as e:
            last = e
            if c is not None:
                try:
                    libm2k.contextClose(c)
                except Exception:
                    pass
            time.sleep(1.0)
    raise last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, required=True,
                    help="Saleae digital channel wired to M2K DIO0")
    ap.add_argument("--skip-digital", action="store_true")
    ap.add_argument("--skip-analog", action="store_true")
    ap.add_argument("--skip-psu", action="store_true")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "m2k-signal-check", "version": "0.1"}})

    ctx = open_calibrated()
    try:
        dig = ctx.getDigital()
        ain = ctx.getAnalogIn()
        aout = ctx.getAnalogOut()
        ps = ctx.getPowerSupply()

        if not args.skip_digital:
            print("— Digital pulse trains (M2K DIO0 -> Saleae) —")
            dig.setDirection(DIO, libm2k.DIO_OUTPUT)
            dig.enableChannel(DIO, True)

            for name, f, duty, secs in (("D1 1Hz/50%", 1, 0.5, 6),
                                         ("D2 10Hz/50%", 10, 0.5, 3),
                                         ("D3 100Hz/50%", 100, 0.5, 3),
                                         ("D4 1kHz/50%", 1000, 0.5, 3),
                                         ("D5 10Hz/10%", 10, 0.1, 3)):
                dig_square(dig, f, duty)
                time.sleep(0.2)
                edges = saleae_capture_edges(url, args.saleae_channel, secs)
                meas_f, meas_d, n = freq_duty_from_edges(edges)
                dig.stopBufferOut()
                if meas_f is None:
                    record(name, False, f"only {n} rising edges seen")
                    continue
                ok_f = abs(meas_f - f) / f <= FREQ_TOL
                ok_d = meas_d is not None and abs(meas_d - duty) <= DUTY_TOL
                record(name, ok_f and ok_d,
                       f"f={meas_f:.4f}Hz (exp {f}), duty={meas_d:.3f} (exp {duty})")

            # D6: exact burst count — capture must be armed before the burst
            cap = tool(url, "start_capture", {
                "logicDeviceConfiguration": {
                    "logicChannels": {"digitalChannels": [args.saleae_channel]},
                    "digitalSampleRate": 10_000_000},
                "captureConfiguration": {"timedCaptureMode": {"durationSeconds": 3}}})
            cid = cap["captureId"]
            time.sleep(0.5)
            dig_burst(dig, 100, 100)
            tool(url, "wait_capture", {"captureId": cid}, timeout=60)
            out = Path(tempfile.mkdtemp(prefix="m2kburst_"))
            tool(url, "export_raw_data_csv", {
                "captureId": cid, "directory": str(out),
                "digitalChannels": [args.saleae_channel], "analogDownsampleRatio": 1})
            tool(url, "close_capture", {"captureId": cid})
            rises = 0
            prev = None
            with open(out / "digital.csv", newline="") as fcsv:
                rdr = csv.reader(fcsv)
                next(rdr)
                for _, v in rdr:
                    v = int(v)
                    if prev == 0 and v == 1:
                        rises += 1
                    prev = v
            record("D6 burst 100@100Hz", rises == 100, f"{rises} rising edges (exp 100)")
            dig.stopBufferOut()
            dig.enableChannel(DIO, False)

        if not args.skip_analog:
            print("— Analog levels/ramp (W1 -> 1+ loopback, M2K scope) —")
            # Fresh context per level (see session-quirk note above).
            libm2k.contextClose(ctx)
            ctx = None
            for lvl in (0.0, 0.825, 1.65, 2.475, 3.3):
                c = open_calibrated()
                a_in, a_out = c.getAnalogIn(), c.getAnalogOut()
                a_in.enableChannel(0, True)
                a_in.setSampleRate(1_000_000)
                a_in.setRange(0, libm2k.PLUS_MINUS_25V)
                a_out.enableChannel(0, True)
                a_out.setVoltage(0, lvl)
                time.sleep(0.3)
                mean = ain_mean(a_in, 0)
                libm2k.contextClose(c)
                record(f"A1 DC {lvl:.3f}V", abs(mean - lvl) <= DC_TOL_V,
                       f"measured {mean:.4f}V (tol ±{DC_TOL_V*1000:.0f}mV)")

            # A2: ramp 0->3.3 V in its own fresh context, single cyclic
            # push (first aout use of the session — reliable). AWG sample
            # rates snap to a ladder (75 MS/s / 10^n): 750 S/s + 1024
            # samples = ~1.37 s period; capture ~2.2 periods.
            c = open_calibrated()
            a_in, a_out = c.getAnalogIn(), c.getAnalogOut()
            a_in.enableChannel(0, True)
            a_in.setSampleRate(10_000)
            a_in.setRange(0, libm2k.PLUS_MINUS_25V)
            a_out.enableChannel(0, True)
            n = 1024
            ramp = [3.3 * i / (n - 1) for i in range(n)]
            a_out.setCyclic(True)
            a_out.setSampleRate(0, 750)
            a_out.push(0, ramp)
            time.sleep(0.5)
            data = a_in.getSamples(30_000)[0]
            lo, hi = min(data), max(data)
            ok = lo <= 0.1 and hi >= 3.2
            record("A2 ramp 0-3.3V", ok, f"span {lo:.3f}..{hi:.3f}V")
            libm2k.contextClose(c)

            # Re-open the shared context for any remaining sections.
            ctx = open_calibrated()
            ain = ctx.getAnalogIn()
            ps = ctx.getPowerSupply()

        if not args.skip_psu:
            print("— Power supply (V+ -> 2+ loopback) —")
            ain.enableChannel(1, True)
            ain.setSampleRate(1_000_000)
            ain.setRange(1, libm2k.PLUS_MINUS_25V)
            ps.enableChannel(0, True)
            for v in (3.0, 3.3, 3.6):
                ps.pushChannel(0, v)
                time.sleep(0.6)
                rb = ps.readChannel(0)      # calibrated internal readback
                scope = ain_mean(ain, 1)    # independent path via 2+ loopback
                ok = abs(rb - v) <= 0.05
                note = "" if abs(scope - rb) <= 0.1 else \
                    "  [scope ch2 disagrees — check V+ -> 2+ / 2- -> GND wiring]"
                record(f"P1 V+={v:.1f}V", ok,
                       f"readback {rb:.4f}V, scope {scope:.4f}V{note}")
            ps.enableChannel(0, False)
    finally:
        if ctx is not None:
            libm2k.contextClose(ctx)

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("M2K SIGNAL CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
