#ifndef WD_H
#define WD_H

#include <stdbool.h>
#include <stdint.h>

// Wind direction driver: 10-bit ADC on PA2 (channel A0), ratiometric to
// VDD, 16× oversampled (TDS FR-S09/S10/S28). Angle mapping never emits
// 3600 (FR-S29); wiper-float detection per FR-S38.

void wd_init(void);              // ADC on, self-calibrated (FR-S18)
uint16_t wd_read_raw16(void);    // sum of 16 conversions: 0..16368

// raw16 -> 0.1° with calibration offset applied, result 0..3599.
uint16_t wd_angle_0_1deg(uint16_t raw16, uint16_t offset_0_1deg);

// Pull-toggle test (FR-S38): true if PA2 appears disconnected/floating.
bool wd_wiper_floating(void);

#endif
