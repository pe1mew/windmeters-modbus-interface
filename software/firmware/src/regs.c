#include "avg.h"
#include "persist.h"
#include "regs.h"
#include "sensors.h" /* HAVE_WIND_SPEED/DIRECTION + BUILD_TYPE */
#include "version.h"

/* ---- Holding registers (TDS §2.8: raw addr, min, max, default) ---- */

static uint16_t h_offset = 0;    /* 40001: 0..3599    */
static uint16_t h_window = 1000; /* 40002: 100..60000 */
static uint16_t h_avg = 10;      /* 40003: 1..600 + FR-S31 */
static uint16_t h_cutoff = 4;    /* 40004: 0..50      */

/* Anemometer calibration (FR-S25/FR-S40): the compile-time values below are
 * the FACTORY DEFAULTS (overridable per firmware with -D); the running values
 * are runtime-writable via 40005/40006 and persisted (FR-S39), so one image
 * calibrates any anemometer in the field with no rebuild. FR-S06 speed:
 *   speed_0.1ms = count * h_ws_c * 10 / (window_ms * h_ws_ppr)
 * — folding pulses-per-rotation into the divisor keeps full pulse resolution. */
#ifndef WS_C_SCALED
#define WS_C_SCALED 980 /* C, 0.001 m/rotation (r = 0.07 m, η = 0.45) */
#endif
#ifndef WS_PULSES_PER_ROTATION
#define WS_PULSES_PER_ROTATION 1
#endif
_Static_assert(WS_C_SCALED >= 1 && WS_C_SCALED <= 6553,
               "default C must be 1..6553 so count*C*10 fits uint32 (FR-S26)");
_Static_assert(WS_PULSES_PER_ROTATION >= 1 && WS_PULSES_PER_ROTATION <= 1000,
               "default pulses/rotation must be 1..1000");
static uint16_t h_ws_c = WS_C_SCALED;              /* 40005: 1..6553 */
static uint16_t h_ws_ppr = WS_PULSES_PER_ROTATION; /* 40006: 1..1000 */

#ifdef TEST_HOOKS
static uint16_t test_hang;       /* 0x00FF, TEST builds only (FR-S20 hook) */
#endif

static const mb_holding_t holdings[] = {
	{0x0000, 0, 3599, &h_offset},
	{0x0001, 100, 60000, &h_window},
	{0x0002, 1, 600, &h_avg},
	{0x0003, 0, 50, &h_cutoff},
	{0x0004, 1, 6553, &h_ws_c},   /* 40005 anemometer C (0.001 m/rot) */
	{0x0005, 1, 1000, &h_ws_ppr}, /* 40006 anemometer pulses/rotation */
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
#ifdef SENSOR_WIND_COMBINED
static uint16_t r_dir_raw;     /* 30013: direction raw ADC — combined
                                * build only; 30005 carries the speed
                                * pulse count here (integrationPlan §10) */
#endif

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
#ifdef SENSOR_WIND_COMBINED
	case 0x000C: return r_dir_raw; /* 30013: combined-only, extends the map */
#endif
	default:
		*ok = false; /* FR-MB13/14: exception 02 past the map edge */
		return 0;
	}
}

static mb_config_t cfg;

static uint16_t shadow_window;
static uint16_t shadow_avg;
#ifdef HAVE_WIND_SPEED
static uint16_t shadow_ws_c;   /* only the speed path resets on a cal change */
static uint16_t shadow_ws_ppr;
#endif

/* FR-S39: last-persisted snapshot. Gates flash access — regs_persist_service
 * only touches flash when a holding register differs from this. */
static persist_settings_t persisted;

void regs_init(uint8_t mb_address)
{
	cfg.address = mb_address;
	cfg.holdings = holdings;
	cfg.n_holdings = (uint8_t)(sizeof(holdings) / sizeof(holdings[0]));
	cfg.input_read = input_read;
	cfg.cross_validate = cross_validate;

	/* FR-S39: seed the holdings from persistent storage; a blank/corrupt
	 * store leaves the compile-time defaults (FR-S21 defined state). */
	persist_settings_t ps;
	if (persist_load(&ps)) {
		h_offset = ps.offset;
		h_window = ps.window;
		h_avg = ps.avg;
		h_cutoff = ps.cutoff;
		h_ws_c = ps.ws_c;
		h_ws_ppr = ps.ws_ppr;
	}
	persisted.offset = h_offset;
	persisted.window = h_window;
	persisted.avg = h_avg;
	persisted.cutoff = h_cutoff;
	persisted.ws_c = h_ws_c;
	persisted.ws_ppr = h_ws_ppr;

	r_status = STATUS_FIRST_WINDOW_INCOMPLETE | STATUS_AVG_NOT_FILLED;
	shadow_window = h_window;
	shadow_avg = h_avg;
#ifdef HAVE_WIND_SPEED
	shadow_ws_c = h_ws_c;
	shadow_ws_ppr = h_ws_ppr;
#endif
	avg_config(h_window, h_avg);
}

void regs_persist_service(void)
{
	/* FR-S39: persist a changed holding set. The RAM compare gates flash
	 * access (no read/write unless something actually changed since the
	 * last save); persist_save is a no-op if it already matches flash.
	 * Called from the main loop AFTER the Modbus response, so the ~6 ms
	 * flash op never lands in the response path (FR-MB20/21). */
	if (h_offset == persisted.offset && h_window == persisted.window &&
	    h_avg == persisted.avg && h_cutoff == persisted.cutoff &&
	    h_ws_c == persisted.ws_c && h_ws_ppr == persisted.ws_ppr)
		return;
	persisted.offset = h_offset;
	persisted.window = h_window;
	persisted.avg = h_avg;
	persisted.cutoff = h_cutoff;
	persisted.ws_c = h_ws_c;
	persisted.ws_ppr = h_ws_ppr;
	persist_save(&persisted);
}

void regs_service(void)
{
	/* FR-S30: a valid write to 40002/40003 clears the averaging accumulator;
	 * 30003/30004/30012 RETAIN their last published values until the first
	 * new window completes (the publishers overwrite them); status bits 0/1
	 * re-assert. */
	bool changed = h_window != shadow_window || h_avg != shadow_avg;
#ifdef HAVE_WIND_SPEED
	/* FR-S40: a calibration change (40005/40006) rescales the speed, so the
	 * boxcar must not mix old- and new-scale entries — clear it too. Speed
	 * path only: on a direction-only build 40005/40006 are inert (FR-MB27),
	 * so a write there must NOT touch the direction average. */
	changed = changed || h_ws_c != shadow_ws_c || h_ws_ppr != shadow_ws_ppr;
#endif
	if (changed) {
		shadow_window = h_window;
		shadow_avg = h_avg;
#ifdef HAVE_WIND_SPEED
		shadow_ws_c = h_ws_c;
		shadow_ws_ppr = h_ws_ppr;
#endif
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
uint16_t regs_ws_c(void)          { return h_ws_c; }   /* 40005, 0.001 m/rot */
uint16_t regs_ws_ppr(void)        { return h_ws_ppr; } /* 40006, pulses/rot  */

void regs_second_tick(void)
{
	if (r_uptime_s < 0xFFFF)
		r_uptime_s++; /* FR-S34: saturating */
#ifdef HAVE_WIND_SPEED
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

#ifdef HAVE_WIND_SPEED
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

#ifdef HAVE_WIND_DIRECTION
void regs_dir_update(uint16_t raw16, uint16_t angle_0_1deg, bool floating)
{
#ifdef SENSOR_WIND_COMBINED
	r_dir_raw = (uint16_t)(raw16 / 16);  /* 30013: speed owns 30005 here */
#else
	r_raw_diag = (uint16_t)(raw16 / 16); /* 30005: 10-bit view (§2.7) */
#endif
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
#endif /* HAVE_WIND_DIRECTION */

#ifdef TEST_HOOKS
bool regs_test_hang_requested(void)
{
	return test_hang == 0xDEAD;
}
#endif
