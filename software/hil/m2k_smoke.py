"""M2K bring-up smoke test — proves libm2k can reach the ADALM2000.

Prerequisites (admin, one-time):
  1. PlutoSDR-M2k-USB-Drivers.exe  (USB drivers for the IIO interface)
  2. libm2k-0.9.0-Windows-setup.exe (libm2k + libiio runtime DLLs)
Run with the Python 3.11 venv (wheels top out at cp311):
  software\\hil\\.venv-m2k\\Scripts\\python.exe software\\hil\\m2k_smoke.py

Exit 0 = context opened, calibrated, subsystems reachable.
"""

import sys

import libm2k


def main() -> int:
    print("[1/4] Enumerating IIO contexts ...")
    uris = libm2k.getAllContexts()
    for u in uris:
        print(f"      {u}")
    if not uris:
        print("      FAIL — no ADALM2000 found. Drivers installed? Device plugged in?")
        return 1

    print("[2/4] Opening context ...")
    ctx = libm2k.m2kOpen(uris[0])
    if ctx is None:
        print("      FAIL — context open failed")
        return 1
    try:
        print(f"      serial: {ctx.getSerialNumber()}")
        print(f"      firmware: {ctx.getFirmwareVersion()}")

        print("[3/4] Calibrating ADC + DAC ...")
        ok_adc = ctx.calibrateADC()
        ok_dac = ctx.calibrateDAC()
        print(f"      ADC: {'OK' if ok_adc else 'FAIL'}, DAC: {'OK' if ok_dac else 'FAIL'}")

        print("[4/4] Subsystems ...")
        for name, getter in (("analog in", ctx.getAnalogIn),
                             ("analog out", ctx.getAnalogOut),
                             ("digital", ctx.getDigital),
                             ("power supply", ctx.getPowerSupply)):
            obj = getter()
            print(f"      {name}: {'OK' if obj is not None else 'MISSING'}")
            if obj is None:
                return 1
        if not (ok_adc and ok_dac):
            return 1
    finally:
        libm2k.contextClose(ctx)

    print("M2K SMOKE TEST PASS — device reachable, calibrated, all subsystems up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
