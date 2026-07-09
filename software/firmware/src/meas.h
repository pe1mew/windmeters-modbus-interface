#ifndef MEAS_H
#define MEAS_H

#include "sensors.h"

// Measurement services (integrationPlan.md stage D): called every main-loop
// pass; internally paced. Speed: 40002-driven windows, FR-S06 scaling,
// FR-S07 cut-off, FR-S27 saturation, FR-S30 window-abort semantics.
// Direction: 100 ms updates (FR-S28), offset (FR-S12), sticky float fault
// (FR-S38).
//
// Per-sensor symbols (not a single meas_init/service) so the combined build
// can run BOTH concurrently — one build linked both would otherwise collide
// on duplicate meas_init/meas_service definitions (integrationPlan.md §10).
// Both services share the 40002 window boundaries but keep independent
// window state, so a one-loop-pass skew between them is harmless.

#ifdef HAVE_WIND_SPEED
void meas_speed_init(void);
void meas_speed_service(void);
#endif
#ifdef HAVE_WIND_DIRECTION
void meas_dir_init(void);
void meas_dir_service(void);
#endif

#endif
