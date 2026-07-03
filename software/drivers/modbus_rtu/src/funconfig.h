#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

// No debugprintf (would distort HIL timing) and no UART printf — PD6 is
// the Modbus line in this project (design/driverDevelopment.md §5.2).
#define FUNCONF_USE_DEBUGPRINTF 0
#define FUNCONF_USE_UARTPRINTF  0

// SysTick on HCLK (48 MHz) — mb.c and main.c pace with raw SysTick->CNT
// arithmetic (bench-learned: the default is HCLK/8).
#define FUNCONF_SYSTICK_USE_HCLK 1

#endif
