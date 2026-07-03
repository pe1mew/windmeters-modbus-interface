# bare CH32V003J4M6 — PlatformIO Blinky

Minimal LED blink for a **bare WCH CH32V003J4M6** (RISC-V, SOP-8 package), built
with [PlatformIO](https://platformio.org/) using the
[ch32v003fun](https://github.com/cnlohr/ch32v003fun) framework and flashed with a
**WCH-LinkE** probe over the 1-wire SDI interface.

This is the PlatformIO counterpart to the Makefile/ch32fun
[nanoCH32V003 blinky](../nanoCH32V003/blinky/) in this repo.

## Layout

| File | Purpose |
|------|---------|
| `platformio.ini` | Board, framework (`ch32v003fun`) and `wch-link` upload settings |
| `src/main.c` | Application — toggles `PD6` (100 ms on / 900 ms off; changed from the original 750/250 to make freshly flashed code visually identifiable) |
| `src/funconfig.h` | ch32v003fun compile-time configuration (defaults are fine) |

## Hardware

The J4M6 is the SOP-8 package, so there is **no on-board LED** — wire your own:

```
  PD6 ──►|── [ ~330 Ω ] ── GND
        LED
```

Usable GPIO on this package: `PA1 PA2 PC1 PC2 PC4 PD4 PD6`.
`PD1` is the **SWIO** programming line — reserve it for the WCH-LinkE.

### Wiring to the WCH-LinkE

| WCH-LinkE | CH32V003J4M6 |
|-----------|--------------|
| `3V3`     | VDD          |
| `GND`     | VSS          |
| `SWDIO / DIO` | `PD1` (SWIO) |

## Build & flash

With the [PlatformIO Core CLI](https://docs.platformio.org/en/latest/core/index.html)
(or the VS Code PlatformIO extension) installed:

```bash
pio run                 # compile
pio run --target upload # compile + flash via WCH-LinkE
pio run --target clean  # remove build artifacts
```

The `ch32v` platform, the `ch32v003fun` framework and the RISC-V toolchain are
downloaded automatically on the first build. Flashing uses the WCH OpenOCD /
`wch-link` backend that ships with the platform.
