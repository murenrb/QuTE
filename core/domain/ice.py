"""Ice properties (owner's fits, docs/models/ice-mixer.md)."""

from core.config.defaults import ICE_LATENT_HEAT_KJ_KG, ICE_PROPS, IceProperties


def ice_hf(t_melt_c: float, p: IceProperties = ICE_PROPS) -> float:
    """Latent heat [kJ/kg] of ice melting at t_melt [°C] (Kirchhoff):
    h_f(t) = h_f(0) + (cp_water,avg − cp_ice,avg)·t, each cp the average of the
    pure value and its fit at t. Below 0 °C it is less than h_f(0)."""
    a_i, b_i = p.cp_ice_coeffs
    a_w, b_w, c_w = p.cp_water_coeffs
    cp_ice_at_t = a_i * t_melt_c + b_i
    cp_water_at_t = a_w * t_melt_c**2 + b_w * t_melt_c + c_w
    cp_water_avg = (p.cp_water_pure_kj_kgk + cp_water_at_t) / 2
    cp_ice_avg = (p.cp_ice_pure_kj_kgk + cp_ice_at_t) / 2
    return ICE_LATENT_HEAT_KJ_KG + (cp_water_avg - cp_ice_avg) * t_melt_c
