"""Ice mixer: the owner's step (both passes), hand-checked, plus the salt balance (D-050)."""

import numpy as np
import pytest

from core.config.defaults import BRINES, ICE_LATENT_HEAT_KJ_KG, BrineType, IceMixerFluid
from core.domain.brine import brine_c, brine_fp, brine_h_solv
from core.domain.ice import ice_hf
from core.domain.modules import IceMixerParams
from core.models.ice_mixer import ice_mixer_step

KAC = BRINES[BrineType.POTASSIUM_ACETATE]
WATER = IceMixerParams(enabled=True, fluid=IceMixerFluid.WATER)
BRINE = IceMixerParams(enabled=True, fluid=IceMixerFluid.BRINE)  # recup 70 %, mix 80 %


def test_ice_hf_by_hand() -> None:
    assert ice_hf(0) == pytest.approx(ICE_LATENT_HEAT_KJ_KG)
    # t = −10: cp_ice = 2.0055, cp_water = 4.1531 → avgs 2.10275, 4.16655
    # h = 330 + (4.16655 − 2.10275)·(−10) = 309.362
    assert ice_hf(-10) == pytest.approx(309.362)


def test_brine_fits_by_hand() -> None:
    # fp(0.2) = −137.95·0.008 − 173.45·0.04 − 11.85·0.2 − 0.2351 = −10.6467
    assert brine_fp(0.2, KAC) == pytest.approx(-10.6467)
    assert brine_fp(0.0, KAC) == 0.0  # pure water
    assert brine_c(brine_fp(0.2, KAC), KAC) == pytest.approx(0.2, abs=0.015)  # fits ≈ inverse
    # h_solv(0.2) = −64·(0.25)² = −4
    assert brine_h_solv(0.2, KAC) == pytest.approx(-4.0)


def test_water_pass_one_calls_what_it_needs() -> None:
    h = ice_mixer_step(1000, 0.0, WATER)
    assert h.m_ice_call_kg_s == pytest.approx(1000 / 330)
    assert h.q_delivered_kwth == pytest.approx(1000)
    assert h.m_water_out_kg_s == pytest.approx(h.m_ice_call_kg_s)  # melt water back
    assert (h.m_brine_call_kg_s, h.m_brine_out_kg_s, h.t_mix_c) == (0, 0, 0)


def test_water_pass_two_is_ice_limited_and_never_over_delivers() -> None:
    short = ice_mixer_step(1000, 0.0, WATER, m_ice_in_kg_s=1.0)
    assert short.q_delivered_kwth == pytest.approx(330)
    extra = ice_mixer_step(1000, 0.0, WATER, m_ice_in_kg_s=10.0)  # more than it asked for
    assert extra.q_delivered_kwth == pytest.approx(1000)
    assert extra.m_ice_call_kg_s == pytest.approx(1000 / 330)


def test_brine_pass_one_by_hand() -> None:
    c_in = 0.3
    t_mix = brine_fp(c_in, KAC) * 0.8
    c_mix = brine_c(t_mix, KAC)
    h_kg = (ice_hf(t_mix) + brine_h_solv(c_mix, KAC)) * 0.7  # solvation heat reduces it
    h = ice_mixer_step(1000, c_in, BRINE)
    assert h.t_mix_c == pytest.approx(t_mix)  # −18.50 °C
    assert h.c_brine_out == pytest.approx(c_mix)  # 0.269
    assert h.q_delivered_kwth == pytest.approx(1000)
    assert h.m_ice_call_kg_s == pytest.approx(1000 / h_kg)
    assert h.m_brine_call_kg_s == pytest.approx(h.m_ice_call_kg_s * c_mix / (c_in - c_mix))
    assert h.m_water_out_kg_s == 0


def test_brine_pass_two_limits() -> None:
    first = ice_mixer_step(1000, 0.3, BRINE)
    ratio = first.m_ice_call_kg_s / first.m_brine_call_kg_s  # kg ice per kg brine
    # ice-limited: half the ice → half the cooling and half the brine
    h = ice_mixer_step(
        1000,
        0.3,
        BRINE,
        m_ice_in_kg_s=first.m_ice_call_kg_s / 2,
        m_brine_in_kg_s=first.m_brine_call_kg_s,
    )
    assert h.q_delivered_kwth == pytest.approx(500)
    assert h.m_brine_call_kg_s == pytest.approx(first.m_brine_call_kg_s / 2)
    # brine-limited: a quarter of the brine → a quarter of the ice it can use
    b = first.m_brine_call_kg_s / 4
    h = ice_mixer_step(1000, 0.3, BRINE, m_ice_in_kg_s=first.m_ice_call_kg_s, m_brine_in_kg_s=b)
    assert h.m_ice_call_kg_s == pytest.approx(b * ratio)
    assert h.q_delivered_kwth == pytest.approx(250)
    # everything supplied → same as pass 1
    h = ice_mixer_step(
        1000,
        0.3,
        BRINE,
        m_ice_in_kg_s=first.m_ice_call_kg_s,
        m_brine_in_kg_s=first.m_brine_call_kg_s,
    )
    assert h.q_delivered_kwth == pytest.approx(1000)


def test_outputs_not_accepted_limit_the_ice_melted() -> None:
    """D-051: the mixer can't dump melt water or diluted brine."""
    h = ice_mixer_step(1000, 0.0, WATER, m_ice_in_kg_s=10.0, m_water_out_max_kg_s=1.0)
    assert h.m_ice_call_kg_s == pytest.approx(1.0) and h.m_water_out_kg_s == pytest.approx(1.0)
    assert h.q_delivered_kwth == pytest.approx(330)
    first = ice_mixer_step(1000, 0.3, BRINE)
    half = first.m_brine_out_kg_s / 2
    h = ice_mixer_step(
        1000,
        0.3,
        BRINE,
        m_ice_in_kg_s=first.m_ice_call_kg_s,
        m_brine_in_kg_s=first.m_brine_call_kg_s,
        m_brine_out_max_kg_s=half,
    )
    assert h.m_brine_out_kg_s == pytest.approx(half)
    assert h.q_delivered_kwth == pytest.approx(500)
    # nothing binding: the pass reproduces its inputs exactly
    same = ice_mixer_step(
        1000,
        0.3,
        BRINE,
        m_ice_in_kg_s=first.m_ice_call_kg_s,
        m_brine_in_kg_s=first.m_brine_call_kg_s,
        m_brine_out_max_kg_s=first.m_brine_out_kg_s,
    )
    assert same == first


def test_mix_eta_capped_at_90() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        IceMixerParams(mix_eta_pct=100)


def test_too_dilute_brine_delivers_nothing() -> None:
    # Near c = 0 the inverse fit gives c_mix ≥ c_in: no cooling below 0 °C possible.
    h = ice_mixer_step(1000, 0.02, BRINE)
    assert (h.m_ice_call_kg_s, h.m_brine_call_kg_s, h.q_delivered_kwth) == (0, 0, 0)


@pytest.mark.parametrize("seed", range(3))
def test_salt_and_mass_balance_hold(seed: int) -> None:
    rng = np.random.default_rng(seed)
    for _ in range(200):
        c_in = float(rng.uniform(0.08, 0.38))
        p = IceMixerParams(
            enabled=True,
            fluid=IceMixerFluid.BRINE,
            recup_eta_pct=float(rng.uniform(50, 90)),
            mix_eta_pct=float(rng.uniform(50, 90)),
        )
        q = float(rng.uniform(0, 5000))
        ice_in = float(rng.uniform(0, 20)) if rng.integers(0, 2) else None
        brine_in = float(rng.uniform(0, 200)) if rng.integers(0, 2) else None
        out_max = float(rng.uniform(0, 200)) if rng.integers(0, 2) else None
        h = ice_mixer_step(q, c_in, p, KAC, ice_in, brine_in, m_brine_out_max_kg_s=out_max)
        assert h.m_brine_call_kg_s * c_in == pytest.approx(h.m_brine_out_kg_s * h.c_brine_out)
        assert h.m_brine_out_kg_s == pytest.approx(h.m_brine_call_kg_s + h.m_ice_call_kg_s)
        assert h.q_delivered_kwth <= q + 1e-9
        if ice_in is not None:
            assert h.m_ice_call_kg_s <= ice_in + 1e-12
        if brine_in is not None:
            assert h.m_brine_call_kg_s <= brine_in + 1e-12
        if out_max is not None:
            assert h.m_brine_out_kg_s <= out_max * (1 + 1e-12)
