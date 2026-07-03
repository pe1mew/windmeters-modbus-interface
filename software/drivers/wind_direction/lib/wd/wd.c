#include "ch32fun.h"
#include "wd.h"

static uint16_t adc_convert_once(void)
{
	ADC1->CTLR2 |= ADC_SWSTART;
	while (!(ADC1->STATR & ADC_EOC))
		;
	return (uint16_t)ADC1->RDATAR; // read clears EOC
}

void wd_init(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOA | RCC_APB2Periph_ADC1;
	// ADCCLK = HCLK/8 = 6 MHz. At /2 (24 MHz) this part shows an
	// end-of-range INL bow of ~+16 LSB near zero (bench-measured against a
	// DMM) — the conservative clock trades conversion time (~14 µs/conv,
	// ~224 µs per 16-burst, far under the 100 ms update budget) for
	// accuracy.
	RCC->CFGR0 = (RCC->CFGR0 & ~RCC_ADCPRE) | RCC_ADCPRE_DIV8;

	funPinMode(PA2, GPIO_CNF_IN_ANALOG);

	ADC1->RSQR1 = 0;       // one conversion per sequence
	ADC1->RSQR3 = 0;       // channel 0 (PA2 = A0)
	ADC1->SAMPTR2 = 6;     // ch0 sample time 73 cycles — FR-S10's ≥71
	ADC1->CTLR2 = ADC_ADON | ADC_EXTSEL; // on; SWSTART as trigger
	Delay_Us(10);

	// Self-calibration before the first conversion (FR-S18 init order).
	ADC1->CTLR2 |= ADC_RSTCAL;
	while (ADC1->CTLR2 & ADC_RSTCAL)
		;
	ADC1->CTLR2 |= ADC_CAL;
	while (ADC1->CTLR2 & ADC_CAL)
		;
}

uint16_t wd_read_raw16(void)
{
	uint16_t sum = 0;
	for (int i = 0; i < 16; i++)
		sum += adc_convert_once(); // max 16 × 1023 = 16368
	return sum;
}

uint16_t wd_angle_0_1deg(uint16_t raw16, uint16_t offset_0_1deg)
{
	// (raw16 × 3600 + 8192) >> 14: max 3597 at raw16 = 16368 — the value
	// 3600 is unreachable by construction (FR-S29).
	uint32_t angle = (((uint32_t)raw16 * 3600u + 8192u) >> 14) + offset_0_1deg;
	return (uint16_t)(angle % 3600u);
}

bool wd_wiper_floating(void)
{
	// Toggle the internal pull on PA2 between two conversions (FR-S38).
	// A connected source (pot wiper ≤ ~3 kΩ, AWG 50 Ω) barely moves; a
	// floating pin follows the pull rail-to-rail.
	funPinMode(PA2, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PA2, FUN_HIGH);
	Delay_Us(10);
	int32_t up = adc_convert_once();
	funDigitalWrite(PA2, FUN_LOW);
	Delay_Us(10);
	int32_t dn = adc_convert_once();
	funPinMode(PA2, GPIO_CNF_IN_ANALOG);
	return (up - dn) > 300;
}
