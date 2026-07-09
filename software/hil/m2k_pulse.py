"""M2K speed stimulus for combined-build HIL: a cyclic square wave on W2
(AWG ch1) -> DUT PC1 (TIM2 ETR), so the anemometer path has live pulses
while the divider drives PA2 (direction). Independent of the DIO raw
master, per the stage-D method (integrationPlan §5).

Holds the M2K context OPEN for --seconds so the pulse train keeps running
while another process (the tester API) exercises the combined register
matrix. Also keeps V+ = 3.3 V enabled so the second MAX3485 on the bus
stays powered (its DE held low = passive receiver, not driving A/B).

Wiring: M2K W2 -> DUT PC1; M2K GND common. (V+ -> 2nd MAX3485 VCC,
DIO0/DIO1 -> its DI/DE, from the raw-master rig — left powered + idle.)

Run:  .venv-m2k\\Scripts\\python.exe m2k_pulse.py [--hz 30] [--seconds 180]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import libm2k
from m2k_signal_check import open_calibrated

W2 = 1          # AnalogOut channel 1 = W2
D_DI, D_DE = 0, 1  # raw-master DIO (kept idle/passive here)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=30.0)
    ap.add_argument("--seconds", type=float, default=180.0)
    ap.add_argument("--rate", type=int, default=75000,
                    help="AWG sample rate (on the 75 MS/s/10^n ladder)")
    args = ap.parse_args()

    ctx = open_calibrated()
    try:
        # Keep the 2nd MAX3485 powered + passive (DE low) so it doesn't
        # load / drive the shared bus during the matrix.
        ps = ctx.getPowerSupply()
        ps.enableChannel(0, True)
        ps.pushChannel(0, 3.3)
        dig = ctx.getDigital()
        for ch in (D_DI, D_DE):
            dig.setOutputMode(ch, libm2k.DIO_PUSHPULL)
            dig.setDirection(ch, libm2k.DIO_OUTPUT)
            dig.enableChannel(ch, True)
        dig.setValueRaw(D_DI, 1)   # idle mark
        dig.setValueRaw(D_DE, 0)   # driver OFF -> passive on the bus

        # Square wave on W2: len = rate / hz samples, half high / half low.
        n = max(4, int(round(args.rate / args.hz)))
        n -= n % 2
        buf = [3.3] * (n // 2) + [0.0] * (n // 2)
        aout = ctx.getAnalogOut()
        aout.enableChannel(W2, True)
        aout.setSampleRate(W2, args.rate)
        aout.setCyclic(True)   # repeat the buffer forever (both channels)
        aout.push(W2, buf)
        actual_hz = args.rate / n
        print(f"W2 square wave up: {actual_hz:.2f} Hz "
              f"({n} samples @ {args.rate} S/s), V+ 3.3 V enabled")
        print(f"holding for {args.seconds:.0f} s ...")
        time.sleep(args.seconds)
    finally:
        libm2k.contextClose(ctx)
        print("M2K released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
