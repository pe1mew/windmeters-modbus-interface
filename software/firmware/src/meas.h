#ifndef MEAS_H
#define MEAS_H

// Measurement services (integrationPlan.md stage D): called every main-loop
// pass; internally paced. Speed: 40002-driven windows, FR-S06 scaling,
// FR-S07 cut-off, FR-S27 saturation, FR-S30 window-abort semantics.
// Direction: 100 ms updates (FR-S28), offset (FR-S12), sticky float fault
// (FR-S38).

void meas_init(void);
void meas_service(void);

#endif
