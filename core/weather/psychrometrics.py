"""Vectorized psychrometrics for deriving wet bulb (docs/integrations/nsrdb-weather.md).

Equations are ASHRAE Handbook—Fundamentals (2017) ch. 1, SI units — the same
ones `psychrolib` implements, but on numpy arrays so 8760 hours solve at once.
The Hyland–Wexler coefficients are published correlation constants, so they
live with the correlation rather than in defaults.py (D-016).
"""

import numpy as np
import numpy.typing as npt

from core.config.defaults import KELVIN_OFFSET, PsychrometricSettings

FloatArray = npt.NDArray[np.float64]

# Ratio of molecular weights of water vapour to dry air (ASHRAE eq. 22).
_MW_RATIO = 0.621945
# Triple point of water, °C: switch between ice and liquid saturation curves.
_TRIPLE_POINT_C = 0.01

# Hyland–Wexler saturation pressure over ice, -100..0 °C (ASHRAE eq. 5).
_ICE = (-5.6745359e03, 6.3925247, -9.677843e-03, 6.2215701e-07, 2.0747825e-09, -9.484024e-13)
_ICE_LN = 4.1635019
# Hyland–Wexler saturation pressure over liquid water, 0..200 °C (ASHRAE eq. 6).
_WATER = (-5.8002206e03, 1.3914993, -4.8640239e-02, 4.1764768e-05, -1.4452093e-08)
_WATER_LN = 6.5459673


def saturation_pressure_pa(t_c: FloatArray) -> FloatArray:
    """Saturation vapour pressure p_ws [Pa] at temperature t [°C] (ASHRAE eqs. 5–6)."""
    t_k = np.asarray(t_c, dtype=float) + KELVIN_OFFSET
    ln_ice = _ICE[0] / t_k + sum(c * t_k**i for i, c in enumerate(_ICE[1:])) + _ICE_LN * np.log(t_k)
    ln_water = (
        _WATER[0] / t_k
        + sum(c * t_k**i for i, c in enumerate(_WATER[1:]))
        + _WATER_LN * np.log(t_k)
    )
    return np.exp(np.where(np.asarray(t_c) < _TRIPLE_POINT_C, ln_ice, ln_water))


def humidity_ratio(vapour_pressure_pa: FloatArray, pressure_pa: FloatArray) -> FloatArray:
    """W [kg/kg dry air] = 0.621945 · p_w / (p − p_w)  (ASHRAE eq. 20)."""
    return _MW_RATIO * vapour_pressure_pa / (pressure_pa - vapour_pressure_pa)


def _humidity_ratio_from_wet_bulb(
    tdb_c: FloatArray, twb_c: FloatArray, pressure_pa: FloatArray
) -> FloatArray:
    """W from dry and wet bulb (ASHRAE eq. 33 above freezing, eq. 35 below)."""
    ws_star = humidity_ratio(saturation_pressure_pa(twb_c), pressure_pa)
    above = ((2501.0 - 2.326 * twb_c) * ws_star - 1.006 * (tdb_c - twb_c)) / (
        2501.0 + 1.86 * tdb_c - 4.186 * twb_c
    )
    below = ((2830.0 - 0.24 * twb_c) * ws_star - 1.006 * (tdb_c - twb_c)) / (
        2830.0 + 1.86 * tdb_c - 2.1 * twb_c
    )
    return np.where(twb_c >= 0.0, above, below)


def wet_bulb_c(
    tdb_c: FloatArray,
    rh_pct: FloatArray,
    pressure_pa: FloatArray,
    settings: PsychrometricSettings,
) -> FloatArray:
    """Thermodynamic wet bulb [°C] from dry bulb [°C], RH [%] and pressure [Pa].

    Solves W(tdb, twb, p) = W(tdb, rh, p) for twb by bisection on
    [tdb − bracket, tdb]; W rises monotonically with twb on that interval.
    """
    tdb = np.asarray(tdb_c, dtype=float)
    p = np.broadcast_to(np.asarray(pressure_pa, dtype=float), tdb.shape)
    rh = np.clip(np.asarray(rh_pct, dtype=float), 0.0, 100.0) / 100.0
    w_target = humidity_ratio(rh * saturation_pressure_pa(tdb), p)

    lo = tdb - settings.wet_bulb_bracket_k
    hi = tdb.copy()
    for _ in range(settings.wet_bulb_iterations):
        mid = 0.5 * (lo + hi)
        too_wet = _humidity_ratio_from_wet_bulb(tdb, mid, p) > w_target
        hi = np.where(too_wet, mid, hi)
        lo = np.where(too_wet, lo, mid)
    return np.asarray(0.5 * (lo + hi), dtype=np.float64)


def standard_pressure_pa(elevation_m: float, sea_level_pa: float) -> float:
    """Standard-atmosphere pressure at elevation Z [m] (ASHRAE eq. 3)."""
    return float(sea_level_pa * (1.0 - 2.25577e-05 * elevation_m) ** 5.2559)
