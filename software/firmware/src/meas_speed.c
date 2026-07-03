#ifdef SENSOR_WIND_SPEED

#include "ch32fun.h"
#include "meas.h"
#include "regs.h"
#include "ws.h"

// FR-S25: calibration factor, fixed-point 0.001 m/rotation, compile-time
// only (no register). Default = the known r = 0.07 m / η = 0.45 rotor.
// Override per anemometer model with -D WS_C_SCALED=<n> in platformio.ini.
#ifndef WS_C_SCALED
#define WS_C_SCALED 980
#endif
_Static_assert(WS_C_SCALED >= 1 && WS_C_SCALED <= 6553,
               "FR-S25/FR-S26: C_scaled must be 1..6553 so the FR-S06 "
               "intermediate (count*C*10 <= 4,294,508,550) fits uint32");

static uint32_t window_ticks;   // active window length in SysTick ticks
static uint16_t window_ms_active;
static uint32_t t_window;

static uint32_t ms_to_ticks(uint16_t ms)
{
	return (uint32_t)(FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * ms;
}

void meas_init(void)
{
	window_ms_active = regs_window_ms();
	window_ticks = ms_to_ticks(window_ms_active);
	ws_window_start();
	t_window = SysTick->CNT;
}

// FR-S06 (ms domain) + FR-S26 (uint32-safe) + FR-S27 (saturation) +
// FR-S07 (cut-off): returns the value for 30002.
static uint16_t scale(uint16_t count, bool saturated, uint16_t window_ms)
{
	if (saturated)
		return 65535; // FR-S27: never a wrapped value
	uint32_t v = ((uint32_t)count * WS_C_SCALED * 10u) / window_ms;
	if (v > 65535u)
		v = 65535u; // FR-S06 clamp
	if (v < regs_cutoff_0_1ms())
		v = 0; // FR-S07 — 30005 keeps the raw count (FR-S24 rule)
	return (uint16_t)v;
}

void meas_service(void)
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

#endif /* SENSOR_WIND_SPEED */
