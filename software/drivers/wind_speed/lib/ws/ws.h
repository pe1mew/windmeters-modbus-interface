#ifndef WS_H
#define WS_H

#include <stdbool.h>
#include <stdint.h>

// Wind speed pulse-counting driver: TIM2 in ETR external-clock mode on PC1
// (AFIO partial remap 2), counting rising edges in hardware with zero CPU
// overhead (TDS FR-S04). Window pacing is the caller's job — this driver
// only counts (design/softwareArchitecture.md; design/driverDevelopment.md §3.1).

void ws_init(void);          // TIM2 ETR on PC1, counter running
void ws_window_start(void);  // zero the counter, clear the overflow flag

// Pulse count since ws_window_start(). If the 16-bit counter overflowed
// during the window, returns 65535 (saturated, never a wrapped value —
// TDS FR-S27) and sets *saturated.
uint16_t ws_window_read(bool *saturated);

#endif
