/**
 * @file funconfig.h
 * @brief ch32v003fun compile-time configuration for the product firmware.
 *
 * Sets the framework's FUNCONF_* options for this build (bench-mandated,
 * software/hil/README.md). The release image runs zero-ISR and has no debug
 * UART: PD6 is the Modbus line (TDS FR-S19), and all pacing is done with raw
 * SysTick->CNT arithmetic (design/softwareArchitecture.md).
 */
#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_DEBUGPRINTF 0  /**< Non-default: no debugprintf over SWIO — it distorts timing. */
#define FUNCONF_USE_UARTPRINTF  0  /**< No UART printf — PD6 is the Modbus line, not a trace UART. */
#define FUNCONF_SYSTICK_USE_HCLK 1 /**< Non-default: SysTick on full HCLK (48 MHz), not HCLK/8. */

#endif
