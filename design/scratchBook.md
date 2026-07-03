# General

# Sensors

## Wind-direction-meter

The wind direction meter has a potentiometer where the full 360 degrees range is covered by the resistance of the potentiometer.
 
## Windspeed-meter

The wind speed meter is a cup-anemometer which gives pulses through a reed-relais.

# Software

 - The interface is addressable over modbus.
 - The interface can read both wind-direction-meter and cup-anemo-meter.
 - The software is configurable via compile-time defines to select either wind speed or wind direction mode. Hardware is identical for both; only the firmware build differs.

## Anemometer calibration factor (C)

The calibration factor C (metres per rotation) converts pulse count to wind speed and can be derived from geometry:

```
C = 2πr / η
```

Where:
 - r = arm length from shaft centre to cup body centre (metres)
 - η ≈ 0.5 for a standard 3-cup anemometer (empirical, holds to ±5% for most hemispherical/conical cup designs)

Practical approximation:
```
C ≈ 2πr / 0.5  =  4πr  ≈  12.57 × r
```

Example with r = 0.075 m: C ≈ 0.94 m/rotation.

### How to measure r

 1. Lay the rotor flat. Measure from the centre of the shaft to the centre of one cup body. That is r.
 2. Direct arm measurement to cup centre is cleaner than deriving from full span.

### Known sensor (r = 0.07 m, η = 0.45)

Using η = 0.45 (typical for small hemispherical cups — slightly below textbook 0.5):
```
C = 2π × 0.07 / 0.45  ≈  0.98 m/rotation
```

Conversion formula:
```
v [m/s]  =  pulses_per_second  ×  0.98
```

### Sensitivity to η

| η assumed | C (m/rot) | Note |
|-----------|-----------|------|
| 0.40 | 1.10 | Draggy cups / compact rotor |
| 0.45 | 0.98 | Typical small 3-cup |
| 0.50 | 0.88 | Ideal textbook |

The η = 0.45 assumption introduces ±10–12% uncertainty vs. wind-tunnel calibration. Acceptable for weather-station use but relevant when setting trigger thresholds (a 10% error on a 10 m/s threshold means actual trigger at 9 or 11 m/s).

### Empirical calibration (eliminates η uncertainty)

Hold the anemometer and a handheld reference anemometer in the same airflow. Read the handheld m/s and the pulse count over the same interval, then solve directly:
```
C  =  v_reference  /  pulses_per_second
```
Five minutes on a breezy day is sufficient.

### Implementation note

C is a compile-time define (decided in TDS FR-S25: integer fixed-point, unit 0.001 m/rotation, default 980; no holding register). The SysTick ISR applies it in the millisecond domain (TDS FR-S06):
```
wind_speed_0.1ms  =  (count × C_scaled × 10) / window_ms
```

### Mechanical factors affecting calibration

| Factor | Effect | Mitigation |
|--------|--------|------------|
| Bearing friction | Dead band at low speeds; reduces η below geometric ideal | Accept or add low-speed cut-off register |
| Rotor inertia | Lag on instantaneous readings; natural low-pass filter | Use the averaged register (`0x0003`) for meaningful data |
| Cup shape | Sets baseline η (hemispherical ≈ 0.45–0.50) | Use η = 0.45 as default for small cups |
| Arm drag | Small η reduction | Absorbed into empirical calibration |
| Bearing wear | C drifts over time | Periodic empirical recalibration |

 - **Starting threshold**: bearing friction creates a dead band (typically 0.3–1 m/s) below which the rotor does not spin. Pulse count = 0 but wind speed ≠ 0 in this range.
 - **Rotor inertia**: the rotor lags rapid wind changes. For instantaneous readings this introduces a time lag; for averaged readings it largely cancels — a natural low-pass filter. Heavier rotors have more lag.
 - **Non-linearity**: η is stable and linear over the normal operating range. At very low speeds (near starting threshold) friction dominates and the formula over-reads slightly.
 - **TODO**: add low-speed cut-off holding register — below the starting threshold report 0 m/s rather than noisy near-zero values. Typical cut-off: 0.3–0.5 m/s. Add as holding register `0x0004` (Modicon 40005 — not yet in the table above).

## Wind speed measurement

 - Method: frequency measurement, rising edges only, over a configurable measurement window (holding register `0x0002`, default 1000ms).
 - Matches TIM2 ETR external clock counter on PC1 — pulses counted in hardware with zero CPU overhead between measurements.
 - Rising edges only: reed relay duty cycle is not guaranteed 50%, so counting both edges would introduce speed-dependent error. Debounce RC filter is optimised for one transition direction.
 - At very low wind speeds resolution is coarse (few pulses per window), but acceptable for a weather station application.
 - Hardware is not a limiting factor: anemometer max pulse rate ~50–100Hz; TIM2 ETR handles up to ~12MHz. Reed relay is mechanically limited to ~1kHz — irrelevant.
 - Firmware structure is minimal — three concurrent elements:
   - TIM2 (ETR, PC1): autonomous hardware pulse counter, runs continuously
   - SysTick: fires at end of each measurement window, reads and resets TIM2, scales count to 0.1 m/s via calibration factor, updates Modbus input register `0x0001`
   - USART1 ISR (PD6): Modbus frame handler
 - Clock: 48MHz internal RC (±1%) gives ±1% timing error on a 1s window — acceptable for weather sensing. No external crystal required.
 - Entire measurement logic fits well within CH32V003 16KB flash alongside Modbus framing code.

## Modbus configuration

 - Valid slave addresses: 1–247 (0 = broadcast, 248–255 reserved).
 - Device address is determined by firmware build (sensor type define) combined with solder jumper:
   - Wind speed:     solder jumper open = 30, bridged = 35
   - Wind direction: solder jumper open = 31, bridged = 36
 - Supported function codes: FC03 (read holding registers), FC04 (read input registers), FC06 (write single register), FC16 (write multiple registers).

**Addressing convention:** registers below are given as raw 0-based wire
addresses — what actually goes in the FC03/04/06/16 PDU — with the
30001/40001-style ("Modicon") number kept alongside for cross-reference
against older notes and datasheets that use it. This matches the convention
adopted by the sibling `windmeters-modbus-interface-tester` project (whose
Register Explorer treats raw as canonical and accepts Modicon only as an
input format). Picking one convention now, while this firmware is still
unwritten, avoids carrying two addressing dialects once real register code
exists.

> **Note (2026-07-02):** the authoritative register map now lives in
> `design/TDS.md` §2.7/§2.8 (extended to 12 input registers incl. status,
> identification, and diagnostics, with per-build applicability and
> defaults). The tables below are the original design reasoning and are
> not maintained.

### Input Registers — FC04, read-only (sensor data)

| Address (raw) | Modicon # | Description | Unit | Range |
|---|---|---|---|---|
| `0x0000` | 30001 | Wind direction, instantaneous | 0.1° | 0–3599 |
| `0x0001` | 30002 | Wind speed, instantaneous | 0.1 m/s | 0–65535 |
| `0x0002` | 30003 | Wind direction, averaged | 0.1° | 0–3599 |
| `0x0003` | 30004 | Wind speed, averaged | 0.1 m/s | 0–65535 |
| `0x0004` | 30005 | Pulse count (raw, diagnostic) | pulses/interval | 0–65535 |

### Holding Registers — FC03/FC06/FC16, read-write (configuration)

| Address (raw) | Modicon # | Description | Unit | Range |
|---|---|---|---|---|
| `0x0000` | 40001 | Modbus device address | — | 1–247 |
| `0x0001` | 40002 | Wind direction offset (calibration) | 0.1° | 0–3599 |
| `0x0002` | 40003 | Measurement interval | ms | e.g. 1000 |
| `0x0003` | 40004 | Averaging window | seconds | default 10 |

### Averaging

 - Both instantaneous and averaged values are provided per sensor — Modbus master can use either.
 - Wind speed averaging: simple running mean over the averaging window (40004).
 - Wind direction averaging: requires circular mean (sine/cosine method) to correctly handle 0°/360° wrap-around — e.g. averaging 350° and 10° must yield 0°, not 180°. Slightly more firmware code but essential for correctness.
 - WMO standard reference: 10-minute mean wind speed and direction. Default averaging window of 10 seconds is a practical compromise for embedded use.
 - Averaging is computed entirely in firmware with no hardware cost — negligible RAM usage on CH32V003.

### Conventions

 - Wind direction 0° = North, clockwise (WMO meteorological standard). Calibration offset (`0x0001`) allows installer to align potentiometer zero to North without mechanical adjustment.
 - All values use integer registers with implied decimal (e.g. 123 = 12.3 m/s, 1234 = 123.4°) — no floating point, compatible with standard SCADA systems.
 - Wind speed derived from pulse frequency using anemometer manufacturer calibration curve (pulses/s → m/s).

# Hardware

## Microporcessor options

In order of preference:
 
 1. CH32V003J4M6, SOIC-8
 2. CH32V003A4M6, SOIC-16
 3. CH32V003F4P6, SOIC-20
 
## Modbus transceiver

 - MAX3485, SOIC-8
 - Interface to MCU (verified compatible with the remap-switching firmware
   discipline, 2026-07-03): DI + RO tied together on net `MB-TX/RX` → PD6;
   DE + R̄Ē tied together on net `MB-RE/DE` → PC2. RO goes high-Z whenever
   DE is asserted, so TX-phase drive on the shared node is contention-free.
 - **10 kΩ pull-down on `MB-RE/DE`** (added 2026-07-03): holds the
   transceiver in receive mode while the MCU is in reset and during
   WCH-LinkE flashing — without it, a floating DE can jam the shared bus.
 - Fail-safe bias verified: R2 20k pulls A to 3V3, R3 20k pulls B to GND
   (idle = mark), alongside the 120Ω terminator behind solder jumper JP1
   and the SM712 TVS on A/B.

## CH32V003J4M6 pin assignment (SOIC-8)

The SOP-8 bonds out only 6 GPIO. Note: none of the USART1 remap combos place both TX and RX on this package. ~~So Modbus uses the USART in **single-wire half-duplex** mode (HDSEL) on PD6~~ **Superseded 2026-07-03 (phase-3 bench): HDSEL intermittently swallows the first received byte after bus idle. The driver instead uses a remap-switching discipline — RX is natively on PD6 in the default map; TX is remapped onto PD6 (partial remap 2) only while transmitting the response. See `software/drivers/modbus_rtu/README.md`.** A separate GPIO drives the RS-485 driver-enable.

| Pin | Name | Assignment | Function used |
|-----|------|------------|---------------|
| 1 | PD6 | RS-485 data | USART1 half-duplex (HDSEL); tie to MAX3485 DI + RO |
| 2 | VSS | Ground | — |
| 3 | PA2 | Wind-direction (analog) | ADC A0 (also OPP0 op-amp input) |
| 4 | VDD | Power | — |
| 5 | PC1 | Anemometer (pulse) | TIM2_CH1_ETR external-clock counter (remap) |
| 6 | PC2 | RS-485 DE//RE | GPIO direction control for MAX3485 |
| 7 | PC4 | Modbus address selector | GPIO in with solder jumper to GND or VDD |
| 8 | PD1 | Programming | SWIO (WCH-LinkE) — keep free for flashing |

Notes:
 - **Wind-direction-meter** (potentiometer) -> PA2 / ADC A0. PA2 is also the op-amp positive input (OPP0) if signal conditioning is wanted.
 - Potentiometer (11kΩ) powered ratiometric from 3.3V: wiper to PA2, ends to 3.3V and GND. ADC reference = VDD (SOIC-8 has no VREF+ pin). Ratiometric connection cancels 3.3V rail ripple — do NOT use an external voltage reference as it would break this cancellation.
 - ADC input voltage range: 0V to VDD (3.3V). Potentiometer wiper sweeps exactly 0V–3.3V over 360°, using the full ADC input range. Absolute maximum: −0.3V to VDD+0.3V — cannot be violated with pot tied directly between 3.3V and GND. No input protection components needed.
 - ADC resolution: 10-bit / 1024 steps → 0.35°/LSB over 360°. Configure ADC with longer sample time (≥71 cycles) to accommodate 11kΩ source impedance.
 - RC filter on 3.3V feed to potentiometer and PA2: 100Ω series + 10µF to GND. Suppresses HLK-K7803 switching ripple (~700kHz) while preserving ratiometric cancellation.
 - **Anemometer** (reed-relay pulses) -> PC1 / TIM2 external clock, hardware pulse counting (no CPU per pulse). PC1 has no ADC, so no analog capability is wasted. Needs AFIO remap (trailing `_` function).
 - **Modbus address selector** on PC4: GPIO input, solder jumper selects between two Modbus addresses (open = address A, bridged = address B). Internal pull-up or pull-down used; read at startup.
 - PD1 is the single-wire debug/flash pin (SWIO); do not use it for I/O.
 
## Power supply

 - DB20x bridge rectifier: sole purpose is polarity protection against reversed 24V PoE wiring — not used for AC rectification. Ensures correct DC polarity into the HLK-K7803 regardless of cable orientation.
 - HLK-K7803-500R3 DC/DC SIP-3 module: 3.3V / 500mA output
 - Bulk capacitor (100µF/50V electrolytic) between bridge and K7803 input
 - Output decoupling: 10µF/50V on K7803 input pin, 22µF/10V on output pin (ceramic, per datasheet)
 - TODO: evaluate LC filter on K7803 output to reduce ripple on ADC supply

## Design directives

 - a 3-pin header on the pcb shall make it possible to program the microprocessor
 - 2 RJ45 connectors shall enable "daisy chain" type interconnect of modbus.
 - The interface uses 24V passive PoE where power is carried on the spare pairs of 10/100 Ethernet:
   - Pins 4 & 5 -> +24V (positive)
   - Pins 7 & 8 -> return (negative/ground)
 - on pcb is a 120 ohm terminator resistor for modbus termination, disconnected by default via a solder jumper.
 - Modbus address selection via solder jumper on PC4 — two selectable addresses.
 - The modbus interface is protected by diodes for overvoltage
 - a RJ14 interface connects to the anemometer or the wind direction sensor
 - the modbus interface is mounted in close proximity to or as part of the anemometer; no long wiring runs
 - anemometer input circuit (screw terminal → PC1):
   - 100Ω series resistor at screw terminal (surge current limiting)
   - 10kΩ pull-up to 3.3V (doubles as debounce R; reed relay pulls PC1 to GND when closed)
   - 100nF to GND (debounce C; τ = 1ms, filters reed-relay bounce <5ms)
   - 3.3V zener (e.g. BZX84-C3V3, SOT-23) from PC1 to GND (overvoltage clamp; precautionary given short wiring)

 