# Technical Design Specification — Windmeters Modbus Interface

| Field        | Value                                    |
|--------------|-------------------------------------------|
| Document     | Technical Design Specification            |
| Project      | `windmeters-modbus-interface` (DUT firmware) |
| Version      | 0.9 (draft — §2 Modbus, §3 Software, §4 Hardware, §5 NFRs; v0.6 removed the device-address register (address is hardware-configured only); v0.7 added FR-S39 holding-register persistence and the combined build variant; v0.8 added runtime+persistent anemometer calibration (FR-S40, 40005/40006); v0.9 promotes the as-built hardware design from the KiCad PCB into the new §4 and closes/narrows the §6 open items) |
| Date         | 2026-07-12                                |
| Status       | Draft. Hardware, power, and calibration derivation are now captured in §4 from the as-built KiCad PCB (`hardware/KiCad/`); residual open items are tracked in §6. |
| Related docs | `hardware/KiCad/windmeter-modbus-interface.kicad_{sch,pcb}` (as-built PCB — source for §4); `design/scratchBook.md` (original register-map/hardware/calibration reasoning, superseded by §2/§4 where they overlap); sibling `windmeters-modbus-interface-tester` repo's `design/progress.md` §7 and `design/whatsNext.md` §3.2 (bench evidence cited in §2) |

---

## 1. Purpose and scope

`scratchBook.md` is working notes: what the registers mean, how the
hardware is wired, how calibration is derived. This document holds the
things the firmware **must** do, each with a testable pass/fail —
including the failure paths (unsupported function codes, unimplemented
registers, out-of-range writes) that otherwise get decided implicitly,
one `if` statement at a time, while `software/firmware/src/main.c` is
still scaffolding.

Requirements are seeded from two sources: the Modbus RTU specification,
and bench observations made testing a real commercial slave (an FG6485A
humidity/temperature sensor) with the `windmeters-modbus-interface-tester`
tool. Version 0.4 additionally incorporates a systematic six-lens gap
audit (firmware lifecycle, protocol completeness, measurement data path,
configuration/persistence, diagnostics, NFRs/testability) that confirmed
38 gaps, including three internal contradictions now resolved (see
FR-MB16, FR-MB26, FR-S21).

Key design decisions fixed in this version:

- Holding registers persisted across reset in flash-emulated non-volatile storage (FR-S39); §2.8 defaults apply only on first boot / erased store (FR-S21).
- Device address is hardware-configured only (build define + PC4 solder jumper); there is no address register — see FR-S03/FR-MB07.
- Exception 04 never emitted; faults handled by watchdog and defined register values — see FR-MB29.
- Hardware captured as-built from the KiCad PCB (§4): one unmodified 2-layer board serves all three build variants (FR-S02), 24 V passive PoE, a MAX3485 transceiver, and RJ14 sensor jacks.

---

## 2. Modbus requirements

### 2.1 Physical layer, framing, and receiver robustness

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB01 | Must | The firmware shall communicate using Modbus RTU framing at 9600 baud, 8 data bits, no parity, 1 stop bit (8N1). | Connect a Modbus analyser or the tester at 9600 8N1; all frames are decoded without framing errors. |
| FR-MB02 | Must | Frames with an invalid CRC-16 shall be silently discarded. No response shall be sent. | Send a frame with a deliberately corrupted CRC; confirm no reply within 200 ms. |
| FR-MB03 | Must | The firmware shall detect the inter-frame gap (3.5 character times) as the frame boundary. One character time is defined as 11 bits per the Modbus RTU specification (11/9600 s ≈ 1.15 ms), so 3.5 character times ≈ 4.0 ms at 9600 baud; this definition applies wherever this document says "character time". A new frame starts after this silence. | Two back-to-back valid requests separated by ≥5 ms are both processed correctly. Send the first 4 bytes of a valid request, pause ≥5 ms, then send the remaining bytes: no response of any kind within 200 ms; an immediately following complete valid request receives a correct response, proving the receiver state machine recovered. |
| FR-MB04 | Must | The RS-485 driver-enable line (DE/RE on PC2) shall be asserted before the first transmitted byte and de-asserted after the last transmitted byte, within one character time (≈1.15 ms at 9600 baud). | Scope DE/RE and TX lines: DE asserts before TX start bit; DE de-asserts within one character time after the last stop bit. |
| FR-MB23 | Must | While the firmware is transmitting (DE asserted), any bytes appearing on the USART receiver shall be discarded and shall not be evaluated as an incoming frame. (The MAX3485 RO and DI are tied on the shared PD6 data node, §4.3; RO is high-Z while DE is asserted, and the firmware uses a remap-switching line discipline — USART1 RX native on PD6, TX remapped onto PD6 only for the response — rather than HDSEL, which bench testing showed intermittently swallows the first byte after bus idle.) Frame reception shall re-arm only after DE is de-asserted and a 3.5-character idle time has elapsed. | Bus-analyser capture: send one valid FC04 request and confirm exactly one response frame is transmitted and the bus then stays idle — no self-triggered frame within 500 ms. Repeat 100 times back-to-back with zero spurious frames. |
| FR-MB24 | Must | On any USART receive error (overrun, framing, noise) or on receiving more bytes without a 3.5-character gap than the receive buffer holds (the buffer shall accept frames up to the 256-byte Modbus RTU ADU maximum), the firmware shall discard the frame in progress, clear the error condition, and resynchronise on the next ≥3.5-character idle gap. No buffer overflow and no receiver lockup shall occur. | Transmit continuous pseudo-random bytes at 9600 baud with no idle gaps for 60 s, then one valid FC04 request: a valid response arrives within the FR-MB20 budget; repeat 10 times with 100% success. Send a 400-byte "frame" followed by a ≥5 ms gap and a valid request: no response to the burst, valid response to the request; 20 repetitions without failure or reset. |
| FR-MB25 | Must | All 16-bit register values and 16-bit address/quantity fields in request and response PDUs shall be transmitted big-endian (high byte first). The CRC-16 field shall be transmitted low byte first, high byte second, per the Modbus RTU specification. | With wind direction held at a known 90.0° (register value 900 = 0x0384), an FC04 read of raw 0x0000 returns data bytes 0x03 then 0x84 in that order, decoded as 900 by the tester with no byte-swap option. The final two bytes of every captured frame validate as CRC low-byte-first. |

### 2.2 Addressing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB05 | Must | The firmware shall respond only to requests addressed to its currently active Modbus address. Requests addressed to any other unicast address shall be silently ignored. | With the DUT as the only slave on the bus, send a valid FC04 request to address 247 (never assigned in this product family per FR-S03): no reply within 200 ms. Send the same request to the DUT's own address: valid reply. |
| FR-MB06 | Must | Broadcast requests (address 0) shall be silently ignored — not executed, no response sent. *Deliberate deviation from Modbus-over-Serial-Line V1.02 §2.2, which requires slaves to execute broadcast writes. Rationale: broadcast execution of configuration writes risks unintended fleet-wide reconfiguration and offers no benefit given jumper-derived addressing (FR-S03). This deviation shall be stated in user-facing register-map documentation.* | Send a valid FC06 write to address 0; confirm no reply within 200 ms and no register change on follow-up read. |
| FR-MB07 | Must | The device address shall be latched at startup per FR-S03 (the single normative source of the address table) and shall not change until the next reset. There is no Modbus-accessible address register. | Wind-speed build: power cycle with solder jumper open → device responds at 30 and not at 35; with jumper bridged → responds at 35 and not at 30. Wind-direction build: same test with 31/36. A jumper change mid-cycle has no effect until the next reset. |
| FR-MB26 | — | **Withdrawn (v0.6).** The device-address holding register was removed from the map: the address is hardware-configured only (build define + PC4 solder jumper, FR-S03) and cannot be read or changed over Modbus. A write to the (now unmapped) former address falls under FR-MB15. | — |

### 2.3 Supported function codes

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB08 | Must | FC04 (Read Input Registers) shall be supported for all input register addresses in §2.7. | FC04 request for each register in §2.7 returns a valid response with correct byte count and data. |
| FR-MB09 | Must | FC03 (Read Holding Registers) shall be supported for all holding register addresses in §2.8. | FC03 request for each register in §2.8 returns a valid response with correct byte count and data. |
| FR-MB10 | Must | FC06 (Write Single Register) shall be supported for all holding register addresses. | FC06 write of a valid value to each holding register is accepted; follow-up FC03 read confirms the new value. |
| FR-MB11 | Must | FC16 (Write Multiple Registers) shall be supported for holding registers. | FC16 write of valid values to two consecutive holding registers is accepted; follow-up reads confirm both values changed. |
| FR-MB12 | Must | Any function code other than FC03, FC04, FC06, FC16 shall be rejected with exception 01 (Illegal Function). | Send FC01, FC02, FC05; confirm exception 01 response for each. Bench evidence: the FG6485A's non-standard exception code (0x81 with code 129) caused the tester decoder to fall back to "unknown" — standard code 01 avoids this. |
| FR-MB30 | Must | The normal (success) response to FC06 shall be a byte-exact echo of the request frame. The normal response to FC16 shall contain: slave address, function code 0x10, starting address (2 bytes), quantity of registers written (2 bytes), CRC — not the register data. | Capture request and response for FC06 write 40001 = 100: the two frames are byte-identical. For an FC16 write of 2 registers at raw 0x0001: the response PDU after the function code is exactly 0x00 0x01 0x00 0x02. |

### 2.4 Register access rules

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB13 | Must | A read request for any register address not listed in §2.7 or §2.8 shall return exception 02 (Illegal Data Address). | FC04 or FC03 request for raw address 0x0020; confirm exception 02. |
| FR-MB14 | Must | A multi-register read (FC03/FC04) whose range spans at least one unimplemented address shall return exception 02 for the entire request. No partial data shall be returned. | FC04 request starting at the last valid input address with count 2; confirm exception 02, not partial data. |
| FR-MB15 | Must | A write to an unimplemented holding register address shall return exception 02. | FC06 write to raw holding address 0x0020; confirm exception 02 and no side effect. |
| FR-MB16 | — | **Withdrawn (v0.4).** Modbus has one address space per function code: FC06/FC16 by definition address the holding-register space (§2.8) exclusively; input registers (§2.7) are reachable only via FC04 and are read-only by construction. There is no wire-level "write to an input register" to reject. A write whose raw address is not listed in §2.8 is handled by FR-MB15. | *Non-normative regression note (owned by FR-MB10):* FC06 write of value 32 to raw 0x0000 (direction offset, valid range 0–3599) returns a normal response and follow-up FC03 confirms the value; FC04 read of raw 0x0000 still returns the measurement, unmodified by that write. Withdrawn IDs are excluded from NFR-TST01. |
| FR-MB27 | Must | Every firmware build shall implement the §2.7/§2.8 register map: the single-sensor builds map raw 0x0000–0x000B (12 input registers), the combined build additionally maps 30013 (§2.7). Input registers whose sensor is not present in the active build shall read 0 (except raw 0x0004, which reports the build-specific diagnostic per §2.7). Configuration holding registers shall accept and store range-valid writes on every build — with no measurement effect where the sensor is absent — and read back the stored value. No mapped register shall return exception 02 on any build. | On a wind-speed build, FC04 read of raw 0x0000–0x0004 quantity 5 returns a normal response with 0x0000 and 0x0002 equal to 0. On a wind-direction build the same read succeeds with 0x0001 and 0x0003 equal to 0. FC06 write of 100 to 40001 (direction offset) on a wind-speed build is accepted and reads back 100. On a combined build both sensors' registers are live and FC04 of 0x000C (30013) succeeds. |
| FR-MB28 | Must | FC03/FC04 requests with quantity = 0 or > 125 shall return exception 03 (Illegal Data Value). FC16 requests with quantity = 0, quantity > 123, or a byte-count field not equal to 2 × quantity shall return exception 03 and shall modify no register. Quantity validation shall be performed before address validation. | FC04 at raw 0x0000 with quantity 0 returns exception 03 (not 02, not an empty data frame) within 200 ms. FC03 with quantity 126 returns exception 03. FC16 to raw 0x0001 with quantity 2 but byte count 5 returns exception 03 and follow-up reads show both registers unchanged. |

### 2.5 Exception handling

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB17 | Must | For any addressed request the firmware cannot fulfil, a well-formed Modbus exception response shall be returned. The firmware shall never stay silent on a valid addressed request. | Send FC04 for an unimplemented address; confirm a response arrives within 200 ms. Bench evidence: the tester's bus scanner detects a device only because it exception-replies — a silent device is invisible to `bus_scan_did_respond()`. |
| FR-MB18 | Must | Exception responses shall use only the standard Modbus exception codes: 01 Illegal Function, 02 Illegal Data Address, 03 Illegal Data Value. No vendor-specific codes shall be used. (Code 04 is standard but deliberately never emitted — FR-MB29.) | For each exception path (FR-MB12/13/15/19/28), confirm the exception byte is one of 01/02/03 and is decoded correctly by the tester's `exception_name` field. Bench evidence: FG6485A returned code 129 (non-standard); the tester decoder fell back to "unknown". |
| FR-MB19 | Must | A write (FC06/FC16) with a value outside the valid range defined in §2.8 shall return exception 03 (Illegal Data Value). The register shall be left unchanged. The firmware shall not clamp the value to the nearest valid bound, and shall not echo success while discarding the value. | Write direction offset (40001) = 4000 (out of range); confirm exception 03; follow-up read shows the register unchanged (not clamped to 3599). Bench evidence (INT-06): FG6485A echoed success for an out-of-range write but silently discarded the value — indistinguishable from a real write without an unprompted read-back. |
| FR-MB22 | Must | An FC16 write shall be atomic: if any value in the request is outside its valid range (including the cross-register constraint FR-S31), the entire request shall be rejected with exception 03 and no register in the range shall be modified. | FC16 write to 40001–40002 with a valid offset (e.g. 100) and an invalid window (e.g. 65000); confirm exception 03 and follow-up reads show both registers unchanged — including the one whose value was valid. |
| FR-MB29 | Should | The firmware shall never emit exception 04 (Slave Device Failure). Internal faults are handled by watchdog reset (FR-S20) and defined register values (FR-S21/FR-S29) instead. Exceptions shall be emitted only per the enumerated triggers: 01 per FR-MB12; 02 per FR-MB13/14/15; 03 per FR-MB19/22/28 and FR-S31. | Code review confirms no code path emits exception 04. Fault injection of documented conditions (bad function code, bad address, bad value, bad quantity) produces only the enumerated codes. |

### 2.6 Response timing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-MB20 | Must | The firmware shall transmit its response within 100 ms of receiving the last byte of a valid request. | Measure time from last RX byte to first TX byte using the tester's raw frame timestamps; confirm ≤100 ms for FC03, FC04, FC06, and FC16 requests. |
| FR-MB21 | Should | Under default configuration, at least 95% of responses shall start within 15 ms of the last request byte. | Issue 1,000 FC04 requests at 50 ms spacing with default configuration: at least 95% of responses start within 15 ms of the last request byte, and 100% within the FR-MB20 limit of 100 ms, measured from the tester's raw frame timestamps. |

### 2.7 Input register map (FC04, read-only)

Measurement registers 30001–30005 and 30012 read 0 from reset until the first measurement window completes (FR-S23). Identification, status, uptime, counter, and time-since-pulse registers (30006–30011) are valid immediately after reset. ● = active on this build; ○ = present but reads 0 on this build (FR-MB27); — = not mapped on this build (FC04 past the map edge returns exception 02, FR-MB13). The map edge is 0x000C (12 registers) on the single-sensor builds and 0x000D (13 registers) on the combined build, which adds 30013.

| Raw | Modicon # | Description | Unit | Range | Speed | Direction | Combined |
|-----|-----------|-------------|------|-------|-------|-----------|----------|
| `0x0000` | 30001 | Wind direction, instantaneous | 0.1° | 0–3599; 65535 = sensor fault (FR-S38) | ○ | ● | ● |
| `0x0001` | 30002 | Wind speed, instantaneous | 0.1 m/s | 0–65535 | ● | ○ | ● |
| `0x0002` | 30003 | Wind direction, averaged | 0.1° | 0–3599; 65535 = sensor fault (FR-S38) | ○ | ● | ● |
| `0x0003` | 30004 | Wind speed, averaged | 0.1 m/s | 0–65535 | ● | ○ | ● |
| `0x0004` | 30005 | Raw sensor diagnostic | build-specific | speed & combined: pulse count last window (0–65535); direction: last raw 10-bit ADC conversion (0–1023) | ● | ● | ● |
| `0x0005` | 30006 | Status flags (normative definition: FR-S33) | bitfield | bit 0 = no completed window yet; bit 1 = averaging accumulator not filled; bit 2 = direction sensor fault; bits 3–15 = 0 | ● | ● | ● |
| `0x0006` | 30007 | Identification | — | high byte = build type (0x01 speed, 0x02 direction, 0x03 combined); low byte = firmware version (FR-S32) | ● | ● | ● |
| `0x0007` | 30008 | Uptime since reset | s | 0–65535, saturating (FR-S34) | ● | ● | ● |
| `0x0008` | 30009 | Bus CRC error count | — | 0–65535, wrapping (FR-S35) | ● | ● | ● |
| `0x0009` | 30010 | Served request count | — | 0–65535, wrapping (FR-S35) | ● | ● | ● |
| `0x000A` | 30011 | Seconds since last pulse | s | 0–65535, clamped (FR-S36) | ● | ○ | ● |
| `0x000B` | 30012 | Gust: max window speed in current averaging window | 0.1 m/s | 0–65535 (FR-S37) | ● | ○ | ● |
| `0x000C` | 30013 | Wind direction, raw 10-bit ADC — combined build only (on single-direction builds this diagnostic is at 30005) | — | 0–1023 | — | — | ● |

### 2.8 Holding register map (FC03/FC06/FC16, read-write)

All holding registers persist across reset in non-volatile storage (FR-S39); the Default column is the value on first boot / when the store is blank or corrupt (FR-S21). Writes outside the valid range are rejected per FR-MB19/FR-MB22. A cross-register constraint between 40003 and 40004 is defined and enforced solely by FR-S31. Registers 40005/40006 are the anemometer calibration (FR-S40) — they affect only the speed path (inert on a direction-only build, per FR-MB27).

| Raw | Modicon # | Description | Unit | Valid range | Default |
|-----|-----------|-------------|------|-------------|---------|
| `0x0000` | 40001 | Wind direction calibration offset | 0.1° | 0–3599 | 0 |
| `0x0001` | 40002 | Measurement window duration | ms | 100–60000 | 1000 |
| `0x0002` | 40003 | Averaging window | s | 1–600, subject to FR-S31 | 10 |
| `0x0003` | 40004 | Low-speed cut-off threshold | 0.1 m/s | 0–50 | 4 |
| `0x0004` | 40005 | Anemometer calibration factor C (FR-S40) | 0.001 m/rotation | 1–6553 | 980 |
| `0x0005` | 40006 | Anemometer pulses per rotation (FR-S40) | pulses/rot | 1–1000 | 1 |

The device address is not a register: it is hardware-configured per FR-S03 and unreachable over Modbus (FR-MB07/FR-MB26).

---

## 3. Software requirements

### 3.1 Build configuration and startup

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S01 | Must | The firmware shall be selectable at compile time for wind speed, wind direction, or combined (both sensors, one slave) mode via a pre-processor define. | Build with `SENSOR_WIND_SPEED` produces a wind-speed binary, `SENSOR_WIND_DIRECTION` a wind-direction binary, and `SENSOR_WIND_COMBINED` a combined binary. All build without error from the same source tree. |
| FR-S02 | Must | A single hardware PCB shall support both sensor types without modification — individually (speed or direction build) or together (combined build). | Flash each release binary onto one unmodified PCB in turn; each build passes its full §2/§3 acceptance suite on that board. |
| FR-S03 | Must | The power-on Modbus device address shall be determined at startup by combining the firmware build type with the state of the solder jumper on PC4. This table is the single normative source of the address assignment: wind speed — jumper open = 30, bridged = 35; wind direction — jumper open = 31, bridged = 36; combined — jumper open = 32, bridged = 37. There is no address register; the address cannot be changed at runtime (FR-MB07). | Reading PC4 GPIO at startup selects the address per the table; the device responds only on that address after power-on (FR-MB07's criterion). |
| FR-S18 | Must | Initialization shall complete in this order before the main loop starts: (1) PC2 (DE/RE) configured as output driven low — receiver enabled, driver disabled — as the first GPIO action after reset; (2) PC4 read and the Modbus address latched; (3) sensor front-end ready — direction build: ADC self-calibration executed before the first conversion; speed build: TIM2 counter cleared at the instant the first measurement window opens; (4) USART1 receiver enabled last. | (a) Direction build: the first non-zero value after power-on at a fixed pot angle is within the FR-S11 tolerance, with no settling sequence of wrong values. (b) Speed build: with pulses applied from before power-on, the first completed window's 30005 equals rate × window ±1 pulse. (c) A valid request sent repeatedly from power-on is never answered from a wrong address. |
| FR-S19 | Must | The firmware shall never transmit on the bus except in response to a valid addressed request (no boot banner, no test bytes). After any reset, received bytes shall be discarded until a bus-idle period of ≥3.5 character times has been observed. | Scope PC2 and the bus across 20 power cycles while another master/slave pair actively exchanges frames: DE never asserts except to answer a valid request to the DUT, and a DUT reset injected mid-frame of third-party traffic produces no response to that partial frame. |

### 3.2 Reliability and lifecycle

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S20 | Must | The independent watchdog (IWDG) shall be enabled before the main loop starts, with a timeout between 100 ms and 2 s, refreshed only from the main loop after both the Modbus service and the measurement service have run — never from an interrupt handler. | (a) Via a debug-build hook that enters an infinite loop, confirm the device resumes answering a valid FC04 within 3 s without a power cycle. (b) 24 h of continuous polling under normal operation triggers zero watchdog resets. |
| FR-S21 | Must | After any reset (power-on, brown-out, watchdog, software), the firmware shall enter a defined state: holding registers restored to their last persisted values (FR-S39), or to §2.8's Default column when the persistent store is blank/corrupt; all measurement accumulators cleared. No Modbus-commanded reset shall exist; power cycling is the only reset a master or installer can invoke. | Trigger each reset source in turn (power cycle, watchdog hook, software reset): after each, the device responds at the jumper-derived address within 1 s, FC03 of raw 0x0000–0x0005 returns the last committed values (FR-S39), and all accumulators are cleared (status bits 0/1 set). On a device with an erased store the same read returns exactly the §2.8 Default column. |
| FR-S39 | Must | The six holding registers (40001–40006) shall persist across every reset and power-loss in on-chip non-volatile storage. On a write that *changes* a holding value (FC06/FC16, after it passes FR-MB19/FR-MB22/FR-S31 validation and the Modbus response has been transmitted), the firmware shall commit the whole holding set so a subsequent reset restores it (superseding the §2.8 defaults, per FR-S21). The commit shall be power-loss atomic — a reset at any point during a commit leaves the previously committed set intact, never a partial/corrupt configuration — and shall fall back to the §2.8 compile-time defaults when no valid record exists (first boot / erased store). Unchanged writes shall not wear the store. | Write non-default 40001–40006, trigger a watchdog reset, confirm FC03 returns the written values (not §2.8 defaults) within 1 s. On an erased store the read returns the §2.8 defaults. Re-writing identical values causes no additional non-volatile write. Power interrupted mid-commit never yields a partial configuration (the prior committed set survives). |
| FR-S40 | Must | The anemometer calibration shall be runtime-configurable and persistent via two holding registers: 40005 = calibration factor C (0.001 m/rotation, 1–6553, default per FR-S25) and 40006 = pulses per rotation (1–1000, default 1), applied per FR-S06. A change to either shall clear the averaging accumulator (as FR-S30 does for 40002/40003) so the boxcar never mixes pre- and post-calibration values. The registers exist on every build (FR-MB27) but affect only the speed path; on a direction-only build they are inert. | At a fixed pulse rate, 30002 tracks 40005 and 1/40006 proportionally (e.g. 40006 = 4 quarters the reading vs 40006 = 1). Both survive a reset (FR-S39). Writing 40005 = 0/6554 or 40006 = 0/1001 is rejected with exception 03 (FR-MB19). Changing 40005 or 40006 re-asserts status bits 0/1 (FR-S33) until a fresh averaging span fills. |
| FR-S22 | Must | The device shall resume full normal operation (all §2 and §3 requirements) after any supply interruption or dip, without manual intervention. Brown-out protection (hardware POR plus PVD if needed) shall guarantee the MCU either operates correctly or is held in reset — no third state. | With a programmable supply, apply a dip matrix (3.3 V rail from 3.0 V to 0 V in 0.3 V steps; durations 1 ms to 10 s; 10 repetitions each): after every event the device answers a valid FC04 within 1 s of rail recovery with register contents equal to the defined post-reset state; zero hung/silent/garbage outcomes across the matrix. |
| FR-S23 | Must | Measurement input registers (30001–30005, 30012) shall be initialised to 0 at reset and shall read 0 until the first measurement window completes (status bit 0, FR-S33). From the first completed window until the averaging accumulator has filled once (status bit 1, FR-S33), averaged registers 30003/30004 shall be computed over only the samples actually acquired since reset — partial-window mean, no zero-padding and no stale seeding. | Apply a steady stimulus equivalent to 5.0 m/s from before power-on with window 1 s / averaging 10 s: every FC04 response before the first window boundary reads 0 in all measurement registers; at t = 3 s register 30004 reads 50 ±2 LSB, not ~15 (the zero-padded value). With 40003 = 600, reads at t = 30 s already reflect the stimulus. Over 20 power cycles no measurement register ever exceeds 60 (6.0 m/s) for the 5.0 m/s stimulus. |
| FR-S24 | Must | All register values returned in a single FC03/FC04 response shall form a coherent snapshot from one measurement update (interrupts briefly masked during the copy, or a double-buffer/sequence-counter scheme). In particular, on the speed build, 30002 and 30005 in the same response shall be consistent: 30002 equals the FR-S06 formula applied to that response's 30005, or 0 where the FR-S07 cut-off applies — never a mixture of two windows. | Drive PC1 with a pulse source alternating between two distinct rates synchronised to window boundaries; poll FC04 for 30001–30005 back-to-back for ≥1 hour (≥50,000 responses): the 30002/30005 consistency rule holds in 100% of responses and no response mixes values from two windows. |

*Interface assumption (non-normative): configuration persists across reset (FR-S39), so a master need not re-apply site configuration after a restart; 30008 (FR-S34) remains available to detect restarts.*

### 3.3 Wind speed measurement (speed build)

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S04 | Must | Wind speed shall be measured by counting rising edges of the anemometer reed-relay signal on PC1 using TIM2 in ETR external-clock counter mode. | Observed via 30005 (FR-S08): drive PC1 with a 50% duty square wave of f Hz for one window of W ms: 30005 reads round(f × W / 1000) ±1 — one count per cycle, proving a single edge polarity is counted (counting both edges would read double). |
| FR-S05 | Must | The measurement window duration shall be configurable via holding register 40002. Default per §2.8. | At a fixed pulse rate f: with 40002 = 500, 30005 reads round(f × 0.5) ±1; with 40002 = 2000, 30005 reads round(f × 2) ±1 (write take-effect semantics per FR-S30). At power-on the window is 1000 ms (§2.8 Default column). |
| FR-S06 | Must | Wind speed shall be computed in the millisecond domain as `v[0.1 m/s] = (count × C_scaled × 10) / (window_ms × pulses_per_rotation)`, where C_scaled is the calibration factor in units of 0.001 m/rotation (40005, FR-S25/FR-S40), pulses_per_rotation is the anemometer's pulses per revolution (40006, FR-S40, ≥ 1 so no divide-by-zero), and window_ms is the duration of the window in which the pulses were counted (the value 40002 had when that window opened). Results exceeding 65535 shall be clamped to 65535. | With 40003 = 10000 ms, 40006 = 1 and a pulse generator at known frequency f: 30002 equals round(f × C × 10) within ±(one pulse-count quantum for the window + 1 LSB) — i.e. ±2 LSB at a 10 s window. With C_scaled = 980, 40006 = 1, 40003 = 500 and a 10 Hz input: 30002 reads 98 ±2 LSB. Setting 40006 = 4 at the same input quarters the reading to 24–25 (no truncation loss — pulses_per_rotation divides the result, not the count). |
| FR-S07 | Must | When the computed wind speed is below the low-speed cut-off threshold (holding register 40004, default per §2.8), input register 30002 shall report 0. | At zero pulse count, 30002 reads 0. At pulse rates corresponding to speeds below the cut-off, 30002 reads 0. Above the cut-off, it reports the calculated value. |
| FR-S08 | Should | The raw pulse count for the last measurement window shall be available in input register 30005 for diagnostic purposes (speed build; see §2.7 for the direction build's use of this register). | Apply f Hz for one window of W ms: FC04 read of 30005 returns round(f × W / 1000) ±1. |
| FR-S25 | Must | The calibration factor C shall have a compile-time default set via a pre-processor define (integer fixed-point, 0.001 m/rotation, valid default range 1–6553 enforced by a static build-time assert, default 980 = r 0.07 m / η 0.45), documented in the source tree. That default seeds holding register 40005 (FR-S40); the running value is 40005, runtime-writable and persisted (FR-S39), so one firmware image calibrates any anemometer with no rebuild. | The compile-time default with `-D WS_C_SCALED=0` or `6554` fails to compile. On a running device, writing 40005 changes 30002 proportionally: at a fixed pulse rate, 40005 = 980 then 1100 give 30002 in the ratio 980:1100 ±1 LSB, and the new value survives a reset (FR-S39). |
| FR-S26 | Must | The wind-speed computation shall be evaluated in integer arithmetic with no intermediate overflow over the full input domain: count 0–65535, window 100–60000 ms, C_scaled 1–6553 (FR-S25). The maximum intermediate, 65535 × 6553 × 10 = 4,294,508,550, fits an unsigned 32-bit integer. | Unit-test the scaling function at the corners: (count = 65535, C_scaled = 6553, window = 100 ms) → 65535 (clamped per FR-S06), not a wrapped value; (count = 65535, C_scaled = 980, window = 60000 ms) → exactly 10704, computed through a >2²⁹ intermediate without wrap. (No corner with C_scaled = 6553 produces an unclamped result within the legal window range — unclamped requires window ≥ 65539 ms.) |
| FR-S27 | Should | If a TIM2 update (overflow) event occurs during a measurement window, the pulse count for that window shall saturate at 65535; register 30005 shall report 65535 and register 30002 shall report the speed computed from the saturated count per FR-S06 — never values derived from a modulo-65536 wrapped count. | Precondition: write 40003 = 60, then 40002 = 60000 (FR-S31 constraint). Inject a 2 kHz square wave downstream of the debounce RC for one full window (120,000 edges): 30005 reads 65535, not 54464. |

*Note (hardware, non-normative): the calibration derivation in §4.7 assumes 1 pulse per rotation; anemometers that emit a different number of pulses per revolution are handled at runtime via holding register 40006 (FR-S40, default 1), so no rebuild is required.*

### 3.4 Wind direction measurement (direction build)

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S09 | Must | Wind direction shall be measured by reading the potentiometer wiper voltage on PA2 using the ADC in 10-bit ratiometric mode referenced to VDD. No external reference shall be used. | Via input register 30005 (raw ADC diagnostic on the direction build, §2.7): wiper at each end stop reads ≤5 and ≥1018 respectively. |
| FR-S10 | Must | The ADC sample time shall be configured to ≥71 cycles to accommodate the 11 kΩ potentiometer source impedance. | Code review confirms the sample-time setting. Via 30005: 32 consecutive reads at a fixed mid position span ≤3 counts. |
| FR-S11 | Must | Wind direction shall be reported in input register 30001 in units of 0.1°, range 0–3599, where 0 = North, increasing clockwise (WMO convention), derived from the oversampled ADC value (FR-S28). Firmware accuracy — with the potentiometer replaced by a precision divider of ≤0.1% ratio accuracy — shall be ±10 LSB (±1.0°), covering quantization and INL. End-to-end accuracy including potentiometer linearity is a separate hardware/calibration item (target ±2°, §6). | At each of 5 known divider ratios, the reported value is within ±10 LSB of the expected angle; 100 reads over 60 s at a fixed ratio span ≤3 counts. |
| FR-S12 | Must | A calibration offset shall be applied to the reading before reporting. The offset shall be configurable via holding register 40001, in units of 0.1°, range 0–3599. | Writing offset value X to 40001: reported direction shifts by X × 0.1°, wrapping correctly at 360°/0°. |
| FR-S28 | Must | Each update of 30001 shall be derived from ≥16 ADC conversions (mean, or median with outlier rejection) at an update rate of ≥10 Hz, feeding the circular mean (FR-S14) at the same cadence. | Code review of the conversion scheme; the FR-S11 stability criterion (span ≤3 counts over 100 reads) passes. |
| FR-S29 | Must | The reported direction shall always lie in 0–3599 — with the sole exception of the FR-S38 fault value 65535; the value 3600 shall never be emitted at the wrap. | A full 360° sweep at 10 Hz logging produces no reading in 3600–65534; crossing the wrap shows a single step between high (359x) and low (000x) values. |
| FR-S38 | Must | A floating wiper (detectable by toggling the internal pull resistor on PA2 between two conversions and comparing readings) shall cause 30001 to hold the last valid direction for up to 2 s; if the condition persists >2 s, registers 30001 and 30003 shall report 65535 (sensor fault, §2.7) and status bit 2 (FR-S33) shall be set until valid readings resume. Floating-input samples shall be excluded from the circular mean. | Disconnecting the wiper at the RJ14 yields 65535 in both registers and status bit 2 within 3 s; recovery within 2 s of reconnection. Rotating slowly through any potentiometer dead zone shows the last valid value held, then a single step across the wrap. A 10-minute continuous-rotation sweep produces no false fault. |

### 3.5 Averaging

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S13 | Must | Averaged wind speed shall be reported in input register 30004 as the arithmetic mean of the measurement-window results falling within the last N seconds (boxcar, not exponential; exact or two-stage per FR-S31), N = value of 40003. Default N = 10 s (§2.8). | At a steady generator pulse rate, after a step change register 30004 is within ±2 LSB of register 30002's steady value no later than one averaging window plus one measurement window after the step (plus one aggregation block where FR-S31's two-stage boxcar is active, N > 64), and remains within ±2 LSB thereafter. |
| FR-S14 | Must | Averaged wind direction shall be reported in input register 30003 using a circular mean (sine/cosine method) over the same boxcar window (exact or two-stage per FR-S31), to correctly handle the 0°/360° wrap-around. | With the input alternating between 3500 (350.0°) and 100 (10.0°) at equal dwell, register 30003 reports a value in [3590–3599] ∪ [0–10] (0.0° ± 1.0°) after one full averaging window, and never reports a value in [1700–1900] (the 180° failure mode of a naive linear mean). |
| FR-S15 | — | **Withdrawn (v0.4).** Range enforcement for the averaging window (40003) is covered by FR-MB19/FR-MB22 against §2.8 (Must); a Should-priority duplicate made the same behaviour simultaneously waivable and mandatory. | Boundary test retained under FR-MB19: write 0 and 601 to 40003 → exception 03, register unchanged; write 1 and 600 → accepted (600 subject to FR-S31 given 40002). |
| FR-S30 | Must | A valid write to 40002 shall abort the in-progress measurement window; the partial count shall be discarded (not published to 30002/30005) and a new window of the new duration shall start immediately. A valid write to 40002 or 40003 shall clear the averaging accumulator; 30003/30004 shall retain their last published values until the first new window completes, then follow the partial-window-mean rule (FR-S23). Status bits 0 and 1 (FR-S33) shall re-assert accordingly: bit 0 until the restarted window completes, bit 1 until the cleared accumulator refills. | At a constant pulse rate, write 40002 = 5000 mid-window: the next change of 30005 occurs no sooner than 5000 ms after the write and corresponds to a full 5000 ms window ±2% (FR-S17); status bit 0 is set from the write until that window completes. Write 40003 = 5 mid-average: bit 1 sets, 30004 never publishes a value outside the interval between its pre-write value and 30002, and reads 30002 ±1 LSB within 5 s, after which bit 1 clears. |
| FR-S31 | Must | The firmware shall enforce (40003 × 1000) ≥ 40002 at all times: any FC06/FC16 write violating this shall be rejected with exception 03 and leave the register(s) unchanged (respecting FR-MB22 atomicity). This row is the single normative source of the constraint. The average shall span N = floor((40003 × 1000) / 40002) completed windows (N ≥ 1). For N ≤ 64 the boxcar shall be exact; for N > 64 a two-stage boxcar is permitted: consecutive windows aggregated into blocks of ⌈N/64⌉ windows (block mean for speed, block sine/cosine sums for direction, block maximum for gust), the published value computed over the stored blocks, with an effective span within ±one block of N windows. This bounds storage at ≤64 entries per quantity, satisfiable at the worst-case ratio N = 6000 within NFR-RES01's RAM ceiling. | Precondition for the first vector: write 40003 = 60, then 40002 = 60000. FC06 write 40003 = 30 then returns exception 03 and 40003 is unchanged; write 40003 = 60 is accepted. With 40002 = 100 and 40003 = 600 at a steady pulse rate, the device meets FR-MB20 timing for ≥10 minutes and 30004 settles to 30002 ±1 LSB. |

### 3.6 Clock and timing

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S16 | Must | The firmware shall operate from the CH32V003 internal 48 MHz RC oscillator (HSI). No external crystal is required. | With no external crystal fitted: 10,000 Modbus request/response cycles at 9600 baud complete with zero framing/CRC errors, and the FR-S17 room-temperature window-timing criterion passes. |
| FR-S17 | Must | The measurement window timing error shall not exceed ±2% relative to the configured window duration at 25 ±10 °C, and ±3% over the full NFR-ENV01 temperature range (HSI drift dominates outside room temperature). | Window measured with an external timer: error ≤ ±2% over 10 consecutive windows at room temperature; ≤ ±3% at the NFR-ENV01 chamber extremes. |

### 3.7 Diagnostics and identification

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| FR-S32 | Must | Input register 30007 shall identify the device: high byte = build type (0x01 wind speed, 0x02 wind direction, 0x03 combined), fixed at compile time, independent of PC4; low byte = firmware version, incremented per release. | FC04 read returns 0x01vv on a wind-speed binary, 0x02vv on a wind-direction binary, and 0x03vv on a combined binary built from the same source commit. The value is identical with jumper open/bridged. The version byte matches the release records for the flashed binary. |
| FR-S33 | Must | Input register 30006 shall report status flags — this row is the single normative bitfield definition: bit 0 = no completed measurement window since reset or since the last 40002 write (FR-S23/FR-S30); bit 1 = averaging accumulator not yet filled since reset or since the last 40002/40003 write (FR-S23/FR-S30); bit 2 = direction sensor fault (FR-S38; direction build only, always 0 on the speed build); bits 3–15 = 0. | At power-on bits 0 and 1 are set; bit 0 clears after the first window, bit 1 after one full averaging window; both re-assert after a 40002 write per FR-S30's criterion. Direction build: wiper disconnect sets bit 2 (FR-S38). Speed build: bit 2 remains 0 throughout. |
| FR-S34 | Must | Input register 30008 shall report whole seconds since the last reset, starting at 0 and saturating at 65535, allowing the master to detect restarts (value went backwards) and re-apply configuration (FR-S21). | A read shortly after power-on returns a low value; a later read has incremented consistently with FR-S17 timing accuracy; a watchdog reset via the test hook returns the register to 0. |
| FR-S35 | Should | Input registers 30009 and 30010 shall count, respectively, every frame discarded for invalid CRC-16 (regardless of address) and every request for which a normal or exception response was transmitted. Both reset to 0 at power-on and wrap at 65535. | After a power cycle both read 0. 100 valid FC04 requests increment 30010 by exactly 100 and leave 30009 unchanged. 20 corrupted-CRC frames increment 30009 by exactly 20 and 30010 by 0. |
| FR-S36 | Should | Input register 30011 (speed build) shall report elapsed whole seconds since the last rising edge on PC1 — initialised to 0 at reset and counting up until the first pulse — clamped at 65535 and reset to 0 on each pulse. Documented limitation: an open sensor wire, a stuck reed relay, and true calm are electrically indistinguishable (10 kΩ pull-up on PC1) — 30002 = 0 does not distinguish calm from a disconnected sensor; 30011 gives the master plausibility-check data. | Halt the pulse input: the register increments 1/s (±2%). Apply a single pulse: the next read returns ≤1. |
| FR-S37 | Should | Input register 30012 (speed build) shall report the maximum single-window instantaneous wind speed (0.1 m/s) observed within the current averaging window (rolling maximum, same window semantics as 30004; exact or two-stage per FR-S31). | Base pulse rate equivalent to 2.0 m/s with one 3 s burst equivalent to 8.0 m/s: within one measurement window of the burst the register reads 80 ±2 LSB while 30004 stays below 40; one full averaging window after the burst exits, it returns to 20 ±2 LSB. |

---

## 4. Hardware (as-built)

This section captures the interface board as built in the KiCad design
(`hardware/KiCad/windmeter-modbus-interface.kicad_{sch,pcb}`, KiCad 9;
schematic title block dated 2026-06-28), superseding the hardware notes in
`design/scratchBook.md`. The pin/net assignments in §4.2 are **normative** —
the firmware in §2/§3 targets them (FR-S03/S04/S09/S18, FR-MB04/FR-MB23);
component reference designators and values are as-built reference. One
unmodified 2-layer PCB serves all three build variants (FR-S02).

### 4.1 Architecture

A CH32V003J4M6 (U1) drives a MAX3485 (U2) RS-485 transceiver. Power is 24 V
passive PoE on the Ethernet spare pairs → a DB207 polarity-protection bridge
(B1) → an HLK-K7803-500R3 3.3 V regulator (P1). The bus is brought out on two
RJ45 jacks (J1, J3) for daisy-chaining; the two sensors connect on separate
RJ14 jacks (J4 anemometer, J5 wind-direction); a 3-pin header (J2) exposes
SWIO for the WCH-LinkE programmer. Termination, RS-485 pair selection, and
address selection are solder jumpers on the bottom side. Board: 2-layer,
1.6 mm, ≈ 67 × 92 mm, four Ø3.2 mm corner mounting holes.

### 4.2 MCU pin assignment (normative)

CH32V003J4M6, JEITA SOIC-8. The SOP-8 bonds out only six GPIO, and no USART1
remap places TX and RX on separate pins simultaneously — hence the
remap-switching data discipline on PD6 (FR-MB23), not HDSEL.

| Pin | Port | Net | Function | Firmware |
|-----|------|-----|----------|----------|
| 1 | PD6 | `MB-TX/RX` | Modbus data — USART1 RX native, TX remapped in for the response; to MAX3485 RO+DI | FR-MB23, FR-S19 |
| 2 | VSS | `GND` | Ground | — |
| 3 | PA2 | `ANALOG_IN` | Wind-direction ADC input (ch0, ratiometric); from J5 wiper | FR-S09/S10/S11 |
| 4 | VDD | `3V3` | +3.3 V supply | — |
| 5 | PC1 | `PULSE_IN` | Anemometer pulse — TIM2 ETR external-clock counter; from J4 via debounce network | FR-S04 |
| 6 | PC2 | `MB-RE/DE` | RS-485 driver enable (DE/RE) — to MAX3485; 10 k pull-down (R7) | FR-MB04, FR-S18 |
| 7 | PC4 | `ADDRESS` | Address-select jumper — 10 k pull-up (R4) + JP6 to GND | FR-S03 |
| 8 | PD1 | `SWIO` | Single-wire debug/flash — to J2; reserved, not used for I/O | — |

### 4.3 RS-485 interface

MAX3485 (U2), powered from 3.3 V.

- **Data**: RO and DI tied on net `MB-TX/RX` → PD6. RO is high-Z while DE is
  asserted, so the shared node is contention-free during transmit and needs
  no pull-up — the fail-safe idle level is set on the A/B bias, not the logic
  node.
- **Enable**: DE and RE tied on net `MB-RE/DE` → PC2, with a 10 kΩ pull-down
  (R7) holding the transceiver in receive while the MCU is in reset or being
  flashed.
- **Bus**: differential pair `RS485-A` / `RS485-B`, on both RJ45 jacks; the
  A/B-to-contact pairing is solder-jumper selectable (JP2/JP3 for J1,
  JP4/JP5 for J3).
- **Fail-safe bias**: R3 20 kΩ pulls A → 3.3 V, R2 20 kΩ pulls B → GND
  (idle = mark).
- **Termination**: R1 120 Ω across A–B, enabled by solder jumper JP1 (open by
  default).
- **Protection**: D1 SM712 TVS across A/B/GND.

### 4.4 Power supply

- **Input**: 24 V passive PoE on the Ethernet spare pairs — RJ45 pins 4 & 5 =
  +24 V, pins 7 & 8 = return — on both J1 and J3, so power passes down the
  daisy chain.
- **Polarity protection**: B1 DB207 bridge (used for reverse-polarity
  protection, not AC rectification) → regulator input; return = GND.
- **Regulator**: P1 HLK-K7803-500R3 (SIP-3, 3.3 V / 500 mA).
- **Filtering**: C3 100 µF electrolytic bulk on the regulator input; C4 4.7 µF
  electrolytic plus C1/C2 100 nF ceramic on the 3.3 V output. No inductor/LC
  filter is fitted.

### 4.5 Sensor front-ends

**Anemometer** (pulse) → PC1, via RJ14 **J4** (pin 1 = 3.3 V, pin 2 = pulse,
pin 3 = GND):

- Pulse path J4 pin 2 → R6 100 Ω series → `PULSE_IN`. On that node: R5 10 kΩ
  pull-up to 3.3 V (also the debounce pull-up — the reed relay pulls the node
  to GND when closed), C5 100 nF to GND (debounce, τ ≈ 1 ms), and D2 zener to
  GND (over-voltage clamp).
- The 10 kΩ pull-up is why an open sensor wire, a stuck-closed relay, and true
  calm are electrically indistinguishable (FR-S36).

**Wind direction** (potentiometer) → PA2, via RJ14 **J5** (pin 1 = 3.3 V,
pin 3 = GND, pin 4 = wiper):

- The potentiometer is in the sensor, not on the PCB, and is fed ratiometrically
  from the 3.3 V rail; the wiper drives `ANALOG_IN` → PA2 directly. The ADC is
  10-bit ratiometric to VDD with no external reference (FR-S09) and a 73-cycle
  sample time for the source impedance (FR-S10). There is no on-board RC filter
  on `ANALOG_IN` — ratiometric operation cancels rail ripple, and an external
  reference would break that cancellation.

### 4.6 Connectors

| Ref | Type | Purpose | Key pins |
|-----|------|---------|----------|
| J1, J3 | RJ45 (TE 215877-1) | Modbus daisy-chain | A/B on the signal contacts (jumper-paired); +24 V on 4 & 5, return on 7 & 8 |
| J4 | RJ14 (6P4C) | Anemometer | 1 = 3.3 V, 2 = pulse, 3 = GND |
| J5 | RJ14 (6P4C) | Wind direction | 1 = 3.3 V, 3 = GND, 4 = wiper |
| J2 | 1×3 header | Programming | GND / SWIO / 3.3 V |

Solder jumpers: JP1 termination; JP2–JP5 RS-485 pair select; JP6 address
select (all bottom-side).

### 4.7 Anemometer calibration derivation (C)

The calibration factor C (metres per rotation) converts pulse rate to wind
speed (FR-S06). It follows from cup-anemometer geometry:

C = 2πr / η

where r is the arm length from shaft centre to cup-body centre and η ≈ 0.45 is
the empirical efficiency of a small three-cup rotor (textbook 0.5; 0.40–0.50
across typical designs). For the reference sensor (r = 0.07 m, η = 0.45),
C ≈ 0.98 m/rotation → the compile-time default 980 (units of 0.001 m/rotation,
FR-S25). The η assumption carries ±10–12 % uncertainty versus a wind-tunnel
figure; where that matters, C is obtained empirically — hold the anemometer
beside a reference in the same airflow and solve C = v_reference /
pulses_per_second.

The compile-time default only **seeds** the running value: C lives in holding
register 40005 and the pulses-per-rotation divisor in 40006, both
runtime-writable and persisted (FR-S40/FR-S39), so one firmware image
calibrates any anemometer with no rebuild. The geometry above assumes one
pulse per rotation; other pulse counts are set in 40006 (default 1).

### 4.8 As-built notes and deviations

Captured from the KiCad design; where the as-built board differs from the
earlier `scratchBook.md` notes, the board governs:

- **Fail-safe bias designators** are the reverse of the notes (as-built: R3 →
  A/3.3 V, R2 → B/GND); the bias function is identical.
- **Power filtering** is C3 100 µF (input) + C4 4.7 µF (output) + 2 × 100 nF,
  not the notes' 10 µF/22 µF split; the 100 µF is the input bulk.
- **Two RJ14 sensor jacks** (J4 anemometer, J5 direction), not one; the
  anemometer enters on a jack, not a screw terminal.
- **No RC filter** on the wind-direction ADC input (the notes' 100 Ω + 10 µF is
  not fitted) — see §4.5.
- **D2 zener** is generic (`BZX84Cxx`) in the KiCad — pin the clamp voltage
  (nominally 3.3 V, BZX84-C3V3) on the manufacturing BOM.
- **Capacitor voltage ratings** are not carried in the KiCad Value fields;
  confirm on the BOM.
- The schematic title block reads "RS458" (typo for RS485) — cosmetic, fix on
  the next PCB revision.

---

## 5. Non-functional requirements

| ID | Priority | Requirement | Pass/Fail criterion |
|----|----------|-------------|---------------------|
| NFR-ENV01 | Must | All §2 and §3 requirements shall be met over an ambient temperature range of −25 °C to +70 °C. *(Range to be confirmed against the deployment site — §6; −40/+85 °C would require re-budgeting FR-S17.)* | In a climate chamber at both extremes: (a) 10,000 FC04 cycles at 9600 8N1 complete with zero framing/CRC errors; (b) the FR-S17 window measurement passes at its full-range tolerance. |
| NFR-RES01 | Should | Each release build variant shall occupy no more than 14,336 bytes of flash (87.5% of 16 KB); static RAM (.data + .bss) plus documented worst-case stack shall not exceed 1,792 bytes (87.5% of 2 KB). | The linker map of each release build shows totals at or below the ceilings; the build script prints the numbers and fails the build when exceeded. |
| NFR-BLD01 | Should | Both variants shall build from a clean checkout with a single documented command using a pinned toolchain (compiler name and exact version recorded in the repository). Two consecutive clean builds of the same commit shall produce bit-identical binaries. | Run the documented command twice from fresh clones of the same commit: SHA-256 of the two binaries per variant are identical; the recorded toolchain version matches the installed one. |
| NFR-TST01 | Should | Every protocol-level pass/fail criterion in §2 that is executable over the serial link shall be implemented as an automated test case in `windmeters-modbus-interface-tester`, and each build variant shall pass 100% of these cases before any release is tagged. Excepted (verified manually per release with bench instruments): FR-MB01 (analyser decode), FR-MB04 (scope timing), FR-MB23 (bus capture). Withdrawn IDs (FR-MB16, FR-MB26) are excluded. | The tester's run report for the release commit lists every non-excepted, active FR-MB ID with result PASS for each variant; any FAIL or missing ID blocks the release. |

---

## 6. Open items

Resolved items are kept briefly for traceability; only the residual work is
still open.

- **Response latency (FR-MB20/21) — CLOSED.** Measured with the real register
  code: median/worst 5.2 ms on the TTL rig, and 1000/1000 through the MAX3485
  at 4.07/4.12/4.17/4.44 ms (min/med/p99/max) — far under the 15 ms typical /
  100 ms hard budgets. The tester's 200 ms / 1-retry default keeps ample
  margin. (`software/hil/testReport.md`, P3-MB-LATENCY / R485-LAT-10D.)

- **NFR-ENV01 temperature range — NARROWED.** The assumed −25…+70 °C is
  covered by the as-built parts (CH32V003, MAX3485, HLK-K7803-500R3, DB207 are
  industrial-grade, typically rated to at least −40…+85 °C). Residual: confirm
  the electrolytic capacitors' temperature grade on the BOM (§4.8), confirm
  the range against the deployment site, and — only if −40/+85 °C is required
  — re-budget FR-S17 for HSI drift with chamber characterisation.

- **End-to-end direction accuracy — firmware CLOSED, sensor residual.** FR-S11
  firmware accuracy (±1.0°) is verified (−3.8 LSB against a precision
  divider). The total including the vane potentiometer's mechanical linearity
  (target ±2°) remains a sensor property, confirmed per installed vane. The C
  derivation has graduated into §4.7. Note: the as-built ADC input has no RC
  filter (§4.5) — the ratiometric supply and 73-cycle sample time carry the
  FR-S11 stability (verified span ≤ 3 counts); an RC filter is a future
  hardware option only if supply ripple ever proves limiting.

- **Hardware & calibration promotion — DONE.** The pin/net map, RS-485
  front-end, power chain, sensor front-ends, connectors, and the C derivation
  are now in §4 (as-built from the KiCad PCB). `scratchBook.md` is retained as
  historical reasoning.

- **Volatile-register coherence — CLOSED.** The 2026-07-03 review asked what a
  writable register is worth when its value evaporates on reset. The distilled
  rule — *operational knobs with universally valid defaults may be volatile;
  installation constants (offset), sensor constants (C, cut-off), and device
  identity (address) belong in hardware, compile-time defaults, or persistent
  storage* — was satisfied by making all six holding registers persistent
  (FR-S39, decision 2026-07-08) and the address hardware-only (v0.6). §2.8
  defaults now apply only on first boot / erased store.

- **Combined variant — SHIPPED; one strategic question open.** `wind_combined`
  (build 0x03, address 32/37) is implemented and validated
  (`design/integrationPlan.md` §10; 77/77 over RS-485 plus the raw suite and
  FR-S38). Undecided: whether the combined build eventually *replaces* the two
  single-sensor variants (its fault machinery already handles an absent
  sensor) — a product decision, not taken here.

- **Hardware BOM follow-ups (§4.8).** Pin the D2 zener clamp voltage
  (nominally BZX84-C3V3) and the capacitor voltage/temperature grades on the
  manufacturing BOM; fix the "RS458" schematic-title typo on the next PCB
  revision.

---

*End of Technical Design Specification v0.9 (2026-07-12: §4 as-built hardware
promoted from the KiCad PCB, §6 open items closed/narrowed; v0.8 FR-S40
calibration; v0.7 FR-S39 persistence + combined variant).*
