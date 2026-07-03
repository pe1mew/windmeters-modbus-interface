#ifndef REGS_H
#define REGS_H

#include <stdbool.h>
#include <stdint.h>
#include "mb.h"

// Register image (integrationPlan.md stage C): the complete TDS §2.7/§2.8
// map on the mb driver interface. Per-build applicability per FR-MB27:
// every raw address 0x0000–0x000B is mapped on BOTH builds; registers of
// the absent sensor read 0; 0x0004 (30005) is the build-specific raw
// diagnostic. Values for 30001–30004/30012 are produced by the
// measurement services (stage D) and averaging engine (stage E) — until
// then they read 0, which is also their defined pre-first-window value
// (FR-S23).

void regs_init(uint8_t mb_address);
const mb_config_t *regs_cfg(void); // holdings + input_read + FR-S31 hook

// Holding-register accessors (owned here, TDS §2.8).
uint16_t regs_offset_0_1deg(void); // 40001
uint16_t regs_window_ms(void);     // 40002
uint16_t regs_avg_s(void);         // 40003
uint16_t regs_cutoff_0_1ms(void);  // 40004

// Measurement-side publishers (called from the main loop services).
void regs_service(void);        // FR-S30: watch 40002/40003, clear the
                                // averaging accumulator on change
void regs_second_tick(void);    // uptime (FR-S34) + pulse-age (FR-S36)
void regs_window_aborted(void); // FR-S30: 40002 write aborted the window
#ifdef SENSOR_WIND_SPEED
// Per closed window: raw count (30005) + scaled/cut-off value (30002).
void regs_publish_speed(uint16_t count, uint16_t inst_0_1ms);
#endif
#ifdef SENSOR_WIND_DIRECTION
void regs_dir_update(uint16_t raw16, uint16_t angle_0_1deg, bool floating);
// Per closed window: circular result (mean sin/cos of the samples, Q15).
void regs_publish_dir_window(int16_t sin_q15, int16_t cos_q15);
#endif

#ifdef TEST_HOOKS
bool regs_test_hang_requested(void); // FR-S20 recovery-test trigger
#endif

#endif
