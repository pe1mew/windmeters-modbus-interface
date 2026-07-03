#include "avg.h"

#ifdef SENSOR_WIND_DIRECTION
#include "circmean.h"
#endif

#define SLOTS 64 /* FR-S31: storage bound; blocks of ceil(N/64) above 64 */

static uint16_t block_size;   /* windows per slot                    */
static uint16_t n_target;     /* N: windows in a full averaging span */
static uint8_t n_slots;       /* ring depth = ceil(N / block_size)   */
static uint32_t windows_seen; /* since last clear (for avg_filled)   */

static uint8_t slot_count; /* filled slots in the ring   */
static uint8_t slot_head;  /* next slot to (over)write   */
static uint16_t in_block;  /* windows in the open block  */

#ifdef SENSOR_WIND_SPEED
static uint16_t s_mean[SLOTS]; /* per-slot mean speed (0.1 m/s) */
static uint16_t s_max[SLOTS];  /* per-slot max window speed     */
static uint32_t b_sum;         /* open block accumulator        */
static uint16_t b_max;
#endif
#ifdef SENSOR_WIND_DIRECTION
static int16_t d_sin[SLOTS]; /* per-slot mean sin/cos (Q15) */
static int16_t d_cos[SLOTS];
static int32_t b_sin;        /* open block accumulators     */
static int32_t b_cos;
#endif

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

	windows_seen = 0;
	slot_count = 0;
	slot_head = 0;
	in_block = 0;
#ifdef SENSOR_WIND_SPEED
	b_sum = 0;
	b_max = 0;
#endif
#ifdef SENSOR_WIND_DIRECTION
	b_sin = 0;
	b_cos = 0;
#endif
}

bool avg_filled(void)
{
	return windows_seen >= n_target;
}

static void close_block_common(void)
{
	slot_head = (uint8_t)((slot_head + 1) % n_slots);
	if (slot_count < n_slots)
		slot_count++;
	in_block = 0;
}

#ifdef SENSOR_WIND_SPEED
void avg_add_speed(uint16_t inst)
{
	b_sum += inst;
	if (inst > b_max)
		b_max = inst;
	if (windows_seen < 0xFFFFFFFFu)
		windows_seen++;
	if (++in_block >= block_size) {
		s_mean[slot_head] = (uint16_t)(b_sum / block_size);
		s_max[slot_head] = b_max;
		b_sum = 0;
		b_max = 0;
		close_block_common();
	}
}

uint16_t avg_speed(void)
{
	/* FR-S23: mean over only what has been acquired — full slots weighted
	 * by block_size plus the open block's windows; no zero-padding. */
	uint32_t sum = 0;
	uint32_t n = 0;
	for (uint8_t i = 0; i < slot_count; i++) {
		sum += (uint32_t)s_mean[i] * block_size;
		n += block_size;
	}
	sum += b_sum;
	n += in_block;
	return n ? (uint16_t)(sum / n) : 0;
}

uint16_t avg_gust(void)
{
	uint16_t g = b_max;
	for (uint8_t i = 0; i < slot_count; i++)
		if (s_max[i] > g)
			g = s_max[i];
	return g;
}
#endif /* SENSOR_WIND_SPEED */

#ifdef SENSOR_WIND_DIRECTION
void avg_add_dir(int16_t sin_q15, int16_t cos_q15)
{
	b_sin += sin_q15;
	b_cos += cos_q15;
	if (windows_seen < 0xFFFFFFFFu)
		windows_seen++;
	if (++in_block >= block_size) {
		d_sin[slot_head] = (int16_t)(b_sin / block_size);
		d_cos[slot_head] = (int16_t)(b_cos / block_size);
		b_sin = 0;
		b_cos = 0;
		close_block_common();
	}
}

uint16_t avg_dir(void)
{
	/* Weighted circular mean: slots carry block_size windows each, the
	 * open block carries in_block. atan2 is scale-invariant, so weighting
	 * the sums is sufficient. */
	int32_t ys = 0;
	int32_t xs = 0;
	for (uint8_t i = 0; i < slot_count; i++) {
		ys += (int32_t)d_sin[i] * block_size;
		xs += (int32_t)d_cos[i] * block_size;
	}
	ys += b_sin;
	xs += b_cos;
	if (slot_count == 0 && in_block == 0)
		return 65535;
	uint32_t a001 = circmean_atan2_001deg(ys, xs);
	return (uint16_t)(((a001 + 50) / 100) % 3600);
}
#endif /* SENSOR_WIND_DIRECTION */
