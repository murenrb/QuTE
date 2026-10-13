"""Brine thermal properties (owner's fits, docs/models/brine-separation.md).

c is the salt mass fraction (0..1). Shared by the sizing (params) and the
hourly model.
"""

import math

from core.config.defaults import BRINE_INPUTS, BrineProperties


def water_activity(c: float, p: BrineProperties) -> float:
    """a_w = a·c³ + b·c² + d·c + e ( melinder)."""
    a, b, d, e = p.aw_coeffs
    return a * c**3 + b * c**2 + d * c + e


def brine_fp(c: float, p: BrineProperties) -> float:
    """Freeze point [°C] = a·c³ + b·c² + d·c + e; 0 for pure water (c = 0)."""
    if c == 0:
        return 0.0
    a, b, d, e = p.fp_coeffs
    return a * c**3 + b * c**2 + d * c + e


def brine_c(t: float, p: BrineProperties) -> float:
    """Concentration that freezes at t [°C] = a·t³ + b·t² + d·t + e (the inverse
    fit of `brine_fp`; the two agree to ≈ 0.01–0.03 in c)."""
    a, b, d, e = p.c_coeffs
    return a * t**3 + b * t**2 + d * t + e


def brine_h_solv(c: float, p: BrineProperties) -> float:
    """Solvation heat [kJ per kg of ice] melted into brine ending at c:
    h = k·(c/(1 − c))², with c/(1 − c) the salt-to-water ratio. Negative = heat
    generated, so it is added to the latent heat (reduces the cooling)."""
    return p.h_solv_coeff * (c / (1 - c)) ** 2


def rho_brine(c: float, p: BrineProperties) -> float:
    """Brine density [kg/m³] = m·c + b."""
    m, b = p.rho_coeffs
    return m * c + b


def vapor_sat_temp(t_brine_c: float, a_w: float) -> float:
    """Saturation temperature (°C) of pure water at the brine's vapor pressure.

    Antoine: log10 P = A − B/(C + T); brine P = a_w · P_sat(T_brine), so
    T_sat = B / (B/(C + T_brine) − log10 a_w) − C (A cancels).
    """
    if a_w <= 0:
        raise ValueError(f"Water activity {a_w:.3f} ≤ 0: concentration outside the fit")
    b, c = BRINE_INPUTS.antoine_b, BRINE_INPUTS.antoine_c
    return b / (b / (c + t_brine_c) - math.log10(a_w)) - c
