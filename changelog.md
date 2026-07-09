# Changelog

All notable changes to the Windmeters Modbus Interface are documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and
this project adheres to [Semantic Versioning](https://semver.org/). No
firmware release has been tagged yet — the version-byte registry lives in
[`software/firmware/RELEASES.md`](software/firmware/RELEASES.md); firmware
version 1 will be tagged `fw-v1` at the first release.

---

## [Unreleased]

### Added — design & requirements

- Design document chain: `scratchBook.md` (brainstorm: sensors, power
  chain, ADC strategy, Modbus conventions, anemometer calibration
  C = 2πr/η) → **`TDS.md` v0.6** — 67 active requirements with measurable
  pass/fail criteria, matured through a 38-finding multi-agent gap audit,
  a 30-issue verification pass, and a fresh-eyes re-check. Key decisions:
  volatile holding registers, hardware-only device addressing (solder
  jumper + build variant), exception 04 never emitted, standard exception
  codes only, atomic FC16, no-clamp range rejection.
- `softwareArchitecture.md`: cooperative super-loop, later amended to
  **zero-interrupt** after bench findings (see firmware below).
- `driverDevelopment.md`: three-driver plan with HIL matrices per phase;
  `integrationPlan.md`: six-stage product-firmware plan with per-stage
  results and the hardware-gated test set (MAX3485 rig + real PCB).
- Open items documented for future decisions: persistence of the north
  offset (volatile-register coherence review) and a combined-sensor
  firmware variant (feasibility assessed: fits comfortably).

### Added — hardware (KiCad)

- Schematic and PCB: CH32V003J4M6 (SOP-8), MAX3485 (DI+RO on PD6,
  DE+R̄Ē on PC2), 24 V passive PoE → DB207 bridge (polarity protection) →
  HLK-K7803 3.3 V buck, dual RJ45 daisy-chain, RJ14 sensor connector,
  120 Ω terminator behind a solder jumper, PC4 address solder jumper,
  SM712 TVS + A/B fail-safe bias, anemometer input RC debounce + zener.
- **10 k pull-down on DE/R̄Ē** — holds the transceiver in receive mode
  while the MCU is in reset or being flashed (a floating DE could jam the
  shared bus).

### Added — drivers (all HIL-verified on silicon)

- `debug_uart` (PD6 TX tracer): 13 879 clean lines, zero errors.
- `wind_speed` (`ws`): TIM2 ETR pulse counting on PC1 — remap confirmed on
  silicon; 9/9 matrix (counts, rising-edges-only, window ±0.34% vs FR-S17's
  ±2%, saturation 65535-never-wrapped).
- `wind_direction` (`wd`) + `circmean` (Q15 sine table + integer CORDIC):
  accuracy −3.8 LSB against a DMM-measured divider (±10 budget), stability
  0.6 LSB, end stops exact, float detection proven; circular mean host-
  tested exhaustively (identity error 0 LSB over all 3600 angles) plus an
  on-target boot self-test.
- `modbus_rtu` (`mb`): 26/26 TDS §2 matrix + 40/40 endurance on a TTL rig,
  response latency 5.2 ms (budget 15/100 ms). Three bench-forced design
  changes: **HDSEL abandoned** (intermittently swallows the first byte
  after bus idle — replaced by a remap-switching line discipline: RX
  natively on PD6, TX remapped in only for the response; self-echo
  eliminated), **interrupts abandoned** (an RXNE ISR corrupted ~1/3 of
  frames with no error flags; polled RX is provably lossless at 9600 baud
  — the architecture is now zero-ISR with no concurrency surface), and
  **TX made push-pull** (first MAX3485 rig session: the open-drain TX
  inherited from the shared TTL wire has no pull-up behind the
  transceiver and transmitted a solid break — the TTL rig's pull-up had
  masked a ship-blocking defect; RO is tri-stated during DE, so push-pull
  is contention-free).

### Added — product firmware (`software/firmware/`, stages A–F)

- ch32v003fun project referencing the verified driver libraries in place;
  two build variants + `_test` envs (bench-only watchdog hang hook);
  NFR-RES01 ceilings enforced as hard build gates.
- `board.c`: FR-S18 init order, jumper address (all four addresses
  verified on the real jumper, including latch-until-reset semantics),
  IWDG ~1 s with PVD-gated feeding — watchdog hang→recovery < 2.5 s with
  all defaults restored. Silicon findings: LSI must be started before
  IWDG configuration; the SPL DBGMCU address faults this core (no debug
  freeze — flashing under a live watchdog bench-verified OK).
- `regs.c`: the complete TDS §2.7/§2.8 register image — per-build zeros,
  identification (build byte + version byte from `version.h`), status
  bits, uptime, CRC/served counters, pulse-age, gust.
- `meas_speed.c`/`meas_dir.c`: 40002-driven measurement windows with
  abort-on-write, ms-domain speed scaling (compile-time calibration
  factor with static-assert bounds), low-speed cut-off, saturation;
  10 Hz direction updates with offset/wrap and sticky float fault.
- `avg.c`: boxcar/two-stage averaging engine (proven live at N = 6000),
  gust tracking with correct decay, warm-up partial means (the
  zero-padding trap defeated: partial mean reads true value, not diluted).
- FR-S32 version chain: `version.h` single source + `RELEASES.md`
  registry + on-DUT verification.
- **`wind_combined` variant (build 0x03, address 32/37)** — one Modbus
  slave serving both sensors (integrationPlan §10). Capability-macro
  refactor (`sensors.h` maps the three `SENSOR_WIND_*` selectors to
  `HAVE_WIND_SPEED`/`HAVE_WIND_DIRECTION`), per-sensor measurement services,
  per-sensor averaging cursors (the two rings advance independently), speed
  pulse count at 30005 and direction raw ADC at the new 30013 (map edge
  extends 0x000C → 0x000D on this build). 6812 B flash / 1192 B RAM; the
  single-sensor builds are unchanged. **Validated over RS-485 at address 32,
  77/77** (`rs485_regs_check.py --build combined --speed-live`) with both
  sensors live simultaneously — divider on PA2 + a 30 Hz M2K W2 → PC1 pulse
  train (`m2k_pulse.py`): one FC04 image carries dir 182.8° + speed 29.4 m/s
  (count 30, gust 29.4, dir-raw at 30013), the per-cursor averaging verified
  live via the FR-S30 dance (both first windows + both cursors filled), full
  protocol/atomicity/FR-S31, served delta exact. The byte-exact raw suite
  (split 10/10, floods 3/3 incl. 60 s soak, baud ±3%, latency 1000/1000) is
  also green on combined — the full §9.1 treatment, matching the single
  builds. An adversarial multi-agent review of the diff found no confirmed
  defects.

### Added — HIL harness (`software/hil/`)

- Scripted bench: Saleae Logic 2 via its built-in MCP server + ADALM2000
  via libm2k (Python 3.11 venv), WCH-LinkE flashing — stimulus, capture,
  and assertion fully automated; M2K firmware updated 0.27 → 0.33.
- Check scripts (each standalone): `smoke_test`, `blinky_check`,
  `uart_check`, `m2k_smoke`, `m2k_signal_check` (15/15 signal
  verification), `ws_check`, `wd_check`, `mb_check`, `regs_check`,
  `meas_check`, `avg_check`, `version_check`, `rs485_check` (MAX3485
  rig: passive judge of live master traffic — DE timing, storm,
  idle-bias, latency), `rs485_regs_check` (full register read/write
  matrix over RS-485, driven through the tester's machine API —
  build-aware: **speed 62/62, direction 72/72**, the latter adding the
  north-offset→angle wraparound check, exact to 0 LSB), `rs485_raw_check`
  (second-MAX3485 raw master on M2K DIO0/DIO1: split frames, garbage
  floods incl. 60 s soak, baud margin to ±3%, 1000-request latency
  histogram ~4.1 ms — §9.1 byte-exact set green on both builds).
- **§9.1 (MAX3485 rig) complete for both variants** over real RS-485
  (speed at addr 30, direction at addr 31) — the only remaining §9.1 row
  is the FR-S38 direction float-fault, which needs a physical PA2
  disconnect. Enabled by a second MAX3485 as an M2K-driven raw master
  (byte-exact malformed vectors) and the tester's machine API as a
  well-formed scripted master returning raw wire frames.
- `acceptance/`: pytest suite (NFR-TST01 core) — one command per flashed
  variant; **green on both builds** (speed 6/6, direction 6/6), including
  build-gate checks and an opt-in reproducible-build comparison.
- A bench-quirk catalogue in `software/hil/README.md` (Saleae analyzer
  limits, M2K session-state behavior, AWG/scope accuracy, DUT UART
  gotchas) — hard-won knowledge that keeps future debugging short.

---

*Older working history predating this changelog lives in the git log
(initial scaffolding, first KiCad PCB and power-circuit commits).*
