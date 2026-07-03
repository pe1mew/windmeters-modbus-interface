#include "ch32fun.h"
#include "mb.h"

// Modbus RTU driver HIL test shell — TTL-level rig (no MAX3485 yet).
//
// NO debug UART here: PD6 IS the bus (FR-S19 — never transmit except in
// response to a valid addressed request). Observability = the bus itself,
// decoded on the Saleae; DE on PC2 is observable on a second channel.
//
// Slave address 30 (wind-speed build value, FR-S03; PC4 jumper handling
// arrives at integration). Holding registers mirror TDS §2.8 exactly;
// input registers serve known patterns for read/byte-order tests plus
// live uptime and the driver's own diagnostic counters.

static uint16_t h_offset = 0;    // 40001: 0..3599, default 0
static uint16_t h_window = 1000; // 40002: 100..60000, default 1000
static uint16_t h_avg = 10;      // 40003: 1..600, default 10 (FR-S31)
static uint16_t h_cutoff = 4;    // 40004: 0..50, default 4

static const mb_holding_t holdings[] = {
	{0x0000, 0, 3599, &h_offset},
	{0x0001, 100, 60000, &h_window},
	{0x0002, 1, 600, &h_avg},
	{0x0003, 0, 50, &h_cutoff},
};

static volatile uint32_t uptime_s;

// FR-S31: (averaging window x 1000) >= measurement window, evaluated
// against the staged pair (falls back to current values if not staged).
static bool cross_validate(const uint16_t *addrs, const uint16_t *vals,
                           uint8_t n)
{
	uint16_t window = h_window;
	uint16_t avg = h_avg;
	for (uint8_t i = 0; i < n; i++) {
		if (addrs[i] == 0x0001)
			window = vals[i];
		if (addrs[i] == 0x0002)
			avg = vals[i];
	}
	return (uint32_t)avg * 1000u >= window;
}

static uint16_t input_read(uint16_t addr, bool *ok)
{
	switch (addr) {
	case 0x0000: return 1234;          // fixed pattern
	case 0x0001: return 250;           // synthetic wind speed
	case 0x0002: return 900;           // 0x0384 — byte-order probe (FR-MB25)
	case 0x0003: return 0;
	case 0x0004: return 511;
	case 0x0005: return 3;             // synthetic status bits
	case 0x0006: return 0x0107;        // build/version pattern (FR-S32 shape)
	case 0x0007: return (uint16_t)uptime_s;
	case 0x0008: return mb_crc_error_count();
	case 0x0009: return mb_served_count();
	case 0x000A: return 42;
	case 0x000B: return 80;
	case 0x000C: return mb_fe_count();
	case 0x000D: return mb_ne_count();
	case 0x000E: return mb_ore_count();
	case 0x0010: return mb_last_bad(0);
	case 0x0011: return mb_last_bad(1);
	case 0x0012: return mb_last_bad(2);
	case 0x0013: return mb_last_bad(3);
	default:
		*ok = false;
		return 0;
	}
}

static const mb_config_t cfg = {
	.address = 30,
	.holdings = holdings,
	.n_holdings = sizeof(holdings) / sizeof(holdings[0]),
	.input_read = input_read,
	.cross_validate = cross_validate,
};

int main()
{
	SystemInit();
	funGpioInitAll();
	mb_init(&cfg);

	const uint32_t second_ticks = FUNCONF_SYSTEM_CORE_CLOCK;
	uint32_t t0 = SysTick->CNT;

	while (1)
	{
		mb_poll();
		if ((uint32_t)(SysTick->CNT - t0) >= second_ticks)
		{
			t0 += second_ticks;
			uptime_s++;
		}
	}
}
