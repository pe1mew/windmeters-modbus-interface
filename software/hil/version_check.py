"""FR-S32 version-chain check: version.h <-> RELEASES.md <-> flashed DUT.

Static checks (always run):
  1. Parse FW_VERSION from software/firmware/src/version.h.
  2. RELEASES.md must contain a row for that version.

DUT check (needs the bench: Logic 2 MCP + M2K master + flashed DUT):
  3. Read register 30007 over Modbus; the low byte must equal FW_VERSION
     and the high byte must be a valid build type (0x01/0x02).

Run:  .venv-m2k\\Scripts\\python.exe version_check.py [--no-dut] [--address 30]

Exit 0 = every executed check passed.
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
FIRMWARE = HERE.parent / "firmware"


def static_checks():
    version_h = (FIRMWARE / "src" / "version.h").read_text()
    m = re.search(r"#define\s+FW_VERSION\s+(\d+)", version_h)
    if not m:
        print("  [FAIL] FW_VERSION not found in version.h")
        return None
    ver = int(m.group(1))
    print(f"  [PASS] version.h: FW_VERSION = {ver}")
    if not 1 <= ver <= 255:
        print(f"  [FAIL] FW_VERSION {ver} outside the 8-bit register field")
        return None

    releases = (FIRMWARE / "RELEASES.md").read_text()
    row = re.search(rf"^\|\s*{ver}\s*\|", releases, re.MULTILINE)
    if not row:
        print(f"  [FAIL] RELEASES.md has no row for version {ver}")
        return None
    print(f"  [PASS] RELEASES.md: row for version {ver} present")
    return ver


def dut_check(ver, host, port, channel, address):
    sys.path.insert(0, str(HERE))
    import libm2k
    from smoke_test import rpc
    from mb_check import Bus, frame, transact

    url = f"http://{host}:{port}/mcp"
    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "version-check", "version": "0.1"}})
    ctx = libm2k.m2kOpen()
    if ctx is None:
        print("  [FAIL] no M2K context")
        return False
    try:
        bus = Bus(ctx)
        req = frame(bytes([address, 0x04, 0, 6, 0, 1]))
        resp = None
        for _ in range(3):
            resp, _gap = transact(url, bus, channel, req)
            if resp and len(resp) == 7 and resp[1] == 0x04:
                break
        if not (resp and len(resp) == 7 and resp[1] == 0x04):
            print(f"  [FAIL] no valid 30007 reply from address {address}")
            return False
        build, dut_ver = resp[3], resp[4]
        ok_build = build in (0x01, 0x02)
        ok_ver = dut_ver == ver
        name = {1: "wind_speed", 2: "wind_direction"}.get(build, "?")
        print(f"  [{'PASS' if ok_build else 'FAIL'}] DUT build type 0x{build:02X} ({name})")
        print(f"  [{'PASS' if ok_ver else 'FAIL'}] DUT version {dut_ver} "
              f"{'==' if ok_ver else '!='} version.h {ver}")
        return ok_build and ok_ver
    finally:
        libm2k.contextClose(ctx)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, default=8)
    ap.add_argument("--address", type=int, default=30,
                    help="DUT slave address (30 speed / 31 direction default)")
    ap.add_argument("--no-dut", action="store_true",
                    help="static checks only (bench not available)")
    args = ap.parse_args()

    ver = static_checks()
    if ver is None:
        print("VERSION CHECK FAIL")
        return 1
    if args.no_dut:
        print("VERSION CHECK PASS (static only — DUT skipped)")
        return 0
    ok = dut_check(ver, args.host, args.port, args.saleae_channel, args.address)
    print("VERSION CHECK " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
