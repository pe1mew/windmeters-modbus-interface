# Phase-4 Integration Plan — Product Firmware

| Field | Value |
|---|---|
| Document | Phase-4 (integration) plan |
| Project | `windmeters-modbus-interface` firmware |
| Date | 2026-07-03 |
| Status | Ready to execute — phases 0–3 exited |
| Related docs | `design/TDS.md` v0.6 (the contract), `design/softwareArchitecture.md` (zero-ISR super-loop), `design/driverDevelopment.md` (driver results §3–§5), `software/hil/README.md` (harness + bench lessons) |

## 1. Purpose

Merge the three verified driver libraries into the single product firmware
(two builds), implement everything in TDS §3 that sits *between* the
drivers and the Modbus register map, and grow the HIL harness into the
NFR-TST01 acceptance/regression suite.

## 2. Inputs — what is already proven

| Component | Source | Verified |
|---|---|---|
| Pulse counting (`ws_*`) | `drivers/wind_speed/lib/ws` | 9/9 HIL: counts, rising-only, FR-S17 0.34%, FR-S27 saturation |
| ADC + angle (`wd_*`) | `drivers/wind_direction/lib/wd` | accuracy −3.8 LSB (divider), stability 0.6 LSB, end stops exact, FR-S38 float detect |
| Circular mean | `drivers/common/circmean` | exhaustive host tests + on-target self-test (FR-S14 exact) |
| Modbus RTU slave (`mb_*`) | `drivers/modbus_rtu/lib/mb` | 26/26 TDS §2 matrix + 40/40 endurance, 5.2 ms latency |
| Architecture | `softwareArchitecture.md` | zero-ISR super-loop (bench-forced; no concurrency surface) |
| Line discipline | remap switching, no HDSEL | bench-forced; PCB confirmed compatible (DE pull-down added) |

## 3. Project decisions

- **Location**: the existing `software/firmware/` scaffolding is adopted —
  its two-environment structure (`wind_speed` / `wind_direction` envs with
  `SENSOR_WIND_SPEED` / `SENSOR_WIND_DIRECTION` defines) stays, but its
  **framework migrates from `noneos-sdk` to `ch32v003fun`**: all drivers
  are built and verified on ch32v003fun; porting them would un-verify
  them. The stale HDSEL comment in its `main.c` header dies with the
  rewrite.
- **TDS editorial note**: FR-S01's criterion names the defines
  `SENSOR_WINDSPEED`/`SENSOR_WINDDIRECTION`; the scaffolding's
  `SENSOR_WIND_SPEED`/`SENSOR_WIND_DIRECTION` are kept — amend FR-S01's
  wording when the TDS is next touched.
- **Reuse in place, no copies**: `lib_extra_dirs` points at
  `../drivers/common`, `../drivers/wind_speed/lib`,
  `../drivers/wind_direction/lib`, `../drivers/modbus_rtu/lib` — a driver
  fix stays fixed in one place, and the driver test shells keep working.
- **`debug_uart` is excluded from release builds** (PD6 is the bus;
  FR-S19). Acceptance is black-box over Modbus — which is exactly what the
  register map's status/ID/diagnostic registers are for.
- **funconfig**: `FUNCONF_USE_DEBUGPRINTF 0`, `FUNCONF_SYSTICK_USE_HCLK 1`
  (both bench-mandated).

## 4. Work stages

Each stage ends green before the next starts; flash/RAM from the linker
map is recorded per stage (NFR-RES01 ceilings: 14,336 B flash / 1,792 B
RAM incl. stack).

**A — Skeleton & build matrix. DONE 2026-07-03.** ch32v003fun migration of
`software/firmware/`, both envs compiling against the in-place driver
libraries, NFR-RES01 ceilings enforced via `board_upload.maximum_size`.
Sizes: wind_speed 2368 B / 552 B RAM, wind_direction 4908 B / 572 B RAM
(ceilings 14336/1792). On-target smoke: speed build 3/3 (identification
0x0101 from version.h, §2.8 defaults, FR-S31 enforced) + full FR-S32
version-chain PASS; direction build identifies as 0x0201 with live driver
data (PA2 read floating — the divider was still disconnected from the
phase-2 float test; reconnect before stage-D direction rows). Bench lesson
recorded: LTO discards any driver math whose result is not externally
observable — linkage checks must read results via registers.

**B — Board bring-up (`board.c`). DONE 2026-07-03.** FR-S18 init order
implemented (PC2 low first → PC4 latch → sensor front-end → USART last);
IWDG at ~1.02 s refreshed only at loop end and only while PVD reports the
rail healthy (a brown-out withholds the feed, turning the watchdog into
the FR-S22 recovery path). On-target results: watchdog/defaults run 6/6 —
TEST_HOOKS hang trigger acknowledged, recovery < 2.5 s (FR-S20 ≤3 s),
all §2.8 defaults restored after the watchdog reset (FR-S21); FR-S03
address matrix 4/4 on the real jumper (speed 30/35, direction 31/36,
vacated addresses silent) plus FR-MB07 latch semantics (mid-run jumper
change inert until reset). Silicon findings: LSI must be started
explicitly before IWDG configuration (waiting on PVU/RVU without it hangs
boot); the SPL DBGMCU address (0xE000D000) hard-faults this core, so
there is NO debug-freeze for the IWDG — reflashing under a live watchdog
was bench-verified to work regardless. Sizes after stage B:
speed 2576 B / 580 B RAM, direction 5144 B / 596 B RAM.

**C — Register image (`regs.c`). DONE 2026-07-03.** Full TDS §2.7/§2.8
map live on both builds — `software/hil/regs_check.py`: **speed 22/22,
direction 24/24**. Proven on target: 12-register sweep with per-build
zeros (FR-MB27), exact map edge (FR-MB13), identification from version.h
(FR-S32), live uptime/served/CRC counters (FR-S34/S35 — served
increments exactly +1 per request), pulse-age counting (FR-S36), status
bits with stage-C semantics (bit 0 clears after the first window, bit 1
held set until the stage-E engine exists), and the full protocol vector
set re-passed against the real holding map (no-clamp, atomic FC16,
FR-S31 pair, exceptions, silence). Bonus: the direction build's floating
PA2 exercised FR-S38 end-to-end — bit 2 set, 65535 sentinels on
30001/30003. Direction-build flash dropped to 3156 B: with averaging not
yet wired, LTO again discards the sine table; it returns in stage E.
Sizes: speed 2728 B, direction 3156 B, speed_test 2756 B.

**D — Measurement services. DONE 2026-07-03.** `meas_speed.c` /
`meas_dir.c` + regs publish API. `software/hil/meas_check.py`: **speed
9/9, direction 4/4** — all values read over Modbus (no debug UART).
Speed: counts exact at 10/100 Hz, `30002 == formula(30005)` verified
atomically in single responses (FR-S06 + FR-S24's consistency rule),
FR-S07 cut-off branch (count kept, speed zeroed), FR-S30 window-change
take-effect (40002=3000 → count 30, formula tracks), FR-S27 saturation at
100 kHz (both registers 65535). Direction: divider angle exact vs raw
(inst 1779 = expected), FR-S12 offset 900 and wrap-at-2000 exact, fault
bit clear with the divider connected. C define carries the FR-S25/S26
static assert (1..6553). Harness note: pulse stimulus moved from M2K
DIO1 to **W2 (AWG)** — the digital subsystem's single pattern buffer
cannot stream pulses while the DIO0 master transmits; the AWG runs
independently, so wind + Modbus traffic coexist like the real deployment.
Gust (30012) intentionally deferred to stage E (its window semantics are
the averaging window's). Sizes: speed 3092 B, direction 3180 B.

**E — Averaging engine. DONE 2026-07-03.** `avg.c` (ring/block engine) +
regs/meas glue; direction windows publish per-window circular results so
both builds share the boxcar structure. `software/hil/avg_check.py`:
**speed 11/11, direction 4/4** — steady convergence (30004==30002,
30003==30001), status bit 1 lifecycle, FR-S30 retain-on-clear + bit
re-assert, the FR-S23 anti-zero-padding trap (partial mean reads 98 where
zero-padding would read ~25), gust capture at a 100 Hz burst and decay
after the window slides (FR-S37), step settling within one averaging
window (FR-S13), and the two-stage boxcar at N=6000/blocks-of-94 with the
device fully responsive (FR-S31). One real bug found by the bench: the
slot ring initially iterated all 64 slots instead of ceil(N/block) — the
boxcar silently averaged 64 windows (stale zeros diluting the mean, gust
never decaying); fixed by sizing the ring to the averaging span. Sine
table back in the direction build as predicted. Sizes: speed 3568 B /
880 B RAM, direction 6056 B / 892 B RAM.

*(Pulled forward from stages C/F, done 2026-07-03: the FR-S32 version
chain — `src/version.h` as the single source of the version byte,
`RELEASES.md` as the release registry FR-S32's criterion refers to, and
`software/hil/version_check.py` verifying define ↔ registry ↔ flashed DUT.
Bump-at-release process documented in RELEASES.md.)*

**F — Acceptance suite (`software/hil/acceptance/`). CORE DONE
2026-07-03.** Pytest orchestrator over the proven check scripts (each
still runnable standalone): version chain, register image + §2 protocol
vectors, measurement services, averaging engine, and NFR-RES01 build
gates; NFR-BLD01 double-clean-build hash compare available as the opt-in
`-m reproducible` marker. **Both builds green: speed 6/6 (3:11),
direction 6/6 (1:20)** — one command per flashed build:
`pytest . --build speed|direction`. Remaining backlog for the full
NFR-TST01 set (tracked, not blocking): FR-S21 reset-matrix as a pytest
(TEST_HOOKS build), FR-MB20/21 latency histogram, the 5-ratio divider
sweep and M2K-V+ VDD sweep (bench work), on-target FR-S14 alternating
stimulus via W1, and the §9 hardware-gated rows.

## 5. Integration HIL rig (TTL, per build)

**Instrumentation principle: the M2K + Saleae bench stays the test
platform for as long as possible.** Every acceptance row that does not
physically require the MAX3485 or the final PCB runs on this TTL rig with
the scripted instruments — fast iteration, fully automated, and every
capture archived. Only the rows in §9 wait for real hardware.

Shared: PD6 node = M2K DIO0 (open-drain master) + pull-up + Saleae ch8;
PC2 → Saleae ch15; PC4 → jumper wire to GND (manual, for the address
rows); grounds common.

| Build | Stimulus |
|---|---|
| wind_speed | M2K **W2 (AWG)** → PC1 — pulse trains run independently of the DIO0 bus master (the digital engine's single pattern buffer cannot stream pulses while transmitting frames; established in stage D) |
| wind_direction | divider on PA2 for accuracy rows; M2K W1 for functional rows; **V+ powers the DUT rail** for the VDD sweep (LinkE 3V3 lead lifted for that row) |

## 6. Budgets

Flash estimate: mb 2.3 K + wd/circmean 3.8 K + ws 0.5 K + regs/averaging/
board ≈ 3–4 K → ≈ 10–11 K of the 14.3 K ceiling — monitored per stage.
RAM: mb buffers 512 B + averaging blocks ≤ 512 B (64 × up to 8 B for
speed/gust/sin/cos) + image/state ≈ 1.2 K of 1.792 K — the two-stage
boxcar block layout is sized in stage E before coding.

**Designated flash reserve (~1.6 KB, direction build):** the circmean
sine table (901-entry quarter-wave Q15, 1802 B — 37% of the current
direction build) is exact and verified but replaceable: CORDIC *rotation*
mode computes sin/cos reusing the 64 B atan table the vectoring-mode
atan2 already carries, at ~±2 Q15 LSB (noise against FR-S14's ±1.0°
tolerance). If stages C–E run over projection, this is the known
recovery: mirror the change in `gen_table.py`'s reference, re-run the
exhaustive host sweep and the on-target boot self-test. Decision
2026-07-03: keep the table while headroom lasts.

## 7. Risks & watch items

- **No ISRs, ever** (architecture amendment): the IWDG and all pacing are
  poll/hardware-based — any temptation to add an interrupt goes through
  root-causing the phase-3 ISR corruption first.
- **Pin 8 sharing (PD1/PD5)**: during the TX phase the USART's RX function
  parks on PD5, which shares the SWIO pin. PD5's GPIO stays unconfigured
  (input) so nothing drives it, but flashing-while-communicating should be
  smoke-tested in stage B.
- **Watchdog test hook**: FR-S20's criterion needs a controlled hang —
  implemented only in a `TEST_HOOKS` build (a magic write to an otherwise
  unmapped holding register), absent from release binaries so FR-MB15
  stays honest.
- **Register-map drift**: `regs.c` is generated-by-hand from TDS
  §2.7/§2.8 — the acceptance sweep (stage C exit) is the drift detector.

## 8. Out of scope for the TTL stages

The rows below wait for hardware; everything else runs on the M2K +
Saleae TTL rig per §5's principle.

## 9. Hardware-gated test set

### 9.1 With the MAX3485 (breadboard rig — before the PCB)

The M2K + Saleae remain the instruments; only the transceiver is added
(DI+RO to PD6, DE+R̄Ē to PC2 with the 10 k pull-down). Realized rig
(first session 2026-07-06): the `windmeters-modbus-interface-tester` on
A/B as live master (its M5Stack RS-485 unit is an auto-direction module:
it drives spaces only and lets bias supply marks — the MAX3485's
negative receiver threshold reads that fine), M2K scope on A/B for the
analog wire view, Saleae ch8/ch15 unchanged. Judge script:
`software/hil/rs485_check.py` (passive — decodes live traffic, asserts
the rows below). For the byte-exact vectors a **second MAX3485 raw
master** joined the rig later the same day (M2K DIO0 → DI, DIO1 →
DE+R̄Ē, V+ → VCC): `software/hil/rs485_raw_check.py` — bit-banged
two-channel patterns with exact timing (rig lessons in
`software/hil/README.md`).

**The first session immediately caught a ship-blocker** — the TX phase
was still open-drain from the TTL-rig days and transmitted a 30 ms break
instead of every response (the rig pull-up had masked it; the PCB has no
pull-up on `MB-TX/RX` either). Fixed to push-pull AF in `mb.c`; full
story in driverDevelopment.md §5.3 (third bench-forced finding). This is
exactly the class of defect this section exists to catch before the PCB.

| Test | TDS ref | Status |
|---|---|---|
| DE assert before first start bit; de-assert within one character time — scope-asserted from Saleae ch15 vs ch8 timestamps | FR-MB04 | **DONE 2026-07-06**: lead 1–100 µs before the first start bit over 117 responses; release lands on the TC flag (−1..+1 µs of the last stop-bit edge at nominal baud, limit 1146 µs); never asserted outside a response window |
| Split-frame vectors: 4 bytes + ≥5 ms pause + remainder → silence, next frame recovers | FR-MB03 | **DONE 2026-07-06**: 10/10 — both halves silently discarded (DUT CRC counter +2 per rep, exactly), recovery request answered every time |
| Garbage floods: 60 s random bytes then a valid request; 400-byte oversize burst + gap + valid request; 10/20 repetitions | FR-MB24 | **DONE 2026-07-06**: 10× 2 s random flood, 1× 60 s soak, 10× 400-byte oversize — recovery request answered 21/21; noise takes the silent FE/overflow discard path (CRC counter untouched, by design) |
| Response-storm check on real transceiver: one request → exactly one response, bus idle ≥500 ms after, ×100 | FR-MB23 | **DONE 2026-07-06**: 117/117 over 400 s — one response per request, zero spontaneous DUT frames, DE windows == responses, bus idle between polls (tester cadence ~3.4 s) |
| Reset-window bus safety: flash the DUT while a third-party pair exchanges frames — DE never asserts (10 k pull-down does its job), no disturbed frames | FR-S19 | **CORE DONE 2026-07-06** (tester as the live traffic): reflash mid-capture, 6.5 s dead window — all 28 master frames CRC-clean throughout, zero DE assertions outside valid responses, DUT recovered and served; the literal third-party-pair variant waits for a second unit (§9.2) |
| Idle-bias sanity: RO idles mark with the R2/R3 bias; DUT gap detection against real RO edges | FR-MB03 | **DONE 2026-07-06**: RO mark in every inter-frame gap; note — rig bias is only the tester module's weak network (≈ +0.05 V differential), readable thanks to the MAX3485's negative threshold; the PCB's R2/R3 (+baseline +200 mV) is the real fail-safe |
| Off-nominal baud probing (±1–3% master) via M2K byte-exact timing | FR-MB01 margin | **DONE 2026-07-06**: answered at every probed offset out to ±3% (actuals +0.94/−1.07/+1.93/−2.01/+2.93/−3.01% from the rate-ladder read-back); DUT HSI contributes ~+0.3% |
| Latency histogram re-run through the transceiver (1000 requests) | FR-MB20/21 | **DONE 2026-07-06**: 1000/1000 transactions, zero CRC errors — min/med/p99/max = 4.06/4.11/4.16/4.17 ms (t3.5 = 4.01 ms, budget 100 ms); the whole distribution spans 110 µs |

Wire-integrity results (both directions through the transceiver,
2026-07-06): every master and DUT frame CRC-valid at PD6 (RO path,
1295 bytes zero framing errors), and DUT responses decoded CRC-clean
directly from the A/B differential on the M2K scope — identification
register read 0x0101 (wind_speed, fw v1) on the wire.

**Register matrix over RS-485 (2026-07-06, speed build): 62/62.** The
tester turns out to ship a machine API (`POST /api/v1/modbus`, tester
repo `manual/api.md`) that returns each transaction's raw TX/RX frames —
a scripted bus-side master with independent CRC verification, no second
transceiver needed for well-formed traffic.
`software/hil/rs485_regs_check.py` runs the full TDS §2.7/§2.8 exercise
through it: FC04 image + all singles + map-edge/straddle exceptions,
FC03 defaults + singles + edge, FC06 range min/max/mid with byte-exact
echo (FR-MB30), out-of-range rejects with no state change (FR-MB19),
unmapped writes (FR-MB15) including the TEST_HOOKS address absent from
the release build, FC16 commit + three-way atomicity (bad value, FR-S31
cross-rule, partially-unmapped range — nothing committed each time),
FR-S30 status-bit dance timed on the wire (bit 0 cleared +0.4 s, bit 1
+9.1 s after an averaging reset), FR-MB05 silence at addresses 31/35,
and end-to-end consistency: DUT served-counter delta exactly equal to
answered transactions (69/69), DUT and master CRC-error counters both
zero across the whole matrix. The 40004 write that coincided with the
open-drain discovery is formally cleared: every accepted cutoff write
was followed by a full image read — the DUT never stopped serving.
This substantially pre-runs §9.2's "full acceptance suite over RS-485"
row for the speed build; the byte-exact malformed vectors followed the
same day via the raw master (see the table above) — **§9.1 is complete
for the speed build**.

**Direction build over RS-485 (2026-07-06, address 31): register matrix
72/72.** `rs485_regs_check.py --build direction` runs the same §2.7/§2.8
exercise (the holding matrix is identical on both builds per FR-MB27;
the input-register active/zero map is build-aware: identification
0x0201, speed regs 30002/30004 and pulse-age/gust 30011/30012 read 0,
raw ADC 516/1023 in range, no DIR_FAULT with PA2 driven) plus a
**direction-only functional block**: writing the 40001 north offset and
reading 30001 back — the angle tracks the offset with exact 3600
wraparound (90°/180°/360° all 0 LSB error, base 181.4°). FR-S30 status
dance identical (bit 0 +0.4 s, bit 1 +9.8 s); served delta 79/79; CRC
counters zero. Raw byte-exact vectors via the second MAX3485 also green
on this build: split 10/10 (DUT CRC counter +20), garbage floods 3/3
(10× 2 s flood, 60 s soak, 10× 400-byte oversize), baud margin to ±3%,
and the 1000-request latency histogram 1000/1000 at 4.07/4.12/4.17/
4.44 ms. PA2 was driven from the divider (method of record) throughout;
the FR-S38 float-fault path is the one direction row still requiring a
physical PA2 disconnect (noted for the next bench pass). §9.1 is now
complete for both builds bar that single float-fault row.

### 9.2 With the real PCB (product hardware)

| Test | TDS ref |
|---|---|
| Power path: 24 V passive PoE → DB207 bridge → HLK-K7803 → 3V3; ripple at PA2/VDD; reversed-polarity survival | scratchBook power §, FR-S09 noise |
| Full acceptance suite (§4 stage F) re-run on the PCB, both builds, over RS-485 with the `windmeters-modbus-interface-tester` as master | NFR-TST01 |
| PC4 solder-jumper address selection on the real jumper | FR-S03 |
| Brown-out / dip matrix on the 24 V input and the 3V3 rail | FR-S22 |
| Reset matrix (power / watchdog / software) on the PCB | FR-S21 |
| Two-unit daisy chain: RJ45 pass-through, terminator solder-jumper on/off, both units polled | bus topology |
| Real anemometer through the PCB RC debounce: bounce realism across ≥1000 closures | FR-S04 |
| Empirical calibration: C from reference-anemometer comparison; pot end-to-end accuracy (±2° target) | scratchBook calibration, TDS §5 |
| Window timing on the PCB (supply/thermal conditions differ from the LinkE rig) | FR-S17 |
| NFR-ENV01 chamber runs when available: 10 k frames + window timing at range extremes | NFR-ENV01, FR-S17 |

## 10. Next-step candidate: combined-sensor firmware variant

Assessed 2026-07-03 (after stage E): **one build serving both sensors is
comfortably feasible** — the design has been converging on it without
saying so.

**Resources (all green):**
- *Pins*: PA2 (ADC) and PC1 (TIM2 ETR) are separate pins, both already in
  the product pin map — the PCB carries both sensor connectors. No
  conflict exists.
- *Flash*: combined ≈ 7 KB (direction build 6056 B + ~1 KB of
  speed-specific code) against the 14 336 B ceiling.
- *RAM*: ≈ 1.2 KB (shared mb/regs + both 256 B averaging rings) against
  1 792 B.
- *Timing*: a non-issue by construction — TIM2 counts pulses in hardware
  while the CPU runs the 224 µs ADC burst every 100 ms (0.2 % CPU);
  worst loop pass ~300 µs vs 1 042 µs per Modbus byte; latency stays
  ~5 ms.

**The two real conflicts are spec, not silicon:**
1. **Register 30005** is per-build by design (pulse count *or* raw ADC) —
   a combined build needs both: move the direction raw view to a new
   register (30013; the map has room) or drop one diagnostic.
2. **Device identity**: build type needs 0x03 (FR-S32) and FR-S03 needs
   an address pair for the combined variant (e.g. open = 32,
   bridged = 37) — one slave now serves both quantities.

**Code changes (modest, mechanical, ~1 day + suite re-runs):**
`meas_speed.c`/`meas_dir.c` define the same `meas_init`/`meas_service`
symbols → rename per sensor and call both; `avg.c`'s ring state is shared
globals under ifdefs → restructure into two instances; `regs.c`'s
per-build zeros become all-live. Status bits stay coherent (both
quantities share the 40002 window boundaries).

**Strategic question:** once a combined build exists, it could become the
ONLY build — the fault machinery already handles absent sensors
gracefully (disconnected vane → 65535 + status bit 2; missing anemometer
→ zero counts + climbing pulse-age), collapsing the SKU and test matrix
to one. Cost: TDS rework (FR-S01/S02/S03/S32/FR-MB27 all assume two
variants) and less self-documenting addressing.

**Recommendation:** introduce it as a *third* variant first
(`wind_combined`, build type 0x03, direction-raw at 30013); retire the
single-sensor variants only after the combined one has passed the full
acceptance suite. **Decision deferred — TDS impact tracked in TDS §5.**
