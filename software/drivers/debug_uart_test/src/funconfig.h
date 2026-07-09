/**
 * @file funconfig.h
 * @brief ch32v003fun compile-time configuration for the debug UART test build.
 *
 * Sets the framework's FUNCONF_* options for this build. Debug printf over the
 * SWIO debug link is disabled project-wide (it would distort HIL timing,
 * design/driverDevelopment.md §2.1); all tracing goes over the PD6 debug UART
 * instead.
 */
#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

#define FUNCONF_USE_DEBUGPRINTF 0  /**< Non-default: no debugprintf over SWIO — it distorts HIL timing. */
#define FUNCONF_USE_UARTPRINTF  0  /**< No framework UART printf; this test drives PD6 directly. */

#endif
