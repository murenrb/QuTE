"""Module registry for the Modules tab and the map (D-036, D-041).

Adding a module: give it a params model in core/domain/modules.py deriving from
SitedModuleParams (scaled in map: drawn area) or BlockModuleParams (scaled in
inputs: block sized by its inputs) — or a plain model if it has no footprint
(e.g. the ice mixer) — an inputs panel and its `OUTPUTS` (plot + text in the
results' module output panel) here, and one `ModuleUI` entry in MODULES. The
Modules tab, the map tools (draw / vertex edit / block edit), snapping, colors
and layout warnings then follow from its category.
Ask the owner which category a new module is if it isn't specified.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.components.module_outputs import ModuleOutputs
from app.components.modules import (
    brine_separation,
    greenhouse,
    hot_water_storage,
    ice_mixer,
    ice_storage,
    power_generation,
    solar_pv,
)
from core.persistence.project import Project
from core.timeseries.columns import SERIES_4, SERIES_6, SERIES_7, SERIES_8, SERIES_9, SERIES_10


@dataclass(frozen=True)
class ModuleUI:
    key: str  # field name in core.domain.modules.ModuleSettings
    label: str
    color: str  # area fill on the map (facility overlays may use color)
    render_inputs: Callable[[Project], None]
    outputs: ModuleOutputs  # plot + text in the module output panel (results)
    description: str  # one line, shown when picking it under "Add module"
    draw_note: str = ""  # shown above the inputs when the area tool is active (sited only)


MODULES: tuple[ModuleUI, ...] = (
    ModuleUI(
        key="solar_pv",
        label="Solar PV",
        color=SERIES_4,
        render_inputs=solar_pv.render_inputs,
        outputs=solar_pv.OUTPUTS,
        description=("Solar panels on a drawn area; size follows the area (scaled in map)."),
        draw_note=(
            "Use the polygon tool to draw the area dedicated to solar. It may cross the "
            "property line or other areas — when closed it snaps to the free land."
        ),
    ),
    ModuleUI(
        key="ice_storage",
        label="Ice storage",
        color=SERIES_7,  # block color on the map
        render_inputs=ice_storage.render_inputs,
        outputs=ice_storage.OUTPUTS,
        description=(
            "Ice maker + ice and water tanks that supply ice to other modules. A block sized "
            "by the tank (scaled in inputs)."
        ),
    ),
    ModuleUI(
        key="power_generation",
        label="Waste heat to power",
        color=SERIES_6,
        render_inputs=power_generation.render_inputs,
        outputs=power_generation.OUTPUTS,
        description=(
            "Transcritical CO2 power cycle running on data center, stored or condenser heat. "
            "A block sized by its rating (scaled in inputs)."
        ),
    ),
    ModuleUI(
        key="hot_water_storage",
        label="Hot water storage",
        color=SERIES_8,
        render_inputs=hot_water_storage.render_inputs,
        outputs=hot_water_storage.OUTPUTS,
        description=(
            "Hot water tanks that store data center heat for later. A block sized by the "
            "tanks (scaled in inputs)."
        ),
    ),
    ModuleUI(
        key="brine_separation",
        label="Brine separation",
        color=SERIES_9,
        render_inputs=brine_separation.render_inputs,
        outputs=brine_separation.OUTPUTS,
        description=(
            "Single-stage evaporator that boils pure water out of a brine using the data "
            "center's hot water. A block sized by the tank (scaled in inputs)."
        ),
    ),
    ModuleUI(
        key="ice_mixer",
        label="Ice mixer",
        color=SERIES_7,  # no footprint: never drawn on the map
        render_inputs=ice_mixer.render_inputs,
        outputs=ice_mixer.OUTPUTS,
        description=(
            "Melts ice from ice storage into water or brine to supply cooling. No footprint "
            "on the map."
        ),
    ),
    ModuleUI(
        key="greenhouse",
        label="Greenhouse",
        color=SERIES_10,
        render_inputs=greenhouse.render_inputs,
        outputs=greenhouse.OUTPUTS,
        description=(
            "Glass greenhouse heated with the data center's return water; its floor is the "
            "drawn area (scaled in map)."
        ),
        draw_note=(
            "Use the polygon tool to draw the greenhouse's floor. It may cross the property "
            "line or other areas — when closed it snaps to the free land."
        ),
    ),
)
BY_KEY = {m.key: m for m in MODULES}
LABELS = {m.key: m.label for m in MODULES}
COLORS = {m.key: m.color for m in MODULES}
