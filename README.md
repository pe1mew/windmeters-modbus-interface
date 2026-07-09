# Windmeters Modbus Interface

A CH32V003-based interface board that bridges classic analog wind sensors —
a **cup anemometer** (reed-relay pulses) and a **wind-vane potentiometer**
(0–360°) — onto **Modbus RTU over RS-485**, powered by 24 V passive PoE and
designed for daisy-chained field buses.

One PCB serves both sensor types; the firmware build selects the variant.
Each variant responds at its own Modbus address, selected by a solder
jumper:

| Variant | Jumper open | Jumper bridged |
|---|---|---|
| Wind speed (`wind_speed`) | **30** | 35 |
| Wind direction (`wind_direction`) | **31** | 36 |
| Both, one slave (`wind_combined`) | **32** | 37 |

The `wind_combined` build serves both sensors through a single Modbus
address; its register map carries speed and direction at their own
register addresses, with the direction raw-ADC diagnostic at 30013 (30005
holds the speed pulse count).

## Project status (2026-07)

| Area | State |
|---|---|
| Requirements | [`design/TDS.md`](design/TDS.md) v0.6 — 67 active requirements, hardened by a multi-agent audit + verification passes |
| Drivers | Pulse counting, ADC/circular-mean, Modbus RTU — all HIL-verified on silicon ([`design/driverDevelopment.md`](design/driverDevelopment.md)) |
| Product firmware | Integration stages A–F complete; **TDS-functionally complete**, acceptance suite green on both variants ([`design/integrationPlan.md`](design/integrationPlan.md)) |
| Hardware | KiCad schematic/PCB in design; MAX3485 rig and real-PCB test rows pending (plan §9) |
| Release | Firmware version 1 not yet tagged ([`software/firmware/RELEASES.md`](software/firmware/RELEASES.md)) |

## Hardware

- **MCU**: WCH CH32V003J4M6 (RISC-V, SOP-8, 16 KB flash / 2 KB RAM) — the
  8-pin package drives the whole design: single-wire UART discipline,
  remap tricks, and a zero-interrupt firmware architecture
  ([`design/softwareArchitecture.md`](design/softwareArchitecture.md)).
- **RS-485**: MAX3485; DI+RO tied to PD6, DE+R̄Ē tied to PC2 with a 10 k
  pull-down (keeps the bus safe during reset/flashing); 120 Ω terminator
  behind a solder jumper; A/B fail-safe bias; SM712 TVS.
- **Power**: 24 V passive PoE on the spare pairs (4/5 = +, 7/8 = −) →
  DB207 bridge (polarity protection only) → HLK-K7803 buck → 3.3 V.
- **Connectors**: 2× RJ45 for the daisy-chained bus, RJ14 to the sensor,
  3-pin header for the WCH-LinkE programmer (SWIO on PD1).

## Modbus register map (summary)

12 input registers (FC04) and 4 holding registers (FC03/06/16), identical
on both variants — absent-sensor registers read 0. Highlights: instantaneous
and averaged values, status bits, identification (build + firmware
version), uptime, CRC/served counters, gust, seconds-since-last-pulse.
Holding: direction offset, measurement window, averaging window, low-speed
cut-off — **persisted in flash across reset/power-loss** (FR-S39); the §2.8
defaults apply only on first boot / erased store. The authoritative map with
ranges, defaults, and requirement IDs is [`design/TDS.md`](design/TDS.md)
§2.7/§2.8.

## Repository layout

| Path | Contents |
|---|---|
| `design/` | The document chain: `scratchBook.md` (working notes) → `TDS.md` (requirements) → `softwareArchitecture.md` (how) → `driverDevelopment.md` (driver phases + results) → `integrationPlan.md` (product firmware phases + results) |
| `hardware/KiCad/` | Schematic + PCB (KiCad); symbol libraries as git submodules |
| `hardware/Documentation/` | Component datasheets (HLK-K78xx, DB20x, Kradex enclosure, …) |
| `software/firmware/` | Product firmware (PlatformIO + ch32v003fun), two build envs + `_test` variants |
| `software/drivers/` | Standalone driver projects with HIL test shells (the verified libraries the product references in place) |
| `software/hil/` | Scripted hardware-in-the-loop harness: Saleae Logic 2 (MCP) + ADALM2000 (libm2k) + `acceptance/` pytest suite |
| `documentation/` | Chip pinout and project reference images |

Clone with submodules:

```sh
git clone --recurse-submodules https://github.com/pe1mew/windmeters-modbus-interface.git
```

## Building and flashing

Requires [PlatformIO](https://platformio.org/) and a WCH-LinkE on SWIO.

```sh
cd software/firmware
pio run -e wind_speed              # or wind_direction, or wind_combined
pio run -e wind_speed -t upload    # flash via WCH-LinkE
```

Resource ceilings (14 336 B flash / 1 792 B RAM, NFR-RES01) are enforced as
hard build gates. `*_test` environments add bench-only hooks — never
release those binaries. The firmware version byte lives in
`src/version.h`; the release process is documented in `RELEASES.md`.

## Testing

- **Host tests** (no hardware): the circular-mean math is exhaustively
  verified in Python — `python software/drivers/common/circmean/test_circmean.py`.
- **Acceptance suite** (bench: Saleae Logic 2 with its MCP server, ADALM2000,
  WCH-LinkE, TTL Modbus rig):

  ```sh
  cd software/hil/acceptance
  ..\.venv-m2k\Scripts\python.exe -m pytest . --build speed
  ```

  One command per flashed variant; covers the register map, protocol
  vectors, measurement services, averaging engine, version chain, and
  build gates. See [`software/hil/README.md`](software/hil/README.md) for
  instrument setup, wiring, and the bench-quirk catalogue.
- **HIL test report** — [`software/hil/testReport.md`](software/hil/testReport.md)
  consolidates every hardware-in-the-loop test (driver-phase, integration-
  stage, and MAX3485 transceiver rig) with its setup, expected result, and
  pass/fail verdict in one place.

## Related repositories

- [`pe1mew/windmeters-modbus-interface-tester`](https://github.com/pe1mew/windmeters-modbus-interface-tester) —
  the Modbus RTU master bench tool (M5Stack AtomS3 + RS-485) used to
  exercise this device; its bench findings seeded this project's TDS.

## License

Software is provided under a Source-Available Non-Commercial License;
documentation and images under CC BY-NC-ND 4.0. See [LICENSE](LICENSE) and
[license.md](license.md). Third-party datasheets and KiCad library
submodules remain under their owners' terms.

## Author

Remko Welling (PE1MEW)
