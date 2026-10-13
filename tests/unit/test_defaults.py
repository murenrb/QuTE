"""Defaults must match docs/assumptions.md and docs/data-model.md."""

from core.config.defaults import ASSUMPTIONS, DC_TYPE_INPUTS, NSRDB, PSYCHRO, SIZING, CoolingType


def test_model_assumptions_match_docs() -> None:
    a = ASSUMPTIONS
    assert a.it_parasitic_frac == 0.10
    assert a.t_approach_c == 10
    assert a.t_pinch_c == 5
    assert a.carnot_fraction == 0.40
    assert a.t_cond_approach_c(CoolingType.DRY) == 10
    assert a.t_cond_approach_c(CoolingType.EVAPORATIVE) == 5
    assert (a.cop_min, a.cop_max) == (0, 10)
    assert a.cop_free(CoolingType.DRY) == 50
    assert a.cop_free(CoolingType.EVAPORATIVE) == 100


def test_sizing_constants_match_docs() -> None:
    assert SIZING.ws_density_slope == 0.008
    assert SIZING.ws_density_intercept == 0.1216
    assert SIZING.redundancy_adder_per_y == 0.10
    assert SIZING.chiller_area_sqft_per_kw(CoolingType.DRY) == 0.4
    assert SIZING.chiller_area_sqft_per_kw(CoolingType.EVAPORATIVE) == 0.2


def test_dc_type_input_defaults_within_ranges() -> None:
    i = DC_TYPE_INPUTS
    for spec in (
        i.t_supply_c,
        i.t_return_c,
        i.rack_density_kw,
        i.white_space_ratio,
        i.redundancy_x,
        i.redundancy_y,
        i.ups_area_sqft_per_kw,
        i.generator_area_sqft_per_kw,
        i.switchgear_area_sqft_per_kw,
    ):
        assert spec.contains(spec.default)
    assert i.white_space_ratio.min == 0.10
    assert i.t_supply_c.default < i.t_return_c.default
    assert i.cooling_type is CoolingType.DRY


def test_weather_settings_match_docs() -> None:
    assert "nsrdb-GOES-tmy-v4-0-0-download.csv" in NSRDB.base_url
    assert NSRDB.dataset_name == "tmy-2024"
    assert NSRDB.interval_min == 60
    assert (NSRDB.max_attempts, NSRDB.retry_backoff_s, NSRDB.timeout_s) == (3, 2.0, 120.0)
    assert NSRDB.coord_decimals == 2
    assert (PSYCHRO.wet_bulb_iterations, PSYCHRO.wet_bulb_bracket_k) == (40, 60.0)


def test_site_setup_defaults_match_docs() -> None:
    from core.config.defaults import DC_INPUTS, FOOTPRINT

    s = DC_INPUTS.it_load_peak_mw
    assert (s.min, s.max, s.default) == (0.1, 2000, 10)
    assert s.contains(s.default)
    assert (FOOTPRINT.min_aspect, FOOTPRINT.max_aspect, FOOTPRINT.edge_tolerance_m) == (
        0.1,
        10.0,
        0.01,
    )
