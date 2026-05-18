"""
scenarios.py — Simulation Scenario Presets
===========================================

A scenario is a named dict of parameters that controls the automatic
behaviour of the simulation loop in server.py. The operator can switch
between scenarios at runtime from the UI.

Parameters
----------
description          : str   — shown in the operator UI dropdown
arrival_rate_per_sec : float — probability per second of a new vehicle spawning
                               automatically (0 = no auto spawn)
reserve_seconds      : float — how long a RESERVED spot is held for a vehicle
                               before expiring (if it never arrives)
avg_park_seconds     : float — mean time a PARKED simulation vehicle stays before
                               leaving (exponential distribution; unused if
                               disable_auto_leave=True)
steal_base_rate      : float — probability per second that a reserved spot is
                               stolen by a rogue vehicle (0 = no theft)
disable_auto_leave   : bool  — if True, parked vehicles stay forever (Demo mode)
prefill_occupied_ratio: float — fraction of all spots pre-filled as OCCUPIED when
                                the scenario is loaded (0 = empty garage)
auto_exit_rate       : float — probability per second that a random OCCUPIED spot
                               becomes FREE (vehicles leaving spontaneously)
auto_entry_rate      : float — probability per second that a new simulation vehicle
                               is spawned automatically
show_controls        : bool  — whether the operator sidebar shows manual controls
                               (vehicle spawn, steal, etc.)

All rates are per-second probabilities applied against effective_dt each tick.
effective_dt = real_dt × speed_multiplier, so faster simulation speeds scale
auto events proportionally.
"""

SCENARIOS = {
    "Demo": {
        "description": "שליטה ידנית מלאה",
        "arrival_rate_per_sec":   0.0,
        "reserve_seconds":      120.0,
        "avg_park_seconds":     300.0,
        "steal_base_rate":        0.0,
        "disable_auto_leave":    True,
        "prefill_occupied_ratio": 0.0,
        "auto_exit_rate":         0.0,
        "auto_entry_rate":        0.0,
        "show_controls":         True,
    },
    "זרימת יציאה": {
        "description": "רוב החניון תפוס, רכבים יוצאים בהדרגה + הוספה ידנית",
        "arrival_rate_per_sec":   0.0,
        "reserve_seconds":       60.0,
        "avg_park_seconds":     180.0,
        "steal_base_rate":        0.0,
        "disable_auto_leave":   False,
        "prefill_occupied_ratio": 0.85,
        "auto_exit_rate":         0.08,
        "auto_entry_rate":        0.0,
        "show_controls":         True,
    },
    "סימולציה מלאה": {
        "description": "כניסה ויציאה אוטומטית + גניבות",
        "arrival_rate_per_sec":   0.0,
        "reserve_seconds":       60.0,
        "avg_park_seconds":     120.0,
        "steal_base_rate":        0.15,
        "disable_auto_leave":   False,
        "prefill_occupied_ratio": 0.70,
        "auto_exit_rate":         0.06,
        "auto_entry_rate":        0.10,
        "show_controls":        False,
    },
    "ניהול ידני 80%": {
        "description": "80% תפוסה, שחרור ידני בלחיצה על חניה",
        "arrival_rate_per_sec":   0.0,
        "reserve_seconds":      120.0,
        "avg_park_seconds":     300.0,
        "steal_base_rate":        0.0,
        "disable_auto_leave":    True,
        "prefill_occupied_ratio": 0.80,
        "auto_exit_rate":         0.0,
        "auto_entry_rate":        0.0,
        "show_controls":         True,
    },
    "Normal": {
        "description": "מצב רגיל",
        "arrival_rate_per_sec":   0.05,
        "reserve_seconds":       60.0,
        "avg_park_seconds":     140.0,
        "steal_base_rate":        0.10,
        "prefill_occupied_ratio": 0.3,
        "auto_exit_rate":         0.0,
        "auto_entry_rate":        0.0,
        "show_controls":         True,
    },
}
