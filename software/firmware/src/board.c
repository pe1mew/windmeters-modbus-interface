#include "ch32fun.h"
#include "board.h"

static uint8_t mb_address;

void board_init_early(void)
{
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOC | RCC_APB2Periph_GPIOD |
	                  RCC_APB2Periph_AFIO;
	RCC->APB1PCENR |= RCC_APB1Periph_PWR;

	// FR-S18 (1): DE/R̄Ē low — receiver enabled, driver off — as the very
	// first GPIO action (the PCB's 10 k pull-down covered the reset window
	// until now).
	funPinMode(PC2, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PC2, FUN_LOW);

	// FR-S18 (2) + FR-S03: PC4 solder jumper, internal pull-up. Open =
	// reads high = base address; bridged to GND = base + 5. Latched once;
	// runtime changes have no effect until reset (FR-MB07).
	funPinMode(PC4, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PC4, FUN_HIGH);
	Delay_Us(50);
	mb_address = (uint8_t)(BOARD_MB_BASE_ADDRESS +
	                       (funDigitalRead(PC4) ? 0 : 5));

	// FR-S22: PVD at the lowest threshold so the nominal rail (3.1–3.3 V)
	// never trips it; a real sag flips PVDO and the main loop stops
	// feeding the watchdog -> IWDG reset into the FR-S21 defined state.
	PWR->CTLR = (PWR->CTLR & ~PWR_CTLR_PLS) | PWR_CTLR_PVDE;

	// FR-S20: IWDG from LSI 128 kHz, /32 -> 4 kHz, reload 4095 ≈ 1.02 s
	// (inside the required 100 ms – 2 s). Start LSI explicitly first —
	// the PVU/RVU sync flags never clear without it (bench: waiting on
	// them before 0xCCCC hard-hung boot).
	//
	// NOTE: no debug-freeze for the IWDG. Writing the DBGMCU/CFGR1 word at
	// the ch32v00x SPL address 0xE000D000 hard-faults this core (bench
	// 2026-07-03) and ch32v003fun exposes no instance for it — so the dog
	// keeps running while the WCH-LinkE holds the core. Flash sessions are
	// short; if uploads ever become flaky, power-cycle before flashing or
	// revisit the correct DBG base for this part.
	RCC->RSTSCKR |= RCC_LSION;
	while (!(RCC->RSTSCKR & RCC_LSIRDY))
		;
	IWDG->CTLR = IWDG_WriteAccess_Enable;
	IWDG->PSCR = IWDG_Prescaler_32;
	IWDG->RLDR = 0xFFF;
	IWDG->CTLR = 0xCCCC; // start — cannot be stopped again (by design)
	board_iwdg_feed();
}

uint8_t board_mb_address(void)
{
	return mb_address;
}

void board_iwdg_feed(void)
{
	IWDG->CTLR = 0xAAAA;
}

bool board_power_ok(void)
{
	return (PWR->CSR & PWR_CSR_PVDO) == 0;
}
