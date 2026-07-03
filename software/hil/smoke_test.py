"""HIL harness smoke test — proves the Saleae Logic 2 MCP link works.

Logic 2 (>= 2.4.44) ships a built-in MCP server (JSON-RPC over HTTP). This
script exercises the full chain: initialize -> get_devices -> start_capture
on the first real device -> wait -> export digital CSV -> close.

Stdlib only — no venv required:
    python smoke_test.py [--port 10530] [--duration 1.0]

Exit code 0 = MCP link, capture, and export all work.

Device quirks learned on the bench (Logic16, classic):
 - omit digitalThresholdVolts: the device uses range-based thresholds
   (1.8-3.6 V / 3.6-5.0 V) and rejects plain voltage values; the hardware
   default range suits 3.3 V logic.
 - export_raw_data_csv requires analogDownsampleRatio even for
   digital-only exports (pass 1).
"""

import argparse
import csv
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

_rpc_id = 0


def rpc(url: str, method: str, params: dict | None = None, timeout: float = 30.0):
    global _rpc_id
    _rpc_id += 1
    payload = {"jsonrpc": "2.0", "id": _rpc_id, "method": method}
    if params is not None:
        payload["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        reply = json.loads(resp.read())
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply.get("result")


def tool(url: str, name: str, arguments: dict, timeout: float = 30.0):
    result = rpc(url, "tools/call", {"name": name, "arguments": arguments}, timeout)
    text = result["content"][0]["text"]
    if result.get("isError"):
        raise RuntimeError(f"{name}: {text}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--duration", type=float, default=1.0)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    print(f"[1/5] MCP initialize @ {url} ...")
    init = rpc(url, "initialize", {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "hil-smoke", "version": "0.1"}})
    server = init["serverInfo"]
    print(f"      OK — {server['name']} {server['version']}")

    print("[2/5] get_devices ...")
    devices = tool(url, "get_devices", {"includeSimulationDevices": True})["devices"]
    real = [d for d in devices if not d["isSimulation"]]
    for d in devices:
        tag = "sim " if d["isSimulation"] else "REAL"
        print(f"      {tag}: {d['deviceType']} id={d['deviceId']}")
    if not devices:
        print("      FAIL — no devices at all")
        return 1
    device = (real or devices)[0]
    print(f"      using {'real' if real else 'simulation'} {device['deviceType']}")

    print(f"[3/5] start_capture, {args.duration}s, digital ch 0+1 @ 10 MS/s ...")
    cap = tool(url, "start_capture", {
        "deviceId": device["deviceId"],
        "logicDeviceConfiguration": {
            "logicChannels": {"digitalChannels": [0, 1]},
            "digitalSampleRate": 10_000_000,
        },
        "captureConfiguration": {
            "timedCaptureMode": {"durationSeconds": args.duration}},
    })
    capture_id = cap["captureId"]
    print(f"      captureId={capture_id}")

    print("[4/5] wait_capture + export_raw_data_csv ...")
    tool(url, "wait_capture", {"captureId": capture_id},
         timeout=args.duration + 60.0)
    out_dir = Path(tempfile.mkdtemp(prefix="saleae_smoke_"))
    tool(url, "export_raw_data_csv", {
        "captureId": capture_id,
        "directory": str(out_dir),
        "digitalChannels": [0, 1],
        "analogDownsampleRatio": 1,
    })
    csv_file = out_dir / "digital.csv"
    with open(csv_file, newline="") as f:
        rows = sum(1 for _ in csv.reader(f)) - 1
    print(f"      {csv_file} — {rows} transition rows")

    print("[5/5] close_capture ...")
    tool(url, "close_capture", {"captureId": capture_id})

    print("SMOKE TEST PASS — MCP link, capture, and export all work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
