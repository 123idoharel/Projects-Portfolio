"""
graphs.py — Core Graph Data Structures
=======================================

Provides the two primitive data structures used by every other module:
  - Node   : a single point in 2-D + floor space (x, y, floor)
  - Graph  : adjacency-list directed graph built from Node objects

These are intentionally thin wrappers. All the domain logic (driving speeds,
pedestrian rules, Dijkstra) lives elsewhere; this module just stores topology.

Usage pattern
-------------
1. offline.py / simulation.py build a Graph from a layout dict:
       nodes = {n["id"]: Node(...) for n in layout["driving"]["nodes"]}
       g = Graph(nodes)
       g.add_edge("A", "B", weight=12.5, edge_type="main", bidir=True)

2. dijkstra.py then runs shortest-path on graph.nodes / graph.adj.

Edge tuple format stored in adj[u]:
    (neighbor_id: str, weight: float, edge_type: str)
"""
from typing import Dict, List, Any


class Node:
    """
    A spatial node in the parking layout.

    Attributes
    ----------
    id    : unique string identifier (e.g. "F0_A3", "ENT_LANE_A", "RAMP_F1")
    floor : 0-based floor number (0 = ground level)
    x, y  : world coordinates in the layout's unit system (typically metres)
    type  : semantic role — one of:
              "intersection"  road junction / aisle node
              "entrance"      vehicle entry point
              "exit"          vehicle exit point
              "ramp"          ramp connecting two floors
              "elevator"      pedestrian/vehicle elevator node
    """
    def __init__(self, id: str, floor: int, x: float, y: float, type: str = "intersection"):
        self.id    = id
        self.floor = floor
        self.x     = x
        self.y     = y
        self.type  = type


class Graph:
    """
    Directed adjacency-list graph over Node objects.

    Edges are stored as tuples: (neighbor_id, weight, edge_type).
    add_edge() adds both directions when bidir=True (the common case for
    driving aisles and all pedestrian edges).

    Attributes
    ----------
    nodes : dict  id → Node
    adj   : dict  id → list of (neighbor_id, weight, edge_type)
    """
    def __init__(self, nodes: Dict[str, Node]):
        self.nodes = nodes
        self.adj: Dict[str, List[tuple]] = {nid: [] for nid in nodes}

    def add_edge(self, u: str, v: str, weight: float,
                 edge_type: str = "main", bidir: bool = True):
        """
        Add a directed edge u → v (and v → u if bidir=True).

        Parameters
        ----------
        u, v      : node ids (must already be in self.nodes)
        weight    : cost — seconds for the driving graph, metres for pedestrian
        edge_type : label for debugging / routing rules (e.g. "main", "aisle",
                    "corridor", "spot_access")
        bidir     : if True, also adds the reverse edge v → u
        """
        if u in self.adj:
            self.adj[u].append((v, weight, edge_type))
        if bidir and v in self.adj:
            self.adj[v].append((u, weight, edge_type))