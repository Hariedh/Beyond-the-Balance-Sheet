"""Small display-formatting helpers. Missing values render as 'n/a', never 0."""
from __future__ import annotations

import math


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def fmt_x(v, digits: int | None = None) -> str:
    """Format a multiple. Default: 2 decimals, but 3 when 0 < |v| < 0.1 so that small values
    such as a 0.016x debt-to-equity are not displayed as a misleading 0.02x."""
    if _missing(v):
        return "n/a"
    if digits is None:
        digits = 3 if 0 < abs(v) < 0.1 else 2
    return f"{v:.{digits}f}x"


def fmt_pct(v, digits: int = 1) -> str:
    return "n/a" if _missing(v) else f"{v * 100:.{digits}f}%"


def fmt_cr(v, digits: int = 0) -> str:
    if _missing(v):
        return "n/a"
    return f"{'-' if v < 0 and round(v, digits) != 0 else ''}₹{abs(v):,.{digits}f} cr"
