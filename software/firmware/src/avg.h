#ifndef AVG_H
#define AVG_H

#include <stdbool.h>
#include <stdint.h>

// Averaging engine (integrationPlan.md stage E): boxcar over
// N = (40003 s × 1000) / 40002 ms measurement windows (FR-S13/S31).
// For N ≤ 64 the boxcar is exact; for N > 64 windows aggregate into
// blocks of ⌈N/64⌉ (FR-S31 two-stage: block mean for speed, block
// sine/cosine sums for direction, block max for gust). Warm-up per
// FR-S23: values computed over only the entries acquired since
// reset/clear — no zero-padding. avg_filled() feeds status bit 1.

void avg_config(uint16_t window_ms, uint16_t avg_s); // also clears (FR-S30)
bool avg_filled(void); // accumulator holds a full averaging span

#ifdef SENSOR_WIND_SPEED
void avg_add_speed(uint16_t inst_0_1ms); // one closed window's 30002 value
uint16_t avg_speed(void);                // 30004
uint16_t avg_gust(void);                 // 30012 (FR-S37)
#endif

#ifdef SENSOR_WIND_DIRECTION
// One closed window's circular result (mean sin/cos of its samples, Q15).
void avg_add_dir(int16_t sin_q15, int16_t cos_q15);
uint16_t avg_dir(void); // 30003: 0..3599, 65535 while empty
#endif

#endif
