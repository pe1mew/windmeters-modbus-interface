/**
 * @file funconfig.h
 * @brief ch32v003fun compile-time configuration for the Modbus RTU driver build.
 *
 * Sets the framework's FUNCONF_* options for this build. Debug printf is off
 * (it would distort HIL timing) and PD6 is the Modbus line, not a trace UART
 * (design/driverDevelopment.md §5.2). mb.c and main.c pace with raw
 * SysTick->CNT arithmetic, so SysTick runs on full HCLK.
 */
#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_DEBUGPRINTF 0  /**< Non-default: no debugprintf over SWIO — it distorts HIL timing. */
#define FUNCONF_USE_UARTPRINTF  0  /**< No UART printf — PD6 is the Modbus line. */
#define FUNCONF_SYSTICK_USE_HCLK 1 /**< Non-default: SysTick on full HCLK (48 MHz), not the default HCLK/8. */

#endif
