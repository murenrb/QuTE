import pytest

from core.timeseries import columns as c
from core.timeseries.columns import ColumnSpec, PlotGroup


def test_step1_plot_groups() -> None:
    names = lambda g: [s.name for s in c.columns_in_group(g)]  # noqa: E731
    # D-054: where the data center's heat ends up (stacked), plus brine
    # separation's boiler heat as a line (it passes its heat on)
    assert names(PlotGroup.THERMAL) == [
        c.COOLING_CHILLER_KWTH,
        c.ICE_MIX_Q_KWTH,
        c.COOLING_FREE_KWTH,
        c.POWER_GEN_POWER_KWTH,
        c.HWS_STACK_KWTH,  # D-065: leaves out what it gives the greenhouse
        c.GREENHOUSE_HEAT_KWTH,  # D-061: from the data center
        c.GREENHOUSE_HEAT_HWS_KWTH,  # D-065: hatched, on top of the stack
        c.BRINE_HEAT_KWTH,
    ]
    hatched = [s.name for s in c.columns_in_group(PlotGroup.THERMAL) if s.hatched]
    assert hatched == [c.GREENHOUSE_HEAT_HWS_KWTH]
    assert names(PlotGroup.ELECTRICAL) == [
        c.IT_LOAD_KW,
        c.IT_PARASITIC_KW,
        c.COOLING_ELEC_KW,
        c.PV_KW,  # generation (negative), stack order 4
        c.ICE_MAKER_ELEC_KW,
        c.POWER_GEN_KW,  # generation (negative)
        c.GRID_NET_KW,
    ]
    # D-060: the Ambient row's two views
    assert set(names(PlotGroup.AMBIENT)) == {c.TDB_C, c.TWB_C, c.TDP_C}
    assert names(PlotGroup.SUN) == [c.GHI_W_M2]


def test_conflicting_registration_rejected() -> None:
    with pytest.raises(ValueError):
        c.register(ColumnSpec(c.IT_LOAD_KW, "MW", "IT load"))
