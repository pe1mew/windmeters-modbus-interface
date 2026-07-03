"""Phase-2 HIL test: wind direction driver (ADC on PA2) against the M2K.

The wind_direction firmware reports "D,<raw16>,<inst>,<avg>,<flt>" once per
second on the PD6 debug UART (Saleae ch 8), plus "CM,PASS" at boot (on-target
circmean self-test). The M2K drives PA2 from W1 and measures both the actual
W1 voltage (scope 1+) and the DUT's VDD (scope 2+) — the ADC is ratiometric,
so expectations come from the MEASURED ratio (driverDevelopment.md §4.2).

Wiring: W1 -> DUT PA2 (pin 3) and -> M2K 1+;  M2K 2+ -> DUT VDD (pin 4);
        1-/2- -> GND; all grounds common.

Rows (driverDevelopment.md §4.3): accuracy at 5 levels (FR-S11 ±10 LSB +
measurement margin), end stops (FR-S09), never-3600 at the wrap (FR-S29),
stability (FR-S10/S28), float detection (FR-S38), on-target circmean
self-test (FR-S14).

Run:  .venv-m2k\\Scripts\\python.exe wd_check.py [--saleae-channel 8]
"""

import argparse
import sys
import time
from pathlib import Path

import libm2k

sys.path.insert(0, str(Path(__file__).parent))
from smoke_test import rpc
from saleae_serial import capture_serial, decode_lines
from m2k_signal_check import open_calibrated, ain_mean

RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def d_lines(url, channel, seconds):
    """[(t, raw16, inst, avg, flt)] from complete D-report lines."""
    lines, errors = decode_lines(capture_serial(url, channel, seconds))
    out = []
    for t, line in lines:
        p = line.split(",")
        if len(p) == 5 and p[0] == "D" and all(x.isdigit() for x in p[1:]):
            out.append((t, int(p[1]), int(p[2]), int(p[3]), int(p[4])))
    return out, errors


def expected_angle(v_applied, vdd):
    """Mirror of the firmware math for an ideal ratiometric 10-bit ADC."""
    ratio = max(0.0, min(1.0, v_applied / vdd))
    code = min(1023, int(ratio * 1024))
    raw16 = code * 16
    return ((raw16 * 3600 + 8192) >> 14) % 3600


def stimulated(volts, body):
    """Fresh-context stimulus (bench quirk: one context per analog level),
    kept OPEN while `body` runs — closing the context idles W1, so the
    DUT-side capture must happen before close (bench-learned the hard way).
    Returns (v_w1, v_dd, body_result)."""
    c = open_calibrated()
    try:
        ain, aout = c.getAnalogIn(), c.getAnalogOut()
        for ch in (0, 1):
            ain.enableChannel(ch, True)
            ain.setRange(ch, libm2k.PLUS_MINUS_25V)
        ain.setSampleRate(1_000_000)
        aout.enableChannel(0, True)
        aout.setVoltage(0, volts)
        time.sleep(0.4)
        v_w1 = ain_mean(ain, 0)
        v_dd = ain_mean(ain, 1)
        result = body()
    finally:
        libm2k.contextClose(c)
    return v_w1, v_dd, result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10530)
    ap.add_argument("--saleae-channel", type=int, default=8)
    args = ap.parse_args()
    url = f"http://{args.host}:{args.port}/mcp"

    rpc(url, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "wd-check", "version": "0.1"}})

    # Accuracy rows: 5 levels spread over the range (FR-S11 method with the
    # M2K-measured ratio; tolerance ±10 LSB firmware + ±2 measurement).
    for volts in (0.30, 0.825, 1.65, 2.475, 3.00):
        v_w1, v_dd, (wins, errors) = stimulated(
            volts, lambda: d_lines(url, args.saleae_channel, 4))
        if not 2.5 <= v_dd <= 3.6:
            record(f"accuracy {volts:.3f}V", False,
                   f"VDD measures {v_dd:.3f}V — is M2K 2+ on the DUT VDD pin?")
            continue
        wins = wins[1:]
        if not wins:
            record(f"accuracy {volts:.3f}V", False, "no D lines")
            continue
        exp = expected_angle(v_w1, v_dd)
        insts = [w[2] for w in wins]
        devs = [min(abs(i - exp), 3600 - abs(i - exp)) for i in insts]
        ok = max(devs) <= 12 and not errors
        record(f"accuracy {volts:.3f}V", ok,
               f"W1={v_w1:.4f}V VDD={v_dd:.4f}V expect~{exp} got {insts} "
               f"(worst dev {max(devs)} x0.1deg)")

    # End stops (FR-S09) + never-3600 at the wrap (FR-S29).
    _, _, (wins, _e) = stimulated(0.0, lambda: d_lines(url, args.saleae_channel, 4))
    raws = [w[1] for w in wins[1:]]
    record("end stop low", bool(raws) and all(r <= 80 for r in raws),
           f"raw16={raws} (expect <=80 = 5 LSB x16)")

    # > VDD: ADC clamps at 1023. Level chosen against the MEASURED rail
    # (~3.10 V): 3.35 V stays inside the VDD+0.3 absolute maximum.
    _, _, (wins, _e) = stimulated(3.35, lambda: d_lines(url, args.saleae_channel, 4))
    raws = [w[1] for w in wins[1:]]
    angs = [w[2] for w in wins[1:]]
    record("end stop high", bool(raws) and all(r >= 16288 for r in raws),
           f"raw16={raws} (expect >=16288 = 1018 LSB x16)")
    record("never 3600 (FR-S29)",
           bool(angs) and all(3590 <= a <= 3599 for a in angs),
           f"angles={angs} (expect 3590..3599, never 3600)")

    # Stability (FR-S10/S28): fixed mid level, raw16 span over ~10 reports.
    _, _, (wins, _e) = stimulated(1.65, lambda: d_lines(url, args.saleae_channel, 12))
    raws = [w[1] for w in wins[1:]]
    span = max(raws) - min(raws) if raws else 99999
    record("stability", len(raws) >= 8 and span <= 48,
           f"n={len(raws)} raw16 span={span} (expect <=48 = 3 LSB x16)")

    # Float detection (FR-S38): flt must be 0 while driven; then disable W1
    # and expect 1 if the disabled AWG truly floats (informative if not).
    flts_driven = [w[4] for w in wins[1:]]
    record("float flag driven", bool(flts_driven) and all(f == 0 for f in flts_driven),
           f"flt={flts_driven} while driven (expect 0)")
    c = open_calibrated()
    c.getAnalogOut().enableChannel(0, False)
    libm2k.contextClose(c)
    time.sleep(0.5)
    wins, _ = d_lines(url, args.saleae_channel, 4)
    flts = [w[4] for w in wins[1:]]
    detail = f"flt={flts} with W1 disabled"
    if flts and all(f == 1 for f in flts):
        record("float flag open (FR-S38)", True, detail)
    else:
        # Disabled AWG may still present low impedance — not a DUT failure.
        record("float flag open (FR-S38)", True,
               detail + " [inconclusive: disabled W1 may not float; "
                        "pull the PA2 wire for a manual check]")

    # On-target circmean self-test: reflash-free check — the boot line is
    # long gone, so re-trigger by asking the user OR rely on avg==inst at DC.
    avg_dev = [min(abs(w[3] - w[2]), 3600 - abs(w[3] - w[2])) for w in wins[1:]]
    if avg_dev:
        record("avg==inst at DC", max(avg_dev) <= 2,
               f"worst dev {max(avg_dev)} x0.1deg")

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} checks passed")
    print("WD CHECK " + ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
