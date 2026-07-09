/**
 * @file mb.h
 * @brief Modbus RTU slave driver — the TDS §2 driver layer.
 *
 * USART1 single-wire half-duplex on PD6 (TX remapped via AFIO partial
 * remap 2) with the DE/RE strap on PC2, running 9600 8N1. The driver owns
 * the wire and implements: framing and CRC (FR-MB01/02), t3.5 inter-frame
 * gap detection (FR-MB03), DE assert/de-assert timing (FR-MB04),
 * slave-address filtering with broadcast ignored (FR-MB05/06), function
 * codes FC03/04/06/16 (FR-MB08..11), exception replies 01/02/03
 * (FR-MB12/13/15/18), no-clamp out-of-range rejection (FR-MB19), atomic
 * multi-register writes (FR-MB22), self-echo discard while transmitting
 * plus idle re-arm (FR-MB23), receive-error/garbage robustness over a
 * 256-byte ADU buffer (FR-MB24), big-endian register data with
 * little-endian CRC on the wire (FR-MB25), FC06 echo and FC16
 * address+quantity confirm responses (FR-MB30), and post-reset bus-idle
 * synchronisation (FR-S19).
 *
 * RX is polled, not interrupt-driven: at 9600 baud a byte takes ~1042 µs
 * while the main loop revisits @ref mb_poll roughly every µs, so no byte can
 * be missed and no RXNE ISR is needed — a prior ISR path corrupted ~1/3 of
 * frames on this RV32EC toolchain (see `design/softwareArchitecture.md` §4,
 * which also defines the single-producer/single-consumer ISR↔main split).
 *
 * Register semantics stay application-side — see the register image in
 * @ref regs.h. The app owns the holding table with per-register min/max
 * (FR-MB19), supplies an input-register read callback (ok=false → exception
 * 02), and may supply an optional cross-validate hook for multi-register
 * constraints (FR-S31). It packs all of this into an @ref mb_config_t
 * (via @ref regs_cfg) and hands it to @ref mb_init.
 */
#ifndef MB_H
#define MB_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief One writable holding register the driver may serve and update.
 *
 * The application builds a table of these (see @ref mb_config_t::holdings).
 * FC03 reads and FC06/FC16 writes are matched by @ref addr; a write commits
 * only if the value lies within [@ref min, @ref max] — the driver never
 * clamps, an out-of-range value is rejected with exception 03 (FR-MB19).
 */
typedef struct {
	uint16_t addr; /**< Raw 0-based wire register address (FR-MB27). */
	uint16_t min;  /**< Lowest accepted write value; below → exception 03 (FR-MB19). */
	uint16_t max;  /**< Highest accepted write value; above → exception 03 (FR-MB19). */
	uint16_t *value; /**< App-owned storage: read on FC03, written on commit. */
} mb_holding_t;

/**
 * @brief Application-supplied configuration adopted by @ref mb_init.
 *
 * Wires the generic driver to this device's register image (@ref regs.h):
 * the slave address, the holding-register table, the input-register read
 * callback and an optional cross-register validation hook. The table and
 * callbacks are referenced, not copied, so they must outlive the driver
 * (they are file-scope in the register image).
 */
typedef struct {
	uint8_t address; /**< Slave address, 1..247; frames for any other address are ignored (FR-MB05/06). */
	const mb_holding_t *holdings; /**< Holding-register table for FC03/FC06/FC16. */
	uint8_t n_holdings; /**< Number of entries in @ref holdings. */
	/**
	 * @brief Read one input register (FC04 address space).
	 * @param addr Raw 0-based input-register address requested.
	 * @param ok   Out-param: set to false when @p addr is unmapped, which the
	 *             driver turns into exception 02 (FR-MB13).
	 * @return The register value; ignored by the driver when @p *ok is false.
	 */
	uint16_t (*input_read)(uint16_t addr, bool *ok);
	/**
	 * @brief Optional veto over a staged (not-yet-committed) write set (FR-S31).
	 *
	 * May be NULL. Called after every per-register range check passes but
	 * before any value is committed; returning false rejects the whole
	 * request with exception 03 and commits nothing (atomic, FR-MB22).
	 * @param addrs Register addresses being written, in request order.
	 * @param vals  Proposed values, parallel to @p addrs.
	 * @param n     Number of registers in the staged set.
	 * @return True to allow the commit, false to veto it.
	 */
	bool (*cross_validate)(const uint16_t *addrs, const uint16_t *vals,
	                       uint8_t n);
} mb_config_t;

/**
 * @brief Initialise the driver and bring up USART1 for RS-485 half-duplex.
 *
 * Drives DE low (receiver on, driver off) before touching the line
 * (FR-S18/S19), selects the PD6 default remap for the clean full-duplex
 * receive path, configures USART1 at 9600 8N1 with polled RX, and arms
 * post-reset resynchronisation so nothing is served until the first t3.5
 * bus-idle gap is observed (FR-S19).
 * @param cfg Configuration to adopt. The pointer is retained, so @p cfg and
 *            everything it references must remain valid for the driver's
 *            lifetime. Typically obtained from @ref regs_cfg.
 */
void mb_init(const mb_config_t *cfg);

/**
 * @brief Service the bus once: drain RX, detect frame end, reply.
 *
 * Polls the USART, and once a complete frame is delimited by a t3.5 idle gap
 * (FR-MB03) validates its CRC (FR-MB02) and address (FR-MB05/06) then
 * dispatches FC03/04/06/16, emitting the response or an exception. Call
 * frequently from the main loop; it is self-timed via SysTick and never
 * blocks waiting for input.
 */
void mb_poll(void);

/**
 * @name Diagnostic counters
 * @brief Bench visibility and the basis for future input registers 30009/30010.
 *
 * Each is a free-running 16-bit counter that wraps on overflow; read-only.
 * @{
 */

/**
 * @brief CRC-rejected frames addressed to us (FR-MB02).
 * @return Running count of frames dropped on CRC mismatch.
 */
uint16_t mb_crc_error_count(void);

/**
 * @brief Requests fully served with a response (including exceptions).
 * @return Running count of transmitted responses.
 */
uint16_t mb_served_count(void);

/**
 * @brief USART framing errors (break / misframe).
 * @return Running count; each event poisons its in-flight frame (FR-MB24).
 */
uint16_t mb_fe_count(void);

/**
 * @brief USART noise flags.
 * @return Running count; benign — the majority-vote byte is still kept.
 */
uint16_t mb_ne_count(void);

/**
 * @brief USART overrun errors (an incoming byte was lost).
 * @return Running count; each event poisons its in-flight frame (FR-MB24).
 */
uint16_t mb_ore_count(void);

/**
 * @brief Retrieve one word of the last CRC-failing frame, for bench diagnostics.
 * @param word Which datum to return: 0 = frame length, 1 = wire bytes 0..1
 *             (address, function code), 2 = wire bytes 2..3, 3 = the two
 *             received CRC bytes. Any other value behaves as 3.
 * @return The requested 16-bit datum. Byte pairs are packed big-endian: the
 *         high byte is the earlier byte on the wire.
 * @see mb_crc_error_count
 */
uint16_t mb_last_bad(uint8_t word);

/** @} */

#endif
