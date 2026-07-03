"""Phase-0 HIL test: verify the debug_uart library over the Saleae.

The debug_uart_test firmware saturates PD6 with counting lines "D,<n>\r\n"
at 115200 8N1. This script captures the line, decodes it with the Saleae
Async Serial analyzer, and asserts the driverDevelopment.md §2.2 exit
criterion: >= 10,000 lines, strict counter continuity (no lost or corrupted
bytes), zero framing errors.

Usage:
    python uart_check.py [--port 10530] [--channel 8] [--seconds 12]
"""

import argparse
import csv
import sys
import tempfile
from pathlib import Path

from smoke_test import rpc, tool  # same-dir MCP helpers


def capture_serial(url: str, channel: int, seconds: float, baud: int) -> Path:
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [channel]},
            "digitalSampleRate": 10_000_000,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": seconds}},
    })
    cid = cap["captureId"]
    try:
        tool(url, "wait_capture", {"captureId": cid}, timeout=seconds + 120)
        ana = tool(url, "add_analyzer", {
            "captureId": cid,
            "analyzerName": "Async Serial",
            "analyzerLabel": "dbg",
            "settings": {"Input Channel": {"numberValue": channel},
                         "Bit Rate (Bits/s)": {"numberValue": baud}},
        })
        analyzer_id = ana.get("analyzerId") if isinstance(ana, dict) else None
        out = Path(tempfile.mkdtemp(prefix="uart_")) / "serial.csv"
        export_args = {"captureId": cid, "filepath": str(out)}
        if analyzer_id is not None:
            export_args["analyzers"] = [{"analyzerId": analyzer_id}]
        tool(url, "export_data_table_csv", export_args, timeout=120)
        return out
    finally:
        tool(url, "close_capture", {"captureId": cid})


def parse_byte(value: str):
    # The data column holds the literal character — including raw CR/LF
    # embedded in the quoted CSV field. Do NOT strip.
    if len(value) == 1:
        return ord(value)
    if value.startswith("0x"):
        return int(value, 16)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--channel", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--min-lines", type=int, default=10_000)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "uart-check", "version": "0.1"}})
    print(f"Capturing ch{args.channel} for {args.seconds}s @ {args.baud} baud ...")
    csv_path = capture_serial(url, args.channel, args.seconds, args.baud)

    # Collect (time, char, error) per byte row. A capture that starts
    # mid-byte legitimately yields garbage + one framing error before the
    # first line boundary — judge only from the first clean "\n" onward.
    events = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        rdr = csv.DictReader(f)
        cols = {c.lower().strip('"'): c for c in rdr.fieldnames}
        val_col = cols.get("data") or cols.get("value")
        err_col = cols.get("error")
        for row in rdr:
            raw = row.get(val_col) or ""
            b = parse_byte(raw)
            err = (row.get(err_col) or "").strip() if err_col else ""
            events.append((float(row["start_time"]), b, err))

    first_nl = next((i for i, (_, b, _) in enumerate(events) if b == 10), None)
    if first_nl is None:
        print("FAIL — no line boundary found in capture")
        return 1
    judged = events[first_nl + 1:]

    errors = [e for e in judged if e[2]]
    stream = bytearray(b for _, b, _ in judged
                       if b is not None and b < 256)
    text = stream.decode("ascii", errors="replace")
    lines = text.split("\r\n")
    # Last line is truncated by the capture window; drop it.
    body = [l for l in lines[:-1] if l]
    counters = []
    malformed = 0
    for l in body:
        if l.startswith("D,") and l[2:].isdigit():
            counters.append(int(l[2:]))
        elif l == "DBGUART,START":
            pass
        else:
            malformed += 1

    gaps = sum(1 for a, b in zip(counters, counters[1:]) if b != a + 1)
    print(f"decoded bytes: {len(stream)}, lines: {len(body)}, "
          f"counter lines: {len(counters)}, malformed: {malformed}")
    print(f"framing/analyzer errors: {len(errors)}, counter gaps: {gaps}")
    if counters:
        print(f"counter range: {counters[0]} .. {counters[-1]}")

    ok = (len(counters) >= args.min_lines and gaps == 0
          and malformed == 0 and not errors)
    print("UART CHECK PASS — debug_uart exit criterion met."
          if ok else "UART CHECK FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
