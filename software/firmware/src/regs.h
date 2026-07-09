/**
 * @file regs.h
 * @brief Modbus register image — the complete TDS §2.7/§2.8 map.
 *
 * Owns the device's holding and input registers and presents them to the
 * @ref mb.h "Modbus driver" via @ref regs_cfg(). Built during integration
 * stage C (`design/integrationPlan.md`).
 *
 * Per-build applicability (FR-MB27): raw addresses 0x0000–0x000B are mapped
 * on every build; registers of an absent sensor read 0; 0x0004 (30005) is
 * the build-specific raw diagnostic. The combined build additionally maps
 * 30013 (direction raw ADC). Instantaneous/averaged values (30001–30004,
 * 30012) read 0 until the first measurement window completes — their defined
 * pre-first-window value (FR-S23) — after which they are produced by the
 * measurement services (@ref meas.h) and averaging engine (@ref avg.h).
 *
 * The four holding registers persist across reset (@ref persist.h, FR-S39).
 */
#ifndef REGS_H
#define REGS_H

#include <stdbool.h>
#include <stdint.h>
#include "mb.h"
#include "sensors.h"

/**
 * @brief Initialise the register image and load persisted settings.
 *
 * Builds the @ref mb_config_t (holding table, input-read callback, FR-S31
 * cross-validate hook), seeds the four holding registers from non-volatile
 * storage (@ref persist_load; blank/corrupt store → §2.8 compile-time
 * defaults, FR-S21), and configures the averaging engine. Call after the
 * sensor front-ends and before @ref meas_speed_init / @ref meas_dir_init so
 * the measurement services latch the persisted measurement window.
 *
 * @param mb_address Latched Modbus slave address (FR-S03), from
 *                   @ref board_mb_address().
 */
void regs_init(uint8_t mb_address);

/**
 * @brief Modbus configuration for the driver.
 * @return Pointer to the internal @ref mb_config_t (holdings, input_read,
 *         FR-S31 cross-validate hook). Valid after @ref regs_init.
 */
const mb_config_t *regs_cfg(void);

/** @name Holding-register accessors (TDS §2.8, owned here) */
/** @{ */
uint16_t regs_offset_0_1deg(void); /**< 40001 north offset, 0.1° units. */
uint16_t regs_window_ms(void);     /**< 40002 measurement window, ms. */
uint16_t regs_avg_s(void);         /**< 40003 averaging window, s. */
uint16_t regs_cutoff_0_1ms(void);  /**< 40004 low-speed cut-off, 0.1 m/s. */
/** @} */

/**
 * @brief Per-loop register housekeeping.
 *
 * FR-S30: on a valid write to 40002/40003, clears the averaging accumulator
 * and re-asserts status bits 0/1. Call once per main-loop pass.
 */
void regs_service(void);

/**
 * @brief Persist a changed holding set to flash (FR-S39).
 *
 * No-op unless a holding register differs from the last-saved snapshot.
 * Blocking (~6 ms) when it writes — call from the main loop @b after the
 * Modbus response so the flash op stays out of the FR-MB20/21 latency path.
 * @see persist_save
 */
void regs_persist_service(void);

/**
 * @brief One-second tick: advance uptime (FR-S34) and pulse-age (FR-S36).
 * @note Call at a 1 Hz cadence from the main loop.
 */
void regs_second_tick(void);

/**
 * @brief Mark the in-progress measurement window aborted (FR-S30).
 *
 * Re-asserts status bit 0 (no completed window) until the restarted window
 * finishes. Called by the measurement services on a 40002 change.
 */
void regs_window_aborted(void);

#ifdef HAVE_WIND_SPEED
/**
 * @brief Publish one closed speed window (speed build / combined build).
 * @param count      Raw pulse count for the window → 30005 (FR-S08).
 * @param inst_0_1ms Scaled, cut-off-applied speed → 30002, 0.1 m/s
 *                   (FR-S06/S07/S27). Also fed to the averaging engine.
 */
void regs_publish_speed(uint16_t count, uint16_t inst_0_1ms);
#endif

#ifdef HAVE_WIND_DIRECTION
/**
 * @brief Update the instantaneous direction (direction / combined build).
 * @param raw16        Raw oversampled ADC (16×); the 10-bit view goes to the
 *                     build's raw-diagnostic register (30005, or 30013 on the
 *                     combined build).
 * @param angle_0_1deg Offset-applied angle, 0.1° units → 30001.
 * @param floating     True if the wiper is open (FR-S38): sets status bit 2
 *                     and forces 30001/30003 to the 65535 fault sentinel.
 */
void regs_dir_update(uint16_t raw16, uint16_t angle_0_1deg, bool floating);

/**
 * @brief Publish one closed direction window's circular result (FR-S14).
 * @param sin_q15 Mean sine of the window's samples, Q15.
 * @param cos_q15 Mean cosine of the window's samples, Q15.
 * @note Fed to the circular averaging engine; updates 30003.
 */
void regs_publish_dir_window(int16_t sin_q15, int16_t cos_q15);
#endif

#ifdef TEST_HOOKS
/**
 * @brief FR-S20 watchdog-recovery test trigger (TEST_HOOKS builds only).
 * @return True once holding register 0x00FF has been written 0xDEAD, telling
 *         the main loop to hang so the IWDG resets the device.
 * @warning Absent from release binaries — never ship a `*_test` build.
 */
bool regs_test_hang_requested(void);
#endif

#endif /* REGS_H */
