#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

// Debug printf over SWIO disabled project-wide — it would distort HIL
// timing (design/driverDevelopment.md §2.1). Tracing goes over PD6.
#define FUNCONF_USE_DEBUGPRINTF 0
#define FUNCONF_USE_UARTPRINTF  0

// SysTick on HCLK (48 MHz), not the default HCLK/8 — main.c's update
// pacing computes ticks as FUNCONF_SYSTEM_CORE_CLOCK / 1000 per ms
// (bench-learned, software/hil/README.md).
#define FUNCONF_SYSTICK_USE_HCLK 1

#endif
