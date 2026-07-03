"""Shared helper: capture a UART line on the Saleae and decode it to
timestamped text lines via the Async Serial analyzer.

Encapsulates the bench-learned quirks (software/hil/README.md): tagged
analyzer setting values, literal-character data column (CR/LF arrive as
embedded newlines in quoted fields), and the judge-from-first-clean-newline
rule for captures that start mid-byte.
"""

import csv
import tempfile
from pathlib import Path

from smoke_test import tool


def capture_serial(url: str, channel: int, seconds: float, baud: int = 115200) -> Path:
    """Timed capture of one digital channel; returns the analyzer CSV path."""
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
        tool(url, "add_analyzer", {
            "captureId": cid,
            "analyzerName": "Async Serial",
            "analyzerLabel": "uart",
            "settings": {"Input Channel": {"numberValue": channel},
                         "Bit Rate (Bits/s)": {"numberValue": baud}},
        })
        out = Path(tempfile.mkdtemp(prefix="serial_")) / "serial.csv"
        tool(url, "export_data_table_csv", {"captureId": cid, "filepath": str(out)},
             timeout=120)
        return out
    finally:
        tool(url, "close_capture", {"captureId": cid})


def decode_events(csv_path: Path, sync_to_newline: bool = True):
    """Per-byte (time, byte, error) tuples.

    sync_to_newline=True (text protocols): judge from the first clean LF —
    captures that start mid-byte yield garbage before it. Pass False for
    BINARY protocols (e.g. Modbus RTU): there is no LF to sync on and the
    rule would silently discard the whole capture."""
    events = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        rdr = csv.DictReader(f)
        cols = {c.lower().strip('"'): c for c in rdr.fieldnames}
        val_col = cols.get("data") or cols.get("value")
        err_col = cols.get("error")
        for row in rdr:
            raw = row.get(val_col) or ""
            b = None
            if len(raw) == 1:
                b = ord(raw)
            elif raw.startswith("0x"):
                b = int(raw, 16)
            err = (row.get(err_col) or "").strip() if err_col else ""
            events.append((float(row["start_time"]), b, err))
    if not sync_to_newline:
        return events
    first_nl = next((i for i, (_, b, _) in enumerate(events) if b == 10), None)
    return events[first_nl + 1:] if first_nl is not None else []


def capture_raw_edges(url: str, channel: int, seconds: float,
                      sample_rate: int = 2_000_000):
    """Timed raw capture of one channel; returns [(time, level)] edge list
    (first entry = initial state)."""
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [channel]},
            "digitalSampleRate": sample_rate,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": seconds}},
    })
    cid = cap["captureId"]
    try:
        tool(url, "wait_capture", {"captureId": cid}, timeout=seconds + 120)
        out = Path(tempfile.mkdtemp(prefix="edges_"))
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


def uart_decode(edges, baud: int, capture_end: float = None):
    """Software UART decode (8N1, LSB first) straight from an edge list —
    used for binary protocols where the Logic 2 Async Serial analyzer
    proved unreliable at 9600 (bench 2026-07-03). Returns
    [(t_start, byte, ok)] with ok=False on stop-bit violations."""
    bit = 1.0 / baud

    def level_at(t):
        lv = edges[0][1]
        for et, ev in edges:
            if et > t:
                break
            lv = ev
        return lv

    out = []
    # Falling edges are start-bit candidates; skip those inside a byte.
    i = 0
    t_next_free = -1.0
    for et, ev in edges:
        if ev != 0 or et < t_next_free:
            continue
        b = 0
        for n in range(8):
            if level_at(et + (1.5 + n) * bit):
                b |= 1 << n
        ok = level_at(et + 9.5 * bit) == 1  # stop bit
        out.append((et, b, ok))
        t_next_free = et + 10 * bit - bit / 2
    return out
    """CRLF-terminated lines as (time_of_first_byte, text). Partial trailing
    line is dropped; analyzer error rows are returned separately."""
    events = decode_events(csv_path)
    errors = [e for e in events if e[2]]
    lines = []
    cur_bytes = bytearray()
    cur_t = None
    for t, b, err in events:
        if err or b is None or b > 255:
            continue
        if cur_t is None:
            cur_t = t
        cur_bytes.append(b)
        if len(cur_bytes) >= 2 and cur_bytes[-2:] == b"\r\n":
            lines.append((cur_t, cur_bytes[:-2].decode("ascii", errors="replace")))
            cur_bytes = bytearray()
            cur_t = None
    return lines, errors
