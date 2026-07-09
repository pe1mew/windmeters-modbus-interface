/**
 * @file avg.h
 * @brief Boxcar averaging engine — mean speed, gust and circular-mean direction.
 *
 * Aggregates the stream of closed measurement windows into the averaged
 * register values the Modbus image publishes: mean speed (30004), peak gust
 * (30012) and circular-mean direction (30003). Built during integration
 * stage E (`design/integrationPlan.md`); fed by the measurement services
 * (@ref meas.h) and read out through the register image (@ref regs.h).
 *
 * Averaging span (FR-S13/S31): a full span is N = (40003 s × 1000) / 40002 ms
 * measurement windows. Storage is bounded to 64 slots, so for N ≤ 64 the
 * boxcar is exact (one window per slot), and for N > 64 windows aggregate
 * two-stage into blocks of ⌈N/64⌉ — slots hold the block mean for speed, the
 * block sine/cosine sums for direction, and the block max for gust (FR-S37).
 * The ring is sized to exactly the span, never the full 64-slot array, so
 * stale windows can never dilute the mean or pin the gust.
 *
 * Warm-up (FR-S23): every average is computed over only the windows acquired
 * since the last clear — no zero-padding — so the values are meaningful before
 * the span is full. @ref avg_filled reports span completion and feeds Modbus
 * status bit 1. A combined build runs two independent per-sensor rings that
 * advance from the same 40002 window boundaries but may close a window a loop
 * pass apart; the build guards (@ref sensors.h) select which are compiled in.
 */
#ifndef AVG_H
#define AVG_H

#include <stdbool.h>
#include <stdint.h>
#include "sensors.h"

/**
 * @brief Configure the averaging span and clear the accumulator.
 *
 * Computes the span N = (@p avg_s × 1000) / @p window_ms windows (FR-S13/S31),
 * picks the block size ⌈N/64⌉ so storage never exceeds 64 slots, and sizes the
 * ring to exactly N windows. Also resets every per-sensor ring and open-block
 * accumulator (FR-S30) so warm-up restarts. Configured by @ref regs_init and
 * re-run whenever 40002/40003 changes.
 *
 * @param window_ms Measurement window length in ms (holding 40002).
 * @param avg_s     Averaging window length in seconds (holding 40003).
 * @note Also clears the accumulator (FR-S30); status bit 1 (warm-up)
 *       consequently re-asserts until a fresh span is acquired.
 * @see avg_filled
 */
void avg_config(uint16_t window_ms, uint16_t avg_s);

/**
 * @brief Whether a full averaging span has been acquired since the last clear.
 * @return True once the accumulator holds a complete span. On a combined build
 *         BOTH rings must have seen the full N windows, so the bit clears only
 *         once genuinely warm.
 * @note Feeds Modbus status bit 1 (warm-up), per FR-S23.
 * @see avg_config
 */
bool avg_filled(void);

#ifdef HAVE_WIND_SPEED
/**
 * @brief Fold one closed window's instantaneous speed into the ring
 *        (speed build / combined build).
 * @param inst_0_1ms The window's scaled, cut-off-applied speed — register
 *                    30002 — in 0.1 m/s units. Accumulated into the open block;
 *                    when the block fills, its mean becomes the slot's stored
 *                    speed and its peak the slot's stored max.
 */
void avg_add_speed(uint16_t inst_0_1ms);

/**
 * @brief Boxcar-averaged wind speed — register 30004 — in 0.1 m/s.
 * @return Mean over only the windows acquired since the last clear: full slots
 *         weighted by the block size plus the open block, with no zero-padding
 *         (FR-S23). Reads 0 before the first window completes.
 */
uint16_t avg_speed(void);

/**
 * @brief Peak gust — register 30012 (FR-S37) — in 0.1 m/s.
 * @return The maximum single-window speed across the whole averaging span
 *         (every closed slot plus the open block).
 */
uint16_t avg_gust(void);
#endif

#ifdef HAVE_WIND_DIRECTION
/**
 * @brief Fold one closed window's circular direction result into the ring
 *        (direction build / combined build).
 *
 * The engine accumulates block sine/cosine sums separately and stores each
 * block's mean sin/cos in a slot (FR-S31 two-stage), preserving the vector
 * average across the span.
 *
 * @param sin_q15 Mean sine of the window's samples, Q15.
 * @param cos_q15 Mean cosine of the window's samples, Q15.
 */
void avg_add_dir(int16_t sin_q15, int16_t cos_q15);

/**
 * @brief Boxcar circular-mean wind direction — register 30003 — in 0.1°.
 * @return Weighted circular mean (atan2 of the block-weighted sin/cos sums,
 *         @ref circmean.h) in 0.1° units, range 0..3599; the 65535 sentinel
 *         while the accumulator is still empty (FR-S23).
 */
uint16_t avg_dir(void);
#endif

#endif
