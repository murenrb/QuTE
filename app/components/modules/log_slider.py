"""Log-spaced options for size sliders (st.select_slider) — ice maker TR, rated kWe."""

import math

# Stops per decade: 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8.
_MANTISSAS = (1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)


def log_stops(lo: float, hi: float, including: float) -> list[float]:
    """Log-spaced options in [lo, hi], plus `including` (the current value, so a
    follow-the-IT-load default is always selectable)."""
    stops = {
        round(m * 10**k, 6)
        for k in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1)
        for m in _MANTISSAS
        if lo <= m * 10**k <= hi
    }
    stops.add(round(including, 6))
    return sorted(stops)
