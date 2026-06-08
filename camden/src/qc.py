"""Sensor quality-control guards.

Low-cost optical PM sensors occasionally fail "stuck": they report a fixed,
often physically implausible value for hours with essentially no variation.
Two PurpleAir units near EMR did exactly this during the 2026-05-29 fire
(both pinned at ~1667 µg/m³, std < 1.1 over 12 h). A stuck sensor must not be
plotted as a measurement or it reads as a catastrophic spike.

The test distinguishes a stuck sensor from a real smoke plume by variance:
a genuine plume has a low clean baseline and large swings (the 2/21/25 fire
ran 2.5 → 1194 → 6 µg/m³ at one sensor), whereas a stuck sensor sits on a
high floor with near-zero spread.

Scope and known limits (intentional, for a narrow high-confidence guard):
  - Detects "stuck HIGH" only (floor > 100 µg/m³). A sensor frozen at a low
    value is not caught — that would need a separate flatline test and risks
    flagging genuinely calm clean air.
  - A real, genuinely steady dense-smoke plateau (e.g. 300 ± 3 µg/m³ for
    hours) would be a false positive. In this dataset real plumes are highly
    variable, so the risk is low, but evaluate on the FIRE WINDOW (not a wider
    pull) so a window of real variation isn't masked by surrounding flatline,
    and vice versa.
"""
from __future__ import annotations

import pandas as pd

STUCK_MIN_FLOOR = 100.0   # µg/m³ — a real baseline never sits this high for hours
STUCK_CV_MAX = 0.02       # std/mean below this = effectively a flat line


def is_stuck(values: pd.Series) -> bool:
    """True if `values` look like a stuck/pinned sensor over the window."""
    v = pd.to_numeric(values, errors="coerce").dropna()
    if len(v) < 5:
        return False
    mean = float(v.mean())
    if mean <= 0:
        return False
    floor = float(v.min())
    cv = float(v.std()) / mean
    return floor > STUCK_MIN_FLOOR and cv < STUCK_CV_MAX
