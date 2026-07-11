#include "persist.h"
#include "ch32fun.h"

/* Top 128 B of the 16 KB flash = two 64-byte pages. This sits inside the
 * NFR-RES01 reserved region (code is gated to 14336 B = 0x3800), so it can
 * never overlap program code. */
#define PAGE_A     0x08003F80u
#define PAGE_B     0x08003FC0u
#define PAGE_SIZE  64u
#define STORE_MAGIC 0x5748u /* 'WH' — bumped from 0x5747 when the record grew
                             * to six holdings; a pre-existing 4-holding record
                             * fails this magic + the CRC, so it reads as
                             * invalid and the store falls back to defaults
                             * (clean format migration, no versioning needed) */

typedef struct {
	uint32_t seq;    /* monotonic; highest valid record is current      */
	uint16_t offset; /* 40001 */
	uint16_t window; /* 40002 */
	uint16_t avg;    /* 40003 */
	uint16_t cutoff; /* 40004 */
	uint16_t ws_c;   /* 40005 anemometer calibration C (0.001 m/rotation) */
	uint16_t ws_ppr; /* 40006 anemometer pulses per rotation */
	uint16_t magic;  /* STORE_MAGIC */
	uint16_t crc;    /* crc16 over the preceding 18 bytes */
} rec_t;

_Static_assert(sizeof(rec_t) == 20, "rec_t must be 20 bytes");

static uint16_t crc16(const uint8_t *p, uint16_t n)
{
	uint16_t crc = 0xFFFF;
	while (n--) {
		crc ^= *p++;
		for (uint8_t i = 0; i < 8; i++)
			crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
	}
	return crc;
}

static bool rec_valid(const rec_t *r)
{
	return r->magic == STORE_MAGIC &&
	       crc16((const uint8_t *)r, 18) == r->crc;
}

/* The page holding the newest valid record, or 0 if the store is empty. */
static const rec_t *newest(void)
{
	const rec_t *a = (const rec_t *)PAGE_A;
	const rec_t *b = (const rec_t *)PAGE_B;
	bool va = rec_valid(a), vb = rec_valid(b);
	if (va && vb)
		return (a->seq >= b->seq) ? a : b;
	if (va)
		return a;
	if (vb)
		return b;
	return 0;
}

bool persist_load(persist_settings_t *out)
{
	const rec_t *r = newest();
	if (!r)
		return false;
	out->offset = r->offset;
	out->window = r->window;
	out->avg = r->avg;
	out->cutoff = r->cutoff;
	out->ws_c = r->ws_c;
	out->ws_ppr = r->ws_ppr;
	return true;
}

/* Erase + fast-program one 64-byte page with the record (rest = 0xFF).
 * Sequence per ch32v003fun flashtest; runs from flash (the controller
 * stalls the bus during the op). No ISRs to worry about (zero-ISR design);
 * the ~6 ms block is well inside the ~1 s IWDG window. */
static void flash_write_record(uint32_t page_addr, const rec_t *r)
{
	uint32_t buf[PAGE_SIZE / 4];
	for (unsigned i = 0; i < PAGE_SIZE / 4; i++)
		buf[i] = 0xFFFFFFFFu;
	__builtin_memcpy(buf, r, sizeof(rec_t));

	FLASH->KEYR = FLASH_KEY1;
	FLASH->KEYR = FLASH_KEY2;
	FLASH->MODEKEYR = FLASH_KEY1; /* unlock fast program/erase */
	FLASH->MODEKEYR = FLASH_KEY2;

	FLASH->CTLR = CR_PAGE_ER; /* fast 64-byte page erase */
	FLASH->ADDR = page_addr;
	FLASH->CTLR = CR_STRT_Set | CR_PAGE_ER;
	while (FLASH->STATR & FLASH_STATR_BSY)
		;

	FLASH->CTLR = CR_PAGE_PG; /* fast page program */
	FLASH->CTLR = CR_BUF_RST | CR_PAGE_PG;
	FLASH->ADDR = page_addr;
	while (FLASH->STATR & FLASH_STATR_BSY)
		;
	volatile uint32_t *dst = (volatile uint32_t *)page_addr;
	for (unsigned i = 0; i < PAGE_SIZE / 4; i++) {
		dst[i] = buf[i];
		FLASH->CTLR = CR_PAGE_PG | FLASH_CTLR_BUF_LOAD;
		while (FLASH->STATR & FLASH_STATR_BSY)
			;
	}
	FLASH->CTLR = CR_PAGE_PG | CR_STRT_Set;
	while (FLASH->STATR & FLASH_STATR_BSY)
		;

	FLASH->CTLR = FLASH_CTLR_LOCK | FLASH_CTLR_FLOCK; /* re-lock */
}

bool persist_save(const persist_settings_t *s)
{
	const rec_t *cur = newest();
	if (cur && cur->offset == s->offset && cur->window == s->window &&
	    cur->avg == s->avg && cur->cutoff == s->cutoff &&
	    cur->ws_c == s->ws_c && cur->ws_ppr == s->ws_ppr)
		return true; /* unchanged — flash already holds it, spare the write */

	/* Ping-pong: write the page NOT holding the current record, so the
	 * current record stays valid until the new one commits (power-loss
	 * safe). A blank store (cur == 0) writes page A. */
	uint32_t target = (cur == (const rec_t *)PAGE_A) ? PAGE_B : PAGE_A;
	rec_t r;
	r.seq = cur ? cur->seq + 1u : 1u;
	r.offset = s->offset;
	r.window = s->window;
	r.avg = s->avg;
	r.cutoff = s->cutoff;
	r.ws_c = s->ws_c;
	r.ws_ppr = s->ws_ppr;
	r.magic = STORE_MAGIC;
	r.crc = crc16((const uint8_t *)&r, 18);

	/* Write, then read back and verify; retry once on mismatch (guards a
	 * silent flash-write failure). If still unconfirmed the store keeps its
	 * previous valid record (power-loss safe) — a failure loses only the
	 * newest change, never corrupts, and never busy-loops the main loop. */
	const rec_t *w = (const rec_t *)target;
	for (int attempt = 0; attempt < 2; attempt++) {
		flash_write_record(target, &r);
		if (rec_valid(w) && w->seq == r.seq && w->offset == s->offset &&
		    w->window == s->window && w->avg == s->avg &&
		    w->cutoff == s->cutoff && w->ws_c == s->ws_c &&
		    w->ws_ppr == s->ws_ppr)
			return true;
	}
	return false;
}
