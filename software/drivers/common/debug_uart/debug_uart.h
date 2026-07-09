/**
 * @file debug_uart.h
 * @brief TX-only serial trace port — a driver-phase bring-up tool on PD6.
 *
 * Provides a tiny blocking, transmit-only UART tracer over USART1 for printf-
 * style bring-up and hardware-in-the-loop debugging during driver development
 * (`design/driverDevelopment.md` §2.2). USART1 is remapped so its TX lands on
 * PD6 — the same pin the product drives for Modbus — and is run in plain
 * push-pull TX (no half-duplex/HDSEL): the transmitter holds the mark level
 * continuously between frames, avoiding the floating-line drift that garbles
 * frames when PD6 is released (bench-verified). The matching RX would fall on
 * PD5, which is not bonded on the SOP-8 package, so receive is impossible and
 * unneeded here. See `design/softwareArchitecture.md`.
 *
 * The line runs 8N1 at 115200 baud unless @c DBG_UART_BAUD is defined at build
 * time (see debug_uart.c). This is a driver-phase tool only and is excluded
 * from release builds (`design/softwareArchitecture.md` §6,
 * `design/driverDevelopment.md` §2.2); it must never be linked into a shipped
 * binary.
 *
 * @note Every routine here is blocking (busy-wait on the UART status flags);
 *       there is no interrupt or DMA path and no output buffering.
 * @warning Because TX is remapped onto the Modbus pin (PD6), tracing and live
 *          Modbus traffic cannot share the bus — use only during bring-up.
 */
#ifndef DEBUG_UART_H
#define DEBUG_UART_H

#include <stdint.h>

/**
 * @brief Bring up USART1 as a TX-only tracer on PD6.
 *
 * Enables the GPIOD/USART1/AFIO clocks, applies the USART1 remap that moves TX
 * to PD6, drives PD6 as a push-pull alternate-function output, programs the
 * baud rate (@c DBG_UART_BAUD, default 115200) from the system core clock, and
 * enables the transmitter in plain 8N1 mode (no HDSEL). Call once before any
 * other @c dbg_* routine.
 *
 * @note Uses continuous push-pull TX rather than half-duplex on purpose: a
 *       released, floating PD6 drifts low and corrupts frames, whereas driving
 *       the mark level continuously is correct for a one-way tracer.
 */
void dbg_init(void);

/**
 * @brief Transmit one raw byte, blocking until the shifter can accept it.
 *
 * Busy-waits on the TXE (transmit-data-register-empty) flag, then writes @p c
 * to the data register. Returns once the byte is queued — not once it has
 * fully left the line; use @ref dbg_flush for that.
 *
 * @param c Byte to send (interpreted as a raw 8-bit value; no newline
 *          translation or other processing is performed).
 */
void dbg_putc(char c);

/**
 * @brief Transmit a NUL-terminated string.
 * @param s Pointer to a NUL-terminated C string; each byte up to (excluding)
 *          the terminating NUL is sent via @ref dbg_putc. Must not be NULL.
 * @note No newline is appended.
 */
void dbg_print(const char *s);

/**
 * @brief Transmit an unsigned 32-bit value as unpadded decimal ASCII.
 * @param v Value to print; emitted in base 10 with no leading zeros and no
 *          sign (e.g. 0 prints as "0", 4294967295 as "4294967295").
 * @see dbg_print_u16
 */
void dbg_print_u32(uint32_t v);

/**
 * @brief Transmit an unsigned 16-bit value as unpadded decimal ASCII.
 * @param v Value to print; widened and formatted via @ref dbg_print_u32, so
 *          the output is identical decimal, no padding.
 */
void dbg_print_u16(uint16_t v);

/**
 * @brief Block until the last queued byte has fully shifted out.
 *
 * Busy-waits on the TC (transmission-complete) flag. Use before disabling the
 * UART, reconfiguring PD6, or handing the pin back to the Modbus driver to
 * guarantee the final frame is not truncated.
 */
void dbg_flush(void);

#endif
