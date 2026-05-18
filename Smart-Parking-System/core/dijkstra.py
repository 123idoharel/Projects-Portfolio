"""
dijkstra.py — Shortest-Path Engine
====================================

Standard Dijkstra implementation used by both the driving and pedestrian graphs.
Intentionally kept simple and graph-agnostic: it operates on any object that
exposes .nodes (dict of ids) and .adj (dict of id → list of (neighbor, weight, _)).

Two functions:
  dijkstra_with_parent(graph, start)
      → returns (dist, parent) for every reachable node from `start`
      → dist[n]   = minimum total cost from start to n
      → parent[n] = previous node on the shortest path to n

  reconstruct_path(parent, start, end)
      → walks the parent pointers backwards from end → start
      → returns the list of node ids in forward order [start, ..., end]

Cost units
----------
  driving graph   : seconds  (edge weight = length_m / speed_mps)
  pedestrian graph: metres   (edge weight = Euclidean distance)

Time complexity: O((V + E) log V) with a binary min-heap.

Where it is called
------------------
  offline.py    : once per entrance at startup — results cached in offline dict
  simulation.py : on-demand when a vehicle is rerouted mid-journey
  pedestrian.py : at route-request time (find_walk_route)
"""
import heapq
from typing import Dict, List, Tuple, Optional


def dijkstra_with_parent(graph, start: str) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
    """
    Run Dijkstra from `start` on `graph`.

    Returns
    -------
    dist   : dict  node_id → minimum cost from start (inf if unreachable)
    parent : dict  node_id → predecessor on the shortest path (None for start)
    """
    dist   = {nid: float("inf") for nid in graph.nodes}
    parent = {nid: None         for nid in graph.nodes}

    if start not in dist:
        return dist, parent

    dist[start] = 0
    pq = [(0, start)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:          # stale entry — skip
            continue
        for v, w, _ in graph.adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v]   = nd
                parent[v] = u
                heapq.heappush(pq, (nd, v))

    return dist, parent


def reconstruct_path(parent: Dict[str, Optional[str]], start: str, end: str) -> List[str]:
    """
    Walk parent pointers from `end` back to `start` and return the path in
    forward order [start, ..., end].

    Returns [] if `end` is unreachable from `start`.
    """
    if parent.get(end) is None and end != start:
        return []

    path, curr = [], end
    while curr is not None:
        path.append(curr)
        if curr == start:
            break
        curr = parent.get(curr)

    path.reverse()
    return path if path and path[0] == start else []