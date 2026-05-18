"""
layout_loader.py — Layout JSON Loading and Validation
======================================================

A layout JSON file is the single source of truth for an entire parking
facility. This module loads it and validates its structure before any
computation begins, failing loudly with a descriptive error if anything
is wrong.

Layout JSON schema (top level)
-------------------------------
{
  "meta"      : { "name": str, ... }          — free-form facility metadata
  "driving"   : {
    "nodes"   : [ { "id", "floor", "x", "y", "type" }, ... ]
    "edges"   : [ { "from", "to", "length_m", "type", "bidir?" }, ... ]
  }
  "spots"     : [
    {
      "id"      : str            e.g. "F0-A03"
      "floor"   : int
      "x", "y"  : float          world coordinates of spot centre
      "road_y"  : float          Y of the driving aisle in front of this spot
      "access"  : [{ "node": driving_node_id }, ...]
                                 one or more road nodes a vehicle can use to
                                 approach this spot
      "theft_risk" : float       optional 0–1 security score
    }, ...
  ]
  "targets"   : [
    {
      "id"       : str
      "type"     : "elevator" | "exit"
      "floor"    : int            (elevator only)
      "x", "y"   : float          (elevator only — world position)
      "subtype"  : str            (elevator only — e.g. "tower_a", "offices")
      "label"    : str            display name shown in the UI
      "drive_node": driving_node_id   (exit only — the road node nearest the exit)
    }, ...
  ]
  "entrances" : [ driving_node_id, ... ]
}

Edge types (driving.edges)
--------------------------
  "main"   — primary driving road connecting aisle intersections
  "aisle"  — lateral spur from main road into a parking aisle

Node types (driving.nodes)
--------------------------
  "intersection"  — aisle junction / road node
  "entrance"      — vehicle entry point
  "exit"          — vehicle exit point
  "ramp"          — ramp connecting two floors
"""
import json
from typing import Any, Dict, Set

REQUIRED_TOP_LEVEL = {"meta", "driving", "spots", "targets", "entrances"}


def load_layout(path: str) -> Dict[str, Any]:
    """Load and validate a layout JSON file. Raises ValueError on bad input."""
    with open(path, "r", encoding="utf-8") as f:
        layout = json.load(f)
    validate_layout(layout)
    return layout


def validate_layout(layout: Dict[str, Any]) -> None:
    """
    Validate the layout dict against the expected schema.

    Checks performed
    ----------------
    1. All required top-level keys are present.
    2. Driving node IDs are unique.
    3. Every driving edge references known node IDs.
    4. Every entrance references a known driving node.
    5. Target IDs are unique; each target has the correct required fields.
    6. Every spot has a non-empty access list, and every access node exists
       in the driving graph.

    Raises ValueError with a descriptive message on any violation.
    """
    missing = REQUIRED_TOP_LEVEL - set(layout.keys())
    if missing:
        raise ValueError(f"Layout missing keys: {sorted(list(missing))}")

    d_nodes = layout["driving"]["nodes"]
    d_edges = layout["driving"]["edges"]
    d_ids   = _unique_ids(d_nodes, "driving.nodes")

    for e in d_edges:
        if e["from"] not in d_ids or e["to"] not in d_ids:
            raise ValueError(f"Driving edge references unknown node: {e}")

    for ent in layout["entrances"]:
        if ent not in d_ids:
            raise ValueError(f"Entrance '{ent}' not in driving nodes")

    target_ids = [t["id"] for t in layout["targets"]]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError(f"Duplicate target IDs found: {target_ids}")

    for t in layout["targets"]:
        if t.get("type") not in ("elevator", "exit", "escalator"):
            raise ValueError(f"Target '{t['id']}' must have type 'elevator', 'escalator', or 'exit'")
        if t.get("type") == "exit" and "drive_node" not in t:
            raise ValueError(f"Exit target '{t['id']}' must have 'drive_node'")
        if t.get("type") == "exit" and t["drive_node"] not in d_ids:
            raise ValueError(f"Exit target '{t['id']}' drive_node not in driving nodes")
        if t.get("type") in ("elevator", "escalator"):
            if "floor" not in t or "x" not in t or "y" not in t:
                raise ValueError(f"Elevator/escalator target '{t['id']}' must have 'floor', 'x', 'y'")

    for s in layout["spots"]:
        if "access" not in s or not s["access"]:
            raise ValueError(f"Spot missing access list: {s}")
        for ap in s["access"]:
            if ap["node"] not in d_ids:
                raise ValueError(f"Spot access references unknown driving node: {ap} in {s['id']}")


def _unique_ids(nodes: list, name: str) -> Set[str]:
    """Return the set of node IDs, raising ValueError on any duplicates."""
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate node ids in {name}")
    return set(ids)
