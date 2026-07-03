#include "ch32fun.h"
#include "circmean.h"
#include "debug_uart.h"
#include "wd.h"

// Wind direction driver HIL test shell.
//
// Boot: run circmean self-test vectors ON TARGET (real RV32EC soft-mul
// path) and report "CM,PASS" / "CM,FAIL,<case>". Then 100 ms updates
// (FR-S28 ≥10 Hz), one report line per second on the PD6 debug UART:
//     D,<raw16>,<inst>,<avg>,<flt>\r\n
// raw16 = 16-conversion sum (0..16368), inst/avg in 0.1° (avg = circular
// mean of the last 10 updates), flt = wiper-float flag (FR-S38).

#define UPDATE_MS 100u
#define UPDATES_PER_REPORT 10u

static uint16_t wrap_dist(uint16_t a, uint16_t b)
{
	uint16_t d = (uint16_t)((a >= b ? a - b : b - a) % 3600u);
	return d > 1800 ? (uint16_t)(3600 - d) : d;
}

static bool selftest_case(const uint16_t *angles, uint16_t count,
                          uint16_t expect, uint16_t tol)
{
	circmean_t cm;
	circmean_reset(&cm);
	for (uint16_t i = 0; i < count; i++)
		circmean_add(&cm, angles[i]);
	return wrap_dist(circmean_get(&cm), expect) <= tol;
}

static uint8_t circmean_selftest(void)
{
	static const uint16_t idsweep[5] = {0, 900, 1800, 2700, 3599};
	for (uint8_t i = 0; i < 5; i++)
		if (!selftest_case(&idsweep[i], 1, idsweep[i], 1))
			return 1;

	uint16_t alt[32]; // FR-S14: 350.0°/10.0° alternating -> 0.0° ±1.0°
	for (uint8_t i = 0; i < 32; i++)
		alt[i] = (i & 1) ? 100 : 3500;
	{
		circmean_t cm;
		circmean_reset(&cm);
		for (uint8_t i = 0; i < 32; i++)
			circmean_add(&cm, alt[i]);
		uint16_t m = circmean_get(&cm);
		if (!(m >= 3590 || m <= 10))
			return 2;
		if (m >= 1700 && m <= 1900)
			return 3;
	}

	static const uint16_t dist[3] = {100, 200, 300};
	if (!selftest_case(dist, 3, 200, 1))
		return 4;

	static const uint16_t wrapd[5] = {3400, 3500, 0, 100, 200};
	if (!selftest_case(wrapd, 5, 0, 1))
		return 5;

	circmean_t empty;
	circmean_reset(&empty);
	if (circmean_get(&empty) != 65535)
		return 6;

	return 0;
}

int main()
{
	SystemInit();
	funGpioInitAll();
	dbg_init();
	wd_init();

	uint8_t st = circmean_selftest();
	if (st == 0) {
		dbg_print("CM,PASS\r\n");
	} else {
		dbg_print("CM,FAIL,");
		dbg_print_u16(st);
		dbg_print("\r\n");
	}
	dbg_print("WD,START\r\n");

	const uint32_t update_ticks = (FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * UPDATE_MS;
	uint32_t t0 = SysTick->CNT;
	uint32_t updates = 0;
	circmean_t cm;
	circmean_reset(&cm);
	uint16_t last_raw16 = 0, last_inst = 0;

	while (1)
	{
		if ((uint32_t)(SysTick->CNT - t0) >= update_ticks)
		{
			t0 += update_ticks;
			last_raw16 = wd_read_raw16();
			last_inst = wd_angle_0_1deg(last_raw16, 0);
			circmean_add(&cm, last_inst);

			if (++updates >= UPDATES_PER_REPORT)
			{
				updates = 0;
				uint16_t avg = circmean_get(&cm);
				circmean_reset(&cm);
				bool flt = wd_wiper_floating();
				dbg_print("D,");
				dbg_print_u16(last_raw16);
				dbg_putc(',');
				dbg_print_u16(last_inst);
				dbg_putc(',');
				dbg_print_u16(avg);
				dbg_putc(',');
				dbg_putc(flt ? '1' : '0');
				dbg_print("\r\n");
			}
		}
	}
}
