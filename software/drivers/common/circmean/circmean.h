#ifndef CIRCMEAN_H
#define CIRCMEAN_H

#include <stdint.h>

// Circular mean over wind-direction angles (0.1° units, 0–3599) using the
// sine/cosine method (TDS FR-S14) — Q15 quarter-wave table + 16-iteration
// integer CORDIC atan2. No multiplies in the hot path (RV32EC has none).
//
// Algorithm reference + exhaustive host tests: gen_table.py /
// test_circmean.py in this folder. circmean.c mirrors the reference
// line-for-line; the drivers additionally run boot-time self-test vectors
// on target (design/driverDevelopment.md §4.1).

typedef struct {
	int32_t sum_sin;   // Q15 accumulators; safe for >64k samples
	int32_t sum_cos;
	uint16_t n;
} circmean_t;

void circmean_reset(circmean_t *cm);
void circmean_add(circmean_t *cm, uint16_t angle_0_1deg);
uint16_t circmean_get(const circmean_t *cm); // 0–3599; 65535 if n == 0

// Exposed for self-tests.
int16_t circmean_sin_q15(uint16_t angle_0_1deg);
uint32_t circmean_atan2_001deg(int32_t y, int32_t x); // 0..359999

#endif
