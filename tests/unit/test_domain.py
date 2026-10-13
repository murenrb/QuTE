import pytest
from pydantic import ValidationError

from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType


def test_defaults_match_docs(dc_type: DataCenterType) -> None:
    assert dc_type.cooling_type == "dry"
    assert (dc_type.t_supply_c, dc_type.t_return_c) == (40, 50)
    assert dc_type.rack_density_kw == 50
    assert dc_type.white_space_ratio == 0.65
    assert (dc_type.redundancy_x, dc_type.redundancy_y) == (1, 1)
    assert dc_type.backup_area_sqft_per_kw == pytest.approx(3.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"white_space_ratio": 0.05},
        {"rack_density_kw": 301},
        {"redundancy_x": 4},
        {"t_supply_c": 50, "t_return_c": 50},
        {"t_supply_c": 55, "t_return_c": 50},
        {"unknown_field": 1},
    ],
)
def test_invalid_types_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DataCenterType(**kwargs)  # type: ignore[arg-type]


def test_json_round_trip(dc_type: DataCenterType) -> None:
    assert DataCenterType.model_validate_json(dc_type.model_dump_json()) == dc_type


def test_default_profile_constant_at_peak(dc_10mw: DataCenter) -> None:
    assert dc_10mw.daily_profile_kw == (10_000.0,) * 24


@pytest.mark.parametrize("profile", [(1.0,) * 23, (-1.0,) * 24, (20_000.0,) * 24])
def test_invalid_profiles_rejected(dc_type: DataCenterType, profile: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        DataCenter(dc_type=dc_type, it_load_peak_mw=10, it_profile_daily_kw=profile)


def test_it_load_must_be_positive(dc_type: DataCenterType) -> None:
    with pytest.raises(ValidationError):
        DataCenter(dc_type=dc_type, it_load_peak_mw=0)


def test_name_synthesized_from_every_input() -> None:
    t = DataCenterType()
    assert t.name == (
        "Dry · 5–40→50 °C · 50 kW/rack · 65% WS · N+1 · UPS/Gen/SWG 1/1.5/0.5 sqft/kW"
    )
    evap = DataCenterType(
        cooling_type="evaporative",
        t_supply_c=30,
        t_supply_min_c=12,
        t_return_c=42.5,
        rack_density_kw=120,
        white_space_ratio=0.8,
        redundancy_x=2,
        redundancy_y=2,
        ups_area_sqft_per_kw=0.8,
        generator_area_sqft_per_kw=2,
        switchgear_area_sqft_per_kw=0.4,
    )
    assert evap.name == (
        "Evap · 12–30→42.5 °C · 120 kW/rack · 80% WS · 2N+2 · UPS/Gen/SWG 0.8/2/0.4 sqft/kW"
    )


@pytest.mark.parametrize(("x", "y", "label"), [(1, 1, "N+1"), (2, 0, "2N"), (2, 1, "2N+1")])
def test_redundancy_label(x: int, y: int, label: str) -> None:
    from core.domain.datacenter_type import redundancy_label

    assert redundancy_label(x, y) == label


def test_name_not_an_input_and_float_noise_ignored() -> None:
    assert DataCenterType(ups_area_sqft_per_kw=1.5000000000000002) == DataCenterType(
        ups_area_sqft_per_kw=1.5
    )
    assert "name" in DataCenterType().model_dump()  # saved for readability, derived on load


def test_every_input_changes_the_file_stem() -> None:
    from core.domain.datacenter_type import type_file_stem

    base = DataCenterType()
    variants = [
        {"cooling_type": "evaporative"},
        {"t_supply_c": 41},
        {"t_return_c": 51},
        {"rack_density_kw": 51},
        {"white_space_ratio": 0.66},
        {"redundancy_x": 2},
        {"redundancy_y": 2},
        {"ups_area_sqft_per_kw": 1.1},
        {"generator_area_sqft_per_kw": 1.6},
        {"switchgear_area_sqft_per_kw": 0.6},
    ]
    # Build through the constructor (model_copy would skip validation).
    types = [DataCenterType(**base.model_dump(exclude={"name"}) | v) for v in variants]
    stems = {type_file_stem(t) for t in [base, *types]}
    names = {t.name for t in [base, *types]}
    assert len(stems) == len(variants) + 1
    assert len(names) == len(variants) + 1


def test_supply_min_cannot_exceed_setpoint() -> None:
    with pytest.raises(ValidationError):
        DataCenterType(t_supply_c=30, t_supply_min_c=31)
    assert DataCenterType(t_supply_c=30, t_supply_min_c=30).t_supply_min_c == 30


def test_old_saved_type_without_min_loads_with_default() -> None:
    t = DataCenterType.model_validate({"t_supply_c": 40, "t_return_c": 50})
    assert t.t_supply_min_c == 5
