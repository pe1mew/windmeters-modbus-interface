# Wind direction driver — 10-bit ADC on PA2, oversampled, circular mean

Phase-2 driver per `design/driverDevelopment.md` §4. Reads the wind-vane
potentiometer ratiometrically (TDS FR-S09), 16× oversampled (FR-S28), with
wiper-float detection (FR-S38). The circular mean lives in
`software/drivers/common/circmean/` (Q15 sine table + integer CORDIC,
exhaustively host-tested + boot self-test on target).

## HIL verification — PASS 2026-07-03

Method of record for accuracy: **resistor divider powered from DUT VDD**
(ratiometric, cancels VDD, kΩ source like the real pot — exactly FR-S11's
method). AWG-based absolute-voltage tests proved unusable for accuracy: the
M2K AWG has a +25 mV output offset and the M2K scope reads ~1%/−30 mV low
(both DMM-anchored), stacking to a fake ±16 LSB "bow".

| Row | Result |
|---|---|
| Accuracy (FR-S11) | −3.8 LSB at divider ratio 0.49899 (9.92k/9.88k, DMM-measured); budget ±10 LSB. Full 5-ratio sweep deferred to acceptance. |
| Stability (FR-S10/S28) | raw16 span 0.6 LSB over 11 s (≤3 required) |
| End stops (FR-S09) | pin→GND: code 0.0; pin→VDD: code 1023.0 — exact |
| Never 3600 (FR-S29) | angle 3596 at the VDD rail, by construction |
| Float detect (FR-S38) | truly open pin: flt=1 every window; pot-like 4.95 kΩ source: flt=0; 50 Ω source: flt=0 |
| Circular mean (FR-S14) | host: identity 0 LSB over all 3600 angles, CORDIC ≤0.0035°, 350°/10°→0.0°; on-target boot self-test CM,PASS |

Deferred to integration/acceptance: 5-ratio accuracy sweep, M2K-powered VDD
sweep (explicit ratiometric-sanity row), offset register wrap via Modbus
(FR-S12 — logic host-proven).

## Bench findings that shaped the driver

- **ADC clock**: HCLK/8 = 6 MHz (`RCC_ADCPRE_DIV8` — the ADCPRE field is
  NOT a plain binary divider; use the named constants). At /2 = 24 MHz the
  part appeared to bow at range ends; later attributed mostly to
  instrument stack, but /8 costs nothing here (~14 µs/conversion, 224 µs
  per 16-burst vs the 100 ms update budget).
- **Float detector**: pull-toggle with 10 µs settle discriminates cleanly:
  truly open pads swing >700 LSB; a 5 kΩ pot moves ~100 LSB (threshold 300).
  A "disconnected" AWG does NOT read as floating — its disabled output is
  still ~50 Ω.
- **The angle mapping never emits 3600**: (raw16×3600+8192)>>14 tops out
  at 3596 at code 1023 — verified at the rail.

## API (`lib/wd/`)

```c
void     wd_init(void);            // ADC on, self-calibrated, 73-cycle sampling
uint16_t wd_read_raw16(void);      // sum of 16 conversions: 0..16368
uint16_t wd_angle_0_1deg(uint16_t raw16, uint16_t offset_0_1deg); // 0..3599
bool     wd_wiper_floating(void);  // FR-S38 pull-toggle test
```

## Test shell output (PD6 debug UART, 115200)

```
CM,PASS               boot self-test of circmean on the target CPU
WD,START
D,<raw16>,<inst>,<avg>,<flt>    per second; angles in 0.1°
```
