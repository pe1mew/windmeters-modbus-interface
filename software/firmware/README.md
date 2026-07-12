# Firmware — Windmeter Modbus interface

PlatformIO project for the **CH32V003J4M6** (RISC-V, SOIC-8, 16 KB flash /
2 KB RAM). One unmodified PCB runs every variant; the sensor build is chosen
at compile time (TDS FR-S01/FR-S02).

Authoritative references: the register map and behaviour contract live in
[`design/TDS.md`](../../design/TDS.md) (§2.7 input / §2.8 holding registers,
§4 as-built hardware and pin assignment); the zero-ISR super-loop design and
module split in
[`design/softwareArchitecture.md`](../../design/softwareArchitecture.md).

## Build environments

| Environment      | Define                   | Sensor(s)                    | Build byte | Address (PC4 open / bridged) |
|------------------|--------------------------|------------------------------|------------|------------------------------|
| `wind_speed`     | `SENSOR_WIND_SPEED`      | cup anemometer               | `0x01`     | **30** / 35                  |
| `wind_direction` | `SENSOR_WIND_DIRECTION`  | wind-vane potentiometer      | `0x02`     | **31** / 36                  |
| `wind_combined`  | `SENSOR_WIND_COMBINED`   | both, behind one slave       | `0x03`     | **32** / 37                  |

`sensors.h` maps the selector onto capability macros
(`HAVE_WIND_SPEED` / `HAVE_WIND_DIRECTION`); the combined build defines both.
Each variant also has a **`*_test`** environment adding `-D TEST_HOOKS` — the
FR-S20 watchdog hang trigger (holding `0x00FF`, magic `0xDEAD`) used by the
HIL persistence/reset checks. **Never release a `*_test` binary.**

## Prerequisites

- [PlatformIO Core](https://platformio.org/install/cli) (`pip install platformio`)
  or the PlatformIO VS Code extension.
- A **WCH-LinkE** programmer on SWIO (PD1, the 3-pin header J2).

The community WCH platform (`platform = ch32v`) and the `ch32v003fun`
framework are pulled automatically on first build. The verified driver
libraries (`ws_*`, `wd_*`, `mb_*`, `circmean`) are referenced **in place**
from [`software/drivers/`](../drivers/) — no copies.

## Usage

```sh
pio run                            # build default env (wind_speed)
pio run -e wind_combined           # build the combined variant
pio run -e wind_combined -t upload # flash via WCH-LinkE
```

There is no serial console: the release firmware never transmits unsolicited
(FR-S19) — PD6 is the Modbus data line. Talk to a flashed device over
RS-485/Modbus RTU (9600 8N1), e.g. with the
[`windmeters-modbus-interface-tester`](https://github.com/pe1mew/windmeters-modbus-interface-tester)
as master.

## Resource ceilings (NFR-RES01)

The 87.5 % ceilings — **14 336 B flash / 1 792 B RAM** — are hard build gates
(`board_upload.maximum_size` / `maximum_ram_size`); a build that exceeds them
fails. As-built (fw v1, with FR-S39 persistence + FR-S40 calibration):

| Variant | Flash | RAM |
|---|---|---|
| `wind_speed` | 4 408 B (31 %) | 908 B (51 %) |
| `wind_direction` | 6 824 B (48 %) | 916 B (51 %) |
| `wind_combined` | 7 604 B (53 %) | 1 216 B (68 %) |

## Configuration and calibration

All six holding registers (40001–40006) are runtime-writable and **persist in
flash across reset/power-loss** (FR-S39). The anemometer calibration
(FR-S40) is register-driven — factor C in 40005, pulses-per-rotation in
40006 — so one binary serves any anemometer with no rebuild. The compile-time
defaults that seed those registers on first boot can be overridden per build:

```ini
build_flags = ... -D WS_C_SCALED=980 -D WS_PULSES_PER_ROTATION=1
```

## Versioning and releases

The firmware version byte (reported in input register 30007, low byte) has a
single source: [`src/version.h`](src/version.h). Releases are registered in
[`RELEASES.md`](RELEASES.md); firmware version 1 will be tagged `fw-v1`.

## Testing

- **Host tests** (no hardware): `python ../drivers/common/circmean/test_circmean.py`.
- **Acceptance suite** (bench, one command per flashed variant):

  ```sh
  cd ../hil/acceptance
  ..\.venv-m2k\Scripts\python.exe -m pytest . --build combined
  ```

  Instrument setup, wiring, and the bench-quirk catalogue are in
  [`software/hil/README.md`](../hil/README.md); every executed HIL test with
  its verdict is consolidated in
  [`software/hil/testReport.md`](../hil/testReport.md).
