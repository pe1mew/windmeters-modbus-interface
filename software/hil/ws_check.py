"""Phase-1 HIL test: wind speed driver (TIM2 ETR on PC1) against the M2K.

The wind_speed firmware reports "W,<count>,<flag>" per 1000 ms window on the
PD6 debug UART (Saleae ch 8). The M2K drives PC1 (DIO0 wire). Asserted rows
from design/driverDevelopment.md §3.3:

  count accuracy   1/10/100/1000 Hz -> count = f x 1s, ±1   (FR-S04/S08)
  rising edges     10%/50%/90% duty at 10 Hz -> same count  (FR-S04)
  window duration  W-line timestamp deltas 1000 ms ±2%      (FR-S17)
  silence          driven low -> count 0
  saturation       100 kHz -> "W,65535,S", never a wrap     (FR-S27)

Run (needs libm2k -> Python 3.11 venv):
    .venv-m2k\\Scripts\\python.exe ws_check.py [--saleae-channel 8]
"""

import argparse
import sys
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc
from saleae_serial import capture_serial, decode_lines
from m2k_signal_check import dig_square

DIO = 0
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def windows_from_capture(url, channel, seconds):
    """Capture and return [(t, count, flag)] for complete W-lines."""
    lines, errors = decode_lines(capture_serial(url, channel, seconds))
    out = []
    for t, line in lines:
        parts = line.split(",")
        if len(parts) == 3 and parts[0] == "W" and parts[1].isdigit():
            out.append((t, int(parts[1]), parts[2]))
    return out, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, default=8,
                    help="Saleae channel wired to DUT PD6 (debug UART)")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "ws-check", "version": "0.1"}})

    ctx = libm2k.m2kOpen()
    if ctx is None:
        print("FAIL — no M2K context")
        return 1
    try:
        dig = ctx.getDigital()
        dig.setDirection(DIO, libm2k.DIO_OUTPUT)
        dig.enableChannel(DIO, True)

        cases = [
            ("count 1Hz",    1,      0.5, 1,     False),
            ("count 10Hz",   10,     0.5, 10,    False),
            ("count 100Hz",  100,    0.5, 100,   False),
            ("count 1kHz",   1000,   0.5, 1000,  False),
            ("duty 10%",     10,     0.1, 10,    False),
            ("duty 90%",     10,     0.9, 10,    False),
            ("saturation",   100000, 0.5, 65535, True),
        ]
        timing_deltas = []
        for name, freq, duty, expect, expect_sat in cases:
            dig_square(dig, freq, duty)
            time.sleep(1.5)  # let the transition window pass
            wins, errors = windows_from_capture(url, args.saleae_channel, 6)
            # First captured line may describe a window that straddled the
            # stimulus change — judge from the second line onward.
            interior = wins[1:]
            if len(interior) < 3:
                record(name, False, f"only {len(interior)} usable windows")
                continue
            counts = [c for _, c, _ in interior]
            flags = {f for _, _, f in interior}
            if expect_sat:
                ok_c = all(c == expect for c in counts)
            else:
                # The DUT window is HSI-paced (±1%); the count is correct
                # for the ACTUAL window duration (FR-S06 semantics). Assert
                # each count against the measured duration of its own
                # window (timestamp delta of consecutive report lines).
                ok_c = True
                for (t0, _, _), (t1, c, _) in zip(interior, interior[1:]):
                    expected = freq * (t1 - t0)
                    if abs(c - expected) > 1.5:
                        ok_c = False
            ok_f = flags == ({"S"} if expect_sat else {"0"})
            record(name, ok_c and ok_f and not errors,
                   f"counts={counts} flags={sorted(flags)} "
                   f"(expect {expect} scaled to measured window, "
                   f"{'S' if expect_sat else '0'})")
            timing_deltas += [b - a for (a, _, _), (b, _, _)
                              in zip(interior, interior[1:])]

        # Silence: drive the line constant low — zero rising edges.
        dig.setCyclic(True)
        dig.push([0, 0, 0, 0])
        time.sleep(1.5)
        wins, errors = windows_from_capture(url, args.saleae_channel, 5)
        counts = [c for _, c, _ in wins[1:]]
        record("silence", bool(counts) and all(c == 0 for c in counts)
               and not errors, f"counts={counts} (expect all 0)")

        # FR-S17: window duration from W-line timestamp deltas, all runs.
        if timing_deltas:
            worst = max(abs(d - 1.0) for d in timing_deltas)
            record("window +-2% (FR-S17)", worst <= 0.02,
                   f"n={len(timing_deltas)}, worst dev from 1000ms = {worst*1000:.2f} ms")
        else:
            record("window ±2% (FR-S17)", False, "no deltas collected")

        dig.stopBufferOut()
        dig.enableChannel(DIO, False)
    finally:
        libm2k.contextClose(ctx)

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("WS CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
