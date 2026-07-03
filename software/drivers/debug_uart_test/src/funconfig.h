#ifndef _FUNCONFIG_H
#define _FUNCONFIG_H

// ch32v003fun compile-time configuration.
// Debug printf over the SWIO debug link is disabled project-wide: it would
// distort HIL timing (design/driverDevelopment.md §2.1). All tracing goes
// over the PD6 debug UART instead.
#define FUNCONF_USE_DEBUGPRINTF 0
#define FUNCONF_USE_UARTPRINTF  0

#endif
