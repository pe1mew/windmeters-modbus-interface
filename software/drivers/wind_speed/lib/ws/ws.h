/**
 * @file ws.h
 * @brief Wind-speed pulse-counting driver — hardware edge counter on PC1.
 *
 * Counts anemometer pulses entirely in hardware: TIM2 runs as an external-clock
 * counter (ETR external clock mode 2) with its timer input remapped to PC1 via
 * AFIO partial remap 2 — the only TIM2 remap that reaches PC1 on the SOP-8
 * CH32V003 package (CH32V003 RM AFIO_PCFR1[9:8]). Rising edges increment the
 * 16-bit counter with zero CPU overhead and no per-pulse interrupt (TDS
 * FR-S04), so pulse trains well above any anemometer's real rate are captured
 * without loss.
 *
 * This driver only counts; it does not pace the measurement window. Opening a
 * window (@ref ws_window_start), timing it, and reading it back
 * (@ref ws_window_read) is the caller's job — the measurement service owns the
 * window cadence (holding register 40002). See `design/softwareArchitecture.md`
 * and `design/driverDevelopment.md` §3.1.
 *
 * @note Single-instance driver: it owns TIM2 and PC1 outright — there is no
 *       handle and no support for a second speed channel.
 */
#ifndef WS_H
#define WS_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief Bring up the pulse counter: TIM2 ETR on PC1, counter running.
 *
 * Enables the GPIOC/AFIO/TIM2 clocks, applies AFIO partial remap 2 to route
 * TIM2_ETR to PC1, drives PC1 as an input with the internal pull-up (an open
 * input then idles high and counts nothing; the product additionally has an
 * external 10k pull-up, while the M2K HIL rig drives push-pull), programs the
 * counter to its full 16-bit range, selects external clock mode 2 (count ETR
 * rising edges), and starts the counter.
 *
 * @note Call once at start-up, before the first @ref ws_window_start. The
 *       counter free-runs from here; window boundaries are established solely
 *       by @ref ws_window_start / @ref ws_window_read.
 */
void ws_init(void);

/**
 * @brief Open a counting window: zero the counter, clear the overflow flag.
 *
 * Resets the counter to 0 and clears the update/overflow (UIF) flag so a
 * subsequent @ref ws_window_read reflects only pulses that arrive after this
 * call.
 *
 * @note The caller times the window; this driver imposes no duration.
 * @see ws_window_read
 */
void ws_window_start(void);

/**
 * @brief Read the pulse count accumulated since @ref ws_window_start.
 *
 * @param saturated Optional out-parameter (may be NULL): set @c true when the
 *                  16-bit counter overflowed during the window, @c false
 *                  otherwise.
 * @return Pulse count since the last @ref ws_window_start. If the counter
 *         overflowed past 65535 during the window it returns 65535 saturated —
 *         never a wrapped (aliased-low) value — per TDS FR-S27.
 * @note Non-destructive: reading does not reset the counter; call
 *       @ref ws_window_start to begin the next window.
 * @warning A saturated result means the true count was at least 65536 and the
 *          exact value is unrecoverable. Size the measurement window so this
 *          cannot occur at the anemometer's maximum rated pulse rate.
 */
uint16_t ws_window_read(bool *saturated);

#endif /* WS_H */
