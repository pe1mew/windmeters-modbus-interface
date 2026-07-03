/*
 * Windmeter Modbus interface — product firmware (CH32V003J4M6, SOIC-8)
 *
 * Zero-ISR cooperative super-loop (design/softwareArchitecture.md).
 * Stage D state (design/integrationPlan.md): full register image (regs.c)
 * + real measurement services (meas_speed.c / meas_dir.c). The averaging
 * engine (30003/30004/30012 + warm-up semantics) is stage E.
 *
 * Pin assignment: design/scratchBook.md — PD6 Modbus line (remap-switching
 * discipline, no HDSEL), PC2 DE/R̄Ē, PA2 wind-direction ADC, PC1 anemometer
 * pulses, PC4 address jumper, PD1 SWIO.
 */

#include "board.h"
#include "ch32fun.h"
#include "mb.h"
#include "meas.h"
#include "regs.h"

#if !defined(SENSOR_WIND_SPEED) && !defined(SENSOR_WIND_DIRECTION)
#error "Define SENSOR_WIND_SPEED or SENSOR_WIND_DIRECTION (select a PlatformIO env)"
#endif
#if defined(SENSOR_WIND_SPEED) && defined(SENSOR_WIND_DIRECTION)
#error "SENSOR_WIND_SPEED and SENSOR_WIND_DIRECTION are mutually exclusive"
#endif

#ifdef SENSOR_WIND_SPEED
#include "ws.h"
#endif
#ifdef SENSOR_WIND_DIRECTION
#include "wd.h"
#endif

int main(void)
{
	SystemInit();
	funGpioInitAll();

	/* FR-S18 init order:
	 * (1) PC2/DE low first + (2) PC4 address latch + IWDG + PVD ... */
	board_init_early();
	/* (3) sensor front-end ready ... */
#ifdef SENSOR_WIND_SPEED
	ws_init();
#endif
#ifdef SENSOR_WIND_DIRECTION
	wd_init(); /* includes ADC self-calibration */
#endif
	meas_init();
	/* (4) USART receiver enabled last. */
	regs_init(board_mb_address());
	mb_init(regs_cfg());

	const uint32_t second_ticks = FUNCONF_SYSTEM_CORE_CLOCK;
	uint32_t t_second = SysTick->CNT;

	while (1)
	{
		mb_poll();
		regs_service(); /* FR-S30: 40002/40003 change -> accumulator clear */
		meas_service();

		if ((uint32_t)(SysTick->CNT - t_second) >= second_ticks)
		{
			t_second += second_ticks;
			regs_second_tick();
		}

#ifdef TEST_HOOKS
		if (regs_test_hang_requested())
			for (;;)
				; /* FR-S20 test: stop servicing AND feeding — dog bites */
#endif
		/* FR-S20: refresh only here, at the end of a full loop pass, and
		 * only while the rail is healthy (FR-S22). */
		if (board_power_ok())
			board_iwdg_feed();
	}
}
