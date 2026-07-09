/**
 * @file funconfig.h
 * @brief ch32v003fun compile-time configuration for the wind speed driver build.
 *
 * Sets the framework's FUNCONF_* options for this build. Debug printf over
 * SWIO is disabled project-wide (it would distort HIL timing,
 * design/driverDevelopment.md §2.1) and tracing goes over PD6. main.c's window
 * pacing computes ticks as FUNCONF_SYSTEM_CORE_CLOCK / 1000 per ms, so SysTick
 * runs on full HCLK.
 */
#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_DEBUGPRINTF 0  /**< Non-default: no debugprintf over SWIO — it distorts HIL timing. */
#define FUNCONF_USE_UARTPRINTF  0  /**< No UART printf; tracing goes over PD6. */
#define FUNCONF_SYSTICK_USE_HCLK 1 /**< Non-default: SysTick on full HCLK (48 MHz), not the default HCLK/8. */

#endif
