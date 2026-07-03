#include "ch32fun.h"
#include "debug_uart.h"
#include "ws.h"

// Wind speed driver HIL test shell: fixed 1000 ms windows paced by SysTick,
// one report line per window on the PD6 debug UART:
//     W,<count>,<flag>\r\n      flag: 0 = normal, S = saturated (FR-S27)
// The HIL check (software/hil/ws_check.py) drives PC1 from the M2K and
// asserts counts, rising-edge-only behaviour, window timing (FR-S17), and
// saturation against the Saleae-decoded stream.

#define WINDOW_MS 1000u

int main()
{
	SystemInit();
	funGpioInitAll();
	dbg_init();
	ws_init();

	dbg_print("WS,START\r\n");

	const uint32_t window_ticks = (FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * WINDOW_MS;
	uint32_t t0 = SysTick->CNT;
	ws_window_start();

	while (1)
	{
		if ((uint32_t)(SysTick->CNT - t0) >= window_ticks)
		{
			t0 += window_ticks; // drift-free window boundaries
			bool sat;
			uint16_t count = ws_window_read(&sat);
			ws_window_start();
			dbg_print("W,");
			dbg_print_u16(count);
			dbg_print(sat ? ",S\r\n" : ",0\r\n");
		}
	}
}
