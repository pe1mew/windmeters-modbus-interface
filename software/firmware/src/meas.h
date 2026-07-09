/**
 * @file meas.h
 * @brief Per-sensor measurement services — window pacing, scaling and faults.
 *
 * Integration stage D (`design/integrationPlan.md`). Each service is called on
 * every main-loop pass and is internally paced; it turns the raw sensor
 * front-ends (@ref sensors.h) into published measurement results by driving
 * the register image (@ref regs.h) and, through it, the averaging engine
 * (@ref avg.h).
 *
 * Speed service: measures over 40002-driven windows and applies FR-S06
 * scaling, the FR-S07 low-speed cut-off, FR-S27 saturation and FR-S30
 * window-abort semantics. Direction service: updates at 10 Hz (FR-S28, one
 * update every 100 ms) with the FR-S12 north offset applied and a sticky
 * FR-S38 wiper-float fault, and accumulates a per-window circular result
 * (FR-S13/S14) for the boxcar average.
 *
 * The API is deliberately a pair of per-sensor symbols rather than a single
 * meas_init/meas_service: the combined build compiles both blocks and must run
 * them concurrently, so one meas_init/meas_service pair linked twice would
 * collide on duplicate definitions (integrationPlan.md §10). Both services
 * share the 40002 window boundaries but keep independent window state, so a
 * one-loop-pass skew between them is harmless.
 *
 * @see regs.h, sensors.h, avg.h
 */
#ifndef MEAS_H
#define MEAS_H

#include "sensors.h"

#ifdef HAVE_WIND_SPEED
/**
 * @brief Initialise the wind-speed measurement service (speed / combined build).
 *
 * Latches the active measurement window from 40002 (@ref regs_window_ms),
 * converts it to SysTick ticks, starts a fresh pulse-count window in the
 * anemometer front-end (@ref ws.h) and records the window-start timestamp.
 * Call once after @ref regs_init so the persisted window is already in effect.
 */
void meas_speed_init(void);

/**
 * @brief Advance the speed window; publish a result when one closes.
 *
 * Call every main-loop pass — the SysTick deadline paces it internally. A
 * valid write to 40002 mid-window (FR-S30) aborts the window in progress: the
 * partial pulse count is discarded, a window of the new duration starts
 * immediately, and @ref regs_window_aborted holds status bit 0 until it
 * completes. Otherwise, once the window elapses its boundary is advanced by a
 * whole window so successive boundaries stay drift-free (FR-S17); the pulse
 * count and its saturation flag are read, a new window is started, and the
 * count together with the FR-S06/S07/S27-scaled 0.1 m/s speed are handed to
 * @ref regs_publish_speed.
 *
 * @note No result is published — and the previously published values persist —
 *       until the first full window closes (FR-S23).
 */
void meas_speed_service(void);
#endif
#ifdef HAVE_WIND_DIRECTION
/**
 * @brief Initialise the wind-direction measurement service (dir / combined build).
 *
 * Seeds the 10 Hz update timer, resets the 1 Hz float-check subsample counter,
 * clears the sticky wiper-float fault (FR-S38), latches the active window from
 * 40002 (@ref regs_window_ms) and clears the per-window circular sin/cos
 * accumulators. Call once after @ref regs_init.
 */
void meas_dir_init(void);

/**
 * @brief Advance the direction update/window cadence; publish results.
 *
 * Call every main-loop pass — both the 10 Hz update tick and the 40002 window
 * boundary are paced internally. A valid write to 40002 (FR-S30) aborts the
 * window in progress: the partial samples are discarded, the accumulator is
 * cleared and @ref regs_window_aborted holds status bit 0. On each 100 ms tick
 * (FR-S28) it reads the oversampled ADC (@ref wd.h), applies the FR-S12 north
 * offset, re-checks the wiper-float fault once per second (FR-S38) and pushes
 * the instantaneous angle via @ref regs_dir_update; non-fault samples are
 * folded into the window's circular sin/cos sums (FR-S38 excludes faults). At
 * each window boundary the mean sine/cosine (FR-S13/S14) are published through
 * @ref regs_publish_dir_window for the circular boxcar average.
 *
 * @note A window that accumulated no non-fault sample publishes nothing, so
 *       the last valid averaged direction is retained.
 */
void meas_dir_service(void);
#endif

#endif /* MEAS_H */
