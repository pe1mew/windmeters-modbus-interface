/**
 * @file sensors.h
 * @brief Build-variant selection → capability-macro mapping (TDS FR-S01/FR-S02).
 *
 * Turns the single build-variant selector that `platformio.ini` passes on the
 * command line (`-D`, see `design/integrationPlan.md` §10) into the derived
 * capability macros the rest of the firmware keys off. Exactly one raw
 * selector is defined per build:
 *
 *   - `SENSOR_WIND_SPEED`     — anemometer only         (build 0x01, addr 30/35)
 *   - `SENSOR_WIND_DIRECTION` — vane only               (build 0x02, addr 31/36)
 *   - `SENSOR_WIND_COMBINED`  — both sensors, one slave (build 0x03, addr 32/37)
 *
 * A combined build simply gains @b both capability macros, so every per-sensor
 * block (@ref regs.h "register image", @ref meas.h "measurement services")
 * compiles in unchanged. The raw `SENSOR_*` selectors are kept for the few
 * places that must distinguish "combined" specifically — e.g. the 30005/30013
 * raw-diagnostic split (@ref regs.h, FR-MB27): one slave carries both sensors,
 * so the direction raw view moves off the shared 30005 slot onto 30013.
 *
 * @note This header is self-contained: it declares no functions and includes
 *       nothing — it is a pure preprocessor mapping consumed at compile time.
 * @see board.h for the matching pin/address map of each variant.
 */
#ifndef SENSORS_H
#define SENSORS_H

#if defined(SENSOR_WIND_COMBINED)
#define HAVE_WIND_SPEED     /**< Capability: anemometer front-end present — gates the speed measurement/publish path (@ref regs_publish_speed). */
#define HAVE_WIND_DIRECTION /**< Capability: vane front-end present — gates the direction measurement/publish path (@ref regs_dir_update). */
#define BUILD_TYPE 0x03     /**< Combined build code; high byte of input register 30007 (`0x0006`), low byte is `FW_VERSION` (regs.c). */
#elif defined(SENSOR_WIND_SPEED)
#define HAVE_WIND_SPEED     /**< Capability: anemometer front-end present (see combined-build definition). */
#define BUILD_TYPE 0x01     /**< Speed-only build code; reported in the high byte of input register 30007 (`0x0006`). */
#elif defined(SENSOR_WIND_DIRECTION)
#define HAVE_WIND_DIRECTION /**< Capability: vane front-end present (see combined-build definition). */
#define BUILD_TYPE 0x02     /**< Direction-only build code; reported in the high byte of input register 30007 (`0x0006`). */
#else
/* No build variant selected — fail the compile with a directive telling the
 * integrator to pick a PlatformIO env (FR-S01). Never silently default. */
#error "Define one of SENSOR_WIND_SPEED / SENSOR_WIND_DIRECTION / " \
       "SENSOR_WIND_COMBINED (select a PlatformIO env)"
#endif

#endif /* SENSORS_H */
