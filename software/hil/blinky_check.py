"""Phase-0 HIL smoke test: capture the blinky on the Saleae and assert timing.

The blinky_template firmware toggles PD6: 100 ms high, 900 ms low (see
software/drivers/blinky_template/src/main.c). The LED/PD6 node is wired to a
Saleae digital channel. This script captures a few cycles, measures the
high/low durations from the exported edge CSV, and asserts them.

Usage:
    python blinky_check.py [--port 10530] [--channel 1] [--seconds 5]

Pass criteria (HSI ±1% + Delay_Ms overhead margin -> ±3% + 2 ms):
    high  ~ 100 ms, low ~ 900 ms, period ~ 1000 ms
"""

import argparse
import csv
import sys
import tempfile
from pathlib import Path

from smoke_test import rpc, tool  # same-dir MCP helpers


def measure(url: str, channel: int, seconds: float):
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [channel]},
            "digitalSampleRate": 10_000_000,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": seconds}},
    })
    capture_id = cap["captureId"]
    try:
        tool(url, "wait_capture", {"captureId": capture_id}, timeout=seconds + 60)
        out_dir = Path(tempfile.mkdtemp(prefix="blinky_"))
        tool(url, "export_raw_data_csv", {
            "captureId": capture_id, "directory": str(out_dir),
            "digitalChannels": [channel], "analogDownsampleRatio": 1,
        })
        rows = []
        with open(out_dir / "digital.csv", newline="") as f:
            rdr = csv.reader(f)
            next(rdr)  # header
            for t, v in rdr:
                rows.append((float(t), int(v)))
        return rows
    finally:
        tool(url, "close_capture", {"captureId": capture_id})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--high-ms", type=float, default=100.0)
    ap.add_argument("--low-ms", type=float, default=900.0)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "blinky-check", "version": "0.1"}})
    print(f"Capturing ch{args.channel} for {args.seconds}s ...")
    rows = measure(url, args.channel, args.seconds)

    # rows: (time, level) — first row is initial state, then one row per edge,
    # final row repeats the last level at capture end. Keep true edges only.
    edges = [rows[0]]
    for t, v in rows[1:]:
        if v != edges[-1][1]:
            edges.append((t, v))
    if len(edges) < 6:
        print(f"FAIL — only {len(edges) - 1} edges captured; "
              f"is the blinky flashed, powered, and wired to ch{args.channel}?")
        return 1

    highs, lows = [], []
    for (t0, v0), (t1, _) in zip(edges, edges[1:]):
        dur_ms = (t1 - t0) * 1000.0
        (highs if v0 == 1 else lows).append(dur_ms)
    # Drop first and last interval: truncated by the capture window.
    intervals = sorted(highs + lows, key=lambda x: 0)  # keep lists as-is
    highs, lows = highs[1:-1] or highs, lows[1:-1] or lows

    def stats(name, vals, expect):
        lo, hi = min(vals), max(vals)
        mean = sum(vals) / len(vals)
        tol = expect * 0.03 + 2.0
        ok = abs(mean - expect) <= tol and (hi - lo) < 2 * tol
        print(f"  {name}: n={len(vals)} mean={mean:7.2f} ms "
              f"min={lo:7.2f} max={hi:7.2f} (expect {expect:.0f} ±{tol:.1f}) "
              f"{'OK' if ok else 'FAIL'}")
        return ok

    print(f"{len(edges) - 1} edges -> {len(highs)} high / {len(lows)} low intervals")
    ok_h = stats("high", highs, args.high_ms)
    ok_l = stats("low ", lows, args.low_ms)
    period = args.high_ms + args.low_ms
    periods = [h + l for h, l in zip(highs, lows)]
    ok_p = stats("perd", periods, period) if periods else False

    if ok_h and ok_l and ok_p:
        print("BLINKY CHECK PASS — flash -> capture -> assert chain proven on DUT.")
        return 0
    print("BLINKY CHECK FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
