"""Small display-formatting helpers. Missing values render as 'n/a', never 0."""
from __future__ import annotations

import math


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def fmt_x(v, digits: int = 2) -> str:
    return "n/a" if _missing(v) else f"{v:.{digits}f}x"


def fmt_pct(v, digits: int = 1) -> str:
    return "n/a" if _missing(v) else f"{v * 100:.{digits}f}%"


def fmt_cr(v, digits: int = 0) -> str:
    return "n/a" if _missing(v) else f"₹{v:,.{digits}f} cr"
