#include "avg.h"

#ifdef HAVE_WIND_DIRECTION
#include "circmean.h"
#endif

#define SLOTS 64 /* FR-S31: storage bound; blocks of ceil(N/64) above 64 */

static uint16_t block_size;   /* windows per slot (shared config)     */
static uint16_t n_target;     /* N: windows in a full averaging span  */
static uint8_t n_slots;       /* ring depth = ceil(N / block_size)    */

/* Per-sensor ring cursor. A combined build runs two rings that advance from
 * the SAME 40002 window boundaries but may close a window a loop pass apart
 * (independent meas services), so the cursor state MUST be per-sensor —
 * sharing it would double-advance the ring on the same window. */
typedef struct {
	uint32_t windows_seen; /* since last clear (for avg_filled) */
	uint8_t slot_count;    /* filled slots in the ring          */
	uint8_t slot_head;     /* next slot to (over)write          */
	uint16_t in_block;     /* windows in the open block         */
} cursor_t;

#ifdef HAVE_WIND_SPEED
static cursor_t cur_s;
static uint16_t s_mean[SLOTS]; /* per-slot mean speed (0.1 m/s) */
static uint16_t s_max[SLOTS];  /* per-slot max window speed     */
static uint32_t b_sum;         /* open block accumulator        */
static uint16_t b_max;
#endif
#ifdef HAVE_WIND_DIRECTION
static cursor_t cur_d;
static int16_t d_sin[SLOTS]; /* per-slot mean sin/cos (Q15) */
static int16_t d_cos[SLOTS];
static int32_t b_sin;        /* open block accumulators     */
static int32_t b_cos;
#endif

static void cursor_reset(cursor_t *c)
{
	c->windows_seen = 0;
	c->slot_count = 0;
	c->slot_head = 0;
	c->in_block = 0;
}

void avg_config(uint16_t window_ms, uint16_t avg_s)
{
	uint32_t n = ((uint32_t)avg_s * 1000u) / window_ms;
	if (n < 1)
		n = 1; /* unreachable when FR-S31 is enforced; belt & braces */
	n_target = (uint16_t)n;
	block_size = (uint16_t)((n + SLOTS - 1) / SLOTS);
	/* Ring depth = exactly the averaging span, NOT the full array: a
	 * 64-deep ring for N=10 would average the last 64 windows (bench bug:
	 * stale entries diluted the mean and pinned the gust). */
	n_slots = (uint8_t)((n_target + block_size - 1) / block_size);

#ifdef HAVE_WIND_SPEED
	cursor_reset(&cur_s);
	b_sum = 0;
	b_max = 0;
#endif
#ifdef HAVE_WIND_DIRECTION
	cursor_reset(&cur_d);
	b_sin = 0;
	b_cos = 0;
#endif
}

bool avg_filled(void)
{
	/* Full averaging span acquired. On a combined build both rings fill
	 * from the same window boundaries within a loop pass — require BOTH so
	 * status bit 1 clears only once genuinely warm. */
#if defined(HAVE_WIND_SPEED) && defined(HAVE_WIND_DIRECTION)
	return cur_s.windows_seen >= n_target && cur_d.windows_seen >= n_target;
#elif defined(HAVE_WIND_SPEED)
	return cur_s.windows_seen >= n_target;
#else
	return cur_d.windows_seen >= n_target;
#endif
}

/* One window into the cursor; true when the open block just filled (caller
 * writes its slot at slot_head, then calls cursor_close). */
static bool cursor_tick(cursor_t *c)
{
	if (c->windows_seen < 0xFFFFFFFFu)
		c->windows_seen++;
	return ++c->in_block >= block_size;
}

static void cursor_close(cursor_t *c)
{
	c->slot_head = (uint8_t)((c->slot_head + 1) % n_slots);
	if (c->slot_count < n_slots)
		c->slot_count++;
	c->in_block = 0;
}

#ifdef HAVE_WIND_SPEED
void avg_add_speed(uint16_t inst)
{
	b_sum += inst;
	if (inst > b_max)
		b_max = inst;
	if (cursor_tick(&cur_s)) {
		s_mean[cur_s.slot_head] = (uint16_t)(b_sum / block_size);
		s_max[cur_s.slot_head] = b_max;
		b_sum = 0;
		b_max = 0;
		cursor_close(&cur_s);
	}
}

uint16_t avg_speed(void)
{
	/* FR-S23: mean over only what has been acquired — full slots weighted
	 * by block_size plus the open block's windows; no zero-padding. */
	uint32_t sum = 0;
	uint32_t n = 0;
	for (uint8_t i = 0; i < cur_s.slot_count; i++) {
		sum += (uint32_t)s_mean[i] * block_size;
		n += block_size;
	}
	sum += b_sum;
	n += cur_s.in_block;
	return n ? (uint16_t)(sum / n) : 0;
}

uint16_t avg_gust(void)
{
	uint16_t g = b_max;
	for (uint8_t i = 0; i < cur_s.slot_count; i++)
		if (s_max[i] > g)
			g = s_max[i];
	return g;
}
#endif /* HAVE_WIND_SPEED */

#ifdef HAVE_WIND_DIRECTION
void avg_add_dir(int16_t sin_q15, int16_t cos_q15)
{
	b_sin += sin_q15;
	b_cos += cos_q15;
	if (cursor_tick(&cur_d)) {
		d_sin[cur_d.slot_head] = (int16_t)(b_sin / block_size);
		d_cos[cur_d.slot_head] = (int16_t)(b_cos / block_size);
		b_sin = 0;
		b_cos = 0;
		cursor_close(&cur_d);
	}
}

uint16_t avg_dir(void)
{
	/* Weighted circular mean: slots carry block_size windows each, the
	 * open block carries in_block. atan2 is scale-invariant, so weighting
	 * the sums is sufficient. */
	int32_t ys = 0;
	int32_t xs = 0;
	for (uint8_t i = 0; i < cur_d.slot_count; i++) {
		ys += (int32_t)d_sin[i] * block_size;
		xs += (int32_t)d_cos[i] * block_size;
	}
	ys += b_sin;
	xs += b_cos;
	if (cur_d.slot_count == 0 && cur_d.in_block == 0)
		return 65535;
	uint32_t a001 = circmean_atan2_001deg(ys, xs);
	return (uint16_t)(((a001 + 50) / 100) % 3600);
}
#endif /* HAVE_WIND_DIRECTION */
