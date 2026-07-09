/**
 * @file persist.h
 * @brief Non-volatile storage for the four persisted holding registers (FR-S39).
 *
 * The four master-writable holding registers (40001 north offset, 40002
 * measurement window, 40003 averaging window, 40004 low-speed cut-off) survive
 * reset and power-loss, so an installation constant such as the north offset,
 * or any set-once knob, need not be re-applied by the Modbus master after every
 * reset. Flash-emulated because the CH32V003 has no EEPROM.
 *
 * @par Storage layout
 * Two 64-byte flash pages in the top 128 B of flash (inside the NFR-RES01
 * reserved region, so they can never overlap program code) form a ping-pong
 * log: one 16-byte record per page. Each record carries a monotonic sequence
 * number, a magic word and a CRC16; the newest valid (highest sequence) record
 * wins. Writing the page that does @b not hold the current record keeps that
 * record valid until the new one commits, which makes the store power-loss
 * safe. Writes are save-on-change (nothing is written when the values are
 * unchanged), so endurance — on the order of 20k writes across the two pages —
 * is never a concern for configuration data.
 *
 * Consumed by the register image (@ref regs.h): @ref persist_load seeds the
 * holding registers at boot and @ref persist_save is driven from
 * @ref regs_persist_service after the Modbus response has been sent.
 */
#ifndef PERSIST_H
#define PERSIST_H

#include <stdbool.h>
#include <stdint.h>

/**
 * @brief The four persisted holding registers (TDS §2.8), one flash record.
 *
 * Mirrors the master-writable holding set that must survive reset/power-loss
 * (FR-S39). Field order and 16-bit width match the on-flash record; each field
 * carries the same scaled encoding the register image exposes (@ref regs.h).
 */
typedef struct {
	uint16_t offset; /**< 40001 — north offset applied to the raw heading, 0.1° units (@ref regs_offset_0_1deg). */
	uint16_t window; /**< 40002 — measurement window, ms (@ref regs_window_ms). */
	uint16_t avg;    /**< 40003 — averaging window, s (@ref regs_avg_s). */
	uint16_t cutoff; /**< 40004 — low-speed cut-off, 0.1 m/s (@ref regs_cutoff_0_1ms). */
} persist_settings_t;

/**
 * @brief Load the newest valid stored record into @p out.
 *
 * Scans both ping-pong pages and copies the highest-sequence record whose
 * magic word and CRC16 both check out.
 *
 * @param out Destination for the persisted settings; written only on success,
 *            left untouched otherwise.
 * @return @c true if a valid record was found and copied; @c false if the
 *         store is blank or corrupt.
 * @note On @c false the caller keeps its compile-time defaults — the FR-S21
 *       defined state still holds when nothing is stored.
 */
bool persist_load(persist_settings_t *out);

/**
 * @brief Persist @p s to flash if it differs from the newest stored record.
 *
 * Save-on-change: if the current record already matches @p s, nothing is
 * written. Otherwise a new record (sequence = current + 1) is programmed into
 * the opposite ping-pong page, then read back and verified, retrying once on
 * mismatch. A write that stays unconfirmed leaves the previous valid record in
 * place — a failure loses only the newest change, never corrupts the store and
 * never busy-loops the main loop.
 *
 * @param s Settings to persist.
 * @return @c true if the store already held @p s or a verified write
 *         succeeded; @c false if the write could not be confirmed after the
 *         retry.
 * @warning BLOCKING (~6 ms: page erase + program). Call from the main loop
 *          @b after the Modbus response has been sent, never inside the write
 *          handler, to keep the flash operation out of the FR-MB20/21 latency
 *          path.
 * @see persist_load
 * @see regs_persist_service
 */
bool persist_save(const persist_settings_t *s);

#endif /* PERSIST_H */
