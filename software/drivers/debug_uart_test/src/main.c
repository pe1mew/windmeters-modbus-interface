#include "ch32fun.h"
#include "debug_uart.h"

// debug_uart HIL test shell: saturate the PD6 link with counting lines
// ("D,<n>\r\n"). The HIL check (software/hil/uart_check.py) decodes the
// stream with the Saleae Async Serial analyzer and asserts >=10k lines,
// strict counter continuity, and zero framing errors
// (design/driverDevelopment.md §2.2 exit criterion).

int main()
{
	SystemInit();
	funGpioInitAll();
	dbg_init();

	dbg_print("DBGUART,START\r\n");

	uint32_t n = 0;
	while (1)
	{
		dbg_print("D,");
		dbg_print_u32(n++);
		dbg_print("\r\n");
	}
}
