#ifndef BOARD_H
#define BOARD_H

#include <stdbool.h>
#include <stdint.h>

// Board bring-up (integrationPlan.md stage B): FR-S18 init order head,
// FR-S03 jumper address, FR-S20 watchdog, FR-S22 PVD.

#if defined(SENSOR_WIND_COMBINED)
#define BOARD_MB_BASE_ADDRESS 32 /* FR-S03: open = 32, bridged = 37 */
#elif defined(SENSOR_WIND_SPEED)
#define BOARD_MB_BASE_ADDRESS 30 /* FR-S03: open = 30, bridged = 35 */
#elif defined(SENSOR_WIND_DIRECTION)
#define BOARD_MB_BASE_ADDRESS 31 /* FR-S03: open = 31, bridged = 36 */
#endif

// FR-S18 steps 1+2 plus watchdog and PVD: PC2/DE low as the FIRST GPIO
// action, PC4 jumper latched, IWDG started (~1 s), PVD armed. Call before
// any sensor or USART init.
void board_init_early(void);

uint8_t board_mb_address(void); // latched at board_init_early (FR-S03/FR-MB07)

// FR-S20: refresh only from the end of the main loop — and only while
// board_power_ok(); withholding the feed during a PVD brown-out turns the
// watchdog into the FR-S22 recovery path (reset into the defined state).
void board_iwdg_feed(void);
bool board_power_ok(void);

#endif
