"""Workspace page with AppTest: tabs, live results, data center flow.

No network: weather is faked and the data dir is isolated (tests/ui/conftest.py).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from app.components import run_model
from core.config.defaults import SIZING
from core.domain.datacenter_type import DataCenterType
from core.persistence.project import to_json
from core.sizing.datacenter_area import size_datacenter
from services.store import default_store, utcnow

ENTRY = str(Path(__file__).resolve().parents[2] / "streamlit_app.py")
WORKSPACE = "app/pages/workspace.py"
SAVE_TYPE = "FormSubmitter:dc_type_form-Save type"


def _workspace() -> AppTest:
    """Start → "Start new setup" → workspace, as a user does."""
    at = AppTest.from_file(ENTRY).run(timeout=30)
    next(b for b in at.button if b.label == "Start new setup").click().run(timeout=30)
    assert at.session_state["project"].site.lat is None
    # AppTest keeps a script's switch_page for one run only; pin the page like a URL.
    return at.switch_page(WORKSPACE).run(timeout=30)


def _saved(at: AppTest) -> dict[str, Any]:
    """This session's autosave in the database (unique per project, D-040, D-069)."""
    return json.loads(
        to_json(default_store().load_project(at.session_state["project_autosave_stem"]))
    )


def _open_tab(at: AppTest, label: str) -> None:
    at.session_state["w_tab"] = label
    at.run(timeout=30)
    assert not at.exception


def _results_figure(at: AppTest) -> dict:  # type: ignore[type-arg]
    """The Plotly figure the results component was last sent (D-060)."""
    (chart,) = at.get("bidi_component")
    return json.loads(json.loads(chart.proto.json)["figure"])


def _state_picker(at: AppTest):  # type: ignore[no-untyped-def]
    """The Control tab's state picker (its key carries a generation, D-068)."""
    return next(s for s in at.selectbox if str(s.key).startswith("w_ctl_selected_"))


def _texts(at: AppTest) -> str:
    return " ".join(str(m.value) for m in [*at.markdown, *at.caption, *at.info, *at.error])


def _run_all_modules(at: AppTest) -> None:
    """Control tab → "Run everything in Default" (modules start off, D-053, D-054)."""
    _open_tab(at, "Control")
    at.button(key="w_ctl_all_on").click().run(timeout=30)
    assert not at.exception


def _add_module(at: AppTest, key: str) -> None:
    """Modules tab → Add module → pick → Add to the site (D-056); opens its tab."""
    at.selectbox(key="w_module_add").set_value(key).run(timeout=30)
    at.button(key="w_module_add_go").click().run(timeout=30)
    assert not at.exception
    assert at.segmented_control(key="w_module").value == key


def _set_location(at: AppTest) -> None:
    at.number_input(key="w_lat").set_value(33.45).run(timeout=30)
    at.number_input(key="w_lon").set_value(-112.07).run(timeout=30)


def test_layout_tabs_and_placeholders() -> None:
    at = _workspace()
    assert not at.exception
    assert [t.label for t in at.tabs] == [
        "Location",
        "Property",
        "Data center",
        "Utility",
        "Modules",
        "Control",
    ]
    assert at.session_state["project"].step == "location"
    text = _texts(at)
    assert "Select a location for the project. Ensure the map shows the entire property" in text
    assert text.count(run_model.INCOMPLETE_MESSAGE) == 1  # results figure (no metrics yet)
    # One line separates the input/map layer from the outputs below it.
    rules = [m for m in at.markdown if "dcs-section-rule" in str(m.value)]
    assert len(rules) == 1


def test_each_tab_renders_and_is_remembered() -> None:
    at = _workspace()
    _open_tab(at, "Property")
    assert "Set the project location on the Location tab first." in _texts(at)
    _open_tab(at, "Modules")
    assert "No modules on the site yet" in _texts(at)  # none to start (D-056)
    _add_module(at, "solar_pv")
    _open_tab(at, "Data center")
    assert at.session_state["project"].step == "data_center"
    _set_location_via_state(at)
    _open_tab(at, "Property")
    assert "Use the polygon tool to select the limits of the property." in _texts(at)


def _set_location_via_state(at: AppTest) -> None:
    p = at.session_state["project"]
    at.session_state["project"] = p.model_copy(
        update={"site": p.site.model_copy(update={"lat": 33.45, "lon": -112.07})}
    )


def test_create_type_from_form_names_it(isolated_data: Path) -> None:
    at = _workspace()
    _open_tab(at, "Data center")
    assert "dct_name" not in [t.key for t in at.text_input]  # name is generated, not typed
    at.slider(key="dct_rack").set_value(80.0)
    at.button(key=SAVE_TYPE).click().run(timeout=30)
    assert not at.exception
    expected = DataCenterType(rack_density_kw=80).name
    assert [t.name for t in default_store().list_types()] == [expected]
    assert at.selectbox(key="w_dc_type").value == expected
    assert any("Saved new type" in s.value for s in at.success)


def test_duplicate_type_uses_saved_version(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _open_tab(at, "Data center")
    at.selectbox(key="w_dc_type").set_value(at.selectbox(key="w_dc_type").options[-1]).run()
    at.button(key=SAVE_TYPE).click().run(timeout=30)
    assert not at.exception
    assert len(default_store().list_types()) == 1
    assert at.selectbox(key="w_dc_type").value == DataCenterType().name
    assert any("saved version will be used" in i.value for i in at.info)


def test_type_form_rejects_return_colder_than_supply() -> None:
    at = _workspace()
    _open_tab(at, "Data center")
    at.slider(key="dct_t_return").set_value(30.0)
    at.button(key=SAVE_TYPE).click().run(timeout=30)
    assert any("warmer than" in e.value for e in at.error)


@pytest.mark.usefixtures("fake_weather")
def test_results_fill_in_live_and_rerun_only_on_change(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = run_model.run_site_model

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_model, "run_site_model", counting)
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    assert run_model.INCOMPLETE_MESSAGE in _texts(at)  # no data center yet
    _open_tab(at, "Data center")
    assert not at.exception
    assert run_model.INCOMPLETE_MESSAGE not in _texts(at)
    # one figure: module output + three rows on one time axis (D-029, D-055, D-060),
    # in the keyed results component (so its zoom survives model runs)
    (chart,) = at.get("bidi_component")
    assert chart.key == "results_figure"
    fig = _results_figure(at)
    assert [m["name"] for m in fig["layout"]["updatemenus"]] == ["ambient", "power", "operation"]
    metric_labels = [m.label for m in at.metric]
    assert "Annual grid energy" in metric_labels and "Free-cooling hours" in metric_labels
    assert len(calls) == 1

    at.run(timeout=30)  # rerun, no input change → no model run
    assert len(calls) == 1
    # module output selector: only modules on the site, none to start (D-055, D-056)
    assert "w_output_module" not in [w.key for w in at.segmented_control]
    _open_tab(at, "Modules")
    _add_module(at, "ice_storage")  # first: the mixer needs its ice
    _add_module(at, "ice_mixer")
    assert at.segmented_control(key="w_output_module").options == ["Ice storage", "Ice mixer"]
    assert at.segmented_control(key="w_output_module").value == "ice_storage"
    runs = len(calls)
    at.segmented_control(key="w_output_module").set_value("ice_mixer").run(timeout=30)
    assert not at.exception
    assert len(at.get("bidi_component")) == 1 and len(calls) == runs  # re-plots only
    # removing a module drops its tab here and in the output
    at.button(key="remove_ice_mixer").click().run(timeout=30)
    assert at.segmented_control(key="w_module").options == ["Ice storage"]
    assert at.segmented_control(key="w_output_module").options == ["Ice storage"]
    assert at.session_state["project"].modules.ice_mixer.enabled is False

    _open_tab(at, "Data center")
    runs = len(calls)
    at.number_input(key="w_it_load_mw").set_value(20.0).run(timeout=30)
    assert len(calls) == runs + 1
    results = at.session_state["results"]
    assert results.frame["it_load_kw"].iloc[0] == 20_000
    assert at.session_state["project"].site.weather_ref == "fake/key.csv"


@pytest.mark.usefixtures("fake_weather")
def test_placement_keeps_area_and_autosaves(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    at.number_input(key="w_it_load_mw").set_value(10.0).run(timeout=30)
    assert any("66,495" in str(t.value) for t in at.table)  # sizing worked example

    dc = at.session_state["project"].facilities[0]
    area_m2 = size_datacenter(dc, SIZING).total_m2
    before = dc.footprint
    at.run(timeout=30)  # reruns alone never change the footprint (no widget round-off creep)
    assert at.session_state["project"].facilities[0].footprint == before
    assert before.area_m2 == pytest.approx(area_m2, rel=1e-12)

    at.number_input(key="w_block_width_ft").set_value(400.0).run(timeout=30)
    fp = at.session_state["project"].facilities[0].footprint
    assert fp.width_m == pytest.approx(400 * 0.3048)
    assert fp.area_m2 == pytest.approx(area_m2, rel=1e-12)
    at.slider(key="w_block_rotation_deg").set_value(30).run(timeout=30)
    assert at.session_state["project"].facilities[0].footprint.rotation_deg == 30.0

    saved = _saved(at)
    assert saved["facilities"][0]["footprint"]["rotation_deg"] == 30.0
    assert saved["step"] == "data_center"


def test_open_project_resumes_on_saved_tab() -> None:
    from core.persistence.project import Project

    default_store().write_autosave(Project(step="modules"), "saved-1", utcnow())
    at = AppTest.from_file(ENTRY).run(timeout=30)
    open_btn = next(b for b in at.button if b.label == "Open project")
    open_btn.click().run(timeout=30)
    assert not at.exception
    assert at.session_state["project"].step == "modules"
    assert "No modules on the site yet" in _texts(at)


@pytest.mark.usefixtures("fake_weather")
def test_length_input_and_align_to_edge(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")  # renders the footprint editor component
    assert not at.exception
    fp = at.session_state["project"].facilities[0].footprint
    at.number_input(key="w_block_length_ft").set_value(500.0).run(timeout=30)
    new = at.session_state["project"].facilities[0].footprint
    assert new.length_m == pytest.approx(500 * 0.3048)
    assert new.area_m2 == pytest.approx(fp.area_m2, rel=1e-12)
    assert at.number_input(key="w_block_width_ft").value == pytest.approx(
        new.width_m / 0.3048, rel=1e-6
    )
    align = next(b for b in at.button if b.label == "Align to property edge")
    assert align.disabled  # no boundary yet

    p = at.session_state["project"]
    ring = ((33.449, -112.071), (33.449, -112.069), (33.451, -112.069), (33.451, -112.071))
    at.session_state["project"] = p.model_copy(
        update={"site": p.site.model_copy(update={"boundary": ring})}
    )
    at.slider(key="w_block_rotation_deg").set_value(33).run(timeout=30)
    next(b for b in at.button if b.label == "Align to property edge").click().run(timeout=30)
    rot = at.session_state["project"].facilities[0].footprint.rotation_deg
    assert min(rot % 90, 90 - rot % 90) == pytest.approx(0, abs=0.5)  # square to the parcel


@pytest.mark.usefixtures("fake_weather")
def test_pv_area_drives_results_and_density(isolated_data: Path) -> None:
    from core.site_layout import place_module_area

    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")  # creates the facility
    p = at.session_state["project"]
    ring = ((33.448, -112.072), (33.448, -112.068), (33.452, -112.068), (33.452, -112.072))
    at.session_state["project"] = p.model_copy(
        update={"site": p.site.model_copy(update={"boundary": ring})}
    )
    _run_all_modules(at)
    _open_tab(at, "Modules")
    _add_module(at, "solar_pv")
    assert "Use the polygon tool to draw the area dedicated to solar" in _texts(at)
    assert "pv_kw" not in at.session_state["results"].frame.columns

    # Simulate a drawn PV area overlapping the property edge (map drawing can't be
    # clicked in AppTest; the handler calls place_module_area exactly like this).
    drawn = ((33.4485, -112.0715), (33.4485, -112.066), (33.4515, -112.066), (33.4515, -112.0715))
    at.session_state["project"] = place_module_area(at.session_state["project"], "solar_pv", drawn)
    at.run(timeout=30)
    assert not at.exception
    pv = at.session_state["project"].modules.solar_pv
    assert pv.placed
    frame = at.session_state["results"].frame
    assert frame["pv_kw"].min() < 0
    assert "Annual PV generation" in [m.label for m in at.metric]
    assert "DC capacity" in [m.label for m in at.metric]

    before = frame["pv_kw"].sum()
    at.slider(key="w_pv_power_density_w_sqft").set_value(8.0).run(timeout=30)
    after = at.session_state["results"].frame["pv_kw"].sum()
    assert after == pytest.approx(before * 8.0 / 6.5, rel=1e-3)

    clear = next(b for b in at.button if b.label == "Clear area and redraw")
    clear.click().run(timeout=30)
    assert not at.session_state["project"].modules.solar_pv.placed
    assert "pv_kw" not in at.session_state["results"].frame.columns
    saved = _saved(at)
    assert saved["modules"]["solar_pv"]["power_density_w_sqft"] == 8.0


@pytest.mark.usefixtures("fake_weather")
def test_ice_storage_toggle_updates_results(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _open_tab(at, "Modules")
    _add_module(at, "ice_storage")
    assert not at.exception
    frame = at.session_state["results"].frame
    assert "ice_soc_frac" in frame.columns
    labels = [m.label for m in at.metric]
    assert "Annual cooling from ice" in labels and "Annual ice maker electricity" in labels
    assert at.select_slider(key="w_ice_size_tr").value == pytest.approx(650)  # 65 TR/MW × 10 MW
    at.select_slider(key="w_ice_size_tr").set_value(2000.0).run(timeout=30)
    assert at.session_state["project"].modules.ice_storage.ice_maker_size_tr == 2000.0
    next(b for b in at.button if b.key == "ice_size_follow").click().run(timeout=30)
    assert at.session_state["project"].modules.ice_storage.ice_maker_size_tr is None


@pytest.mark.usefixtures("fake_weather")
def test_ice_mixer_panel_and_solved_run(isolated_data: Path) -> None:
    """D-050, D-052: no footprint; with ice storage on, the mixer uses its ice."""
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _run_all_modules(at)
    _open_tab(at, "Modules")
    _add_module(at, "ice_storage")
    _add_module(at, "ice_mixer")
    assert not at.exception
    mixer = at.session_state["project"].modules.ice_mixer
    assert mixer.enabled and mixer.fluid == "water"
    # water: the brine-only sliders are hidden (owner)
    assert not any(s.key == "w_imix_recup_eta_pct" for s in at.slider)
    frame = at.session_state["results"].frame
    assert frame["ice_mix_ice_kg_s"].sum() > 0
    assert frame["ice_supplied_kg_s"].sum() > 0
    # brine without brine separation: a warning, and the run reports the error
    at.radio(key="w_imix_fluid").set_value("brine").run(timeout=30)
    assert not at.exception
    assert any("brine separation" in w.value for w in at.warning)
    at.slider(key="w_imix_recup_eta_pct").set_value(60.0).run(timeout=30)
    mixer = at.session_state["project"].modules.ice_mixer
    assert mixer.fluid == "brine" and mixer.recup_eta_pct == 60.0
    # back to water: the brine settings are kept
    at.radio(key="w_imix_fluid").set_value("water").run(timeout=30)
    assert at.session_state["project"].modules.ice_mixer.recup_eta_pct == 60.0


@pytest.mark.usefixtures("fake_weather")
def test_pv_tilt_defaults_to_site_latitude(isolated_data: Path) -> None:
    at = _workspace()
    _set_location(at)  # lat 33.45
    _open_tab(at, "Modules")
    _add_module(at, "solar_pv")
    assert at.number_input(key="w_pv_tilt_deg").value == pytest.approx(33.45)
    assert at.session_state["project"].modules.solar_pv.tilt_deg is None
    # Other inputs don't freeze the tilt.
    at.slider(key="w_pv_power_density_w_sqft").set_value(7.0).run(timeout=30)
    assert at.session_state["project"].modules.solar_pv.tilt_deg is None
    # A typed tilt sticks …
    at.number_input(key="w_pv_tilt_deg").set_value(25.0).run(timeout=30)
    assert at.session_state["project"].modules.solar_pv.tilt_deg == 25.0
    # … until reset to the latitude.
    next(b for b in at.button if b.label == "Use site latitude").click().run(timeout=30)
    assert at.session_state["project"].modules.solar_pv.tilt_deg is None
    assert at.number_input(key="w_pv_tilt_deg").value == pytest.approx(33.45)


@pytest.mark.usefixtures("fake_weather")
def test_greenhouse_inputs(isolated_data: Path) -> None:
    """D-061: added like PV (drawn area); its sliders save to the project."""
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Modules")
    _add_module(at, "greenhouse")
    gh = at.session_state["project"].modules.greenhouse
    assert gh.enabled and not gh.placed  # no area drawn yet
    assert at.slider(key="w_gh_transmissivity_pct").value == 90.0
    at.slider(key="w_gh_t_set_c").set_value(25.0).run(timeout=30)
    at.slider(key="w_gh_u_w_m2k").set_value(6.4).run(timeout=30)
    gh = at.session_state["project"].modules.greenhouse
    assert (gh.t_set_c, gh.u_w_m2k, gh.transmissivity_pct) == (25.0, 6.4, 90.0)
    # the guide is linked right under the U slider (owner)
    assert any("aggie-horticulture.tamu.edu" in str(c.value) for c in at.caption)
    assert not at.exception


def test_pv_azimuth_defaults_by_hemisphere() -> None:
    at = _workspace()
    _set_location(at)  # Phoenix: northern hemisphere → south-facing
    _open_tab(at, "Modules")
    _add_module(at, "solar_pv")
    assert at.number_input(key="w_pv_azimuth_deg").value == 180.0
    p = at.session_state["project"]
    at.session_state["project"] = p.model_copy(  # move the site to Cape Town
        update={"site": p.site.model_copy(update={"lat": -33.9, "lon": 18.4})}
    )
    at.run(timeout=30)
    assert at.number_input(key="w_pv_azimuth_deg").value == 0.0  # faces north
    assert at.number_input(key="w_pv_tilt_deg").value == pytest.approx(33.9)
    at.number_input(key="w_pv_azimuth_deg").set_value(45.0).run(timeout=30)
    assert at.session_state["project"].modules.solar_pv.azimuth_deg == 45.0
    next(b for b in at.button if b.label == "Face the equator").click().run(timeout=30)
    assert at.session_state["project"].modules.solar_pv.azimuth_deg is None


def test_reset_session_reopens_the_project_in_the_link() -> None:
    """Regression (D-040, D-069): a session Streamlit dropped while the browser was
    away came back blank and its first click overwrote the autosave. The URL
    (?project=<stem>) names the project, so it is reopened, never another one."""
    from core.domain.site import Site
    from core.persistence.project import Project

    ring = ((39.74, -105.17), (39.74, -105.16), (39.75, -105.16))
    real = Project(site=Site(name="Golden", lat=39.7407, lon=-105.1686, boundary=ring))
    default_store().write_autosave(real, "golden-1", utcnow())
    default_store().write_autosave(Project(), "someone-elses", utcnow())  # newer

    at = AppTest.from_file(ENTRY).run(timeout=30)
    at.query_params["project"] = "golden-1"
    at.switch_page(WORKSPACE).run(timeout=30)  # new session lands on the project's URL
    assert not at.exception
    assert at.session_state["project"].site.lat == 39.7407  # reopened, not blank
    at.session_state["w_tab"] = "Property"
    at.run(timeout=30)  # the click that used to blank the file
    saved = json.loads(to_json(default_store().load_project("golden-1")))
    assert saved["site"]["lat"] == 39.7407 and len(saved["site"]["boundary"]) == 3


@pytest.mark.parametrize("link", [None, "not-saved"])
def test_no_project_in_the_link_goes_to_start(link: str | None) -> None:
    """Without a saved project in the URL the workspace goes to Start (other
    people's projects are never reopened)."""
    from core.persistence.project import Project

    default_store().write_autosave(Project(), "someone-elses", utcnow())
    at = AppTest.from_file(ENTRY).run(timeout=30)
    if link:
        at.query_params["project"] = link
    at.switch_page(WORKSPACE).run(timeout=30)
    assert not at.exception
    assert not at.tabs  # Start page shown, not a blank workspace
    assert [e.stem for e in default_store().list_projects()] == ["someone-elses"]


def test_workspace_url_names_the_project() -> None:
    at = _workspace()
    at.number_input(key="w_lat").set_value(10.0).run(timeout=30)
    assert at.query_params["project"] == [at.session_state["project_autosave_stem"]]


def test_two_new_projects_get_separate_autosaves() -> None:
    stems = []
    for lat in (10.0, 20.0):
        at = _workspace()
        at.number_input(key="w_lat").set_value(lat).run(timeout=30)
        at.number_input(key="w_lon").set_value(-100.0).run(timeout=30)
        stems.append(at.session_state["project_autosave_stem"])
    assert stems[0] != stems[1]
    assert [default_store().load_project(s).site.lat for s in stems] == [10.0, 20.0]


def test_save_and_restore_a_version(isolated_data: Path) -> None:
    at = _workspace()
    at.number_input(key="w_lat").set_value(10.0).run(timeout=30)
    at.number_input(key="w_lon").set_value(-100.0).run(timeout=30)
    at.text_input(key="version_label").input("first try").run(timeout=30)
    next(b for b in at.button if b.label == "Save").click().run(timeout=30)
    assert any("Saved version" in s.value for s in at.success)
    at.number_input(key="w_lat").set_value(20.0).run(timeout=30)
    assert _saved(at)["site"]["lat"] == 20.0

    restore = next(b for b in at.button if b.key == "restore_version_0")
    restore.click().run(timeout=30)
    assert not at.exception
    assert at.session_state["project"].site.lat == 10.0
    assert at.number_input(key="w_lat").value == 10.0  # widgets re-seeded
    assert _saved(at)["site"]["lat"] == 10.0
    stem = at.session_state["project_autosave_stem"]
    history = default_store().list_history(stem)
    assert any(default_store().load_snapshot(h.id).site.lat == 20.0 for h in history)


def test_opened_project_keeps_its_stem() -> None:
    from core.domain.site import Site
    from core.persistence.project import Project

    default_store().write_autosave(
        Project(site=Site(name="Legacy", lat=1.0, lon=2.0)), "legacy-1", utcnow()
    )
    at = AppTest.from_file(ENTRY).run(timeout=30)
    next(b for b in at.button if b.label == "Open project").click().run(timeout=30)
    assert at.session_state["project_autosave_stem"] == "legacy-1"


@pytest.mark.usefixtures("fake_weather")
def test_ice_storage_block_is_placed_and_sized_by_inputs(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _open_tab(at, "Modules")
    _add_module(at, "ice_storage")
    assert not at.exception
    from core.site_layout import module_context

    project = at.session_state["project"]
    ice = project.modules.ice_storage
    assert ice.footprint is not None  # placed beside the data center
    assert ice.footprint.area_m2 == pytest.approx(
        ice.resolved(module_context(project)).block_area_m2
    )
    assert "Footprint" in [m.label for m in at.metric]
    at.number_input(key="w_ice_energy_density_kwh_sqft").set_value(30.0).run(timeout=30)
    resized = at.session_state["project"].modules.ice_storage.footprint
    assert resized.area_m2 == pytest.approx(ice.footprint.area_m2 / 2)
    assert resized.center == ice.footprint.center
    at.number_input(key="w_ice_block_width_ft").set_value(10.0).run(timeout=30)
    reshaped = at.session_state["project"].modules.ice_storage.footprint
    assert reshaped.area_m2 == pytest.approx(resized.area_m2)  # area held while reshaping


@pytest.mark.usefixtures("fake_weather")
def test_clicking_an_object_on_the_map_selects_its_tab(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.components.map_view as mv

    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")  # creates the DC block → map editor on this tab
    event = {"value": None}
    monkeypatch.setattr(mv, "map_editor", lambda project, **kw: event["value"])
    p = at.session_state["project"]
    at.session_state["project"] = p.model_copy(
        update={
            "modules": p.modules.model_copy(
                update={"ice_storage": p.modules.ice_storage.model_copy(update={"enabled": True})}
            )
        }
    )
    at.run(timeout=30)
    # Click the ice block (shown read-only on the Data center tab).
    event["value"] = {"kind": "select", "owner": "ice_storage", "event_id": "c1"}
    at.run(timeout=30)
    at.run(timeout=30)  # the selection applies at the start of the next run
    assert not at.exception
    assert at.session_state["project"].step == "modules"
    assert at.segmented_control(key="w_module").value == "ice_storage"


@pytest.mark.usefixtures("fake_weather")
def test_utility_tab_paints_and_bills(isolated_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.components.tabs.utility as utility_tab

    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    event = {"value": None}
    monkeypatch.setattr(utility_tab, "tariff_editor", lambda tariff, key: event["value"])
    _open_tab(at, "Utility")
    assert at.radio(key="w_weekend_pricing").value == "follow_schedule"
    base = at.session_state["results"].frame["energy_cost_usd"].sum()
    # Paint peak on every July afternoon hour via the painter's event.
    event["value"] = {
        "kind": "paint",
        "category": "peak",
        "event_id": "p1",
        "cells": [[6, h] for h in range(12, 18)],
    }
    at.run(timeout=30)
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["project"].utility.schedule[6][13] == "peak"
    assert at.session_state["results"].frame["energy_cost_usd"].sum() > base
    labels = [m.label for m in at.metric]
    assert "Annual utility cost" in labels and "Average utility cost" in labels
    at.radio(key="w_weekend_pricing").set_value("off_peak").run(timeout=30)
    assert at.session_state["project"].utility.weekend.value == "off_peak"
    saved = _saved(at)
    assert saved["utility"]["weekend"] == "off_peak"


@pytest.mark.usefixtures("fake_weather")
def test_power_generation_toggle_updates_results(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _run_all_modules(at)
    _open_tab(at, "Modules")
    _add_module(at, "power_generation")
    assert not at.exception
    frame = at.session_state["results"].frame
    assert frame["power_gen_kw"].min() < 0  # generation is negative
    labels = [m.label for m in at.metric]
    assert "Annual power generation" in labels
    assert at.slider(key="w_pgen_rated_pct_of_it").value == pytest.approx(2)
    assert at.slider(key="w_pgen_rated_pct_of_it").max == pytest.approx(150)
    assert "= 0.20 MWe" in _texts(at)  # 2 % × 10 MW, in grey under the slider
    assert at.slider(key="w_pgen_t_cold_max_c").max == pytest.approx(30)  # free-cooling cutoff
    pg = at.session_state["project"].modules.power_generation
    assert pg.footprint is not None and pg.footprint.area_m2 == pytest.approx(400 * 0.09290304)
    at.slider(key="w_pgen_rated_pct_of_it").set_value(10.0).run(timeout=30)
    assert at.session_state["project"].modules.power_generation.rated_pct_of_it == 10.0
    assert "= 1.00 MWe" in _texts(at)


@pytest.mark.usefixtures("fake_weather")
def test_hot_water_storage_panel(isolated_data: Path) -> None:
    from core.config.defaults import HwsTankType

    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _run_all_modules(at)
    _open_tab(at, "Modules")
    _add_module(at, "hot_water_storage")
    assert not at.exception
    assert at.slider(key="w_hws_storage_hours").value == 12
    frame = at.session_state["results"].frame
    assert frame["hws_charge_kwth"].sum() > 0
    assert "Heat into hot water storage" in [m.label for m in at.metric]
    fp = at.session_state["project"].modules.hot_water_storage.footprint
    assert fp is not None and fp.width_m > 1.5 * fp.length_m  # two tank: 2:1 default
    assert not any("perfect stratification" in m.value for m in at.markdown)
    at.radio(key="w_hws_tank_type").set_value(HwsTankType.THERMOCLINE).run(timeout=30)
    assert not at.exception
    assert any("perfect stratification" in m.value for m in at.markdown)
    fp2 = at.session_state["project"].modules.hot_water_storage.footprint
    assert fp2 is not None and fp2.width_m == pytest.approx(fp2.length_m)  # square
    assert fp2.center == pytest.approx(fp.center)  # stays where it was


def test_type_form_supply_range_sets_min_and_setpoint(isolated_data: Path) -> None:
    at = _workspace()
    _open_tab(at, "Data center")
    assert at.slider(key="dct_t_supply").value == (5.0, 40.0)
    at.slider(key="dct_t_supply").set_value((12.0, 35.0))
    at.button(key=SAVE_TYPE).click().run(timeout=30)
    assert not at.exception
    (saved,) = default_store().list_types()
    assert (saved.t_supply_min_c, saved.t_supply_c) == (12.0, 35.0)


@pytest.mark.usefixtures("fake_weather")
def test_brine_separation_panel(isolated_data: Path) -> None:
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _run_all_modules(at)
    _open_tab(at, "Modules")
    _add_module(at, "brine_separation")
    assert not at.exception
    assert at.slider(key="w_brine_conc_wt_pct").value == (20.0, 40.0)
    assert at.slider(key="w_brine_concentrate_hours").value == 24
    assert at.selectbox(key="w_brine_brine_type").options == ["Potassium acetate"]
    frame = at.session_state["results"].frame
    assert frame["brine_heat_kwth"].sum() > 0
    labels = [m.label for m in at.metric]
    assert "Water recovered from brine" in labels
    fp = at.session_state["project"].modules.brine_separation.footprint
    assert fp is not None and fp.width_m == pytest.approx(fp.length_m)  # square block
    at.slider(key="w_brine_conc_wt_pct").set_value((25.0, 45.0)).run(timeout=30)
    br = at.session_state["project"].modules.brine_separation
    assert (br.conc_low_wt_pct, br.conc_high_wt_pct) == (25.0, 45.0)


@pytest.mark.usefixtures("fake_weather")
def test_control_tab_builds_a_state_machine(isolated_data: Path) -> None:
    """D-053, D-054: Default only at first (nothing listed); add a state, give it
    IFs and a THEN, and the live run follows it."""
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _open_tab(at, "Control")
    assert _state_picker(at).value == "default"
    assert "Nothing listed" in _texts(at)
    before = _state_picker(at).key
    at.button(key="w_ctl_add").click().run(timeout=30)
    assert not at.exception
    # D-068: code changed the selection, so the picker is a new widget (the
    # browser can't send back the old one's value), and an IF edit keeps it
    assert _state_picker(at).key != before
    at.selectbox(key="w_ctl_if_s1_source").set_value("ambient").run(timeout=30)
    assert _state_picker(at).value == "s1"
    control = at.session_state["project"].control
    assert [s.name for s in control.states] == ["State 1"]
    assert _state_picker(at).value == "s1"  # opens the new state
    at.text_input(key="w_ctl_name_s1").set_value("Afternoon").run(timeout=30)
    # a name typed next to Add state names the new state (owner)
    at.text_input(key="w_ctl_new_name").set_value("Night").run(timeout=30)
    at.button(key="w_ctl_add").click().run(timeout=30)
    assert [s.name for s in at.session_state["project"].control.states] == ["Afternoon", "Night"]
    assert _state_picker(at).value == "s2"
    assert at.text_input(key="w_ctl_new_name").value == ""
    at.button(key="w_ctl_del_s2").click().run(timeout=30)
    assert len(at.get("bidi_component")) >= 1  # the diagram (and results figure) mounted
    _state_picker(at).set_value("s1").run(timeout=30)
    # IF time: hour of day ≥ 12
    at.selectbox(key="w_ctl_if_s1_source").set_value("time").run(timeout=30)
    at.selectbox(key="w_ctl_if_s1_var_time").set_value("hour").run(timeout=30)
    at.selectbox(key="w_ctl_if_s1_op").set_value("≥").run(timeout=30)
    at.number_input(key="w_ctl_if_s1_value").set_value(12.0).run(timeout=30)
    at.button(key="w_ctl_if_s1_add").click().run(timeout=30)
    # IF date ≥ 01-01 (always true; checks the MM-DD input)
    at.selectbox(key="w_ctl_if_s1_var_time").set_value("date").run(timeout=30)
    at.selectbox(key="w_ctl_if_s1_op").set_value("≥").run(timeout=30)
    at.text_input(key="w_ctl_if_s1_date").set_value("01-01").run(timeout=30)
    at.button(key="w_ctl_if_s1_add").click().run(timeout=30)
    assert "IF Time: Date is ≥ 01-01" in " ".join(str(m.value) for m in at.markdown)
    # THEN data center IT load = 50 %
    at.selectbox(key="w_ctl_then_s1_target").set_value("data_center").run(timeout=30)
    at.number_input(key="w_ctl_then_s1_value_data_center_it_load_pct").set_value(50.0).run(
        timeout=30
    )
    at.button(key="w_ctl_then_s1_add").click().run(timeout=30)
    assert not at.exception
    s1 = at.session_state["project"].control.state("s1")
    assert s1.name == "Afternoon"
    assert (s1.conditions[0].variable, s1.conditions[0].op, s1.conditions[0].value) == (
        "hour",
        "≥",
        12.0,
    )
    assert (s1.conditions[1].variable, s1.conditions[1].value) == ("date", 101.0)
    assert (s1.actions[0].target, s1.actions[0].value) == ("data_center", 50.0)
    # Edit: the IF leaves the list and fills the add row; Add puts it back in place
    at.button(key="w_ctl_ed_if_s1_0").click().run(timeout=30)
    assert len(at.session_state["project"].control.state("s1").conditions) == 1
    assert at.selectbox(key="w_ctl_if_s1_var_time").value == "hour"
    assert at.number_input(key="w_ctl_if_s1_value").value == 12.0
    at.number_input(key="w_ctl_if_s1_value").set_value(13.0).run(timeout=30)
    at.button(key="w_ctl_if_s1_add").click().run(timeout=30)
    conds = at.session_state["project"].control.state("s1").conditions
    assert [(c.variable, c.value) for c in conds] == [("hour", 13.0), ("date", 101.0)]
    at.button(key="w_ctl_ed_if_s1_0").click().run(timeout=30)
    at.number_input(key="w_ctl_if_s1_value").set_value(12.0).run(timeout=30)
    at.button(key="w_ctl_if_s1_add").click().run(timeout=30)
    # IF utility: energy price ≥ a rate category from the Utility tab (owner, D-059)
    at.selectbox(key="w_ctl_if_s1_source").set_value("utility").run(timeout=30)
    ref = at.selectbox(key="w_ctl_if_s1_ref_utility_energy_price")
    assert ref.options[-3:] == [
        "the Off peak rate (0.1 $/kWh)",
        "the Shoulder rate (0.15 $/kWh)",
        "the Peak rate (0.2 $/kWh)",
    ]
    ref.set_value("rate:peak").run(timeout=30)
    at.selectbox(key="w_ctl_if_s1_op").set_value("≥").run(timeout=30)
    at.button(key="w_ctl_if_s1_add").click().run(timeout=30)
    rate_if = at.session_state["project"].control.state("s1").conditions[-1]
    assert (rate_if.reference, rate_if.category) == ("rate", "peak")
    assert "IF Utility: Energy price is ≥ the Peak rate (0.2 $/kWh)" in " ".join(
        str(m.value) for m in at.markdown
    )
    at.button(key="w_ctl_ed_if_s1_2").click().run(timeout=30)  # Edit fills it back in
    assert at.selectbox(key="w_ctl_if_s1_ref_utility_energy_price").value == "rate:peak"
    # the same THEN twice is refused
    at.button(key="w_ctl_then_s1_add").click().run(timeout=30)
    assert len(at.session_state["project"].control.state("s1").actions) == 1
    frame = at.session_state["results"].frame
    pm = frame.index.hour >= 12
    assert (frame["control_state"][pm] == 1).all() and (frame["control_state"][~pm] == 0).all()
    assert frame["it_load_kw"][pm].max() == pytest.approx(0.5 * frame["it_load_plan_kw"].max())
    at.button(key="w_ctl_del_s1").click().run(timeout=30)
    assert at.session_state["project"].control.states == ()
    assert _state_picker(at).value == "default"


@pytest.mark.usefixtures("fake_weather")
def test_control_tab_link_thens_in_order(isolated_data: Path) -> None:
    """D-054: build power generation's links in Default from the sentence rows;
    the editor flags what is missing, and ↑ / ↓ reorder the THENs."""
    default_store().save_type(DataCenterType())
    at = _workspace()
    _set_location(at)
    _open_tab(at, "Data center")
    _open_tab(at, "Modules")
    _add_module(at, "power_generation")
    _open_tab(at, "Control")
    k = "w_ctl_then_default_"
    at.selectbox(key=k + "target").set_value("power_generation").run(timeout=30)
    at.selectbox(key=k + "setting_power_generation").set_value("heat_in").run(timeout=30)
    at.selectbox(key=k + "to_power_generation_heat_in").set_value("data_center").run(timeout=30)
    at.button(key=k + "add").click().run(timeout=30)
    assert not at.exception
    assert any("no cooling" in str(w.value) for w in at.warning)  # no cold side yet
    assert (at.session_state["results"].frame["power_gen_kw"] == 0).all()
    at.selectbox(key=k + "setting_power_generation").set_value("cooling_in").run(timeout=30)
    at.selectbox(key=k + "to_power_generation_cooling_in").set_value("coolant").run(timeout=30)
    at.button(key=k + "add").click().run(timeout=30)
    assert not at.exception
    acts = at.session_state["project"].control.default.actions
    assert [(a.setting, a.to) for a in acts] == [
        ("heat_in", "data_center"),
        ("cooling_in", "coolant"),
    ]
    assert not any("no cooling" in str(w.value) for w in at.warning)
    assert at.session_state["results"].frame["power_gen_kw"].min() < 0
    at.button(key="w_ctl_up_then_default_1").click().run(timeout=30)
    acts = at.session_state["project"].control.default.actions
    assert [a.setting for a in acts] == ["cooling_in", "heat_in"]
    # Edit a link THEN: its sentence and other end fill the add row; it goes back in place
    at.button(key="w_ctl_ed_then_default_0").click().run(timeout=30)
    assert [a.setting for a in at.session_state["project"].control.default.actions] == ["heat_in"]
    assert at.selectbox(key=k + "setting_power_generation").value == "cooling_in"
    assert at.selectbox(key=k + "to_power_generation_cooling_in").value == "coolant"
    at.button(key=k + "add").click().run(timeout=30)
    acts = at.session_state["project"].control.default.actions
    assert [a.setting for a in acts] == ["cooling_in", "heat_in"]
