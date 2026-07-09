/**
 * @file circmean.h
 * @brief Circular (vector) mean of wind-direction angles — TDS FR-S14.
 *
 * Averages wind-direction angles held in 0.1° units (0–3599) by the
 * sine/cosine method: accumulate each sample's unit vector, then take the
 * argument of the resultant. This avoids the wrap-around error a scalar mean
 * makes near north — e.g. 3599 and 0001 must average to 0000, not ~1800.
 *
 * Everything is fixed-point and multiply-free for the RV32EC core, which has
 * no hardware multiply: sines come from a Q15 quarter-wave lookup
 * (@ref circmean_sin_q15) and the resultant's angle from a 16-iteration
 * integer CORDIC atan2 (@ref circmean_atan2_001deg).
 *
 * The generated table and the golden algorithm reference live in gen_table.py;
 * test_circmean.py exhaustively cross-checks this code against it on the host.
 * circmean.c mirrors that reference line-for-line, and the drivers additionally
 * replay boot-time self-test vectors on target (design/driverDevelopment.md
 * §4.1). Results feed the direction measurement/averaging path — accumulate
 * with @ref circmean_add and read back with @ref circmean_get; the register
 * map (@ref regs.h) is the downstream consumer.
 */
#ifndef CIRCMEAN_H
#define CIRCMEAN_H

#include <stdint.h>

/**
 * @brief Running circular-mean accumulator for one direction window.
 *
 * Holds the summed unit-vector components of every sample added since the
 * last @ref circmean_reset, plus the sample count. Query the resultant with
 * @ref circmean_get without disturbing the sums. Zero-initialise via
 * @ref circmean_reset before first use.
 */
typedef struct {
	int32_t sum_sin;   /**< Σ sin over the samples, Q15; headroom for >64k samples. */
	int32_t sum_cos;   /**< Σ cos over the samples, Q15; headroom for >64k samples. */
	uint16_t n;        /**< Samples accumulated since @ref circmean_reset. */
} circmean_t;

/**
 * @brief Clear an accumulator to the empty state.
 * @param cm Accumulator to reset; both running sums and the sample count go
 *           to 0. Must be called before the first @ref circmean_add.
 */
void circmean_reset(circmean_t *cm);

/**
 * @brief Accumulate one direction sample into the running mean.
 *
 * Adds the sample's Q15 sine and cosine to the accumulator and increments the
 * count. The cosine is taken from the same quarter-wave table by looking up
 * the angle advanced 90° (+900 in 0.1° units, modulo 3600), so no separate
 * cosine table is needed.
 *
 * @param cm           Accumulator to update.
 * @param angle_0_1deg Sample angle in 0.1° units, 0–3599.
 */
void circmean_add(circmean_t *cm, uint16_t angle_0_1deg);

/**
 * @brief Resultant circular mean of everything accumulated so far.
 *
 * Evaluates atan2(sum_sin, sum_cos) and rounds it from 0.001° down to 0.1°
 * units. The accumulator is not modified, so it may be queried mid-window.
 *
 * @param cm Accumulator to evaluate.
 * @return Mean direction in 0.1° units, 0–3599; @c 65535 when no samples have
 *         been added (@c n == 0) — the same empty/fault sentinel the register
 *         map uses (FR-S38).
 */
uint16_t circmean_get(const circmean_t *cm);

/**
 * @brief Q15 sine of an angle, from the quarter-wave lookup table.
 *
 * Multiply-free: reduces the angle into the first quadrant, indexes the
 * 0–90° Q15 table, then applies the sign/mirror for the other three quadrants.
 *
 * @param angle_0_1deg Angle in 0.1° units, 0–3599.
 * @return sin(angle) in Q15 fixed-point (−32767…32767 ≈ −1.0…+1.0).
 * @note Public only so the on-target self-tests (driverDevelopment.md §4.1)
 *       can exercise it directly.
 */
int16_t circmean_sin_q15(uint16_t angle_0_1deg);

/**
 * @brief Two-argument arctangent by 16-iteration integer CORDIC.
 *
 * Returns the polar angle of the vector (x, y); the argument order mirrors the
 * C library's @c atan2(y, x). Negative-x inputs are folded into the right
 * half-plane and rotated back by 180° afterwards, and oversized operands are
 * pre-scaled to keep the iterations in range.
 *
 * @param y Vertical component (e.g. sum_sin); may be any sign.
 * @param x Horizontal component (e.g. sum_cos); may be any sign.
 * @return Angle in 0.001° units, 0…359999. Returns 0 for the degenerate
 *         (0, 0) input.
 * @note Public only so the on-target self-tests (driverDevelopment.md §4.1)
 *       can exercise it directly.
 */
uint32_t circmean_atan2_001deg(int32_t y, int32_t x);

#endif
