#include "sensors.h"
#ifdef HAVE_WIND_SPEED

#include "ch32fun.h"
#include "meas.h"
#include "regs.h"
#include "ws.h"

// Anemometer calibration is runtime-writable + persisted (holding 40005 C and
// 40006 pulses/rotation; FR-S25/FR-S40) — read fresh from regs.c at each
// window so one firmware image serves any anemometer. Defaults + range
// static-asserts live in regs.c.

static uint32_t window_ticks;   // active window length in SysTick ticks
static uint16_t window_ms_active;
static uint32_t t_window;

static uint32_t ms_to_ticks(uint16_t ms)
{
	return (uint32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * ms;
}

void meas_speed_init(void)
{
	window_ms_active = regs_window_ms();
	window_ticks = ms_to_ticks(window_ms_active);
	ws_window_start();
	t_window = SysTick->CNT;
}

// FR-S06 (ms domain) + FR-S26 (uint32-safe) + FR-S27 (saturation) +
// FR-S07 (cut-off): returns the value for 30002.
//   v = count * C * 10 / (window_ms * pulses_per_rotation)
// Numerator count*C*10 <= 65535*6553*10 fits uint32 (regs.c static-assert);
// pulses/rotation is >= 1 (holding min), so no divide-by-zero, and folding it
// into the divisor (not count/ppr) keeps full pulse resolution.
static uint16_t scale(uint16_t count, bool saturated, uint16_t window_ms)
{
	if (saturated)
		return 65535; // FR-S27: never a wrapped value
	uint32_t v = ((uint32_t)count * regs_ws_c() * 10u) /
	             ((uint32_t)window_ms * regs_ws_ppr());
	if (v > 65535u)
		v = 65535u; // FR-S06 clamp
	if (v < regs_cutoff_0_1ms())
		v = 0; // FR-S07 — 30005 keeps the raw count (FR-S24 rule)
	return (uint16_t)v;
}

void meas_speed_service(void)
{
	// FR-S30: a valid write to 40002 aborts the window in progress; the
	// partial count is discarded and a new window of the new duration
	// starts immediately.
	uint16_t cfg_ms = regs_window_ms();
	if (cfg_ms != window_ms_active) {
		window_ms_active = cfg_ms;
		window_ticks = ms_to_ticks(cfg_ms);
		ws_window_start();          // discard partial count
		t_window = SysTick->CNT;
		regs_window_aborted();      // status bit 0 until it completes
		return;
	}

	if ((uint32_t)(SysTick->CNT - t_window) < window_ticks)
		return;
	t_window += window_ticks; // drift-free boundaries (FR-S17)

	bool sat;
	uint16_t count = ws_window_read(&sat);
	ws_window_start();
	regs_publish_speed(count, scale(count, sat, window_ms_active));
}

#endif /* HAVE_WIND_SPEED */
