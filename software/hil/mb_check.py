"""Phase-3 HIL test: Modbus RTU slave driver — TTL rig, M2K as bus master.

The M2K bit-bangs request frames on DIO0 at 9600 8N1, then tristates the
pin so the DUT can answer on the same wire (single-wire half-duplex; an
external pull-up provides the idle bias the MAX3485 will later supply).
The Saleae decodes the whole transaction on the PD6 channel; both request
and response appear in one capture, split by inter-byte gaps.

Wiring (driverDevelopment.md §5.2, TTL variant):
    DUT PD6 (pin 1)  <- M2K DIO0, Saleae ch 8, pull-up 4.7-10k to VDD
    DUT PC2 (pin 6)  <- Saleae ch 15 (DE observation)
    LED removed from PD6 (it would sag the pulled-up idle level)

Run:  .venv-m2k\\Scripts\\python.exe mb_check.py [--saleae-channel 8]

Vectors map to TDS §2 (FR-MB IDs in each test name).
"""

import argparse
import sys
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc, tool
from saleae_serial import uart_decode
import tempfile

DIO = 0
BAUD = 9600
SPB = 10  # samples per bit
SLAVE = 30
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


def frame(payload: bytes) -> bytes:
    return payload + crc16(payload)


def uart_samples(data: bytes, lead_bits=40, tail_bits=8):
    """Bit-bang UART sample buffer for the pattern generator (LSB first)."""
    bits = [1] * lead_bits  # driven-high lead-in: gives the DUT its t3.5
    for b in data:
        bits.append(0)  # start
        bits += [(b >> i) & 1 for i in range(8)]
        bits.append(1)  # stop
    bits += [1] * tail_bits
    return [(bit << DIO) for bit in bits for _ in range(SPB)]


class Bus:
    """M2K DIO0 as half-duplex master in OPEN-DRAIN mode.

    Open-drain + the external pull-up removes every shared-wire hazard the
    earlier tristate dance had (enable glitches acting as UART breaks,
    driven-high tails colliding with the DUT's reply): the master drives
    only the 0 bits and the pull-up makes the 1s, so it can stay enabled
    permanently and the DUT can answer at any time."""

    def __init__(self, ctx):
        self.dig = ctx.getDigital()
        self.dig.setSampleRateOut(BAUD * SPB)
        self.dig.setCyclic(False)
        self.dig.setOutputMode(DIO, libm2k.DIO_OPENDRAIN)
        self.dig.setDirection(DIO, libm2k.DIO_OUTPUT)
        self.dig.setValueRaw(DIO, 1)  # released — pull-up idles the line
        self.dig.enableChannel(DIO, True)

    def release(self):
        pass  # open-drain: '1' IS released; nothing to do

    def send(self, data: bytes, lead_bits=96):
        # lead_bits=96 = 10 ms released-high lead-in: push() start can
        # glitch a phantom start bit; the DUT then swallows the frame's
        # first byte (bench: stashed bad frame = request minus address
        # byte). The long lead orphans any phantom byte behind a full t3.5
        # so the DUT discards it before the real frame begins. Open-drain
        # makes the long lead free (no contention with the reply).
        buf = uart_samples(data, lead_bits=lead_bits, tail_bits=4)
        self.dig.push(buf)
        time.sleep(len(buf) / (BAUD * SPB) * 1.001 + 0.002)


def transact(url, bus, channel, request: bytes, capture_s=1.2, lead_bits=40):
    """One request/response cycle, decoded from a single Saleae capture via
    software UART decode of the raw edges (the Logic 2 Async Serial
    analyzer scrambles byte values at 9600 — bench 2026-07-03).
    Returns (response_bytes, gap_ms request-end -> response-start)."""
    cap = tool(url, "start_capture", {
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [channel]},
            "digitalSampleRate": 2_000_000,
        },
        "captureConfiguration": {"timedCaptureMode": {"durationSeconds": capture_s}},
    })
    cid = cap["captureId"]
    try:
        time.sleep(0.15)
        bus.send(request, lead_bits=lead_bits)
        tool(url, "wait_capture", {"captureId": cid}, timeout=capture_s + 60)
        out = Path(tempfile.mkdtemp(prefix="mb_"))
        tool(url, "export_raw_data_csv", {
            "captureId": cid, "directory": str(out),
            "digitalChannels": [channel], "analogDownsampleRatio": 1})
    finally:
        tool(url, "close_capture", {"captureId": cid})

    rows = []
    import csv as _csv
    with open(Path(out) / "digital.csv", newline="") as f:
        rdr = _csv.reader(f)
        next(rdr)
        for t, v in rdr:
            rows.append((float(t), int(v)))
    edges = [rows[0]]
    for t, v in rows[1:]:
        if v != edges[-1][1]:
            edges.append((t, v))
    events = [(t, b) for t, b, ok in uart_decode(edges, BAUD) if ok]
    # Split byte stream into frames on >2 ms inter-byte gaps.
    frames = []
    cur = []
    for i, (t, b) in enumerate(events):
        if cur and t - events[i - 1][0] > 0.002:
            frames.append(cur)
            cur = []
        cur.append((t, b))
    if cur:
        frames.append(cur)
    # Locate the request frame; the response is the next frame after it.
    req = list(request)
    for i, fr in enumerate(frames):
        if [b for _, b in fr] == req:
            if i + 1 < len(frames):
                resp = frames[i + 1]
                gap_ms = (resp[0][0] - fr[-1][0]) * 1000.0
                return bytes(b for _, b in resp), gap_ms
            return b"", None
    return None, None  # request not even seen on the wire


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, default=8)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "mb-check", "version": "0.1"}})
    ctx = libm2k.m2kOpen()
    if ctx is None:
        print("FAIL — no M2K context")
        return 1
    bus = Bus(ctx)
    timings = []

    def expect(name, request, want, note=""):
        resp, gap = transact(url, bus, args.saleae_channel, request)
        if resp is None:
            record(name, False, "request not observed on the wire")
            return None
        if want is None:
            ok = resp == b""
            record(name, ok, f"reply={resp.hex() if resp else 'none'} "
                             f"(expect silence){note}")
        else:
            ok = resp == want
            record(name, ok, f"reply={resp.hex()} expect={want.hex()}{note}")
            if ok and gap is not None:
                timings.append(gap)
        return resp

    def read_input_u16(addr):
        """Best-effort read of one input register (None on no/bad reply)."""
        resp, _ = transact(url, bus, args.saleae_channel,
                           frame(bytes([SLAVE, 0x04, addr >> 8, addr & 0xFF, 0, 1])))
        if resp and len(resp) == 7 and resp[1] == 0x04:
            return (resp[3] << 8) | resp[4]
        return None

    try:
        # Setup: registers persist across harness runs — restore §2.8
        # defaults so the expected values below hold, and prove FC16 while
        # at it.
        expect("setup: restore defaults (FC16)",
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 4, 8,
                            0, 0, 0x03, 0xE8, 0, 10, 0, 4])),
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 4])))

        # — reads —
        expect("FC04 single (FR-MB08)",
               frame(bytes([SLAVE, 0x04, 0, 0, 0, 1])),
               frame(bytes([SLAVE, 0x04, 2, 0x04, 0xD2])))  # 1234
        expect("FC04 multi + byte order (FR-MB25)",
               frame(bytes([SLAVE, 0x04, 0, 1, 0, 2])),
               frame(bytes([SLAVE, 0x04, 4, 0x00, 0xFA, 0x03, 0x84])))  # 250,900
        expect("FC03 all holdings (FR-MB09)",
               frame(bytes([SLAVE, 0x03, 0, 0, 0, 4])),
               frame(bytes([SLAVE, 0x03, 8, 0, 0, 0x03, 0xE8, 0, 10, 0, 4])))
        # — silence rows —
        expect("wrong address silent (FR-MB05)",
               frame(bytes([247, 0x04, 0, 0, 0, 1])), None)
        expect("broadcast silent (FR-MB06)",
               frame(bytes([0, 0x06, 0, 0, 0, 100])), None)
        crc_before = read_input_u16(8)
        expect("bad CRC silent (FR-MB02)",
               frame(bytes([SLAVE, 0x04, 0, 0, 0, 1]))[:-1] + b"\x00", None)
        crc_after = read_input_u16(8)
        record("crc counter +1 (FR-MB02 diag)",
               crc_before is not None and crc_after == crc_before + 1,
               f"counter {crc_before} -> {crc_after} (expect +1)")
        # — exceptions —
        expect("FC01 -> exc 01 (FR-MB12)",
               frame(bytes([SLAVE, 0x01, 0, 0, 0, 1])),
               frame(bytes([SLAVE, 0x81, 0x01])))
        expect("unmapped read -> exc 02 (FR-MB13)",
               frame(bytes([SLAVE, 0x04, 0, 0x20, 0, 1])),
               frame(bytes([SLAVE, 0x84, 0x02])))
        expect("spanning read -> exc 02 (FR-MB14)",
               frame(bytes([SLAVE, 0x04, 0, 0x0E, 0, 2])),
               frame(bytes([SLAVE, 0x84, 0x02])))
        expect("qty 0 -> exc 03 (FR-MB28)",
               frame(bytes([SLAVE, 0x04, 0, 0, 0, 0])),
               frame(bytes([SLAVE, 0x84, 0x03])))
        expect("qty 126 -> exc 03 (FR-MB28)",
               frame(bytes([SLAVE, 0x04, 0, 0, 0, 126])),
               frame(bytes([SLAVE, 0x84, 0x03])))
        expect("unmapped write -> exc 02 (FR-MB15)",
               frame(bytes([SLAVE, 0x06, 0, 0x20, 0, 1])),
               frame(bytes([SLAVE, 0x86, 0x02])))
        # — writes —
        req = frame(bytes([SLAVE, 0x06, 0, 0, 0x0E, 0x10]))  # offset := 3600?
        expect("write 3600 -> exc 03, no clamp (FR-MB19)",
               req, frame(bytes([SLAVE, 0x86, 0x03])))
        expect("offset unchanged after reject",
               frame(bytes([SLAVE, 0x03, 0, 0, 0, 1])),
               frame(bytes([SLAVE, 0x03, 2, 0, 0])))
        req = frame(bytes([SLAVE, 0x06, 0, 0, 0x00, 0x64]))  # offset := 100
        expect("FC06 write + byte-exact echo (FR-MB30)", req, req)
        expect("offset readback 100 (FR-MB10)",
               frame(bytes([SLAVE, 0x03, 0, 0, 0, 1])),
               frame(bytes([SLAVE, 0x03, 2, 0, 100])))
        # FC16 atomic: valid offset 200 + invalid window 65000 -> both unchanged
        expect("FC16 atomic reject (FR-MB22)",
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 2, 4, 0, 200, 0xFD, 0xE8])),
               frame(bytes([SLAVE, 0x90, 0x03])))
        expect("both regs unchanged after atomic reject",
               frame(bytes([SLAVE, 0x03, 0, 0, 0, 2])),
               frame(bytes([SLAVE, 0x03, 4, 0, 100, 0x03, 0xE8])))
        # FC16 valid write of 2 regs + confirm response (FR-MB30/FR-MB11)
        expect("FC16 write 2 regs (FR-MB11/30)",
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 2, 4, 0, 150, 0x07, 0xD0])),
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 2])))  # window := 2000
        expect("FC16 readback",
               frame(bytes([SLAVE, 0x03, 0, 0, 0, 2])),
               frame(bytes([SLAVE, 0x03, 4, 0, 150, 0x07, 0xD0])))
        # FR-S31 cross-constraint via hook: window 60000 with avg 10 -> exc 03
        expect("FR-S31 violating write -> exc 03",
               frame(bytes([SLAVE, 0x06, 0, 1, 0xEA, 0x60])),
               frame(bytes([SLAVE, 0x86, 0x03])))
        # paired FC16 window=60000 & avg=60 -> accepted (constraint on staged pair)
        expect("FR-S31 paired write accepted",
               frame(bytes([SLAVE, 0x10, 0, 1, 0, 2, 4, 0xEA, 0x60, 0, 60])),
               frame(bytes([SLAVE, 0x10, 0, 1, 0, 2])))
        # bytecount mismatch (FR-MB28)
        expect("FC16 bytecount mismatch -> exc 03 (FR-MB28)",
               frame(bytes([SLAVE, 0x10, 0, 0, 0, 2, 5, 0, 1, 0, 2, 0])),
               frame(bytes([SLAVE, 0x90, 0x03])))

        if timings:
            worst = max(timings)
            typical = sorted(timings)[len(timings) // 2]
            record("response timing (FR-MB20/21)", worst < 100.0 and typical < 15.0,
                   f"median {typical:.1f} ms, worst {worst:.1f} ms "
                   f"(limits: typ<15, hard<100)")
    finally:
        bus.release()
        libm2k.contextClose(ctx)

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("MB CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
