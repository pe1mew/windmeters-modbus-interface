# Driver Development Plan

| Field | Value |
|---|---|
| Document | Driver development plan |
| Project | `windmeters-modbus-interface` firmware |
| Date | 2026-07-03 |
| Related docs | `design/TDS.md` v0.6 (requirement IDs cited below), `design/softwareArchitecture.md` (the contract drivers integrate into), `design/scratchBook.md`, `software/drivers/blinky_template/` (verified starting point) |

## 1. Approach

Three drivers are developed **standalone**, each as its own PlatformIO project
copied from the verified `software/drivers/blinky_template`. Each driver gets
its own hardware-in-the-loop (HIL) test rig observed by a Saleae logic
analyser that Claude can drive through the Logic 2 automation API — flash,
capture, assert, iterate. Only after each driver passes its HIL exit criteria
are they integrated into the single application (phase 4, out of scope here).

Driver order (dependency- and risk-driven):

| Phase | Driver | Why this order |
|---|---|---|
| 0 | Common foundations (debug UART on PD6 + HIL harness) | Everything else depends on it; the PD6 half-duplex UART is also the riskiest unknown of the Modbus driver, so it gets de-risked first |
| 1 | Wind speed (pulse, TIM2 ETR) | Smallest driver; validates the AFIO remap question early |
| 2 | Wind direction (analog, ADC) | Adds oversampling + fixed-point math; math is host-testable before HIL |
| 3 | Modbus RTU | Largest driver; reuses the phase-0 UART work; its HIL suite is an early execution of the TDS §2 test set (NFR-TST01) |

## 2. Common foundations (phase 0)

### 2.1 Project conventions

- One folder per driver, each a self-contained PlatformIO project cloned from
  the template:
  - `software/drivers/wind_speed/`
  - `software/drivers/wind_direction/`
  - `software/drivers/modbus_rtu/`
  - `software/drivers/common/` — shared library code (no project files)
- Shared code is pulled in per project via `lib_extra_dirs = ../common` in
  `platformio.ini`. First resident: `debug_uart` (below). Driver logic itself
  is written as a `lib`-style pair (`ws_*.c/h`, `wd_*.c/h`, `mb_*.c/h`) with a
  thin `main.c` test shell around it, so phase-4 integration is a copy of the
  library files, not surgery on test code.
- Build/flash/monitor loop (all runnable by Claude via CLI):
  ```
  pio run                  # compile
  pio run -t upload        # flash via WCH-LinkE (SDI on PD1)
  pio device monitor       # 115200 8N1, via the WCH-LinkE's own UART RX pin
  ```
- `funconfig.h`: `FUNCONF_USE_DEBUGPRINTF 0` in all drivers — debug printf
  over SDI halts timing and would distort HIL measurements; all tracing goes
  over the PD6 UART (or the bus itself, for the Modbus driver).

### 2.2 Debug UART on PD6 (deliverable: `common/debug_uart`)

On the SOP-8 package USART1 TX (PD5) is not bonded out, so the debug output
uses the same trick the product does for Modbus: **USART1 in single-wire
half-duplex mode (HDSEL) on PD6**, TX-only, 115200 8N1 to match
`monitor_speed`.

- API: `dbg_init()`, `dbg_putc()`, `dbg_print(str)`, `dbg_print_u16/u32(v)` —
  integer-only formatting, no printf, to keep flash cost near zero.
- Every driver test build streams its observations as short ASCII lines
  (e.g. `W,1000,17` = window of 1000 ms, 17 pulses). Machine-parseable,
  human-readable, timestamped for free by the Saleae capture.
- Wiring: PD6 → WCH-LinkE UART RX (so `pio device monitor` shows it) and in
  parallel → one Saleae digital channel.
- **Exit criterion: MET (2026-07-03).** `software/hil/uart_check.py` decoded
  13 879 lines in a 12 s capture (≥10 000 required) with zero counter gaps
  across 138 795 bytes and zero framing errors. Implementation:
  `software/drivers/common/debug_uart/` (USART1 remap {RM1,RM}={1,0} puts TX
  on PD6; HDSEL set; TX-only), exercised by the
  `software/drivers/debug_uart_test/` project (772 B flash). Throughput at
  saturation ≈ 93% of the theoretical 11 520 B/s.
- Analyzer-CSV parsing notes for future HIL scripts: `add_analyzer` settings
  need tagged values (`{"numberValue": 8}`); the exported data column holds
  the **literal character** (CR/LF appear as embedded newlines in quoted
  fields — do not strip); a capture that starts mid-byte yields garbage plus
  one framing error before the first line boundary — judge only from the
  first clean `\n` onward.

This deliverable doubles as the first half of the Modbus UART driver
(FR-MB01 framing; HDSEL behaviour groundwork for FR-MB23).

### 2.3 HIL harness (deliverable: `software/hil/`)

- Interface (verified 2026-07-03): Saleae **Logic 2 ≥ 2.4.44 ships a built-in
  MCP server** — JSON-RPC over HTTP at `http://127.0.0.1:10530/mcp`. It
  exposes the full automation surface: `get_devices`, `start/stop/wait/
  load/save/close_capture`, `add_analyzer` (e.g. Async Serial on the PD6
  channel), `export_raw_data_csv`, `export_data_table_csv`. Claude drives it
  natively as a registered MCP server; scripts reach the same endpoint with
  stdlib `urllib` — no gRPC, no extra packages. (The older `logic2-automation`
  gRPC route on port 10430 remains a fallback if ever enabled; not used.)
- `software/hil/smoke_test.py` (passing): initialize → enumerate devices →
  1 s timed capture on the real device → export digital CSV → close. Run:
  `python software/hil/smoke_test.py --port 10530`. It also documents the
  bench quirks (Logic16 rejects plain `digitalThresholdVolts` values — omit
  it, the default range suits 3.3 V logic; `export_raw_data_csv` requires
  `analogDownsampleRatio: 1` even for digital-only exports).
- Bench device: **classic Logic16** (digital-only — see §4.2 consequence),
  ≥10 MS/s on the channel counts used here; 10 MS/s gives ~87 samples per
  bit at 115200 baud, ample.
- `conftest.py` + pytest: each driver gets `test_<driver>.py` whose asserts
  are written against the exported CSVs. One command runs flash + capture +
  assert:
  ```
  pytest software/hil/test_wind_speed.py
  ```
- The Saleae **observes only** — it generates no stimulus. Stimulus per rig is
  defined in each driver section below.
- `software/hil/blinky_check.py` (passing, 2026-07-03): flashes are done via
  `%USERPROFILE%\.platformio\penv\Scripts\pio.exe run -t upload` (`pio` is
  not on PATH); the script captures the blinky and asserts the duty timing
  from the edge CSV. Measured on the DUT: high 100.5 ms, low 904.2 ms,
  period 1004.7 ms — +0.5% vs nominal, consistent with HSI tolerance and
  well inside the FR-S17 ±2% budget. The full flash→capture→assert chain is
  proven.

### 2.4 Rig basics

- Power: 3.3 V from the WCH-LinkE — no PoE/power board at driver stage.
- Common ground between LinkE, breadboard, and Saleae is mandatory.
- Confirm the SOP-8 shared-pin bonding against
  `documentation/CH32V003J4M6-Pinout.jpg` before wiring each rig (several port
  nets share physical pins on this package).
- PD1 stays reserved for the WCH-LinkE (SWIO) on every rig.
- Logic16 lead labels ≠ channel indices: the harness has two 8-channel
  banks, so a bank-2 lead labelled "1" is channel 8+ in software. Current
  bench wiring: DUT PD6 lands on **Saleae channel 8**. When a rig changes,
  run an all-channel sweep capture first to locate the signals before
  assuming channel numbers.

### 2.5 Stimulus source — ADALM2000 (M2K)

The bench has an ADALM2000. It fills the stimulus side of every rig (the
Saleae only observes) and is scriptable, closing the HIL loop with no human
in it: flash (`pio`) → stimulate (libm2k) → observe (Saleae MCP) → assert
(pytest).

- **Pattern generator / AWG** (16 DIO @ 3.3 V logic; 2 AWG channels):
  pulse trains at exact frequencies from the M2K's own crystal timebase —
  independent of the DUT HSI, tens-of-ppm class, three orders of magnitude
  tighter than the FR-S17 ±2% budget it verifies. Burst mode gives exact-N
  pulse counts; duty cycle is programmable (rising-edge-only test).
- **AWG DC levels/ramps** 0–3.3 V for PA2. Caveat: the DUT ADC is
  ratiometric to its VDD while the AWG is absolute — for accuracy rows,
  measure both the DUT VDD and the applied voltage with the M2K's own scope
  channels and compute the expected angle from the measured ratio.
- **Programmable supply** (0..+5 V, ~50 mA) can power the DUT rail for the
  VDD-sweep test (§4.3 ratiometric sanity, 3.0–3.6 V).
- **Automation**: libm2k Python bindings, driven from the same pytest
  scripts as the Saleae. Windows setup (verified 2026-07-03): the libm2k
  wheels top out at **cp311** and are not on PyPI (GitHub release
  `python-wheels.zip`); the wheel alone is insufficient — it needs the
  system DLLs from `libm2k-0.9.0-Windows-setup.exe`, and the M2K's IIO USB
  interface needs `PlutoSDR-M2k-USB-Drivers.exe` (both admin). A dedicated
  Python 3.11 venv (`software/hil/.venv-m2k`) hosts the bindings; see
  `software/hil/README.md`.
- **Cautions**: keep AWG outputs configured 0–3.3 V (hardware can swing
  ±5 V, beyond the CH32V003 absolute maximum of VDD+0.3 V); common ground
  between M2K, Saleae, WCH-LinkE, and DUT.
- **Bring-up: DONE (2026-07-03).** Firmware updated v0.27 → v0.33 (libm2k
  0.9.0 requires ≥0.32). `software/hil/m2k_smoke.py` and
  `software/hil/m2k_signal_check.py` both PASS — 15/15 signals verified:
  pulse trains 1 Hz–1 kHz measured on the Saleae with ≤100 ppm disagreement
  between the two independent crystals (FR-S17's reference is sound),
  asymmetric duty, exact-100 burst, DC levels 0–3.3 V, ramp, and supply
  3.0/3.3/3.6 V. Device quirks and required usage patterns are documented
  in `software/hil/README.md` (notably: fresh libm2k context per analog
  stimulus configuration; steady-state-only frequency measurement).

## 3. Phase 1 — wind speed driver (`wind_speed`)

Pulse counting on PC1 with TIM2 in ETR external-clock mode, per scratchBook
and TDS FR-S04..S08, FR-S17, FR-S27.

### 3.1 Deliverable API (`ws.h`)

```c
void     ws_init(void);                 // TIM2 ETR on PC1, AFIO remap
void     ws_window_start(void);         // clear counter + overflow flag
uint16_t ws_window_read(bool *saturated); // count, UIF-based saturation (FR-S27)
```
Window pacing (SysTick ms counter) lives in the test shell now and in the
application later — the driver only counts.

### 3.2 Rig

| Signal | Pin | Saleae |
|---|---|---|
| Pulse in | PC1 | ch 0 |
| Debug UART | PD6 | ch 1 |
| Stimulus source | see below | ch 0 (same node) |

Stimulus options, in order of preference:
1. **ADALM2000 pattern generator / AWG** (§2.5) at defined frequencies and
   burst counts — clock-independent, scriptable via libm2k; required for
   the calibration-grade FR-S17 checks.
2. **Loopback self-stimulus**: spare GPIO (PC4 or PD4, confirm bonding)
   jumpered to PC1, toggled by the test build. Validates counting logic and
   edge polarity, but shares the DUT clock — timing checks are
   self-referential, so it cannot verify FR-S17. Fallback only.
3. A real reed relay / anemometer for bounce realism (RC debounce per
   scratchBook fitted on the rig).

### 3.3 Test matrix (HIL, Saleae-asserted)

| Test | Method | Pass (TDS ref) |
|---|---|---|
| Count accuracy | f = 1/10/100 Hz bursts, UART reports per window | count = f×W ±1 (FR-S04/S08) |
| Rising edges only | Asymmetric duty (10%/90%) at fixed f | count unchanged vs 50% duty (FR-S04) |
| Window duration | Timestamps of UART window-report lines | ±2% at room temp (FR-S17) — requires stimulus option 1 |
| Saturation | Short window + high f scaled to force overflow, or direct UIF unit hook | reports 65535, not wrapped (FR-S27) |
| Debounce realism | Reed relay stimulus through RC filter | no double counts across 1000 closures |

**Exit criteria: MET (2026-07-03), 9/9 HIL rows PASS** except the
hardware-dependent bounce-realism row (deferred until a physical reed relay
is on the rig). `software/hil/ws_check.py` results: counts exact at
1/10/100/1000 Hz when scaled to the measured window (the nominal-window
comparison at 1 kHz reads 1003 — the HSI-paced window is +0.3% long and the
count is correct for it, exactly FR-S06's semantics); 10%/90% duty give
identical counts (rising-only, FR-S04); worst window deviation 3.35 ms of
1000 ms = 0.34% vs FR-S17's ±2%, measured against the M2K/Saleae
independent timebases; 100 kHz × 1 s reports 65535+S, never a wrap
(FR-S27). The TIM2 partial-remap-2 question is settled: AFIO_PCFR1[9:8]=10
puts ETR on PC1, coexists with the USART1 remap — see
`software/drivers/wind_speed/README.md`. Two portable findings: (1)
ch32v003fun's SysTick default is HCLK/8 — set `FUNCONF_SYSTICK_USE_HCLK 1`
or tick math runs 8× slow; (2) HDSEL releases the TX line between frames,
so a bursty debug UART on a lightly-loaded pin idles low and garbles every
frame — `common/debug_uart` now runs plain TX (no HDSEL); the Modbus driver
keeps HDSEL and relies on the RS-485 transceiver/bias for the idle level.

## 4. Phase 2 — wind direction driver (`wind_direction`)

ADC on PA2, ratiometric to VDD, oversampled, per TDS FR-S09..S12, FR-S28,
FR-S29, FR-S38.

### 4.1 Deliverable API (`wd.h`)

```c
void     wd_init(void);            // ADC on PA2 (A0), sample time ≥ 71 cycles
uint16_t wd_read_raw16(void);      // mean of 16 conversions (FR-S28)
uint16_t wd_angle_0_1deg(uint16_t raw, uint16_t offset_0_1deg); // 0..3599 (FR-S29)
bool     wd_wiper_floating(void);  // pull-toggle detection (FR-S38)
```
Plus `common/circmean`: fixed-point sin/cos table + atan2 for the circular
mean — **pure functions, developed with host-side unit tests first** (plain
`gcc` + asserts on the PC; no hardware needed to get the wrap-around math
right, including the 350°/10° → 0° case of FR-S14).

### 4.2 Rig

| Signal | Pin | Saleae |
|---|---|---|
| Pot wiper / divider | PA2 | ch 0 **analog** |
| Debug UART | PD6 | ch 1 digital |

Stimulus, in order of preference:
1. **ADALM2000 AWG** (§2.5) driving PA2 with DC levels/slow ramps, expected
   angle computed from the M2K-measured VDD:applied-voltage ratio
   (ratiometric caveat in §2.5); scriptable via libm2k.
2. 10-turn trim pot between 3.3 V and GND / fixed resistor dividers at known
   ratios (DMM-measured, ≤0.1% ratio accuracy per FR-S11's method) — manual
   fallback, and the reference method if M2K measurement accuracy is ever in
   doubt.

The bench Saleae is a classic Logic16 (digital-only, confirmed), so analog
observation happens on the M2K's scope channels; the Saleae observes only
the PD6 debug UART on this rig.

### 4.3 Test matrix

| Test | Method | Pass (TDS ref) |
|---|---|---|
| End stops | Wiper at each end | raw ≤5 / ≥1018 (FR-S09) |
| Stability | Fixed mid position, 32 reads over UART | span ≤3 counts (FR-S10/S28) |
| Accuracy | 5 known divider ratios | ±10 LSB of expected angle (FR-S11) |
| Offset & wrap | Sweep offset values in test build | shift + correct wrap, never 3600 (FR-S12/S29) |
| Float detection | Lift wiper wire mid-capture | fault flagged; recovery on reconnect (FR-S38 timing checked in integration) |
| Ratiometric sanity | Vary VDD 3.0–3.6 V (M2K programmable supply, §2.5) with fixed ratio divider | reported angle unchanged ±2 LSB |

**Exit criteria: MET (2026-07-03).** Accuracy −3.8 LSB against a
DMM-measured resistor divider (ratio 0.49899) vs the ±10 LSB budget;
stability 0.6 LSB over 11 s; end stops exact (code 0.0 / 1023.0 at the
rails); never-3600 proven at the VDD rail (angle 3596); float detector
flt=1 on a truly open pin, flt=0 for pot-like (5 kΩ) and AWG (50 Ω)
sources; circmean host tests exhaustive (identity 0 LSB over all 3600
angles, CORDIC ≤0.0035°) plus on-target boot self-test CM,PASS. ADC
self-calibration confirmed in `wd_init()`; ADC clock set to HCLK/8.
Deferred to acceptance: 5-ratio sweep, M2K-powered VDD sweep, FR-S12
offset-register wrap (logic host-proven). **Method lesson (recorded in
§2.5 and `software/hil/README.md`): AWG-based absolute-voltage accuracy
testing is unusable here — the M2K AWG has a +25 mV output offset and the
M2K scope reads ~1%/−30 mV low (both DMM-anchored); the divider method is
the method of record, and it also exercises the real ratiometric
topology.** See `software/drivers/wind_direction/README.md`.

## 5. Phase 3 — Modbus RTU driver (`modbus_rtu`)

Slave stack on USART1 half-duplex (PD6) with DE/RE on PC2, per TDS §2
(FR-MB01..FR-MB30 as applicable to the driver layer).

### 5.1 Deliverable API (`mb.h`)

```c
void mb_init(uint8_t address);            // UART 9600 8N1, DE low first (FR-S19)
void mb_poll(uint32_t ms_now);            // gap detect (FR-MB03), parse, respond
// Register access is delegated through a table the application owns:
typedef struct { uint16_t addr, min, max; uint16_t *value; } mb_holding_t;
uint16_t (*mb_input_read)(uint16_t addr, bool *ok);
```
Framing, CRC-16, FC03/04/06/16 dispatch, quantity validation (FR-MB28),
exception generation (FR-MB12/13/15/19), FC06 echo / FC16 response format
(FR-MB30), self-reception discard while transmitting (FR-MB23) all live in
the driver. Address selection, register semantics, and averaging stay
application-side.

### 5.2 Rig

| Signal | Pin | Saleae |
|---|---|---|
| Modbus data | PD6 | ch 0 (async serial analyzer, 9600) |
| DE/RE | PC2 | ch 1 |
| Marker GPIO (optional) | spare pin | ch 2 |

- Master-side stimulus: **USB–serial adapter cross-wired to PD6** (TTL level,
  no MAX3485 needed for logic tests) driven by a Python script
  (`pymodbus`/raw-frame injection for the malformed cases), or the sibling
  `windmeters-modbus-interface-tester` for the well-formed cases.
- A second rig variant with two MAX3485s adds RS-485 electrical realism for
  the DE-timing and idle-bias measurements.
- Optional: the M2K pattern generator (§2.5) can inject the FR-MB24
  garbage floods with byte-exact timing and off-nominal baud rates for
  tolerance probing — cases a USB–serial adapter cannot time precisely.
- PD6 is occupied by the bus, so debug tracing = the bus traffic itself plus
  an optional marker GPIO pulsed at interesting internal events (frame
  accepted, exception path taken); no debugprintf (it would wreck FR-MB20/21
  timing measurements).

### 5.3 Test matrix — this is TDS §2 executed early

| Test group | TDS refs | Saleae's role |
|---|---|---|
| Framing, CRC discard, gap handling, split frames | FR-MB01/02/03 | timestamps prove silence + recovery |
| DE assert/de-assert timing | FR-MB04 | measure DE vs start/stop bit edges — the bench-instrument row NFR-TST01 excepts becomes scriptable here |
| Address filter, broadcast ignore | FR-MB05/06 | no-response proof |
| FC dispatch, exceptions 01/02/03, quantity checks | FR-MB08–15, 28 | decode replies, assert exception bytes |
| Echo/response formats, byte order | FR-MB25/30 | byte-exact frame comparison |
| Self-reception (response storm) | FR-MB23 | one request → exactly one response, bus idle after |
| Garbage flood, oversize frames, receiver recovery | FR-MB24 | inject noise then a valid request |
| Response latency | FR-MB20/21 | 1000-request timing histogram from capture |
| Out-of-range / atomic FC16 writes | FR-MB19/22 | write + read-back sequences |

**Exit criteria: core MET on the TTL rig (2026-07-03)** — 26/26 matrix
vectors (FR-MB02/05/06/08–15/19/22/25/28/30 + FR-S31 hook) plus 40/40
endurance, latency median/worst 5.2 ms (FR-MB21 ≤15 ms typical). Two
findings forced design changes, both recorded in
`software/drivers/modbus_rtu/README.md` and `design/softwareArchitecture.md`:
HDSEL intermittently swallows the first byte after idle → replaced by
remap-switching line discipline (RX natively on PD6, TX remapped only
during response); the RXNE ISR corrupted ~1/3 of frames → polled RX,
zero-interrupt architecture. Master-side bench lessons live in
`software/hil/README.md` (M2K open-drain mode, phantom start bits, Saleae
analyzer unreliable at 9600 → raw-edge software UART decode).
**Deferred to the MAX3485 rig / acceptance:** FR-MB04 DE-timing asserts,
FR-MB24 garbage-flood/oversize vectors, FR-MB03 split-frame vectors,
RS-485 electrical rows.

## 6. Phase 4 — integration (preview only)

Combine `common/` + the three driver libraries under the application
super-loop architecture defined in `design/softwareArchitecture.md`
(ISR-minimal capture, main-loop services, structural snapshot coherence),
apply the FR-S18 init order, add the register image / averaging / status
logic (FR-S13/14/23/30/31/33), watchdog (FR-S20), and run the full TDS test
set. Detailed plan to be written when phase 3 exits.

## 7. Risks and open items

- **TIM2 ETR remap on PC1** — documented as needing AFIO remap (scratchBook);
  if the remap proves wrong on real silicon, fallback is TIM2 input-capture
  counting or PC4 as the pulse pin (PCB not yet finalised). Phase 1 resolves
  this in its first days.
- **HDSEL echo behaviour** — phase 0 runs TX-only so the echo question
  (FR-MB23) is first *observed* in phase 3; the Saleae storm test is designed
  to catch it immediately.
- ~~**Saleae analog capability**~~ — resolved 2026-07-03: bench unit is a
  classic Logic16, digital-only; divider-step method (§4.2) is the plan of
  record for the direction driver.
- ~~**Stimulus source for FR-S17**~~ — resolved 2026-07-03: the bench
  ADALM2000 (§2.5) provides clock-independent, libm2k-scriptable pulses.
  Remaining sub-item: libm2k Windows driver/bindings install unverified —
  run the §2.5 bring-up smoke script when the M2K is first connected.
- **PA1/PD4 availability** — template README lists them as usable; verify
  against the pinout scan before relying on them for marker/stimulus pins.
