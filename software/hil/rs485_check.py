"""Integration-plan §9.1 HIL test: Modbus RTU through the real MAX3485,
with the windmeters-modbus-interface-tester as bus master.

Passive judge: the tester polls the DUT on its own; the Saleae captures
the DI/RO node (PD6), the driver-enable line (PC2/DE), and the bus pair
(A/B), and this script decodes and asserts the §9.1 rows that need only
observed traffic:

    FR-MB04   DE asserted before the response's first start bit,
              released within one character time after the last stop bit
    FR-MB23   one request -> exactly one response, DE only ever high
              inside a response window (no spontaneous transmissions)
    FR-MB03   RO idles mark between frames (fail-safe / bias sanity)
    FR-MB20/21  request-end -> response-start latency statistics

Wiring (MAX3485 breadboard rig):
    DUT PD6 (pin 1) = MAX3485 DI+RO  <- Saleae ch 8
    DUT PC2 (pin 6) = DE+R~E~, 10k pull-down  <- Saleae ch 15
    Bus A  <- Saleae ch 0   (optional; script degrades gracefully)
    Bus B  <- Saleae ch 1   (optional)
    Tester (RS-485 master) on A/B; grounds common.

Run:  .venv-m2k\\Scripts\\python.exe rs485_check.py [--duration 60]

If the DUT never answers, the script reports which addresses the master
polled instead of failing cryptically — that is the "tester aimed at the
wrong address" diagnostic.
"""

import argparse
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc, tool
from saleae_serial import uart_decode

BAUD = 9600
BIT = 1.0 / BAUD
CHAR = 11 * BIT          # Modbus character time (11 bit times)
T35 = 3.5 * CHAR         # inter-frame silent interval, 4.01 ms @ 9600
FRAME_GAP = 0.002        # byte-gap frame splitter (established, mb_check)
BUILDS = {0x01: "wind_speed", 0x02: "wind_direction", 0x03: "wind_combined"}
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes((crc & 0xFF, crc >> 8))


def capture(url, channels, seconds, sample_rate=2_000_000):
    """Multi-channel timed capture; returns {channel: [(t, level), ...]}
    edge lists (first entry = initial state at t=0)."""
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": channels},
            "digitalSampleRate": sample_rate,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": seconds}},
    })
    cid = cap["captureId"]
    try:
        tool(url, "wait_capture", {"captureId": cid}, timeout=seconds + 120)
        out = Path(tempfile.mkdtemp(prefix="rs485_"))
        tool(url, "export_raw_data_csv", {
            "captureId": cid, "directory": str(out),
            "digitalChannels": channels, "analogDownsampleRatio": 1},
            timeout=120)
    finally:
        tool(url, "close_capture", {"captureId": cid})

    edges = {ch: [] for ch in channels}
    with open(out / "digital.csv", newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        cols = [int(h.split()[-1]) for h in header[1:]]  # "Channel N"
        for row in rdr:
            t = float(row[0])
            for i, ch in enumerate(cols):
                v = int(row[1 + i])
                if not edges[ch] or edges[ch][-1][1] != v:
                    edges[ch].append((t, v))
    return edges


def level_at(edges, t):
    lv = edges[0][1]
    for et, ev in edges:
        if et > t:
            break
        lv = ev
    return lv


def split_frames(events):
    """[(t, byte, ok)] -> [[(t, byte, ok)], ...] on >FRAME_GAP byte gaps."""
    frames, cur = [], []
    for t, b, ok in events:
        if cur and t - cur[-1][0] > FRAME_GAP:
            frames.append(cur)
            cur = []
        cur.append((t, b, ok))
    if cur:
        frames.append(cur)
    return frames


def de_windows(edges):
    """PC2 edge list -> [(t_rise, t_fall)] closed windows."""
    wins, rise = [], None
    for t, v in edges[1:]:
        if v == 1 and rise is None:
            rise = t
        elif v == 0 and rise is not None:
            wins.append((rise, t))
            rise = None
    return wins


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--ch-pd6", type=int, default=8)
    ap.add_argument("--ch-de", type=int, default=15)
    ap.add_argument("--ch-a", type=int, default=0)
    ap.add_argument("--ch-b", type=int, default=1)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    init = rpc(url, "initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "rs485-check", "version": "0.1"}})
    print(f"Saleae MCP: {init['serverInfo']['name']} {init['serverInfo']['version']}")

    chans = [args.ch_a, args.ch_b, args.ch_pd6, args.ch_de]
    print(f"Capturing {args.duration:.0f} s on channels {chans} "
          f"(A, B, PD6, DE) — tester should be polling ...")
    edges = capture(url, chans, args.duration)
    pd6, de = edges[args.ch_pd6], edges[args.ch_de]
    a_edges, b_edges = edges[args.ch_a], edges[args.ch_b]

    if len(pd6) < 2:
        print("NO TRAFFIC on PD6 — tester not polling / rig not powered.")
        return 1

    events = uart_decode(pd6, BAUD)
    bad = [e for e in events if not e[2]]
    frames = split_frames(events)
    wins = de_windows(de)

    # Classify: a frame is DUT TX if its first start bit lies in a DE window.
    def in_window(t):
        return any(r - 20e-6 <= t <= f + 20e-6 for r, f in wins)

    master, dut = [], []
    for fr in frames:
        (dut if in_window(fr[0][0]) else master).append(fr)

    def fbytes(fr):
        return bytes(b for _, b, _ in fr)

    def fend(fr):
        return fr[-1][0] + 10 * BIT  # 8N1: last stop bit edge

    n_req = len(master)
    print(f"\n{len(events)} bytes ({len(bad)} framing errors), "
          f"{len(frames)} frames: {n_req} master, {len(dut)} DUT, "
          f"{len(wins)} DE windows")

    # Which addresses does the master poll?
    from collections import Counter
    polled = Counter(fbytes(fr)[0] for fr in master if fr)
    print(f"master polls addresses: "
          f"{', '.join(f'{a} (x{n})' for a, n in sorted(polled.items()))}")

    if not dut:
        print("\nDUT NEVER RESPONDED. It only answers its own address "
              "(30/35 speed, 31/36 direction) — point the tester there.")
        return 1

    dut_addr = fbytes(dut[0])[0]
    print(f"DUT responds as address {dut_addr}")

    # Identify the build from an FC04 read covering offset 6 (30007).
    for fr in dut:
        d = fbytes(fr)
        if len(d) >= 5 and d[1] == 0x04 and d[2] >= 14:
            ident = (d[3 + 12] << 8) | d[4 + 12]
            build, ver = ident >> 8, ident & 0xFF
            print(f"identification 0x{ident:04X}: "
                  f"{BUILDS.get(build, f'build {build}?')} fw v{ver}")
            break

    print()
    # ---- CRC integrity through the transceiver ----------------------------
    def crc_ok(d):
        return len(d) >= 4 and crc16(d[:-2]) == d[-2:]

    bad_m = [fr for fr in master if not crc_ok(fbytes(fr))]
    bad_d = [fr for fr in dut if not crc_ok(fbytes(fr))]
    record("wire integrity: CRC valid on every frame (RO path)",
           not bad and not bad_m and not bad_d,
           f"{len(events)} bytes, {len(bad)} framing errors, "
           f"bad CRC: {len(bad_m)} master / {len(bad_d)} DUT")

    # ---- pair requests to the DUT with responses ---------------------------
    to_dut = [fr for fr in master if fbytes(fr)[0] == dut_addr]
    pairs, orphan_resp = [], list(dut)
    for req in to_dut:
        t0 = fend(req)
        resp = next((r for r in orphan_resp if r[0][0] > t0), None)
        nxt = next((m[0][0] for m in master if m[0][0] > t0), float("inf"))
        if resp and resp[0][0] < nxt:
            orphan_resp.remove(resp)
            pairs.append((req, resp))
        else:
            pairs.append((req, None))
    answered = [(q, r) for q, r in pairs if r]

    record("FR-MB23: every request to DUT -> exactly one response",
           len(answered) == len(to_dut) and not orphan_resp,
           f"{len(to_dut)} requests, {len(answered)} responses, "
           f"{len(orphan_resp)} spontaneous DUT frames")

    record("FR-MB23: DE windows == DUT responses (never idles asserted)",
           len(wins) == len(dut),
           f"{len(wins)} DE windows / {len(dut)} DUT frames")

    # ---- FR-MB04: DE timing per response -----------------------------------
    if answered:
        leads, trails = [], []
        for (req, resp) in answered:
            win = next(((r, f) for r, f in wins
                        if r - 20e-6 <= resp[0][0] <= f + 20e-6), None)
            if not win:
                continue
            leads.append(resp[0][0] - win[0])
            trails.append(win[1] - fend(resp))
        lead_ok = all(l > 0 for l in leads)
        # Lower bound: frame end is computed at NOMINAL baud, but the DUT's
        # HSI runs up to +-1% (FR-MB01 margin) — 10 bits of skew is +-10 us.
        # DE dropping right on the TC flag then reads slightly "early".
        trail_ok = all(-15e-6 <= t <= CHAR for t in trails)
        record("FR-MB04: DE asserted before first start bit",
               lead_ok and len(leads) == len(answered),
               f"lead {min(leads)*1e6:.0f}..{max(leads)*1e6:.0f} us "
               f"over {len(leads)} responses")
        record("FR-MB04: DE released within one character of last stop bit",
               trail_ok,
               f"trail {min(trails)*1e6:.0f}..{max(trails)*1e6:.0f} us "
               f"(limit {CHAR*1e6:.0f} us)")

        # DE must never overlap a master frame
        clash = [fr for fr in master
                 if any(r <= fr[0][0] <= f for r, f in wins)]
        record("FR-MB04: DE never asserted during a master frame",
               not clash, f"{len(clash)} overlaps")

    # ---- FR-MB20/21: latency ------------------------------------------------
    if answered:
        gaps = [r[0][0] - fend(q) for q, r in answered]
        gmin, gmax = min(gaps), max(gaps)
        gavg = sum(gaps) / len(gaps)
        record("FR-MB20/21: response after t3.5, within 100 ms",
               gmin >= T35 and gmax <= 0.100,
               f"gap min/avg/max = {gmin*1e3:.2f}/{gavg*1e3:.2f}/"
               f"{gmax*1e3:.2f} ms over {len(gaps)} transactions")

    # ---- FR-MB03: RO idles mark between frames ------------------------------
    idles = []
    for i in range(len(frames) - 1):
        gap_s, gap_e = fend(frames[i]) + BIT, frames[i + 1][0][0] - 1e-4
        if gap_e > gap_s:
            idles.append(level_at(pd6, (gap_s + gap_e) / 2))
    record("FR-MB03: RO idles mark between frames",
           all(v == 1 for v in idles),
           f"{len(idles)} inter-frame gaps checked, "
           f"{sum(1 for v in idles if v != 1)} not mark")

    # ---- A/B wire view (informational unless wired) --------------------------
    if len(a_edges) > 1:
        a_ev = uart_decode(a_edges, BAUD)
        a_frames = split_frames(a_ev)
        match = len(a_frames) == len(frames)
        record("bus A carries the same frame count as RO",
               match, f"A: {len(a_frames)} frames vs PD6: {len(frames)}")
    else:
        print("  [info] A/B channels silent — bus-side probes not wired")

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
