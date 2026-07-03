#include "circmean.h"
#include "circmean_table.h"

// atan(2^-i) in 0.001° for i = 0..15 (see gen_table.py ATAN_001DEG).
static const int32_t atan_tab[16] = {
	45000, 26565, 14036, 7125, 3576, 1790, 895, 448,
	224, 112, 56, 28, 14, 7, 3, 2,
};

int16_t circmean_sin_q15(uint16_t a)
{
	uint16_t q = a / 900;
	uint16_t r = a % 900;
	switch (q) {
	case 0:  return circmean_sin_tab[r];
	case 1:  return circmean_sin_tab[900 - r];
	case 2:  return (int16_t)-circmean_sin_tab[r];
	default: return (int16_t)-circmean_sin_tab[900 - r];
	}
}

uint32_t circmean_atan2_001deg(int32_t y, int32_t x)
{
	if (x == 0 && y == 0)
		return 0;
	int flip = 0;
	if (x < 0) { // fold by point reflection into the right half-plane
		x = -x;
		y = -y;
		flip = 1;
	}
	while (x >= (1L << 26) || y >= (1L << 26) || y <= -(1L << 26)) {
		x >>= 1;
		y >>= 1;
	}
	int32_t ang = 0;
	for (int i = 0; i < 16; i++) {
		int32_t xs = x >> i;
		int32_t ys = y >> i;
		if (y > 0) {
			x += ys;
			y -= xs;
			ang += atan_tab[i];
		} else {
			x -= ys;
			y += xs;
			ang -= atan_tab[i];
		}
	}
	if (flip)
		ang += 180000; // rotate back — a mirror here is the 180° bug
	ang %= 360000;
	if (ang < 0)
		ang += 360000;
	return (uint32_t)ang;
}

void circmean_reset(circmean_t *cm)
{
	cm->sum_sin = 0;
	cm->sum_cos = 0;
	cm->n = 0;
}

void circmean_add(circmean_t *cm, uint16_t angle_0_1deg)
{
	cm->sum_sin += circmean_sin_q15(angle_0_1deg);
	cm->sum_cos += circmean_sin_q15((uint16_t)((angle_0_1deg + 900) % 3600));
	cm->n++;
}

uint16_t circmean_get(const circmean_t *cm)
{
	if (cm->n == 0)
		return 65535;
	uint32_t a001 = circmean_atan2_001deg(cm->sum_sin, cm->sum_cos);
	return (uint16_t)(((a001 + 50) / 100) % 3600);
}
