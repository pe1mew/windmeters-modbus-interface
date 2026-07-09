/**
 * @file wd.h
 * @brief Wind-direction driver — ratiometric potentiometer angle sensing.
 *
 * Reads the direction pot's wiper on PA2 (ADC channel A0) as a 10-bit
 * conversion, ratiometric to VDD (no external reference), 16× oversampled
 * (TDS FR-S09/S10/S28), and maps the result to a 0.1°-resolution compass
 * angle. Consumed by the register image (@ref regs.h "regs_dir_update") on
 * the direction and combined builds.
 *
 * Two invariants shape the API. The angle map is constructed so that the
 * saturated value 3600 (== 360.0°) is never emitted (FR-S29): a raw sample
 * folds into 0..3599 with north-offset wrap. Separately, an open/floating
 * wiper is detectable by @ref wd_wiper_floating (FR-S38), which the register
 * layer turns into status bit 2 and the fault sentinel.
 *
 * @see regs.h  Register image that publishes angle, raw ADC and the float flag.
 */
#ifndef WD_H
#define WD_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Power up and self-calibrate the direction ADC (FR-S18).
 *
 * Enables the GPIOA and ADC1 clocks, puts PA2 in analog input mode, selects
 * channel 0 (A0) with a 73-cycle sample time (satisfies FR-S10's ≥71) and a
 * single-conversion sequence, then runs the ADC self-calibration (RSTCAL
 * followed by CAL) before the first conversion, per the FR-S18 init order.
 *
 * ADCCLK is set to HCLK/8 = 6 MHz. The conservative divider (rather than /2
 * at 24 MHz) avoids an end-of-range INL bow of ~+16 LSB near zero measured on
 * this part against a bench DMM; the cost is conversion time (~14 µs/conv,
 * ~224 µs per 16-sample burst), which stays far under the 100 ms update
 * budget.
 *
 * @note Call once at startup before @ref wd_read_raw16 or
 *       @ref wd_wiper_floating.
 */
void wd_init(void);

/**
 * @brief Take one 16× oversampled raw direction sample (FR-S09/S28).
 *
 * Runs 16 back-to-back conversions on channel A0 and returns their sum.
 * Blocking (~224 µs). The value is ratiometric to VDD — there is no absolute
 * voltage reference — so it is meaningful only as a fraction of full scale,
 * which is exactly how @ref wd_angle_0_1deg interprets it.
 *
 * @return Sum of 16 conversions, range 0..16368 (16 × 1023). Not divided
 *         down; the extra 4 bits of range are the oversampling gain.
 */
uint16_t wd_read_raw16(void);

/**
 * @brief Map a raw16 sample to a 0.1° compass angle with north offset applied.
 *
 * Scales the oversampled sum to tenths of a degree as
 * `(raw16 × 3600 + 8192) >> 14` (the +8192 is round-to-nearest over the 2^14
 * full scale), adds the caller's north offset, and folds the sum modulo 3600.
 * The scale maxes out at 3597 (raw16 = 16368), so 3600 is unreachable by
 * construction and, combined with the wrap, the result is always in 0..3599 —
 * the direction value is never 3600 (FR-S29).
 *
 * @param raw16         Oversampled sum from @ref wd_read_raw16 (0..16368).
 * @param offset_0_1deg North/zero calibration offset in 0.1° units, e.g. the
 *                      40001 holding register (@ref regs_offset_0_1deg).
 * @return Offset-applied angle in 0.1° units, 0..3599 (never 3600, FR-S29).
 */
uint16_t wd_angle_0_1deg(uint16_t raw16, uint16_t offset_0_1deg);

/**
 * @brief Detect an open/floating wiper by pull toggling (FR-S38).
 *
 * Momentarily switches PA2 to a pulled input, converts once with the internal
 * pull driven high and once with it driven low, then restores analog mode. A
 * connected low-impedance source (pot wiper ≤ ~3 kΩ, AWG source ~50 Ω) barely
 * moves between the two reads; a disconnected pin follows the pull rail-to-
 * rail, so a swing beyond 300 LSB flags a float.
 *
 * @return True if PA2 appears disconnected/floating; false when a source
 *         holds the node.
 * @warning Reconfigures PA2 (pull up/down, then back to analog) and performs
 *          two conversions with settling — do not interleave with
 *          @ref wd_read_raw16 on the same node. PA2 is left in analog mode on
 *          return.
 * @see regs_dir_update  Raises status bit 2 and forces the fault sentinel.
 */
bool wd_wiper_floating(void);

#endif /* WD_H */
