#include "avg.h"
#include "regs.h"
#include "version.h"

#ifdef SENSOR_WIND_SPEED
#define BUILD_TYPE 0x01
#endif
#ifdef SENSOR_WIND_DIRECTION
#define BUILD_TYPE 0x02
#endif

/* ---- Holding registers (TDS §2.8: raw addr, min, max, default) ---- */

static uint16_t h_offset = 0;    /* 40001: 0..3599    */
static uint16_t h_window = 1000; /* 40002: 100..60000 */
static uint16_t h_avg = 10;      /* 40003: 1..600 + FR-S31 */
static uint16_t h_cutoff = 4;    /* 40004: 0..50      */
#ifdef TEST_HOOKS
static uint16_t test_hang;       /* 0x00FF, TEST builds only (FR-S20 hook) */
#endif

static const mb_holding_t holdings[] = {
	{0x0000, 0, 3599, &h_offset},
	{0x0001, 100, 60000, &h_window},
	{0x0002, 1, 600, &h_avg},
	{0x0003, 0, 50, &h_cutoff},
#ifdef TEST_HOOKS
	{0x00FF, 0, 0xFFFF, &test_hang},
#endif
};

/* FR-S31: (40003 s × 1000) ≥ 40002 ms, evaluated against the staged pair. */
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

/* ---- Input-register state (TDS §2.7) ---- */

static uint16_t r_dir_inst;    /* 30001 (direction build; else 0)   */
static uint16_t r_speed_inst;  /* 30002 (speed build; else 0)       */
static uint16_t r_dir_avg;     /* 30003 (stage E)                   */
static uint16_t r_speed_avg;   /* 30004 (stage E)                   */
static uint16_t r_raw_diag;    /* 30005: pulse count / raw 10-bit   */
static uint16_t r_status;      /* 30006 bitfield (FR-S33)           */
static uint16_t r_uptime_s;    /* 30008, saturating (FR-S34)        */
static uint16_t r_pulse_age_s; /* 30011 (speed build; FR-S36)       */
static uint16_t r_gust;        /* 30012 (stage E; speed build)      */

#define STATUS_FIRST_WINDOW_INCOMPLETE 0x0001 /* bit 0 (FR-S23/S30) */
#define STATUS_AVG_NOT_FILLED          0x0002 /* bit 1 (FR-S23/S30) */
#define STATUS_DIR_FAULT               0x0004 /* bit 2 (FR-S38)     */

static uint16_t input_read(uint16_t addr, bool *ok)
{
	switch (addr) {
	case 0x0000: return r_dir_inst;
	case 0x0001: return r_speed_inst;
	case 0x0002: return r_dir_avg;
	case 0x0003: return r_speed_avg;
	case 0x0004: return r_raw_diag;
	case 0x0005: return r_status;
	case 0x0006: return (uint16_t)((BUILD_TYPE << 8) | FW_VERSION);
	case 0x0007: return r_uptime_s;
	case 0x0008: return mb_crc_error_count();
	case 0x0009: return mb_served_count();
	case 0x000A: return r_pulse_age_s;
	case 0x000B: return r_gust;
	default:
		*ok = false; /* FR-MB13/14: exception 02 past the map edge */
		return 0;
	}
}

static mb_config_t cfg;

static uint16_t shadow_window;
static uint16_t shadow_avg;

void regs_init(uint8_t mb_address)
{
	cfg.address = mb_address;
	cfg.holdings = holdings;
	cfg.n_holdings = (uint8_t)(sizeof(holdings) / sizeof(holdings[0]));
	cfg.input_read = input_read;
	cfg.cross_validate = cross_validate;

	r_status = STATUS_FIRST_WINDOW_INCOMPLETE | STATUS_AVG_NOT_FILLED;
	shadow_window = h_window;
	shadow_avg = h_avg;
	avg_config(h_window, h_avg);
}

void regs_service(void)
{
	/* FR-S30: a valid write to 40002 or 40003 clears the averaging
	 * accumulator; 30003/30004/30012 RETAIN their last published values
	 * until the first new window completes (the publishers overwrite
	 * them); status bits 0/1 re-assert. */
	if (h_window != shadow_window || h_avg != shadow_avg) {
		shadow_window = h_window;
		shadow_avg = h_avg;
		avg_config(h_window, h_avg);
		r_status |= STATUS_FIRST_WINDOW_INCOMPLETE | STATUS_AVG_NOT_FILLED;
	}
}

const mb_config_t *regs_cfg(void)
{
	return &cfg;
}

uint16_t regs_offset_0_1deg(void) { return h_offset; }
uint16_t regs_window_ms(void)     { return h_window; }
uint16_t regs_avg_s(void)         { return h_avg; }
uint16_t regs_cutoff_0_1ms(void)  { return h_cutoff; }

void regs_second_tick(void)
{
	if (r_uptime_s < 0xFFFF)
		r_uptime_s++; /* FR-S34: saturating */
#ifdef SENSOR_WIND_SPEED
	if (r_pulse_age_s < 0xFFFF)
		r_pulse_age_s++; /* FR-S36: window handler zeroes it on pulses */
#endif
}

void regs_window_aborted(void)
{
	/* FR-S30/FR-S33: bit 0 re-asserts until the restarted window
	 * completes (a publish clears it). */
	r_status |= STATUS_FIRST_WINDOW_INCOMPLETE;
}

#ifdef SENSOR_WIND_SPEED
void regs_publish_speed(uint16_t count, uint16_t inst_0_1ms)
{
	r_raw_diag = count;        /* 30005: raw pulse count (FR-S08)     */
	r_speed_inst = inst_0_1ms; /* 30002: FR-S06/S07/S27 applied       */
	if (count > 0)
		r_pulse_age_s = 0;     /* FR-S36 */

	avg_add_speed(inst_0_1ms); /* FR-S13 boxcar entry                 */
	r_speed_avg = avg_speed(); /* 30004: partial mean during warm-up  */
	r_gust = avg_gust();       /* 30012 (FR-S37)                      */

	r_status &= (uint16_t)~STATUS_FIRST_WINDOW_INCOMPLETE; /* FR-S23 */
	if (avg_filled())
		r_status &= (uint16_t)~STATUS_AVG_NOT_FILLED;
}
#endif

#ifdef SENSOR_WIND_DIRECTION
void regs_dir_update(uint16_t raw16, uint16_t angle_0_1deg, bool floating)
{
	r_raw_diag = (uint16_t)(raw16 / 16); /* 30005: 10-bit view (§2.7) */
	if (floating) {
		r_status |= STATUS_DIR_FAULT;    /* FR-S38 */
		r_dir_inst = 65535;
		r_dir_avg = 65535;
	} else {
		r_status &= (uint16_t)~STATUS_DIR_FAULT;
		r_dir_inst = angle_0_1deg;
	}
}

void regs_publish_dir_window(int16_t sin_q15, int16_t cos_q15)
{
	avg_add_dir(sin_q15, cos_q15); /* FR-S14 circular boxcar entry */
	if (!(r_status & STATUS_DIR_FAULT))
		r_dir_avg = avg_dir(); /* 30003 */
	r_status &= (uint16_t)~STATUS_FIRST_WINDOW_INCOMPLETE; /* FR-S23 */
	if (avg_filled())
		r_status &= (uint16_t)~STATUS_AVG_NOT_FILLED;
}
#endif

#ifdef TEST_HOOKS
bool regs_test_hang_requested(void)
{
	return test_hang == 0xDEAD;
}
#endif
