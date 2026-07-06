#include "ch32fun.h"
#include "mb.h"

#define MB_BAUD      9600u
#define MB_ADU_MAX   256u                         // FR-MB24
// t3.5 in SysTick ticks (HCLK). One character = 11 bits per the Modbus
// spec basis (TDS FR-MB03): 3.5 x 11 / 9600 = 4.01 ms.
#define MB_GAP_TICKS ((FUNCONF_SYSTEM_CORE_CLOCK / 1000u) * 4u + \
                      (FUNCONF_SYSTEM_CORE_CLOCK / 100000u))     // 4.01 ms

#define AFIO_PCFR1_USART1_RM_BIT  (1u << 2)
#define AFIO_PCFR1_USART1_RM1_BIT (1u << 21)

static const mb_config_t *g_cfg;

// ISR <-> main-loop shared state (SPSC per softwareArchitecture.md §4).
static volatile uint8_t  rx_buf[MB_ADU_MAX];
static volatile uint16_t rx_len;
static volatile uint32_t last_rx_ticks;
static volatile uint8_t  rx_error;      // ORE/FE/NE or overflow this frame
static volatile uint8_t  tx_active;     // FR-MB23: discard own echo
static volatile uint8_t  synced;        // FR-S19: wait for bus idle first

static uint16_t crc_errors;
static uint16_t served;
static uint16_t fe_count, ne_count, ore_count; // RX-error diagnostics
static uint16_t bad_len;                        // last CRC-failing frame:
static uint8_t bad_head[4];                     //   first 4 bytes
static uint8_t bad_tail[2];                     //   received CRC bytes

static uint8_t tx_buf[MB_ADU_MAX];

// RX servicing — POLLED, not interrupt-driven. Bench history (2026-07-03):
// with the RXNE ISR, ~1/3 of frames arrived at the frame parser with
// missing leading bytes / scrambled values while the wire was verified
// pristine and no USART error flag ever set — symptoms consistent with
// ISR prologue/state corruption on this RV32EC toolchain path. The main
// loop spins in ~1 µs versus 1042 µs per byte at 9600 baud, so polling
// cannot miss bytes and needs no ISR at all (softwareArchitecture.md
// updated accordingly).
static void mb_rx_service(void)
{
	uint32_t st = USART1->STATR;
	// FE (break/misframe) and ORE (byte lost) poison the frame (FR-MB24).
	// NE alone does not: the majority-vote data is still valid.
	if (st & (USART_STATR_ORE | USART_STATR_FE)) {
		if (st & USART_STATR_FE)
			fe_count++;
		if (st & USART_STATR_ORE)
			ore_count++;
		(void)USART1->DATAR; // STATR-then-DATAR read clears the flags
		rx_error = 1;
		last_rx_ticks = SysTick->CNT;
		return;
	}
	if (st & USART_STATR_NE)
		ne_count++; // benign: cleared by the DATAR read below
	if (st & USART_STATR_RXNE) {
		uint8_t b = (uint8_t)USART1->DATAR;
		last_rx_ticks = SysTick->CNT;
		if (tx_active || !synced)
			return;          // own echo (FR-MB23) / pre-sync (FR-S19)
		if (rx_len < MB_ADU_MAX)
			rx_buf[rx_len++] = b;
		else
			rx_error = 1;    // oversize burst (FR-MB24)
	}
}

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

void mb_init(const mb_config_t *cfg)
{
	g_cfg = cfg;

	// FR-S18/FR-S19: DE low (receiver enabled, driver off) before anything.
	RCC->APB2PCENR |= RCC_APB2Periph_GPIOC | RCC_APB2Periph_GPIOD |
	                  RCC_APB2Periph_USART1 | RCC_APB2Periph_AFIO;
	funPinMode(PC2, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP);
	funDigitalWrite(PC2, FUN_LOW);

	// Line discipline: NO HDSEL. Bench finding (2026-07-03): in HDSEL
	// half-duplex this part intermittently (~35%) swallows the FIRST byte
	// after bus idle with no error flags — the rest of the frame arrives,
	// CRC fails, the frame is silently discarded. Instead we exploit the
	// SOP-8 remap geometry: DEFAULT map has USART1_RX natively on PD6 (TX
	// on unbonded PD5) — a clean full-duplex receive path. For the
	// response, mb_send() temporarily switches to partial remap 2 (TX on
	// PD6), transmits, and switches back. Modbus is strictly
	// request/response, so the direction is always known. Side benefit:
	// no self-echo during reception at all (FR-MB23 satisfied by
	// interrupt-off + flag-clear during the TX window).
	AFIO->PCFR1 &= ~(AFIO_PCFR1_USART1_RM_BIT | AFIO_PCFR1_USART1_RM1_BIT);
	funPinMode(PD6, GPIO_CNF_IN_PUPD); // RX phase: input, pull-up assist
	funDigitalWrite(PD6, FUN_HIGH);

	USART1->BRR = (FUNCONF_SYSTEM_CORE_CLOCK + MB_BAUD / 2) / MB_BAUD;
	USART1->CTLR3 = 0;
	USART1->CTLR1 = USART_CTLR1_TE | USART_CTLR1_RE |
	                USART_CTLR1_UE; // 9600 8N1, polled RX (no RXNEIE)

	rx_len = 0;
	rx_error = 0;
	tx_active = 0;
	synced = 0; // FR-S19: discard until a t3.5 idle is observed
	last_rx_ticks = SysTick->CNT;
}

static void mb_send(const uint8_t *p, uint16_t n)
{
	tx_active = 1;
	// TX phase: remap 2 puts USART1_TX on PD6; pin becomes AF output.
	// Push-pull, NOT open-drain: the MAX3485 tri-states RO while DE is
	// high, so nothing else drives or pulls the node during the response
	// — an open-drain TX only ever drove the start bits and put a solid
	// break on the bus (bench 2026-07-06, first MAX3485 rig session; the
	// TTL rig masked it because its external pull-up supplied the highs).
	// Contention-safe: RO is high-Z for exactly the DE-high window.
	AFIO->PCFR1 |= AFIO_PCFR1_USART1_RM1_BIT;
	funPinMode(PD6, GPIO_Speed_10MHz | GPIO_CNF_OUT_PP_AF);

	funDigitalWrite(PC2, FUN_HIGH);              // DE asserted (FR-MB04)
	for (uint16_t i = 0; i < n; i++) {
		while (!(USART1->STATR & USART_STATR_TXE))
			;
		USART1->DATAR = p[i];
	}
	while (!(USART1->STATR & USART_STATR_TC))
		;
	funDigitalWrite(PC2, FUN_LOW);               // within one char (FR-MB04)

	// Back to RX phase: pin to input, default map (RX on PD6).
	funPinMode(PD6, GPIO_CNF_IN_PUPD);
	funDigitalWrite(PD6, FUN_HIGH);
	AFIO->PCFR1 &= ~AFIO_PCFR1_USART1_RM1_BIT;
	// Discard anything the receiver picked up meanwhile (floating PD5 in
	// the TX window) and re-arm only after a fresh t3.5 idle (FR-MB23).
	(void)USART1->STATR;
	(void)USART1->DATAR;
	tx_active = 0;
	rx_len = 0;
	rx_error = 0;
	last_rx_ticks = SysTick->CNT;
	served++;
}

static void send_exception(uint8_t fc, uint8_t code)
{
	tx_buf[0] = g_cfg->address;
	tx_buf[1] = (uint8_t)(fc | 0x80);
	tx_buf[2] = code; // 01/02/03 only (FR-MB18/FR-MB29)
	uint16_t c = crc16(tx_buf, 3);
	tx_buf[3] = (uint8_t)(c & 0xFF); // CRC low byte first (FR-MB25)
	tx_buf[4] = (uint8_t)(c >> 8);
	mb_send(tx_buf, 5);
}

static const mb_holding_t *find_holding(uint16_t addr)
{
	for (uint8_t i = 0; i < g_cfg->n_holdings; i++)
		if (g_cfg->holdings[i].addr == addr)
			return &g_cfg->holdings[i];
	return 0;
}

static void finish_and_send(uint16_t n) // append CRC, transmit
{
	uint16_t c = crc16(tx_buf, n);
	tx_buf[n] = (uint8_t)(c & 0xFF);
	tx_buf[n + 1] = (uint8_t)(c >> 8);
	mb_send(tx_buf, (uint16_t)(n + 2));
}

static void handle_read(const uint8_t *f, uint16_t len, bool input_space)
{
	uint8_t fc = f[1];
	if (len != 8) {
		send_exception(fc, 0x03);
		return;
	}
	uint16_t addr = (uint16_t)((f[2] << 8) | f[3]); // big-endian (FR-MB25)
	uint16_t qty = (uint16_t)((f[4] << 8) | f[5]);
	if (qty < 1 || qty > 125) {      // FR-MB28, before address validation
		send_exception(fc, 0x03);
		return;
	}
	// Validate the whole range first — no partial data (FR-MB14).
	for (uint16_t i = 0; i < qty; i++) {
		bool ok = true;
		if (input_space) {
			(void)g_cfg->input_read((uint16_t)(addr + i), &ok);
		} else {
			ok = find_holding((uint16_t)(addr + i)) != 0;
		}
		if (!ok) {
			send_exception(fc, 0x02); // FR-MB13
			return;
		}
	}
	tx_buf[0] = g_cfg->address;
	tx_buf[1] = fc;
	tx_buf[2] = (uint8_t)(qty * 2);
	uint16_t n = 3;
	for (uint16_t i = 0; i < qty; i++) {
		bool ok = true;
		uint16_t v = input_space
			? g_cfg->input_read((uint16_t)(addr + i), &ok)
			: *find_holding((uint16_t)(addr + i))->value;
		tx_buf[n++] = (uint8_t)(v >> 8); // big-endian data (FR-MB25)
		tx_buf[n++] = (uint8_t)(v & 0xFF);
	}
	finish_and_send(n);
}

static void handle_write(const uint8_t *f, uint16_t len)
{
	// Stage -> validate all -> commit: FC06 is FC16 with n=1 (FR-MB22).
	uint16_t addrs[8];
	uint16_t vals[8];
	uint8_t n;
	uint8_t fc = f[1];

	if (fc == 0x06) {
		if (len != 8) {
			send_exception(fc, 0x03);
			return;
		}
		addrs[0] = (uint16_t)((f[2] << 8) | f[3]);
		vals[0] = (uint16_t)((f[4] << 8) | f[5]);
		n = 1;
	} else { // FC16
		if (len < 11) {
			send_exception(fc, 0x03);
			return;
		}
		uint16_t qty = (uint16_t)((f[4] << 8) | f[5]);
		uint8_t bytecount = f[6];
		// FR-MB28: quantity/bytecount checks before address validation.
		if (qty < 1 || qty > 123 || bytecount != qty * 2 ||
		    len != (uint16_t)(9 + bytecount)) {
			send_exception(fc, 0x03);
			return;
		}
		if (qty > 8) {
			// More registers than the whole map holds — some address in
			// the range is necessarily unmapped (FR-MB15).
			send_exception(fc, 0x02);
			return;
		}
		uint16_t start = (uint16_t)((f[2] << 8) | f[3]);
		n = (uint8_t)qty;
		for (uint8_t i = 0; i < n; i++) {
			addrs[i] = (uint16_t)(start + i);
			vals[i] = (uint16_t)((f[7 + 2 * i] << 8) | f[8 + 2 * i]);
		}
	}

	// Pass 1: every address mapped (FR-MB15) — nothing committed yet.
	for (uint8_t i = 0; i < n; i++) {
		if (!find_holding(addrs[i])) {
			send_exception(fc, 0x02);
			return;
		}
	}
	// Pass 2: every value in range — reject whole request, no clamping
	// (FR-MB19), atomically (FR-MB22).
	for (uint8_t i = 0; i < n; i++) {
		const mb_holding_t *h = find_holding(addrs[i]);
		if (vals[i] < h->min || vals[i] > h->max) {
			send_exception(fc, 0x03);
			return;
		}
	}
	// Pass 3: cross-register constraints (FR-S31 via app hook).
	if (g_cfg->cross_validate && !g_cfg->cross_validate(addrs, vals, n)) {
		send_exception(fc, 0x03);
		return;
	}
	// Commit.
	for (uint8_t i = 0; i < n; i++)
		*((mb_holding_t *)find_holding(addrs[i]))->value = vals[i];

	if (fc == 0x06) {
		// FR-MB30: byte-exact echo of the request.
		for (uint8_t i = 0; i < 8; i++)
			tx_buf[i] = f[i];
		mb_send(tx_buf, 8);
	} else {
		// FR-MB30: address + quantity confirm.
		tx_buf[0] = g_cfg->address;
		tx_buf[1] = 0x10;
		tx_buf[2] = f[2];
		tx_buf[3] = f[3];
		tx_buf[4] = f[4];
		tx_buf[5] = f[5];
		finish_and_send(6);
	}
}

void mb_poll(void)
{
	mb_rx_service(); // polled RX: drain the data register first

	uint32_t idle = (uint32_t)(SysTick->CNT - last_rx_ticks);

	if (!synced) {
		if (idle >= MB_GAP_TICKS)
			synced = 1; // FR-S19: first t3.5 idle observed
		return;
	}
	if (rx_len == 0 && !rx_error)
		return;
	if (idle < MB_GAP_TICKS)
		return; // frame still in flight (FR-MB03)

	// Snapshot and release the buffer.
	uint16_t len = rx_len;
	uint8_t err = rx_error;
	uint8_t frame[MB_ADU_MAX];
	for (uint16_t i = 0; i < len; i++)
		frame[i] = rx_buf[i];
	rx_len = 0;
	rx_error = 0;

	if (err || len < 4)
		return; // corrupt/runt: discard silently, resync (FR-MB24)
	uint16_t c = crc16(frame, (uint16_t)(len - 2));
	if (frame[len - 2] != (uint8_t)(c & 0xFF) ||
	    frame[len - 1] != (uint8_t)(c >> 8)) {
		crc_errors++;
		bad_len = len; // stash for bench diagnostics (mb_last_bad)
		for (uint8_t i = 0; i < 4; i++)
			bad_head[i] = (i < len) ? frame[i] : 0;
		bad_tail[0] = frame[len - 2];
		bad_tail[1] = frame[len - 1];
		return; // FR-MB02: silent discard
	}
	if (frame[0] != g_cfg->address)
		return; // other unicast or broadcast: silent (FR-MB05/06)

	switch (frame[1]) {
	case 0x03: handle_read(frame, len, false); break;
	case 0x04: handle_read(frame, len, true); break;
	case 0x06:
	case 0x10: handle_write(frame, len); break;
	default:   send_exception(frame[1], 0x01); break; // FR-MB12
	}
}

uint16_t mb_crc_error_count(void) { return crc_errors; }
uint16_t mb_served_count(void)    { return served; }
uint16_t mb_fe_count(void)        { return fe_count; }
uint16_t mb_ne_count(void)        { return ne_count; }
uint16_t mb_ore_count(void)       { return ore_count; }

uint16_t mb_last_bad(uint8_t word) // 0:len 1:b0b1 2:b2b3 3:rx-crc
{
	switch (word) {
	case 0:  return bad_len;
	case 1:  return (uint16_t)((bad_head[0] << 8) | bad_head[1]);
	case 2:  return (uint16_t)((bad_head[2] << 8) | bad_head[3]);
	default: return (uint16_t)((bad_tail[0] << 8) | bad_tail[1]);
	}
}
