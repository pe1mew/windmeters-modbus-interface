#ifndef MB_H
#define MB_H

#include <stdbool.h>
#include <stdint.h>

// Modbus RTU slave driver — USART1 single-wire half-duplex on PD6 (HDSEL,
// TX remapped) with DE/RE on PC2. Implements the TDS §2 driver layer:
// framing/CRC (FR-MB01/02), t3.5 gap detect (FR-MB03), DE timing
// (FR-MB04), address filter + broadcast ignore (FR-MB05/06), FC03/04/06/16
// (FR-MB08..11), exceptions 01/02/03 (FR-MB12/13/15/18), no-clamp range
// rejection (FR-MB19), atomic FC16 (FR-MB22), self-echo discard while
// transmitting + idle re-arm (FR-MB23), receive-error/garbage robustness
// with a 256-byte ADU buffer (FR-MB24), big-endian data / little-endian
// CRC (FR-MB25), FC06 echo & FC16 confirm responses (FR-MB30), post-reset
// bus-idle sync (FR-S19).
//
// Register semantics stay application-side: the app owns the holding
// table (with per-register min/max, FR-MB19), an input-read callback
// (ok=false -> exception 02), and an optional cross-validate hook for
// multi-register constraints (FR-S31).

typedef struct {
	uint16_t addr; // raw 0-based wire address
	uint16_t min;
	uint16_t max;
	uint16_t *value;
} mb_holding_t;

typedef struct {
	uint8_t address; // slave address, 1..247
	const mb_holding_t *holdings;
	uint8_t n_holdings;
	// Read one input register; set *ok=false if addr is unmapped.
	uint16_t (*input_read)(uint16_t addr, bool *ok);
	// Optional (may be NULL): veto a staged write set (FR-S31-style
	// cross-register constraints). Return false -> exception 03, nothing
	// committed.
	bool (*cross_validate)(const uint16_t *addrs, const uint16_t *vals,
	                       uint8_t n);
} mb_config_t;

void mb_init(const mb_config_t *cfg);
void mb_poll(void); // call from the main loop; self-timed via SysTick

// Diagnostics (future input registers 30009/30010 + bench visibility).
uint16_t mb_crc_error_count(void);
uint16_t mb_served_count(void);
uint16_t mb_fe_count(void);  // framing errors (frame-poisoning)
uint16_t mb_ne_count(void);  // noise flags (benign, byte kept)
uint16_t mb_ore_count(void); // overruns (frame-poisoning)
uint16_t mb_last_bad(uint8_t word); // last CRC-fail frame: 0:len 1:b0b1 2:b2b3 3:rx-crc

#endif
