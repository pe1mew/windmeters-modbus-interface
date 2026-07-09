#ifndef SENSORS_H
#define SENSORS_H

/*
 * Build-variant selection (TDS FR-S01/FR-S02, integrationPlan.md §10).
 *
 * platformio.ini sets exactly ONE of these via -D:
 *   SENSOR_WIND_SPEED       — anemometer only        (build 0x01, addr 30/35)
 *   SENSOR_WIND_DIRECTION   — vane only              (build 0x02, addr 31/36)
 *   SENSOR_WIND_COMBINED    — both sensors, one slave (build 0x03, addr 32/37)
 *
 * The rest of the firmware keys off the derived CAPABILITY macros below, so
 * a combined build simply has both capabilities and every per-sensor block
 * compiles in. Keep the raw SENSOR_* selectors for the few places that must
 * distinguish "combined" specifically (e.g. the 30005/30013 raw-diagnostic
 * split — one slave carries both, so the direction raw view moves off the
 * shared 30005 slot).
 */

#if defined(SENSOR_WIND_COMBINED)
#define HAVE_WIND_SPEED
#define HAVE_WIND_DIRECTION
#define BUILD_TYPE 0x03
#elif defined(SENSOR_WIND_SPEED)
#define HAVE_WIND_SPEED
#define BUILD_TYPE 0x01
#elif defined(SENSOR_WIND_DIRECTION)
#define HAVE_WIND_DIRECTION
#define BUILD_TYPE 0x02
#else
#error "Define one of SENSOR_WIND_SPEED / SENSOR_WIND_DIRECTION / " \
       "SENSOR_WIND_COMBINED (select a PlatformIO env)"
#endif

#endif /* SENSORS_H */
