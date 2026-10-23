"""Independent small-instance checks used during domain review.

This module is intentionally separate from the reference residual implementation.
It enumerates simple paths and source cuts for compact multigraphs, preserving
parallel-edge identity and input-order projection.  The checker is private
release evidence, not part of the candidate image.
"""
from __future__ import annotations
from itertools import combinations
from math import isfinite

def simple_paths(nodes, edges, source, sink):
    adjacency = {node: [] for node in nodes}
    for number, edge in enumerate(edges):
        if edge[0] != edge[1]:
            adjacency[edge[0]].append((edge[1], edge[3], number))
    found = []
    def walk(node, visited, cost):
        if node == sink:
            found.append((cost, tuple(visited)))
            return
        for target, weight, _number in adjacency[node]:
            if target not in visited:
                walk(target, visited + [target], cost + weight)
    walk(source, [source], 0.0)
    return sorted(found)

def cut_capacity(nodes, edges, source_side):
    side = set(source_side)
    return sum(edge[2] for edge in edges if edge[0] in side and edge[1] not in side)

def validate_numeric_edges(nodes, edges):
    known = set(nodes)
    for edge in edges:
        if len(edge) != 4:
            return False
        u, v, capacity, cost = edge
        if u not in known or v not in known:
            return False
        if isinstance(capacity, bool) or isinstance(cost, bool):
            return False
        if not isfinite(float(capacity)) or capacity < 0:
            return False
        if not isfinite(float(cost)):
            return False
    return True

def enumerate_cuts(nodes, source, sink):
    middle = [node for node in nodes if node not in {source, sink}]
    for size in range(len(middle) + 1):
        for chosen in combinations(middle, size):
            yield {source, *chosen}

def canonical_path(nodes, edges, source, sink):
    paths = simple_paths(nodes, edges, source, sink)
    return None if not paths else min(paths, key=lambda item: (item[0], item[1]))

def verify_projection(nodes, source_side):
    positions = {node: index for index, node in enumerate(nodes)}
    return list(source_side) == sorted(source_side, key=positions.__getitem__)

def verify_tolerance(left, right):
    return abs(left - right) <= 1e-12 + 1e-9 * max(1.0, abs(right))
