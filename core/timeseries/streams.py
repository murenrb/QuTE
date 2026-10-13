"""Flows exchanged between modules inside one hour of the solver (docs/solver.md).

A stream is written by one module and read by others. The answers to a
request (what was supplied / accepted) are *sticky*: if the hour doesn't
settle they are capped (D-052). Requests, flows a module must get rid of, and
values derived from others are recalculated from the capped answers. Unlike
columns, streams live only while an hour is being solved.

Links (D-054): which module exchanges with which is set by the hour's state
(its link THENs). Every possible link has its streams; a link the state
doesn't make simply stays unasked (None). Each link has three streams:

- want (`*_req`, calls): what the receiver would take. Never limited by an
  answer it depends on, so it can rise again when supply frees up (otherwise
  flows could only ratchet down).
- answer (`*_sent`, supplied, accepted): what the sender can give of the want
  (≤ want, sticky).
- used: what the receiver actually took (≤ answer), after its other limits.
  The sender's own balance uses this, so every kW / kg is counted once.
"""

# IT load actually run this hour (kW): planned × the state's IT load THEN (D-053)
IT_LOAD_KW = "it_load_kw"


# Heat (kW_th), receiver asks, sender answers: data center → brine separation /
# power generation / hot water storage; hot water storage → power generation;
# brine separation's condenser → power generation.
def heat_req(sender: str, receiver: str) -> str:
    return f"heat_req:{sender}>{receiver}"


def heat_sent(sender: str, receiver: str) -> str:
    return f"heat_sent:{sender}>{receiver}"  # sticky, answers heat_req


def heat_used(sender: str, receiver: str) -> str:
    return f"heat_used:{sender}>{receiver}"


# Cooling (kW_th) from the ice mixer: the consumer asks, the mixer answers.
def cool_req(receiver: str) -> str:
    return f"cool_req:ice_mixer>{receiver}"


def cool_sent(receiver: str) -> str:
    return f"cool_sent:ice_mixer>{receiver}"  # sticky, answers cool_req


def cool_used(receiver: str) -> str:
    return f"cool_used:ice_mixer>{receiver}"


# Heat a module rejects into the supply coolant (kW_th): free cooling when
# possible, else the chillers (the data center node carries it).
def coolant_load(sender: str) -> str:
    return f"coolant_load:{sender}"


# Temperatures fixed for the hour (°C), for modules that work against them.
ICE_MIX_T_C = "ice_mix_t_c"  # the ice mixer's cold side
HWS_T_HOT_C = "hws_t_hot_c"  # hot water storage's delivery temperature (hot tank − pinch)
CONDENSER_T_C = "condenser_t_c"  # brine separation's vapor, as a heat source

# Ice (kg/s): ice mixer ↔ ice storage
ICE_CALL_KG_S = "ice_call_kg_s"  # mixer wants
ICE_SUPPLIED_KG_S = "ice_supplied_kg_s"  # ice storage can give (sticky)
ICE_USED_KG_S = "ice_used_kg_s"  # mixer melted
MELT_WATER_KG_S = "melt_water_kg_s"  # melt water the want would return
MELT_WATER_ACCEPTED_KG_S = "melt_water_accepted_kg_s"  # water tank has room for (sticky)
MELT_WATER_USED_KG_S = "melt_water_used_kg_s"  # melt water actually returned

# Brine (kg/s): ice mixer ↔ brine separation
BRINE_C_START = "brine_c_start"  # tank salt fraction at the start of the hour (fixed)
BRINE_CALL_KG_S = "brine_call_kg_s"  # mixer wants
BRINE_SUPPLIED_KG_S = "brine_supplied_kg_s"  # brine tank can give, at BRINE_C_START (sticky)
BRINE_USED_KG_S = "brine_used_kg_s"  # mixer used
BRINE_RETURN_KG_S = "brine_return_kg_s"  # diluted brine the want would return
BRINE_RETURN_C = "brine_return_c"  # its salt fraction
BRINE_RETURN_ACCEPTED_KG_S = "brine_return_accepted_kg_s"  # brine tank has room for (sticky)
BRINE_RETURN_USED_KG_S = "brine_return_used_kg_s"  # diluted brine actually returned

# Water (kg/s): brine separation's recovered water → ice storage (the rest drains)
RECOVERED_WATER_KG_S = "recovered_water_kg_s"
RECOVERED_WATER_ACCEPTED_KG_S = "recovered_water_accepted_kg_s"

# Electricity (kW, loads +, generation −): every stream with this prefix is
# summed into the grid draw the state machine can test.
ELEC_PREFIX = "elec:"


def elec(name: str) -> str:
    return f"{ELEC_PREFIX}{name}"
