# Firmware — Windmeter Modbus interface

PlatformIO project for the **CH32V003J4M6** (RISC-V, SOIC-8, 16 KB flash / 2 KB RAM).

The same board runs either sensor variant; the sensor type is chosen at build
time. See [`design/scratchBook.md`](../design/scratchBook.md) for the pin
assignment, Modbus register map and design rationale.

## Prerequisites

- [PlatformIO Core](https://platformio.org/install/cli) (`pip install platformio`)
  or the PlatformIO VS Code extension.
- A **WCH-LinkE** programmer connected to SWIO (PD1).

The community WCH platform is pulled automatically from
`platform = https://github.com/Community-PIO-CH32V/platform-ch32v.git` on first build.

## Build environments

| Environment      | Define                  | Sensor          |
|------------------|-------------------------|-----------------|
| `wind_speed`     | `SENSOR_WIND_SPEED`     | cup anemometer  |
| `wind_direction` | `SENSOR_WIND_DIRECTION` | potentiometer   |

## Usage

```sh
pio run                          # build default env (wind_speed)
pio run -e wind_direction        # build wind-direction variant
pio run -e wind_speed -t upload  # flash via WCH-LinkE
pio device monitor               # serial monitor (9600 baud)
```
