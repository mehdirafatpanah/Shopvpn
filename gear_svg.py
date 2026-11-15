# -*- coding: utf-8 -*-
"""ساخت مسیر SVG چرخدنده؛ برای صفحه‌های «به زودی» و «در حال ساخت‌وساز» (بدون فایل خارجی)."""
import math


def gear_path(cx: float, cy: float, r_out: float, r_in: float, teeth: int, hole: float) -> str:
    step = 2 * math.pi / teeth
    pts = []
    for i in range(teeth):
        a = i * step
        for ang, r in ((a - step * .30, r_in), (a - step * .17, r_out), (a + step * .17, r_out), (a + step * .30, r_in)):
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
    d += (f" M{cx - hole:.1f} {cy:.1f}a{hole} {hole} 0 1 0 {2 * hole} 0a{hole} {hole} 0 1 0 {-2 * hole} 0Z")
    return d
