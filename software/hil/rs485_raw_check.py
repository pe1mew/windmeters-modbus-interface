"""§9.1 byte-exact vectors through a second MAX3485 raw master:
M2K DIO0 -> DI, DIO1 -> DE+R~E~, V+ -> VCC (3.3 V), A/B on the bus.
The M2K bit-bangs frames with exact timing the tester's auto-direction
master cannot produce; the Saleae (ch8 = DUT PD6/RO node, ch15 = DUT DE)
judges the DUT's behavior.

Groups (--group all|split|flood|baud|latency):
  split    FR-MB03: 4 bytes + >=5 ms pause + remainder -> both halves
           discarded (CRC-counter evidence), silence, next valid frame
           answered. x10.
  flood    FR-MB24: 10x 2 s random-byte flood + valid request; 1x 60 s
           random soak + valid request; 10x 400-byte oversize burst +
           gap + valid request. Receiver recovers every time.
  baud     FR-MB01 margin: valid requests at ~+-1/2/3 % master baud
           (M2K rate ladder read back for the true offset). +-1 % must
           answer; beyond is informational margin.
  latency  FR-MB20/21: 1000 clean requests, response-gap histogram from
           one long capture (t3.5 <= gap <= 100 ms).

Run:  .venv-m2k\\Scripts\\python.exe rs485_raw_check.py [--group all]

Leaves the DUT untouched (no writes) and restarts the tester's poller.
"""

import argparse
import csv
import json
import random
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import libm2k
from m2k_signal_check import open_calibrated
from smoke_test import rpc, tool
from saleae_serial import uart_decode
from rs485_check import crc16, de_windows, split_frames, BAUD, T35

SPB = 10
D_DATA, D_DE = 0, 1
SLAVE = 30
RESULTS = []
RNG = random.Random(0x5EED)


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def api(path, body=None, timeout=15.0):
    base = "http://windmeter-tester.local"
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None
        else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def dut_diag():
    """(crc_errors, served) via the tester API — bus must be quiet.

    The tester passively hears ALL raw-master traffic on the shared bus
    and only drains its RX buffer during its own transactions, so the
    first read after M2K activity fails with crc_error on the backlog —
    that failed read IS the flush; retry."""
    for _ in range(3):
        r = api("/api/v1/modbus", {"slave": SLAVE, "function": 4,
                                   "register": 8, "count": 2})
        if r.get("ok"):
            return tuple(r["registers"])
        if r.get("status") != "crc_error":
            break
    print(f"    [warn] diag read failed: {r.get('status')} "
          f"{r.get('detail', '')}")
    return (None, None)


def fc04(reg, n, addr=SLAVE):
    p = bytes([addr, 4, reg >> 8, reg & 0xFF, n >> 8, n & 0xFF])
    return p + crc16(p)


VALID_REQ = fc04(0x0006, 1)


class RawMaster:
    """Two-channel bit-bang master behind the second MAX3485."""

    def __init__(self, ctx, rate=BAUD * SPB):
        ps = ctx.getPowerSupply()
        ps.enableChannel(0, True)
        ps.pushChannel(0, 3.3)          # VCC of the master transceiver
        self.dig = ctx.getDigital()
        self.set_rate(rate)
        self.dig.setCyclic(False)
        for ch in (D_DATA, D_DE):
            self.dig.setOutputMode(ch, libm2k.DIO_PUSHPULL)
            self.dig.setDirection(ch, libm2k.DIO_OUTPUT)
            self.dig.enableChannel(ch, True)
        self.dig.setValueRaw(D_DATA, 1)
        self.dig.setValueRaw(D_DE, 0)

    def set_rate(self, rate):
        self.dig.setSampleRateOut(rate)
        self.rate = self.dig.getSampleRateOut()

    def compose(self, segments):
        """('mark', bits) | ('frame', bytes) | ('park', bits) -> samples.
        mark/frame drive with DE=1; park releases the driver (DE=0)."""
        out = []
        for kind, val in segments:
            if kind == "mark":
                out += [(1 << D_DATA) | (1 << D_DE)] * (val * SPB)
            elif kind == "park":
                out += [(1 << D_DATA)] * (val * SPB)
            else:
                bits = []
                for b in val:
                    bits.append(0)
                    bits += [(b >> i) & 1 for i in range(8)]
                    bits.append(1)
                out += [((bit << D_DATA) | (1 << D_DE)) for bit in bits
                        for _ in range(SPB)]
        return out

    def play(self, segments):
        buf = self.compose(segments)
        self.dig.push(buf)
        time.sleep(len(buf) / self.rate + 0.01)


# ---- Saleae helpers ---------------------------------------------------------

def capture_during(url, fn, seconds, channels=(8, 15), rate=2_000_000):
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": list(channels)},
            "digitalSampleRate": rate},
        "captureConfiguration": {"timedCaptureMode":
                                 {"durationSeconds": seconds}}})
    cid = cap["captureId"]
    try:
        time.sleep(0.15)
        fn()
        tool(url, "wait_capture", {"captureId": cid}, timeout=seconds + 120)
        out = Path(tempfile.mkdtemp(prefix="raw485_"))
        tool(url, "export_raw_data_csv", {
            "captureId": cid, "directory": str(out),
            "digitalChannels": list(channels), "analogDownsampleRatio": 1},
            timeout=180)
    finally:
        tool(url, "close_capture", {"captureId": cid})
    edges = {ch: [] for ch in channels}
    with open(out / "digital.csv", newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        cols = [int(h.split()[-1]) for h in header[1:]]
        for row in rdr:
            t = float(row[0])
            for i, ch in enumerate(cols):
                v = int(row[1 + i])
                if not edges[ch] or edges[ch][-1][1] != v:
                    edges[ch].append((t, v))
    return edges


def dut_frames(edges):
    """Frames on ch8 that lie inside DUT DE windows, with CRC verdicts."""
    wins = de_windows(edges[15])
    frames = split_frames(uart_decode(edges[8], BAUD))
    out = []
    for fr in frames:
        if any(r - 20e-6 <= fr[0][0] <= f + 20e-6 for r, f in wins):
            d = bytes(b for _, b, _ in fr)
            out.append((fr[0][0], d,
                        len(d) >= 4 and crc16(d[:-2]) == d[-2:]))
    return out, wins, frames


# ---- vector groups ----------------------------------------------------------

def g_split(url, m):
    print("\n== FR-MB03 split frames: 4 bytes + 5 ms pause + remainder ==")
    c0, _ = dut_diag()
    ok_all, responded_to_half = 0, 0
    for rep in range(10):
        segs = [("mark", 96), ("frame", VALID_REQ[:4]),
                ("mark", 48),                       # 5.0 ms driven-mark pause
                ("frame", VALID_REQ[4:]),
                ("mark", 48),                       # > t3.5 so the DUT can
                ("frame", VALID_REQ),               # resync before recovery
                ("mark", 2), ("park", 8)]
        edges = capture_during(url, lambda: m.play(segs), 1.6)
        resp, wins, _ = dut_frames(edges)
        # the only DUT frame must be the answer to the trailing valid request
        if len(resp) == 1 and resp[0][2]:
            ok_all += 1
        else:
            print(f"    rep {rep}: {len(resp)} DUT frame(s) "
                  + " ".join("ok" if r[2] else "bad" for r in resp))
        if len(resp) > 1:
            responded_to_half += 1
    record("split halves never answered; trailing valid frame is (x10)",
           ok_all == 10 and responded_to_half == 0,
           f"{ok_all}/10 clean, {responded_to_half} stray responses")
    c1, _ = dut_diag()
    if c0 is not None and c1 is not None:
        # each rep: both halves fail CRC -> +2
        record("split halves land in the DUT CRC-discard counter (FR-MB02)",
               c1 - c0 == 20, f"30009: {c0} -> {c1} (delta {c1 - c0}, "
               f"expect 20)")


def g_flood(url, m):
    print("\n== FR-MB24 garbage floods ==")
    c0, _ = dut_diag()
    ok = 0
    for rep in range(10):
        noise = bytes(RNG.randrange(256) for _ in range(1920))  # ~2 s @ 9600
        segs = [("mark", 8), ("frame", noise), ("mark", 48),
                ("frame", VALID_REQ), ("mark", 2), ("park", 8)]
        edges = capture_during(url, lambda: m.play(segs), 5.2)
        resp, _, _ = dut_frames(edges)
        if len(resp) == 1 and resp[0][2]:
            ok += 1
    record("10x 2 s random flood -> valid request answered", ok == 10,
           f"{ok}/10")

    print("  60 s soak running ...")
    for _ in range(6):  # 6 x 10 s chunks (buffer-size bound)
        noise = bytes(RNG.randrange(256) for _ in range(960 * 10))
        m.play([("mark", 8), ("frame", noise), ("mark", 2), ("park", 4)])
    edges = capture_during(
        url, lambda: m.play([("mark", 96), ("frame", VALID_REQ),
                             ("mark", 2), ("park", 8)]), 1.4)
    resp, _, _ = dut_frames(edges)
    record("60 s random soak -> next valid request answered (FR-MB24)",
           len(resp) == 1 and resp[0][2],
           f"{len(resp)} response(s), CRC "
           f"{'OK' if resp and resp[0][2] else 'n/a'}")

    ok = 0
    for rep in range(10):
        burst = bytes(RNG.randrange(256) for _ in range(400))  # > MB_ADU_MAX
        segs = [("mark", 8), ("frame", burst), ("mark", 48),
                ("frame", VALID_REQ), ("mark", 2), ("park", 8)]
        edges = capture_during(url, lambda: m.play(segs), 1.9)
        resp, _, _ = dut_frames(edges)
        if len(resp) == 1 and resp[0][2]:
            ok += 1
    record("10x 400-byte oversize burst -> valid request answered "
           "(FR-MB24 overflow path)", ok == 10, f"{ok}/10")
    c1, s1 = dut_diag()
    print(f"  DUT diagnostics after floods: crc_errors {c0} -> {c1}, "
          f"served {s1}")


def g_baud(url, m):
    print("\n== FR-MB01 margin: off-nominal master baud ==")
    results = []
    for pct in (1.0, -1.0, 2.0, -2.0, 3.0, -3.0):
        m.set_rate(round(BAUD * SPB * (1 + pct / 100)))
        actual_pct = (m.rate / (BAUD * SPB) - 1) * 100
        edges = capture_during(
            url, lambda: m.play([("mark", 96), ("frame", VALID_REQ),
                                 ("mark", 2), ("park", 8)]), 1.4)
        resp, _, _ = dut_frames(edges)
        answered = len(resp) == 1 and resp[0][2]
        results.append((pct, actual_pct, answered))
        print(f"    {pct:+.0f}% (actual {actual_pct:+.2f}%): "
              f"{'answered' if answered else 'silent'}")
    m.set_rate(BAUD * SPB)
    one_pct = [r for r in results if abs(r[0]) <= 1.001]
    record("+-1 % master baud answered (FR-MB01)",
           all(r[2] for r in one_pct),
           "; ".join(f"{r[1]:+.2f}%:{'ok' if r[2] else 'NO'}"
                     for r in results))


def g_latency(url, m, n_req=1000):
    print(f"\n== FR-MB20/21: {n_req}-request latency histogram ==")
    state = {}

    def firehose():
        for i in range(n_req):
            m.play([("mark", 40), ("frame", VALID_REQ), ("mark", 2),
                    ("park", 2)])
            time.sleep(0.03)
        state["sent"] = n_req

    seconds = n_req * 0.105 + 8
    edges = capture_during(url, firehose, seconds)
    resp, wins, frames = dut_frames(edges)
    masters = [fr for fr in frames
               if not any(r - 20e-6 <= fr[0][0] <= f + 20e-6
                          for r, f in wins)]
    gaps = []
    bad_crc = 0
    for fr in masters:
        if bytes(b for _, b, _ in fr) != VALID_REQ:
            continue
        t_end = fr[-1][0] + 10 / BAUD
        nxt = next((r for r in resp if r[0] > t_end), None)
        nxt_m = next((x[0][0] for x in masters if x[0][0] > t_end),
                     float("inf"))
        if nxt and nxt[0] < nxt_m:
            gaps.append(nxt[0] - t_end)
            if not nxt[2]:
                bad_crc += 1
            resp.remove(nxt)
    gaps.sort()
    if gaps:
        med = gaps[len(gaps) // 2]
        p99 = gaps[int(len(gaps) * 0.99)]
        record(f"{len(gaps)} transactions judged (>=95% of {n_req})",
               len(gaps) >= n_req * 0.95, f"{len(gaps)} paired, "
               f"{bad_crc} bad-CRC responses")
        record("FR-MB20/21: all gaps in [t3.5, 100 ms]",
               gaps[0] >= T35 and gaps[-1] <= 0.100,
               f"min/med/p99/max = {gaps[0]*1e3:.2f}/{med*1e3:.2f}/"
               f"{p99*1e3:.2f}/{gaps[-1]*1e3:.2f} ms")
    else:
        record("latency histogram", False, "no transactions paired")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="all",
                    choices=["all", "split", "flood", "baud", "latency"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--build", choices=["speed", "direction"], default="speed",
                    help="DUT variant (sets default slave + poller restart)")
    ap.add_argument("--slave", type=int, default=None,
                    help="DUT address (default 30 speed / 31 direction)")
    ap.add_argument("--no-poller-restart", action="store_true")
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    global SLAVE, VALID_REQ
    SLAVE = args.slave if args.slave is not None else (
        31 if args.build == "direction" else 30)
    # Pass SLAVE explicitly: fc04's addr default binds at def-time (=30).
    VALID_REQ = fc04(0x0006, 1, SLAVE)   # identification read
    print(f"raw-master target: {args.build} build, address {SLAVE}")

    rpc(url, "initialize", {"protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "rs485-raw", "version": "0.1"}})
    st = api("/api/v1/status")
    if st.get("busy", {}).get("wind_poll_active"):
        api("/wind/stop", {})
        time.sleep(0.5)
        print("tester poller stopped (bus must be quiet for the raw master)")

    ctx = open_calibrated()
    try:
        m = RawMaster(ctx)
        print(f"raw master up: rate {m.rate:.0f} "
              f"({(m.rate/(BAUD*SPB)-1)*100:+.2f}% vs nominal)")
        if args.group in ("all", "split"):
            g_split(url, m)
        if args.group in ("all", "flood"):
            g_flood(url, m)
        if args.group in ("all", "baud"):
            g_baud(url, m)
        if args.group in ("all", "latency"):
            g_latency(url, m)
    finally:
        libm2k.contextClose(ctx)

    if not args.no_poller_restart:
        api("/wind/start", {"type": args.build, "addr": SLAVE,
                            "interval_ms": 3000})
        print(f"\ntester poller restarted ({args.build} @ {SLAVE}, 3 s)")

    fails = [x for x in RESULTS if not x[1]]
    print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(len(fails))}"
          f" — {len(RESULTS) - len(fails)}/{len(RESULTS)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
