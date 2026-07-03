#ifndef DEBUG_UART_H
#define DEBUG_UART_H

#include <stdint.h>

// TX-only debug tracing on PD6: USART1 remapped (TX -> PD6) in single-wire
// half-duplex mode, matching the product's Modbus pin usage
// (design/softwareArchitecture.md). 115200 8N1 unless DBG_UART_BAUD is
// defined at build time.
//
// Driver-phase tool only — excluded from release builds
// (design/softwareArchitecture.md §6, design/driverDevelopment.md §2.2).

void dbg_init(void);
void dbg_putc(char c);
void dbg_print(const char *s);
void dbg_print_u32(uint32_t v); // decimal, no padding
void dbg_print_u16(uint16_t v); // decimal, no padding
void dbg_flush(void);           // block until the last byte has left the shifter

#endif
