"""Host-side validation of the circular-mean algorithm (integer reference,
mirrored line-for-line by circmean.c). Run: python test_circmean.py

Covers TDS FR-S14 (wrap-around correctness) plus identity, distribution,
and worst-case accuracy sweeps.
"""

import math
import sys

from gen_table import circmean_ref, cordic_atan2_001deg, sin_q15

fails = 0


def check(name, cond, detail=""):
    global fails
    if not cond:
        fails += 1
        print(f"  FAIL {name} {detail}")


def wrap_dist(a, b):
    d = abs(a - b) % 3600
    return min(d, 3600 - d)


# 1. Identity: single-sample mean == the sample, +-1 LSB, for ALL angles.
worst = 0
for a in range(3600):
    m = circmean_ref([a])
    worst = max(worst, wrap_dist(m, a))
check("identity sweep", worst <= 1, f"worst={worst} LSB")
print(f"identity sweep: worst error {worst} x 0.1deg over all 3600 angles")

# 2. FR-S14: alternating 3500/100 -> 0.0deg +-1.0deg, never ~180deg.
m = circmean_ref([3500, 100] * 16)
check("FR-S14 wrap", m >= 3590 or m <= 10, f"mean={m}")
check("FR-S14 not-180", not (1700 <= m <= 1900), f"mean={m}")
print(f"FR-S14 alternating 350.0/10.0 -> mean {m/10:.1f} deg")

# 3. Distributions.
cases = [
    ([100, 200, 300], 200),
    ([3400, 3500, 0, 100, 200], 0),
    ([1750, 1850], 1800),
    ([0, 0, 0, 900], 225),          # atan2(1, 3) = 18.43 deg -> 184
    ([2700, 2700, 900], 2700),      # 2:1 opposite -> stays at majority
    (list(range(0, 200)), 100),     # dense arc
]
cases[3] = ([0, 0, 0, 900], 184)
for angles, expect in cases:
    m = circmean_ref(angles)
    check(f"dist {angles[:4]}..", wrap_dist(m, expect) <= 1,
          f"mean={m} expect={expect}")

# 4. CORDIC atan2 accuracy sweep vs math.atan2 (0.001 deg domain).
worst001 = 0
for deg10 in range(0, 3600, 7):
    y = sin_q15(deg10) * 1000
    x = sin_q15((deg10 + 900) % 3600) * 1000
    ref = math.degrees(math.atan2(y, x)) % 360.0
    got = cordic_atan2_001deg(y, x) / 1000.0
    d = min(abs(got - ref), 360 - abs(got - ref))
    worst001 = max(worst001, d)
check("cordic sweep", worst001 <= 0.05, f"worst={worst001:.4f} deg")
print(f"CORDIC vs math.atan2: worst {worst001:.4f} deg")

# 5. Empty -> sentinel.
check("empty sentinel", circmean_ref([]) == 65535)

# 6. Output domain: never 3600.
for a in (3595, 3599, 0, 1):
    check("domain", 0 <= circmean_ref([a] * 5) <= 3599)

print("CIRCMEAN HOST TESTS " + ("PASS" if fails == 0 else f"FAIL ({fails})"))
sys.exit(0 if fails == 0 else 1)
