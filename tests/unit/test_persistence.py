import json
from typing import Any

import pandas as pd
import pytest

from core.config.defaults import ASSUMPTIONS, CoolingType
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import ModuleSettings, SolarPVParams
from core.domain.site import Site
from core.geometry.footprint import square_footprint
from core.models.site_model import run_site_model
from core.persistence import project as proj
from core.persistence.files import slugify
from core.persistence.project import (
    Project,
    ProjectFileError,
    from_json,
    inputs_hash,
    to_json,
)


@pytest.fixture
def project() -> Project:
    t = DataCenterType(cooling_type=CoolingType.EVAPORATIVE, rack_density_kw=80)
    fp = square_footprint((33.45, -112.07), 5000.0, 15.0)
    return Project(
        site=Site(
            name="Phoenix test",
            lat=33.45,
            lon=-112.07,
            boundary=((33.449, -112.071), (33.449, -112.069), (33.451, -112.069)),
        ),
        facilities=(DataCenter(dc_type=t, it_load_peak_mw=25, footprint=fp),),
        step="site_optimization",
    )


# --- helpers ---------------------------------------------------------------------


def test_slugify() -> None:
    assert slugify("  Phoenix / Site #2 ") == "phoenix-site-2"
    assert slugify("***") == "untitled"


# --- project file ------------------------------------------------------------------


def test_round_trip_identical(project: Project) -> None:
    assert from_json(to_json(project)) == project


def test_round_trip_reproduces_model_results(
    project: Project, synthetic_weather: pd.DataFrame
) -> None:
    loaded = from_json(to_json(project))
    a = run_site_model(project.facilities[0], synthetic_weather, project.assumptions)
    b = run_site_model(loaded.facilities[0], synthetic_weather, loaded.assumptions)
    pd.testing.assert_frame_equal(a, b)


def test_default_assumptions_saved(project: Project) -> None:
    data = json.loads(to_json(project))
    assert data["assumptions"]["carnot_fraction"] == ASSUMPTIONS.carnot_fraction


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("{bad", "bad JSON"),
        ("[1, 2]", "JSON object"),
        ('{"site": {"lat": 200}}', "site.lat"),
        ('{"schema_version": 99}', "newer version"),
        ('{"schema_version": 0}', "Unknown"),
    ],
)
def test_corrupt_files_give_clear_errors(text: str, match: str) -> None:
    with pytest.raises(ProjectFileError, match=match):
        from_json(text)


def test_old_schema_version_migrates(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a future v3 schema that renames a field."""
    monkeypatch.setattr(proj, "PROJECT_SCHEMA_VERSION", 3)

    def v2_to_v3(d: dict[str, Any]) -> dict[str, Any]:
        d = dict(d)
        d["step"] = d.pop("workflow_step")
        return d

    monkeypatch.setitem(proj.MIGRATIONS, 2, v2_to_v3)
    old = json.loads(to_json(project))
    old["schema_version"] = 2
    old["workflow_step"] = old.pop("step")
    migrated = proj.migrate(old)
    assert migrated["schema_version"] == 3
    assert migrated["step"] == "site_optimization"


def test_inputs_hash_ignores_labels_but_not_inputs(project: Project) -> None:
    h = inputs_hash(project)
    renamed = project.model_copy(
        update={
            "step": "site_setup",
            "site": project.site.model_copy(
                update={"name": "Other", "address": "x", "weather_ref": "k"}
            ),
        }
    )
    assert inputs_hash(renamed) == h
    dc = project.facilities[0].model_copy(update={"it_load_peak_mw": 26})
    assert inputs_hash(project.model_copy(update={"facilities": (dc,)})) != h


def test_projects_saved_before_modules_still_load(project: Project) -> None:
    data = json.loads(to_json(project))
    data.pop("modules")
    loaded = from_json(json.dumps(data))
    assert not loaded.modules.solar_pv.placed
    assert loaded == project


def test_v1_project_with_old_pv_settings_migrates() -> None:
    v1 = {
        "schema_version": 1,
        "modules": {"solar_pv": {"enabled": True, "system_capacity_kw": 2000, "tilt_deg": 25}},
    }
    loaded = from_json(json.dumps(v1))
    assert loaded.schema_version == 6  # migrated v1 → … → v6
    assert loaded.modules.solar_pv.tilt_deg == 25
    assert not loaded.modules.solar_pv.placed  # PV off until an area is drawn


def test_v2_ice_defaults_migrate_to_new_defaults() -> None:
    v2 = {
        "schema_version": 2,
        "modules": {
            "ice_storage": {"enabled": True, "ice_maker_size_tr": 1000, "tank_charge_time_h": 1}
        },
    }
    ice = from_json(json.dumps(v2)).modules.ice_storage
    assert ice.ice_maker_size_tr is None  # old default → follow 65 TR/MW
    assert ice.tank_charge_time_h == 24  # below the new 6 h minimum → new default
    custom = {
        "schema_version": 2,
        "modules": {"ice_storage": {"ice_maker_size_tr": 2000, "tank_charge_time_h": 8}},
    }
    kept = from_json(json.dumps(custom)).modules.ice_storage
    assert (kept.ice_maker_size_tr, kept.tank_charge_time_h) == (2000, 8)  # user's own values


def test_v3_drawn_pv_stays_on_the_site() -> None:
    """D-056: drawn-area modules got an `enabled` flag; a drawn PV area keeps PV on."""
    from tests.unit.test_solar_pv import square_area

    area = SolarPVParams(area=(square_area(10_000),)).model_dump(mode="json")["area"]
    drawn = {"schema_version": 3, "modules": {"solar_pv": {"area": area}}}
    pv = from_json(json.dumps(drawn)).modules.solar_pv
    assert pv.enabled and pv.placed
    blank = {"schema_version": 3, "modules": {"solar_pv": {"tilt_deg": 25}}}
    assert not from_json(json.dumps(blank)).modules.solar_pv.enabled


def test_v4_greenhouse_loses_its_wind_input() -> None:
    """D-062: U became the input; the first version's wind speed input is dropped."""
    v4 = {"schema_version": 4, "modules": {"greenhouse": {"enabled": True, "wind_m_s": 3.0}}}
    gh = from_json(json.dumps(v4)).modules.greenhouse
    assert gh.enabled and gh.u_w_m2k == 7.5


def test_v5_power_generation_rating_becomes_pct_of_it() -> None:
    """D-063: a saved kWe rating becomes its % of the IT peak; none saved
    (followed the IT load) = the default %; the derived kWe isn't saved."""
    facility = {"dc_type": {}, "it_load_peak_mw": 100.0}

    def v5(rated_kw: float | None) -> str:
        pg = {"enabled": True, "rated_kw": rated_kw}
        return json.dumps(
            {"schema_version": 5, "facilities": [facility], "modules": {"power_generation": pg}}
        )

    assert from_json(v5(7000.0)).modules.power_generation.rated_pct_of_it == 7.0
    assert from_json(v5(None)).modules.power_generation.rated_pct_of_it == 2.0
    assert from_json(v5(500_000.0)).modules.power_generation.rated_pct_of_it == 150.0
    resolved = ModuleSettings().power_generation.model_copy(update={"rated_kw": 5.0})
    assert "rated_kw" not in resolved.model_dump()


def test_enabled_keys_follow_add_and_remove() -> None:
    m = ModuleSettings().with_enabled("ice_mixer", True).with_enabled("solar_pv", True)
    assert m.enabled_keys() == ("solar_pv", "ice_mixer")  # field order
    off = m.with_enabled("ice_mixer", False)
    assert off.enabled_keys() == ("solar_pv",)
    assert off.ice_mixer.fluid == m.ice_mixer.fluid  # inputs kept for adding it back


def test_projects_without_utility_load_default_tariff(project: Project) -> None:
    data = json.loads(to_json(project))
    data.pop("utility")
    loaded = from_json(json.dumps(data))
    assert loaded.utility.cheapest.id == "offpeak"
