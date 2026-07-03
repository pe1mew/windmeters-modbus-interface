# Wind speed driver — TIM2 ETR pulse counting on PC1

Phase-1 driver per `design/driverDevelopment.md` §3. Counts anemometer
reed-relay pulses in hardware (zero CPU per pulse, TDS FR-S04) using TIM2 in
external-clock mode 2 on PC1.

## HIL verification — PASS 2026-07-03 (9/9)

`software/hil/ws_check.py`, M2K DIO0 driving PC1, report stream decoded off
the Saleae:

| Row | Result |
|---|---|
| Counts 1 / 10 / 100 / 1000 Hz | exact, scaled to the measured window |
| Rising edges only (10% / 90% duty) | identical counts (FR-S04) |
| Window pacing | worst 3.35 ms deviation on 1000 ms = 0.34% (FR-S17 ±2%) |
| Saturation (100 kHz × 1 s = 100k edges) | reports 65535 + `S` flag, never a wrapped value (FR-S27) |
| Silence (line low / open with pull-up) | 0 counts |

Outstanding (hardware-dependent): reed-relay bounce realism through the RC
debounce — run when a physical reed relay is on the rig.

## The remap (the phase's big unknown — confirmed on silicon)

`AFIO_PCFR1[9:8] = 10` (TIM2 partial remap 2) places TIM2_CH1/ETR on PC1 —
the only mapping that reaches PC1 on the SOP-8. Configured in `ws_init()`
with a read-modify-write that preserves the USART1 remap bits. TIM2 then
runs in external clock mode 2 (`SMCFGR = TIM_ECE`, rising edges, no input
filter — the product's RC network debounces externally).

## API (`lib/ws/`)

```c
void     ws_init(void);                   // remap + counter running
void     ws_window_start(void);           // CNT=0, clear UIF
uint16_t ws_window_read(bool *saturated); // count; 65535 + flag if UIF set
```

Window pacing is the caller's job (test shell here: SysTick-paced 1000 ms,
`FUNCONF_SYSTICK_USE_HCLK 1` — ch32v003fun's default SysTick clock is
HCLK/8, which silently makes naive tick math 8× slow).

## Test shell output (PD6 debug UART, 115200)

```
WS,START
W,<count>,<flag>      one line per window; flag 0 normal, S saturated
```
