#include "sensors.h"
#ifdef HAVE_WIND_DIRECTION

#include "ch32fun.h"
#include "circmean.h"
#include "meas.h"
#include "regs.h"
#include "wd.h"

static uint32_t t_update;
static uint8_t subsample;
static bool fault; // sticky between the 1 Hz float checks (FR-S38)

// Window accumulation for the averaging engine (FR-S13/S14 tie boxcar
// entries to measurement windows on both builds): per-sample sin/cos sums
// -> window circular result at each 40002 boundary. Fault samples are
// excluded (FR-S38).
static uint32_t window_ticks;
static uint16_t window_ms_active;
static uint32_t t_window;
static int32_t w_sin, w_cos;
static uint16_t w_n;

#define UPDATE_TICKS (FUNCONF_SYSTEM_CORE_CLOCK / 10u) /* FR-S28: 10 Hz */

static uint32_t ms_to_ticks(uint16_t ms)
{
	return (uint32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * ms;
}

void meas_dir_init(void)
{
	t_update = SysTick->CNT;
	subsample = 0;
	fault = false;
	window_ms_active = regs_window_ms();
	window_ticks = ms_to_ticks(window_ms_active);
	t_window = SysTick->CNT;
	w_sin = w_cos = 0;
	w_n = 0;
}

void meas_dir_service(void)
{
	/* FR-S30: a 40002 write aborts the window in progress (partial
	 * samples discarded; regs_service clears the accumulator). */
	uint16_t cfg_ms = regs_window_ms();
	if (cfg_ms != window_ms_active) {
		window_ms_active = cfg_ms;
		window_ticks = ms_to_ticks(cfg_ms);
		t_window = SysTick->CNT;
		w_sin = w_cos = 0;
		w_n = 0;
		regs_window_aborted();
		return;
	}

	if ((uint32_t)(SysTick->CNT - t_update) >= UPDATE_TICKS) {
		t_update += UPDATE_TICKS;
		uint16_t raw16 = wd_read_raw16();                           /* FR-S28 */
		uint16_t angle = wd_angle_0_1deg(raw16, regs_offset_0_1deg()); /* FR-S12 */
		if (++subsample >= 10) {
			subsample = 0;
			fault = wd_wiper_floating();                             /* FR-S38 */
		}
		regs_dir_update(raw16, angle, fault);
		if (!fault) { /* FR-S38: fault samples excluded from the mean */
			w_sin += circmean_sin_q15(angle);
			w_cos += circmean_sin_q15((uint16_t)((angle + 900) % 3600));
			w_n++;
		}
	}

	if ((uint32_t)(SysTick->CNT - t_window) >= window_ticks) {
		t_window += window_ticks;
		if (w_n > 0)
			regs_publish_dir_window((int16_t)(w_sin / w_n),
			                        (int16_t)(w_cos / w_n));
		w_sin = w_cos = 0;
		w_n = 0;
	}
}

#endif /* HAVE_WIND_DIRECTION */
