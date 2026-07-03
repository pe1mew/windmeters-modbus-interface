#include "ch32fun.h"
#include "debug_uart.h"

#ifndef DBG_UART_BAUD
#define DBG_UART_BAUD 115200
#endif

// USART1 remap {RM1,RM} = {1,0} places TX on PD6 (RX would land on PD5,
// which is not bonded on the SOP-8 — irrelevant for TX-only use).
#define AFIO_PCFR1_USART1_RM_BIT  (1u << 2)
#define AFIO_PCFR1_USART1_RM1_BIT (1u << 21)

void dbg_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOD | RCC_APB2Periph_USART1 | RCC_APB2Periph_AFIO;

	AFIO->PCFR1 = (AFIO->PCFR1 & ~(AFIO_PCFR1_USART1_RM_BIT | AFIO_PCFR1_USART1_RM1_BIT))
	              | AFIO_PCFR1_USART1_RM1_BIT;

	funPinMode(PD6, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);

	USART1->BRR = (FUNCONF_SYSTEM_CORE_CLOCK + DBG_UART_BAUD / 2) / DBG_UART_BAUD;
	// No HDSEL here: in half-duplex mode the transmitter RELEASES the line
	// between frames, and a floating PD6 drifts low (bench-verified: 893 ms
	// idle-low gaps garbled every frame). Plain TX drives the mark level
	// continuously — correct for a TX-only tracer. The Modbus driver DOES
	// use HDSEL; there the MAX3485/bus bias defines the idle level.
	USART1->CTLR3 = 0;
	USART1->CTLR1 = USART_CTLR1_TE | USART_CTLR1_UE; // TX only, 8N1
}

void dbg_putc(char c)
{
	while (!(USART1->STATR & USART_STATR_TXE))
		;
	USART1->DATAR = (uint8_t)c;
}

void dbg_print(const char *s)
{
	while (*s)
		dbg_putc(*s++);
}

void dbg_print_u32(uint32_t v)
{
	char buf[10]; // max 4294967295
	int i = 0;
	do {
		buf[i++] = '0' + (v % 10);
		v /= 10;
	} while (v);
	while (i)
		dbg_putc(buf[--i]);
}

void dbg_print_u16(uint16_t v)
{
	dbg_print_u32(v);
}

void dbg_flush(void)
{
	while (!(USART1->STATR & USART_STATR_TC))
		;
}
