#ifndef PERSIST_H
#define PERSIST_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Persistent holding-register storage (TDS FR-S39): the four holding
 * registers survive reset/power-loss, so an installation constant (north
 * offset) or a set-once knob need not be re-applied by the master after
 * every reset. Flash-emulated — the CH32V003 has no EEPROM.
 *
 * Two 64-byte flash pages in the top 128 B of flash form a ping-pong log:
 * one 16-byte record per page, the newest valid (highest sequence) record
 * wins. Power-loss safe (the current record stays valid until the new one
 * commits) and save-on-change (no write when nothing differs), so endurance
 * — ~20k writes over the two pages — is never a concern for configuration.
 */

typedef struct {
	uint16_t offset; /* 40001 */
	uint16_t window; /* 40002 */
	uint16_t avg;    /* 40003 */
	uint16_t cutoff; /* 40004 */
} persist_settings_t;

/* Load the newest valid stored record into *out. Returns true on success;
 * false if the store is blank or corrupt (caller keeps its compile-time
 * defaults — FR-S21 defined state still holds when nothing is stored). */
bool persist_load(persist_settings_t *out);

/* Persist *s if it differs from the newest stored record. Returns true if a
 * flash write occurred. BLOCKING (~6 ms, erase + program) — call from the
 * main loop AFTER the Modbus response has been sent, never inside the write
 * handler (FR-MB20/21 latency). */
bool persist_save(const persist_settings_t *s);

#endif /* PERSIST_H */
