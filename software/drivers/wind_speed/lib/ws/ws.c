#include "ch32fun.h"
#include "ws.h"

// TIM2 remap {bit9,bit8} = {1,0} (partial remap 2) places TIM2_CH1/ETR on
// PC1 — the only remap that does so on the SOP-8 package (scratchBook.md,
// CH32V003 RM AFIO_PCFR1[9:8]).
#define AFIO_PCFR1_TIM2_RM_MASK (3u << 8)
#define AFIO_PCFR1_TIM2_RM_PC1  (2u << 8)

void ws_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOC | RCC_APB2Periph_AFIO;
	RCC->APB1PCENR |= RCC_APB1Periph_TIM2;

	AFIO->PCFR1 = (AFIO->PCFR1 & ~AFIO_PCFR1_TIM2_RM_MASK) | AFIO_PCFR1_TIM2_RM_PC1;

	// PC1 input with pull-up: an open input idles high and counts nothing
	// (product has an external 10k pull-up; the M2K rig drives push-pull).
	funPinMode(PC1, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PC1, FUN_HIGH);

	TIM2->ATRLR = 0xFFFF;      // full 16-bit range; UIF = overflow past 65535
	TIM2->SMCFGR = TIM_ECE;    // external clock mode 2: count ETR rising edges
	TIM2->CTLR1 = TIM_CEN;
}

void ws_window_start(void)
{
	TIM2->CNT = 0;
	TIM2->INTFR = 0;           // rc_w0: writing 0 clears UIF
}

uint16_t ws_window_read(bool *saturated)
{
	uint16_t count = TIM2->CNT;
	bool sat = (TIM2->INTFR & 0x0001) != 0; // UIF: counter wrapped in window
	if (saturated)
		*saturated = sat;
	return sat ? 0xFFFF : count;
}
