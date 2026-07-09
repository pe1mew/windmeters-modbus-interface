/**
 * @file board.h
 * @brief Board bring-up and platform services — RS-485 quiescing, jumper
 *        address latch, watchdog and brown-out detection for the ch32v003 node.
 *
 * The head of the firmware's initialisation order (integration stage B,
 * `design/integrationPlan.md`): FR-S18 init-order head, FR-S03 jumper-selected
 * Modbus address, FR-S20 independent watchdog and FR-S22 programmable voltage
 * detector (PVD). @ref board_init_early runs first — before the sensor
 * front-ends, the USART and the Modbus register image (@ref regs.h) — leaving
 * the transceiver quiescent and the safety hardware armed. The latched slave
 * address then feeds @ref regs_init via @ref board_mb_address, and the main
 * loop drives the FR-S20/FR-S22 recovery path through @ref board_iwdg_feed and
 * @ref board_power_ok.
 */
#ifndef BOARD_H
#define BOARD_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @def BOARD_MB_BASE_ADDRESS
 * @brief Per-build Modbus base slave address (FR-S03), before the jumper offset.
 *
 * Selected at compile time from the active sensor build (the `SENSOR_WIND_*`
 * define set by the build system). This value is the address with the PC4
 * solder jumper open; bridging that jumper to GND adds 5
 * (see @ref board_mb_address). Each variant occupies a distinct address pair so
 * a speed, a direction and a combined unit can coexist on one RS-485 segment
 * without collision.
 */
#if defined(SENSOR_WIND_COMBINED)
#define BOARD_MB_BASE_ADDRESS 32 /**< Combined build: open = 32, bridged = 37 (FR-S03). */
#elif defined(SENSOR_WIND_SPEED)
#define BOARD_MB_BASE_ADDRESS 30 /**< Speed build: open = 30, bridged = 35 (FR-S03). */
#elif defined(SENSOR_WIND_DIRECTION)
#define BOARD_MB_BASE_ADDRESS 31 /**< Direction build: open = 31, bridged = 36 (FR-S03). */
#endif

/**
 * @brief Earliest board bring-up: RS-485 quiescing, address latch, watchdog, PVD.
 *
 * Executes integration stage B, the head of the FR-S18 initialisation order,
 * and @b must run before any sensor or USART init. In sequence it:
 *  1. enables the GPIOC/GPIOD/AFIO and PWR peripheral clocks;
 *  2. FR-S18 step 1 — drives PC2 (the MAX3485 DE/R̄Ē pair) low as the very
 *     first GPIO action, enabling the receiver and disabling the driver so the
 *     node stays off the bus; until this point only the PCB's 10 k pull-down
 *     held the line;
 *  3. FR-S18 step 2 / FR-S03 — samples the PC4 solder jumper (internal
 *     pull-up, ~50 µs settle) and latches the Modbus slave address once
 *     (see @ref board_mb_address);
 *  4. FR-S22 — arms the PVD at its lowest threshold so the nominal 3.1–3.3 V
 *     rail never trips it, while a genuine sag flips PVDO
 *     (see @ref board_power_ok);
 *  5. FR-S20 — starts the LSI (128 kHz) and the IWDG (/32 → 4 kHz, reload 4095
 *     ≈ 1.02 s, inside the required 100 ms–2 s window) and gives it a first
 *     feed.
 *
 * @note The IWDG is deliberately left running under the debugger: this ch32v003
 *       core has no usable IWDG debug-freeze (writing the SPL DBGMCU word
 *       hard-faults it, bench 2026-07-03), so a halted core is reset after
 *       ~1 s — power-cycle before flashing if uploads turn flaky.
 * @warning Once the IWDG is started it cannot be stopped again by design; the
 *          main loop must keep it fed via @ref board_iwdg_feed while
 *          @ref board_power_ok holds.
 * @see board_iwdg_feed, board_mb_address, board_power_ok
 */
void board_init_early(void);

/**
 * @brief Modbus slave address latched during @ref board_init_early
 *        (FR-S03/FR-MB07).
 * @return @ref BOARD_MB_BASE_ADDRESS when the PC4 jumper is open, or base + 5
 *         when it is bridged to GND. Fixed for the life of the reset — a
 *         mid-run jumper change has no effect until the next reset (FR-MB07).
 * @note Pass this to @ref regs_init as the driver's slave address.
 */
uint8_t board_mb_address(void);

/**
 * @brief Feed (refresh) the independent watchdog (FR-S20).
 *
 * Reloads the IWDG down-counter. Call only from the @b end of the main loop,
 * and only while @ref board_power_ok returns true: withholding the feed during
 * a PVD brown-out is what lets the watchdog fire, which is the deliberate
 * FR-S22 recovery path — a reset back into the FR-S21 defined state.
 * @warning Never feed unconditionally; the conditional feed @e is the brown-out
 *          recovery mechanism, not merely a liveness kick.
 * @see board_power_ok
 */
void board_iwdg_feed(void);

/**
 * @brief Supply-rail health from the programmable voltage detector (FR-S22).
 * @return True while the rail is above the PVD threshold (PVDO clear); false
 *         during a brown-out sag.
 * @note Gates @ref board_iwdg_feed — a sustained sag stops the feed and lets
 *       the FR-S20 watchdog reset the device into the FR-S21 defined state.
 */
bool board_power_ok(void);

#endif
