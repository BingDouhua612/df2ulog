"""Static tables shared by the converter (plan §4.4, ADR-10, appendix E).

Nothing here is allowed to import pymavlink/pyulog.
"""

from __future__ import annotations

GPS_LEAP_SECONDS: int = 18

# pymavlink's MULT_TO_PREFIX mapping, used only for units in reports.
MULT_TO_PREFIX: dict[float, str] = {
    0.1: "d",
    0.01: "c",
    0.001: "m",
    1e-6: "µ",
    1e-9: "n",
    1.0: "",
    0.0: "",
}

# ArduPilot LogEvent ids commonly present in flight logs. Unknown ids fall back
# to "EVENT_<id>" (appendix E explicitly allows a partial table).
EV_NAMES: dict[int, str] = {
    10: "ARMED",
    11: "DISARMED",
    15: "TAKEOFF",
    16: "LANDING",
    17: "LAND_COMPLETE_MAYBE",
    18: "LAND_COMPLETE",
    19: "LOST_GPS",
    20: "FLIP_START",
    21: "FLIP_END",
    25: "SET_HOME",
    26: "SET_SIMPLE_ON",
    27: "SET_SIMPLE_OFF",
    28: "NOT_LANDED",
    29: "SET_SUPERSIMPLE_ON",
    30: "AUTO_ARMED",
    31: "AUTO_TAKEOFF",
    38: "FAILSAFE_RADIO",
    39: "FAILSAFE_BATT",
    40: "FAILSAFE_GPS",
    41: "FAILSAFE_GCS",
    42: "FAILSAFE_FENCE",
    43: "FAILSAFE_EKF",
    44: "FLIGHT_MODE",
    45: "FAILSAFE_TERRAIN",
    46: "FAILSAFE_ADSB",
    47: "FAILSAFE_ENGINE",
    48: "FAILSAFE_LEAK",
    49: "PARACHUTE_DISABLED",
    50: "PARACHUTE_ENABLED",
    51: "PARACHUTE_RELEASED",
    52: "LANDING_GEAR_DEPLOYED",
    53: "LANDING_GEAR_RETRACTED",
    54: "MOTORS_EMERGENCY_STOPPED",
    55: "MOTORS_EMERGENCY_STOP_CLEAR",
    56: "MOTORS_INTERLOCK_DISABLED",
    57: "MOTORS_INTERLOCK_ENABLED",
    58: "ROTOR_RUNUP_COMPLETE",
    59: "ROTOR_SPEED_BELOW_CRITICAL",
    60: "EKF_ALT_RESET",
    61: "LANDER_ABORT",
    62: "LANDER_SAFE",
    63: "LANDER_CANCEL",
    64: "BRAKE",
    65: "THROW_START",
    66: "THROW_END",
    67: "DATAFLASH_ERASED",
}

# Message types handled as metadata / specially, never emitted as data topics.
DEFAULT_SKIP_TYPES: frozenset[str] = frozenset(
    {
        "FMT",
        "FMTU",
        "UNIT",
        "MULT",
        "PARM",
        "MSG",
        "VER",
        "RTC",
        "EV",
        "MODE",
        "FILE",
        "DU32",
        "D32",
        "D16",
        "DFLT",
    }
)


def event_name(event_id: int) -> str:
    """Return the ArduPilot event name, falling back to EVENT_<id>."""
    return EV_NAMES.get(event_id, f"EVENT_{event_id}")
