#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

// Product firmware ch32v003fun configuration (bench-mandated settings,
// software/hil/README.md):
// - no debugprintf over SWIO (distorts timing; release has no debug UART
//   at all — PD6 is the Modbus line, TDS FR-S19)
// - SysTick on HCLK: all pacing uses raw SysTick->CNT arithmetic
//   (design/softwareArchitecture.md — zero-ISR)
#define FUNCONF_USE_DEBUGPRINTF 0
#define FUNCONF_USE_UARTPRINTF  0
#define FUNCONF_SYSTICK_USE_HCLK 1

#endif
