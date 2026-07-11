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
  persisted holding registers (FR-S39), hardware-only device addressing
  (solder jumper + build variant), exception 04 never emitted, standard
  exception codes only, atomic FC16, no-clamp range rejection.
- `softwareArchitecture.md`: cooperative super-loop, later amended to
  **zero-interrupt** after bench findings (see firmware below).
- `driverDevelopment.md`: three-driver plan with HIL matrices per phase;
  `integrationPlan.md`: six-stage product-firmware plan with per-stage
  results and the hardware-gated test set (MAX3485 rig + real PCB).
- Two decisions were documented as deferred, then both subsequently taken
  and implemented (see firmware): holding-register persistence (the
  volatile-register coherence review → FR-S39) and the combined-sensor
  firmware variant (→ `wind_combined`).

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
- **Persistent holding registers (FR-S39).** The four holding registers
  (40001–40004) now survive reset/power-loss — the CH32V003 has no EEPROM,
  so `persist.c` flash-emulates it: two 64-byte pages at the top of flash
  (above the NFR-RES01 code gate) as a ping-pong log, one 16-byte CRC'd
  record per page, newest-sequence-wins, power-loss atomic, save-on-change.
  `regs_init` seeds the holdings from flash (blank/corrupt → §2.8 defaults,
  so FR-S21's defined state still holds); a changed set is committed from
  the main loop *after* the Modbus response (the ~6 ms flash op stays out
  of the FR-MB20/21 latency path). ~560 B flash / 8 B RAM. This takes the
  long-deferred TDS §5 persistence decision (resolution (c), all four
  registers). Bench-verified 7/7 (`rs485_persist_check.py`): non-default
  settings survive a watchdog reset, an erased store falls back to
  defaults, and the ping-pong handles successive saves. Requirements
  updated: new FR-S39, FR-S21 carve-out, holding-map + interface-assumption
  notes.
- **Runtime + persistent anemometer calibration (FR-S40, TDS v0.8).** The
  anemometer calibration moved from a compile-time-only `WS_C_SCALED` to two
  persistent holding registers — **40005** (calibration factor C, 0.001
  m/rotation) and **40006** (pulses per rotation) — with the compile-time
  values as factory defaults. FR-S06 speed is now
  `count × C × 10 / (window_ms × pulses_per_rotation)`, so one firmware image
  serves any anemometer with no rebuild: a field installer sets the two
  registers over Modbus and they persist. A change clears the averaging
  accumulator (like FR-S30). The persistence record grew 16 → 20 B with a
  bumped magic, so a pre-existing store cleanly re-defaults. Verified on the
  deployed combined unit: defaults [980, 1], writes + range-reject (exc 03),
  the four-pulse case set live to 40006 = 4. FR-S25/FR-S06 reworked, FR-S39
  now covers six registers, §2.8 map extended.

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
- **§9.1 (MAX3485 rig) complete on all three variants** over real RS-485
  (speed 30, direction 31, combined 32). Enabled by a second MAX3485 as an
  M2K-driven raw master (byte-exact malformed vectors) and the tester's
  machine API as a well-formed scripted master returning raw wire frames.
  The last row, **FR-S38 wind-direction float-fault + recovery, was
  validated over the transceiver** (`rs485_float_check.py`): PA2 wiper
  lifted → DIR_FAULT + 65535 sentinels (fault 4/4); re-driven → sticky
  fault clears, real angle returns (recovery 4/4).
- `acceptance/`: pytest suite (NFR-TST01 core) — one command per flashed
  variant; **green on both builds** (speed 6/6, direction 6/6), including
  build-gate checks and an opt-in reproducible-build comparison.
- A bench-quirk catalogue in `software/hil/README.md` (Saleae analyzer
  limits, M2K session-state behavior, AWG/scope accuracy, DUT UART
  gotchas) — hard-won knowledge that keeps future debugging short.

### Added — documentation & tooling

- **Comprehensive Doxygen** on every project header (file blocks with FR-ID
  rationale and `@ref` cross-links; `@param`/`@return`/`@note` on all public
  functions, macros, structs and members) — comment-only, all variants build
  to identical sizes.
- **`Doxyfile`** builds a single browsable site with the project README as
  the landing page, folding the design docs (TDS, integration plan,
  architecture, driver development, scratchbook) + HIL report in as pages
  alongside the API reference; generates with zero warnings.
- **UML diagrams** (`design/diagrams/`, PlantUML sources + rendered PNGs):
  a component diagram, a zero-ISR super-loop sequence diagram, and the
  Modbus RTU line-discipline state machine — embedded in
  `softwareArchitecture.md` §7.
- **`design/README.md`** indexes the design-document chain and variants;
  root docs (README, contributing) updated for the three variants,
  persistence, and the documentation site.

---

*Older working history predating this changelog lives in the git log
(initial scaffolding, first KiCad PCB and power-circuit commits).*
