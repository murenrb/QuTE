"""Control tab: the user's state machine (docs/control.md, D-053, D-054).

The state diagram on top (click a state to edit it), and the selected state's
setup underneath: its name, priority and allowed moves, its IFs (all must
hold to enter / stay) and its THENs. Each state is a complete description:
a module runs only if a THEN names it, and links are served in THEN order.
The Default state has no IFs.

Rules read as sentences: the first blank is the component, the rest of the
blanks follow from the choice (the IFs / THENs each module declares).
Widgets mirror the project on every render (set before they are drawn), and
every change is saved straight into the project.
"""

from typing import Any

import streamlit as st

from app import state
from app.components.control_diagram import clicked_state, node_label, state_diagram
from core.config.defaults import CoolingType, IceMixerFluid
from core.control.catalog import (
    SOURCES,
    SPECS,
    TARGETS,
    end_label,
    run_everything_in_default,
)
from core.control.engine import ALWAYS_ON, warnings
from core.domain.control import (
    DATA_CENTER,
    DEFAULT_STATE_ID,
    OFFERED_REFERENCES,
    Action,
    Condition,
    ControlSettings,
    ControlState,
    ControlVariable,
    Operator,
    Reference,
    SettingKind,
    date_text,
    date_value,
)
from core.domain.utility import UtilityTariff
from core.persistence.project import Project, inputs_hash
from core.timeseries import columns as col

P = f"{state.WIDGET_PREFIX}ctl_"
# The state being edited lives in K_CURRENT, a plain session key the browser
# never sees. The picker widget's key carries a generation number that code
# bumps whenever it changes the selection (Add / Delete state, a diagram
# click), so the picker is a new widget then and the browser can't send back
# an old value (owner: "taken back to Default" after Add state, D-068).
K_CURRENT = P + "current"
K_PICKER_GEN = P + "picker_gen"
K_SELECTED = P + "selected"  # + "_<generation>": the picker widget
K_NEW_NAME = P + "new_name"
DIAGRAM_KEY = "ctl_diagram"
PICKER_KEY = "ctl_picker"  # container pinned at the top of the tab (style.py)
K_SCROLL = "ctl_scroll_to_editor"  # set by a diagram click: bring the editor into view
REFERENCE_LABELS = {
    Reference.VALUE: "a value",
    Reference.DAY_MEAN: "the daily average",
    Reference.DAY_MEDIAN: "the daily median",
    Reference.DAY_Q1: "the daily lower quartile",
    Reference.DAY_Q3: "the daily upper quartile",
    Reference.YEAR_MEAN: "the annual average",
    Reference.YEAR_MEDIAN: "the annual median",
    Reference.MONTH_MEAN: "the month's average",
    Reference.MONTH_MEDIAN: "the month's median",
    Reference.RATE: "a rate category",
}
BLANK = "…"
RATE_PREFIX = "rate:"  # "Than" option for a rate category: "rate:<category id>" (D-059)
TARGET_KEYS = {t.key for t in TARGETS}


# --- project edits -------------------------------------------------------------


def _settings() -> ControlSettings:
    return state.get_project().control


def _store(settings: ControlSettings) -> None:
    p = state.get_project()
    state.set_project(p.model_copy(update={"control": settings}))


def _update_state(state_id: str, **changes: Any) -> None:
    s = _settings()
    _store(s.replace(s.state(state_id).model_copy(update=changes)))


def _add_state() -> None:
    """A new state may move anywhere and starts with the Default state's THENs.
    Its name is the one typed next to the button (or "State n")."""
    s = _settings()
    name = str(st.session_state.get(K_NEW_NAME) or "").strip() or f"State {len(s.states) + 1}"
    new = ControlState(id=s.new_state_id(), name=name, actions=s.default.actions)
    _store(s.model_copy(update={"states": (*s.states, new)}))
    _select(new.id)
    st.session_state[K_NEW_NAME] = ""


def _delete_state(state_id: str) -> None:
    _store(_settings().remove(state_id))
    _select(DEFAULT_STATE_ID)


def _move(state_id: str, by: int) -> None:
    """Change priority (position in the list)."""
    s = _settings()
    ids = [x.id for x in s.states]
    i = ids.index(state_id)
    j = min(max(i + by, 0), len(ids) - 1)
    states = list(s.states)
    states[i], states[j] = states[j], states[i]
    _store(s.model_copy(update={"states": tuple(states)}))


def _renamed(state_id: str) -> None:
    name = str(st.session_state[P + f"name_{state_id}"]).strip()
    if name:
        _update_state(state_id, name=name)


def _next_changed(state_id: str) -> None:
    chosen = tuple(st.session_state[P + f"next_{state_id}"])
    others = [x.id for x in _settings().states if x.id != state_id]
    # Every other state ticked = "any", which also covers states added later.
    _update_state(state_id, next_states=None if set(chosen) == set(others) else chosen)


def _parse_date(text: str) -> float | None:
    try:
        month, day = (int(x) for x in text.strip().split("-"))
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return date_value(month, day)


def _add_condition(state_id: str) -> None:
    k = P + f"if_{state_id}_"
    source = str(st.session_state[k + "source"])
    variable = SPECS[source].variable(str(st.session_state[k + f"var_{source}"]))
    if variable.kind == "on_off":
        on = st.session_state[k + "always"] == "On"
        value = 1.0 if on else 0.0
        c = Condition(source=source, variable=variable.key, op=Operator.EQ, value=value)
    elif variable.kind == "date":
        date = _parse_date(str(st.session_state[k + "date"]))
        if date is None:
            state.flash("control", "error", "Enter the date as MM-DD, e.g. 06-01.")
            return
        op = Operator(st.session_state[k + "op"])
        c = Condition(source=source, variable=variable.key, op=op, value=date)
    else:
        ref_key = k + f"ref_{source}_{variable.key}"
        ref, category = _parse_reference(str(st.session_state.get(ref_key, Reference.VALUE)))
        if not variable.statistics:
            ref, category = Reference.VALUE, None
        c = Condition(
            source=source,
            variable=variable.key,
            op=Operator(st.session_state[k + "op"]),
            value=float(st.session_state[k + "value"]),
            reference=ref,
            category=category,
        )
    conds = list(_settings().state(state_id).conditions)
    if c in conds:
        state.flash("control", "info", "That IF is already in this state.")
        return
    conds.insert(_insert_at(k, len(conds)), c)
    _update_state(state_id, conditions=tuple(conds))


def _parse_reference(option: str) -> tuple[Reference, str | None]:
    """A "Than" option → (reference, rate category id)."""
    if option.startswith(RATE_PREFIX):
        return Reference.RATE, option.removeprefix(RATE_PREFIX)
    return Reference(option), None


def _reference_option(c: Condition) -> str:
    return RATE_PREFIX + (c.category or "") if c.reference is Reference.RATE else c.reference.value


def _insert_at(k: str, n: int) -> int:
    """Where an Add puts the rule: back where it was while editing, else at the end."""
    at = st.session_state.pop(k + "editing", None)
    return n if at is None else min(int(at), n)


def _remove_condition(state_id: str, i: int) -> None:
    conds = list(_settings().state(state_id).conditions)
    del conds[i]
    _update_state(state_id, conditions=tuple(conds))


def _edit_condition(state_id: str, i: int) -> None:
    """Take the IF out and put it in the add row, to change and add back (owner)."""
    c = _settings().state(state_id).conditions[i]
    _remove_condition(state_id, i)
    k = P + f"if_{state_id}_"
    ss = st.session_state
    ss[k + "editing"] = i
    present = _present(state.get_project())
    if c.source not in SPECS or (c.source in TARGET_KEYS and c.source not in present):
        return
    ss[k + "source"] = c.source
    ss[k + f"var_{c.source}"] = c.variable
    v = (
        SPECS[c.source].variable(c.variable)
        if c.variable in {x.key for x in SPECS[c.source].ifs}
        else None
    )
    if v is not None and v.kind == "on_off":
        ss[k + "always"] = "On" if c.value >= 1 else "Off"
        return
    ss[k + "op"] = c.op.value
    if v is not None and v.kind == "date":
        ss[k + "date"] = date_text(c.value)
        return
    ss[k + "value"] = float(c.value)
    if v is not None and v.statistics:
        option = _reference_option(c)
        if c.reference is not Reference.RATE or c.category in {
            x.id for x in state.get_project().utility.categories
        }:
            ss[k + f"ref_{c.source}_{c.variable}"] = option


def _add_action(state_id: str) -> None:
    """Append a THEN (a number or a flag replaces an earlier one for the same setting)."""
    k = P + f"then_{state_id}_"
    target = str(st.session_state[k + "target"])
    key = str(st.session_state[k + f"setting_{target}"])
    s = SPECS[target].setting(key)
    value = float(st.session_state.get(k + f"value_{target}_{key}", s.default))
    to = str(st.session_state[k + f"to_{target}_{key}"]) if s.kind is SettingKind.LINK else None
    new = Action(target=target, setting=key, value=value if s.has_value else 0.0, to=to)
    acts = list(_settings().state(state_id).actions)
    if new in acts:
        st.session_state.pop(k + "editing", None)
        state.flash("control", "info", "That THEN is already in this state.")
        return
    at = _insert_at(k, len(acts))
    if s.kind is not SettingKind.LINK:  # replaces an earlier one for the same setting
        kept = [a for a in acts if (a.target, a.setting) != (target, key)]
        at -= sum(1 for a in acts[:at] if a not in kept)
        acts = kept
    acts.insert(at, new)
    _update_state(state_id, actions=tuple(acts))


def _remove_action(state_id: str, i: int) -> None:
    acts = list(_settings().state(state_id).actions)
    del acts[i]
    _update_state(state_id, actions=tuple(acts))


def _edit_action(state_id: str, i: int) -> None:
    """Take the THEN out and put it in the add row; Add puts it back in its place."""
    a = _settings().state(state_id).actions[i]
    _remove_action(state_id, i)
    k = P + f"then_{state_id}_"
    ss = st.session_state
    ss[k + "editing"] = i
    present = _present(state.get_project())
    if (
        a.target not in present
        or a.target not in SPECS
        or not SPECS[a.target].has_setting(a.setting)
    ):
        return
    s = SPECS[a.target].setting(a.setting)
    ss[k + "target"] = a.target
    ss[k + f"setting_{a.target}"] = a.setting
    if s.has_value:
        ss[k + f"value_{a.target}_{a.setting}"] = float(a.value)
    if s.kind is SettingKind.LINK and a.to and (a.to in present or a.to in ALWAYS_ON):
        ss[k + f"to_{a.target}_{a.setting}"] = a.to


def _move_action(state_id: str, i: int, by: int) -> None:
    acts = list(_settings().state(state_id).actions)
    j = min(max(i + by, 0), len(acts) - 1)
    acts[i], acts[j] = acts[j], acts[i]
    _update_state(state_id, actions=tuple(acts))


def _run_everything() -> None:
    _store(run_everything_in_default(_settings()))


# --- text --------------------------------------------------------------------


def _rate_label(tariff: UtilityTariff, v: ControlVariable, category: str | None) -> str:
    """'the Peak rate (0.2 $/kWh)', from the Utility tab's rate categories (D-059)."""
    cat = next((x for x in tariff.categories if x.id == category), None)
    if cat is None:
        return "a rate no longer in the utility tariff"
    return f"the {cat.name} rate ({getattr(cat, v.rate_field):g} {v.unit})"


def condition_text(c: Condition, tariff: UtilityTariff | None = None) -> str:
    spec = SPECS.get(c.source)
    if spec is None or c.variable not in {v.key for v in spec.ifs}:
        return f"{c.source}.{c.variable} (no longer available)"
    v = spec.variable(c.variable)
    if v.kind == "on_off":
        return f"IF {spec.label}: {v.label} {'on' if c.value >= 1 else 'off'}"
    if v.kind == "date":
        rhs = date_text(c.value)
    elif c.reference is Reference.VALUE:
        rhs = f"{c.value:g} {v.unit}".rstrip()
    elif c.reference is Reference.RATE:
        rhs = _rate_label(tariff or UtilityTariff(), v, c.category)
    else:
        rhs = REFERENCE_LABELS[c.reference]
    return f"IF {spec.label}: {v.label} is {c.op.value} {rhs}"


def action_text(a: Action) -> str:
    spec = SPECS.get(a.target)
    if spec is None or not spec.has_setting(a.setting):
        return f"{a.target}.{a.setting} (no longer available)"
    s = spec.setting(a.setting)
    to = end_label(a.target, a.setting, a.to) if a.to else BLANK
    return f"THEN {spec.label}: " + s.label.format(value=f"{a.value:g}", to=to)


def _than_label(option: str, v: ControlVariable, tariff: UtilityTariff) -> str:
    ref, category = _parse_reference(option)
    return _rate_label(tariff, v, category) if ref is Reference.RATE else REFERENCE_LABELS[ref]


def _blank_label(label: str) -> str:
    return label.format(value=BLANK, to=BLANK)


def _variable_label(v: ControlVariable) -> str:
    return f"{v.label} ({v.unit})" if v.unit else v.label


# --- widgets -----------------------------------------------------------------


def _present(project: Project) -> set[str]:
    """The data center and the modules added on the Modules tab."""
    return set(project.modules.enabled_keys()) | {DATA_CENTER}


def _diagram_clicked() -> None:
    """A state clicked in the diagram (callback: runs before the page is drawn,
    so the picker shows it in the same rerun, D-066)."""
    select_state(clicked_state(DIAGRAM_KEY))


def select_state(state_id: str | None) -> None:
    if state_id in {s.id for s in _settings().all_states}:
        _select(state_id)
        st.session_state[K_SCROLL] = True


def _scroll_to_editor() -> None:
    """After a click on the diagram, scroll so the diagram sits just below the
    pinned state picker and the editor fills the rest: the change is in view
    (owner)."""
    if not st.session_state.pop(K_SCROLL, False):
        return
    anchor = f".st-key-{DIAGRAM_KEY}"
    st.html(
        "<script>setTimeout(() => {"
        f"const el = document.querySelector('{anchor}');"
        f"const picker = document.querySelector('.st-key-{PICKER_KEY}');"
        "const bar = picker && picker.closest('[data-testid=\"stLayoutWrapper\"]');"
        "const panel = el && el.closest('[data-testid=\"stTabPanel\"]');"
        "if (!panel) return;"
        "const below = (bar ? bar.getBoundingClientRect().height : 0)"
        " + parseFloat(getComputedStyle(panel).paddingTop);"
        "const dy = el.getBoundingClientRect().top - panel.getBoundingClientRect().top - below;"
        "panel.scrollBy({top: dy, behavior: 'smooth'});"
        "}, 150);</script>",
        unsafe_allow_javascript=True,
    )


def _hours_active(project: Project, sid: str) -> None:
    """How long the state was active in the current results (spots a state whose
    IFs never or always hold)."""
    r = state.get_results()
    if r is None or not r.inputs_hash.startswith(inputs_hash(project) + "|"):
        return
    if col.CONTROL_STATE not in r.frame.columns:
        return
    number = [s.id for s in project.control.all_states].index(sid)
    hours = int((r.frame[col.CONTROL_STATE] == number).sum())
    st.caption(f"Active {hours:,} h of {len(r.frame):,} in the current results.")


def _header(settings: ControlSettings, sid: str) -> None:
    """Name, priority, delete, allowed moves (not for Default)."""
    st.session_state[P + f"name_{sid}"] = settings.state(sid).name
    st.text_input("Name", key=P + f"name_{sid}", on_change=_renamed, args=(sid,))
    ids = [x.id for x in settings.states]
    c1, c2, c3 = st.columns(3)
    first, last = ids.index(sid) == 0, ids.index(sid) == len(ids) - 1
    up, down, delete = P + f"up_{sid}", P + f"down_{sid}", P + f"del_{sid}"
    c1.button("Higher priority", key=up, on_click=_move, args=(sid, -1), disabled=first)
    c2.button("Lower priority", key=down, on_click=_move, args=(sid, 1), disabled=last)
    c3.button("Delete state", key=delete, on_click=_delete_state, args=(sid,))
    others = [x for x in ids if x != sid]
    if others:
        nxt = settings.state(sid).next_states
        st.session_state[P + f"next_{sid}"] = list(others if nxt is None else nxt)
        st.multiselect(
            "Can move to",
            others,
            format_func=lambda i: node_label(settings, i),
            key=P + f"next_{sid}",
            on_change=_next_changed,
            args=(sid,),
            help="It can always fall back to Default. All ticked = any state, "
            "including ones added later.",
        )


def _editing_note(k: str, kind: str) -> None:
    if k + "editing" in st.session_state:
        st.caption(f"Editing a rule: change it below and press **Add {kind}** to put it back.")


def _free_cooling_note(project: Project) -> str | None:
    """Ambient IFs: where free cooling stops, for reference (owner)."""
    if not project.facilities:
        return None
    t = project.facilities[0].dc_type
    approach = project.assumptions.t_approach_c
    ambient = "dry bulb" if t.cooling_type is CoolingType.DRY else "wet bulb"
    return (
        f"Free cooling runs while the heat-rejection ambient ({ambient}) is below "
        f"{t.t_supply_c - approach:g} °C (supply {t.t_supply_c:g} °C − approach "
        f"{approach:g} K); at or above it the chillers run."
    )


def _ifs(project: Project, settings: ControlSettings, sid: str) -> None:
    st.markdown("**IF** — all must hold to enter or stay in this state")
    for i, c in enumerate(settings.state(sid).conditions):
        a, ed, rm = st.columns([5, 1, 1])
        a.write(condition_text(c, project.utility))
        ed.button("Edit", key=P + f"ed_if_{sid}_{i}", on_click=_edit_condition, args=(sid, i))
        rm.button("Remove", key=P + f"rm_if_{sid}_{i}", on_click=_remove_condition, args=(sid, i))
    present = _present(project)
    sources = [s for s in SOURCES if s.ifs and (s.key in present or s.key not in TARGET_KEYS)]
    k = P + f"if_{sid}_"
    c1, c2 = st.columns(2)
    source = c1.selectbox(
        "IF", [s.key for s in sources], format_func=lambda x: SPECS[x].label, key=k + "source"
    )
    spec = SPECS[source]
    var_key = c2.selectbox(
        "Variable",
        [v.key for v in spec.ifs],
        format_func=lambda x: _variable_label(spec.variable(x)),
        key=k + f"var_{source}",
    )
    variable = spec.variable(var_key)
    if variable.kind == "on_off":
        st.selectbox("Is", ["On", "Off"], key=k + "always")
    else:
        c3, c4, c5 = st.columns(3)
        c3.selectbox("Is", [o.value for o in Operator], key=k + "op")
        if variable.kind == "date":
            state.seed(k + "date", "06-01")
            c4.text_input("Than (MM-DD)", key=k + "date")
        else:
            ref = Reference.VALUE
            if variable.statistics:
                options = [r.value for r in OFFERED_REFERENCES]
                if variable.rate_field:  # the Utility tab's rate categories (owner, D-059)
                    options += [RATE_PREFIX + x.id for x in project.utility.categories]
                ref_key = k + f"ref_{source}_{var_key}"
                if st.session_state.get(ref_key, options[0]) not in options:
                    del st.session_state[ref_key]  # its rate category was deleted
                ref, _ = _parse_reference(
                    c4.selectbox(
                        "Than",
                        options,
                        format_func=lambda r: _than_label(r, variable, project.utility),
                        key=ref_key,
                    )
                )
            state.seed(k + "value", 0.0)
            c5.number_input(
                f"Value ({variable.unit})" if variable.unit else "Value",
                key=k + "value",
                disabled=ref is not Reference.VALUE,
                format="%.4g",
            )
    if source == "ambient":
        note = _free_cooling_note(project)
        if note:
            st.caption(note)
    _editing_note(k, "IF")
    st.button("Add IF", key=k + "add", on_click=_add_condition, args=(sid,))


def _then_rows(settings: ControlSettings, sid: str) -> None:
    acts = settings.state(sid).actions
    for i, a in enumerate(acts):
        x, up, down, ed, rm = st.columns([6, 1, 1, 1, 1])
        x.write(action_text(a))
        up.button(
            "↑",
            key=P + f"up_then_{sid}_{i}",
            on_click=_move_action,
            args=(sid, i, -1),
            disabled=i == 0,
        )
        down.button(
            "↓",
            key=P + f"down_then_{sid}_{i}",
            on_click=_move_action,
            args=(sid, i, 1),
            disabled=i == len(acts) - 1,
        )
        ed.button("Edit", key=P + f"ed_then_{sid}_{i}", on_click=_edit_action, args=(sid, i))
        rm.button("Remove", key=P + f"rm_then_{sid}_{i}", on_click=_remove_action, args=(sid, i))
    if not acts:
        st.caption("Nothing listed: IT load at 100 % of plan, every module off.")


def _thens(project: Project, settings: ControlSettings, sid: str) -> None:
    st.markdown(
        "**THEN** — the complete description of this state: a module runs only if a "
        "THEN names it, and links are served in this order"
    )
    _then_rows(settings, sid)
    present = _present(project)
    on_brine = project.modules.ice_mixer.fluid is IceMixerFluid.BRINE
    for w in warnings(settings.state(sid), SPECS, present, on_brine):
        st.warning(w)
    k = P + f"then_{sid}_"
    targets = [t.key for t in TARGETS if t.key in present]
    c1, c2, c3 = st.columns([2, 3, 2])
    target = c1.selectbox("THEN", targets, format_func=lambda x: SPECS[x].label, key=k + "target")
    spec = SPECS[target]
    key = c2.selectbox(
        "Does",
        [s.key for s in spec.thens],
        format_func=lambda x: _blank_label(spec.setting(x).label),
        key=k + f"setting_{target}",
    )
    s = spec.setting(key)
    with c3:
        if s.has_value:
            vkey = k + f"value_{target}_{key}"
            if vkey not in st.session_state:
                st.session_state[vkey] = float(s.default)
            st.number_input(
                f"Value ({s.unit})" if s.unit else "Value",
                float(s.min),
                float(s.max),
                step=float(s.step),
                key=vkey,
            )
        if s.kind is SettingKind.LINK:
            ends = [e for e in s.ends if e in present or e in ALWAYS_ON]
            st.selectbox(
                "To / from",
                ends,
                format_func=lambda e: end_label(target, key, e),
                key=k + f"to_{target}_{key}",
            )
    _editing_note(k, "THEN")
    st.button("Add THEN", key=k + "add", on_click=_add_action, args=(sid,))


def _select(state_id: str) -> None:
    """Code changes the state being edited: a new picker widget shows it."""
    st.session_state[K_CURRENT] = state_id
    st.session_state[K_PICKER_GEN] = st.session_state.get(K_PICKER_GEN, 0) + 1


def current_state() -> str:
    return str(st.session_state.get(K_CURRENT, DEFAULT_STATE_ID))


def picker_key() -> str:
    return f"{K_SELECTED}_{st.session_state.get(K_PICKER_GEN, 0)}"


def _picked() -> None:
    """The user picked a state in the picker."""
    st.session_state[K_CURRENT] = st.session_state[picker_key()]


def _picker(settings: ControlSettings) -> None:
    """The state being edited, and a new state's name + Add state."""
    ids = [s.id for s in settings.all_states]
    c1, c2, c3 = st.columns([3, 2, 1])
    c1.selectbox(
        "Edit state",
        ids,
        index=ids.index(current_state()),
        format_func=lambda i: node_label(settings, i),
        key=picker_key(),
        on_change=_picked,
        label_visibility="collapsed",
    )
    c2.text_input(
        "New state name",
        key=K_NEW_NAME,
        placeholder="New state name",
        label_visibility="collapsed",
    )
    c3.button("Add state", key=P + "add", on_click=_add_state, width="stretch")


def render(project: Project) -> None:
    settings = project.control
    ids = [s.id for s in settings.all_states]
    if current_state() not in ids:  # deleted, or another project
        _select(DEFAULT_STATE_ID)
    state.show_flash("control")
    with st.container(key=PICKER_KEY):  # pinned at the top while the editor scrolls (owner)
        _picker(settings)
    sid = current_state()
    state_diagram(settings, sid, DIAGRAM_KEY, _diagram_clicked)
    st.divider()
    _scroll_to_editor()
    _hours_active(project, sid)
    if sid == DEFAULT_STATE_ID:
        st.caption(
            "Active whenever no other state's IFs hold. The data center is always "
            "cooled free when possible, mechanically when needed. New states start "
            "with a copy of these THENs."
        )
        _thens(project, settings, sid)
        st.button(
            "Run everything in Default",
            key=P + "all_on",
            on_click=_run_everything,
            help="Every module on, wired as before the state machine: brine separation "
            "first on the data center's heat, then power generation (supply coolant as "
            "its cold side) and hot water storage; the ice mixer cools the data center "
            "with ice from ice storage; recovered water goes to ice storage; PV generates.",
        )
        return
    _header(settings, sid)
    _ifs(project, settings, sid)
    _thens(project, settings, sid)
