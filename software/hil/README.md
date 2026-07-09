# HIL test harness

Scripted hardware-in-the-loop testing per `design/driverDevelopment.md` §2.3/§2.5:
flash (`pio`) → stimulate (ADALM2000 / libm2k) → observe (Saleae Logic 2 MCP)
→ assert (Python).

> **Consolidated results:** [`testReport.md`](testReport.md) is the single
> record of every HIL test with its setup, expected result, pass criteria,
> and verdict. This README covers *how* to run the harness (instruments,
> wiring, quirks); the test report covers *what was tested and the outcome*.
> Regenerate the report when the check scripts or the design docs change.

## Instruments

| Instrument | Interface | Role |
|---|---|---|
| Saleae Logic16 (classic, digital-only) | Logic 2 built-in MCP server, `http://127.0.0.1:10530/mcp` (JSON-RPC/HTTP) | Observer: digital captures, protocol analyzers, CSV export |
| ADALM2000 (M2K) | libm2k (Python 3.11 venv) | Stimulus: pulse trains, bursts, DC levels/ramps, programmable supply; its scope verifies analog |
| WCH-LinkE | `pio run -t upload` (`%USERPROFILE%\.platformio\penv\Scripts\pio.exe`) | Flash + 3.3 V DUT power + UART monitor RX |

## Python environments

- Saleae scripts are **stdlib-only** — any Python ≥3.10 works (system 3.13 fine).
- libm2k wheels top out at **cp311**, and the wheel alone is not enough —
  it needs the system-installed libm2k/libiio DLLs. Setup (one-time):
  1. Run `PlutoSDR-M2k-USB-Drivers.exe` (admin) — IIO/RNDIS USB drivers.
  2. Run `libm2k-0.9.0-Windows-setup.exe` (admin) — runtime DLLs.
  3. `python3.11 -m venv .venv-m2k` and
     `.venv-m2k\Scripts\pip install libm2k-0.9.0-cp311-cp311-win_amd64.whl`
     (wheel from the libm2k GitHub release `python-wheels.zip`).

## Scripts

| Script | Purpose | Status |
|---|---|---|
| `smoke_test.py` | Saleae MCP link: devices, capture, export | PASS 2026-07-03 |
| `blinky_check.py` | Flash→capture→assert chain on the DUT (blinky timing) | PASS 2026-07-03 (ch8) |
| `uart_check.py` | debug_uart §2.2 exit criterion (async-serial decode) | PASS 2026-07-03 |
| `m2k_smoke.py` | M2K reachable, calibrated, subsystems up | PASS 2026-07-03 (fw v0.33) |
| `m2k_signal_check.py` | Generate + verify every driver-phase stimulus signal | PASS 2026-07-03, 15/15 |
| `saleae_serial.py` | Shared module: UART capture + timestamped line decode | library |
| `ws_check.py` | Wind speed driver phase-1 matrix (counts, duty, timing, saturation) | PASS 2026-07-03, 9/9 |
| `wd_check.py` | Wind direction phase-2 matrix (AWG-based; superseded for accuracy rows by the divider method — see README notes) | superseded 2026-07-03 |
| `mb_check.py` | Modbus RTU phase-3 matrix (26 vectors, TDS §2) + timing; M2K as open-drain bit-banged master | PASS 2026-07-03, 26/26 + 40/40 endurance |
| `rs485_check.py` | MAX3485-rig passive judge of live master traffic: DE timing, storm, idle-bias, latency, wire CRC both directions | PASS 2026-07-06, 8/8 (117 transactions) |
| `rs485_regs_check.py` | Full TDS §2.7/§2.8 register read/write matrix over RS-485 via the tester's machine API; `--build speed\|direction\|combined` | PASS: speed 62/62, direction 72/72 (2026-07-06), **combined 77/77** (2026-07-08, `--speed-live`) |
| `rs485_raw_check.py` | Byte-exact §9.1 vectors via second-MAX3485 raw master: split frames, garbage floods, off-baud, 1000-request latency histogram | PASS 2026-07-06, all groups (both builds) |
| `m2k_pulse.py` | M2K W2 (AWG) → PC1 speed pulse train; holds the context open (+V+ keepalive) so another process runs the matrix concurrently | used for combined `--speed-live` |
| `rs485_float_check.py` | FR-S38 wind-direction float-fault + recovery over RS-485 (`--expect fault\|driven`, `--build direction\|combined`) | PASS 2026-07-08, fault 4/4 + recovery 4/4 |

## Bench wiring notes

- Saleae Logic16 lead labels ≠ channel indices (two 8-lead banks). DUT PD6
  is currently on **channel 8**. After rewiring, locate signals with an
  all-channel sweep capture first.
- `m2k_signal_check.py` rig: M2K DIO0 → Saleae **channel 15** (current bench);
  M2K W1 → M2K 1+; M2K V+ → M2K 2+; all grounds common (M2K, Saleae, LinkE,
  DUT).
- Keep M2K AWG outputs configured 0–3.3 V near the DUT (hardware can swing
  ±5 V — beyond CH32V003 absolute maximums).
- **MAX3485 rig (2026-07-06)**: DUT transceiver DI+RO → PD6 (Saleae ch8 on
  that node), DE+R̄Ē → PC2 (ch15) with the 10 k pull-down; bus A/B → M2K
  scope 1+/2+ for the analog wire view. **Second MAX3485 as raw master**:
  M2K DIO0 → DI, DIO1 → DE+R̄Ē, **V+ → VCC (3.3 V)** — every raw-master
  script must enable V+ itself (`ps.enableChannel(0, True)` +
  `pushChannel(0, 3.3)`): an unpowered MAX3485 sits inert and the static
  DE/DI test (drive space, drive mark, release) is the 10-second wiring
  proof. The `windmeters-modbus-interface-tester` on the same bus is both
  a third node and a scriptable well-formed master (machine API, see its
  `manual/api.md`).

## MAX3485-rig lessons (2026-07-06, learned the hard way)

- **The tester never stops listening.** Its Modbus master only drains its
  UART RX during its own transactions, so it buffers every byte the raw
  master puts on the shared bus; its next transaction then parses the
  stale backlog and reports CRC_ERR (log showed ~30 overheard frames
  ahead of the true response). One throwaway read IS the flush — retry
  once on `crc_error` before trusting a tester-API read after raw-master
  traffic (`rs485_raw_check.dut_diag`).
- **Inter-frame marks in composed patterns must exceed t3.5 (4.01 ms).**
  A 2.5 ms gap between a garbage tail and the recovery request made the
  DUT (correctly) coalesce them into one discarded frame — 48 bit times
  of mark (5 ms) is the house gap.
- **Noise floods don't move the DUT's CRC counter** — random bytes arrive
  framing-poisoned (FE/overflow) and take the silent-discard path;
  only cleanly-framed-wrong-CRC frames (e.g. split halves) increment
  30009. Assert flood recovery by behavior, not by that counter.
- The DUT answers master baud offsets to ±3 % in both directions
  (measured with the rate read back from the ladder); its own HSI adds
  ~+0.3 %.

## M2K / libm2k quirks (learned on the bench, fw v0.33 + libm2k 0.9.0)

- **Firmware ≥0.32 is mandatory** for libm2k 0.9.0 (shipped fw v0.27 gave
  erratic AWG output and version errors). Update: copy `m2k.frm` from the
  m2k-fw release onto the M2K mass-storage drive and eject; it self-flashes
  (~1 min, don't unplug).
- **Analog-out session-state corruption**: within one context, repeated
  output reconfiguration misbehaves — `stop()` wedges the DAC until
  `reset()`; a second cyclic `push()` at the same sample rate is silently
  ignored; non-cyclic pushes and `setVoltage()` inherit stale state. The
  reliable pattern is a **fresh `m2kOpen()` + calibrate per analog stimulus
  configuration** (~1.5 s each). Digital out is unaffected.
- Rapid close/reopen can transiently fail ("Cannot set the number of kernel
  buffers") — retry with ~1 s backoff (`open_calibrated()` helper).
- **Pattern generator start stub**: the first period after `push()` is
  anomalous; frequency/duty measurements must judge steady state only.
- **Large cyclic digital buffers get truncated** (1 Hz @ 1 MS/s ran 6%
  fast) — scale the sample rate to keep one period at ~10k samples.
- AWG sample rates snap to a discrete ladder (75 MS/s / 10ⁿ); at low rates
  the DC output droops between buffer wraps — generate DC at 750 kS/s or
  via `setVoltage()`.
- Absolute AWG+scope accuracy stacks badly — DMM-anchored on this unit:
  the **AWG outputs setpoint +25 mV** (constant), the **scope reads
  ~1%/−30 mV low** (affine, drifts ~10 mV between sessions). Never assert
  DUT accuracy against M2K absolute voltages; use a **resistor divider
  from DUT VDD** (ratiometric, DMM-measured ratio) as the method of
  record. The M2K remains fine for dynamics, end stops, and anything
  ratio-cancelled.
- **Keep the libm2k context OPEN while the DUT-side capture runs**:
  `contextClose()` idles the AWG outputs. Measure-then-close-then-capture
  silently tests a dead stimulus (cost a full debugging afternoon).
- A "disabled" AWG channel is NOT high-impedance (~50 Ω to its idle
  level) — it cannot emulate a disconnected sensor for float-detection
  tests; physically lift the wire instead.

## Saleae MCP quirks (learned on the bench)

- `add_analyzer` settings need tagged values: `{"Input Channel": {"numberValue": 8}}`.
- `export_raw_data_csv` requires `analogDownsampleRatio` even for digital-only.
- Async-serial data-table CSV holds the *literal* character per byte — CR/LF
  arrive as embedded newlines inside quoted fields; don't strip.
- A capture that starts mid-byte yields garbage + one framing error before
  the first line boundary — judge from the first clean `\n` onward.
- Classic Logic16 rejects `digitalThresholdVolts` values — omit it (default
  range suits 3.3 V logic).

## Modbus TTL-rig lessons (phase 3, learned the hard way)

- **The Logic 2 Async Serial analyzer is unreliable at 9600 baud** on this
  setup — byte values scramble while the raw edges are perfect. Binary
  protocols use `saleae_serial.uart_decode()` (software UART over the raw
  edge export) instead. Also: `decode_events(..., sync_to_newline=False)`
  for binary — the text-protocol first-LF rule silently discards
  LF-free captures.
- **M2K as shared-wire master: use open-drain output mode**
  (`setOutputMode(DIO_OPENDRAIN)` + the external pull-up), permanently
  enabled. The tristate dance (direction flips per transaction) sprays
  break glitches and phantom start bits; `push()` starts can still glitch —
  keep a ~10 ms driven-high lead-in so any phantom byte orphans behind a
  t3.5 gap.
- **A master must release the wire immediately after its last stop bit** —
  the DUT replies ~5 ms later; holding the line driven collides with the
  reply.
- DUT-side registers exposing error counters and a last-bad-frame stash
  are worth their flash cost many times over: the stash is what proved
  "first byte swallowed" and later "ISR corruption" beyond argument.

## DUT-side UART gotchas (learned on the bench)

- **HDSEL idles the line floating**: in half-duplex mode the USART releases
  TX between frames; a lightly-loaded pin drifts low and every following
  frame decodes with framing errors. `common/debug_uart` therefore runs
  plain TX (idle mark driven). Continuous streams mask this — it only bites
  bursty output.
- **HDSEL also intermittently swallows the first RX byte after idle**
  (~35%, no error flags) — the Modbus driver abandoned HDSEL entirely for
  a remap-switching discipline (RX on PD6 via the default map; TX remapped
  in only for the response). See `software/drivers/modbus_rtu/README.md`.
- **Interrupts are suspect on this toolchain path**: an RXNE ISR corrupted
  ~1/3 of received frames with no USART error flags; polled RX fixed it
  outright. The architecture is now zero-ISR
  (`design/softwareArchitecture.md`) — root-cause before ever adding one.
- **ch32v003fun SysTick default is HCLK/8**: define
  `FUNCONF_SYSTICK_USE_HCLK 1` when pacing with raw `SysTick->CNT` math, or
  everything runs 8× slow.
- Count-vs-frequency asserts must scale to the **measured** window duration
  (report-line timestamp deltas): the DUT window is HSI-paced (±1%), so at
  1 kHz a nominal-window compare is off by several counts while the DUT is
  behaving exactly per FR-S06.
