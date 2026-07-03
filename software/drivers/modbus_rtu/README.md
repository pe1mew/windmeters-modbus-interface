# Modbus RTU slave driver — USART1 on PD6, DE/RE on PC2

Phase-3 driver per `design/driverDevelopment.md` §5. Implements the TDS §2
driver layer: framing/CRC, t3.5 gap detection, address filtering,
FC03/04/06/16, standard exceptions, no-clamp range rejection, atomic FC16,
quantity validation, big-endian data / little-endian CRC, FC06 echo & FC16
confirm responses, and app-owned register semantics (holding table with
min/max, input-read callback, cross-validate hook for FR-S31).

## HIL verification — PASS 2026-07-03 (TTL rig, no transceiver)

`software/hil/mb_check.py`, M2K as bit-banged open-drain master on the
shared PD6 wire, Saleae raw-edge decode:

- **26/26 matrix vectors** covering FR-MB02/05/06/08–15/19/22/25/28/30 and
  FR-S31 cross-register constraint via the hook
- **40/40 endurance transactions**, zero loss
- **Response latency: median 5.2 ms, worst 5.2 ms** (FR-MB21 typical <15 ms,
  FR-MB20 hard <100 ms)

Deferred to the MAX3485 rig / acceptance: FR-MB04 DE-timing scope asserts
(PC2 is on Saleae ch15, not yet asserted), FR-MB24 garbage-flood and
oversize-frame vectors, FR-MB03 split-frame timing vectors, RS-485
electrical rows.

## Two hard-won design decisions (bench-forced, both product-relevant)

**1. No HDSEL — remap-switching line discipline.** In HDSEL single-wire
mode this part intermittently (~35%) swallowed the FIRST byte after bus
idle with no error flags (wire verified pristine at 10 MS/s; the stashed
frame was the request minus its address byte). Instead the driver uses the
SOP-8 remap geometry: the DEFAULT USART map has **RX natively on PD6**;
`mb_send()` temporarily switches to partial remap 2 (TX→PD6), transmits,
and switches back. Modbus is strictly request/response, so the direction is
always known. Side benefit: no self-echo during reception (FR-MB23
satisfied by flag-clearing around the TX window).

**2. Polled RX — zero interrupts.** With the RXNE ISR, ~1/3 of frames
reached the parser with missing/scrambled leading bytes while the USART
never flagged an error — symptoms of ISR prologue/state corruption on this
toolchain path (`__attribute__((interrupt))` on RV32EC, unconfirmed root
cause; treat ANY interrupt use in this project as suspect until
investigated). Polling from the main loop (~1 µs cycle vs 1042 µs per
byte) is provably lossless and removed every failure instantly:
26/26 + 40/40 vs the ISR build's chaos. `softwareArchitecture.md` is
amended accordingly.

## Diagnostics (exposed as shell input registers)

`mb_crc_error_count` / `mb_served_count` (future 30009/30010), plus bench
registers: FE/NE/ORE counters and a last-CRC-fail frame stash (len, first
bytes, received CRC) — the stash is what cracked the first-byte-loss hunt.

## API (`lib/mb/`)

```c
mb_config_t cfg = {.address, .holdings, .n_holdings,
                   .input_read, .cross_validate};
void mb_init(const mb_config_t *cfg);
void mb_poll(void);   // main loop; self-timed via SysTick->CNT
```
