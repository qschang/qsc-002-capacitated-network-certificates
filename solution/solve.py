#!/usr/bin/env python3
from __future__ import annotations

import heapq
import json
import os
import sys
import tempfile
from decimal import Decimal, InvalidOperation

SCALE = 1_000_000
SCALE_DIGITS = 6


def fail(message: str) -> None:
    raise ValueError(message)


def pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate JSON key")
        result[key] = value
    return result


def load(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(
            stream,
            object_pairs_hook=pairs_no_duplicates,
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=lambda _value: fail("non-finite JSON number"),
        )


def decimal_units(value, limit):
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        fail("numeric field")
    if value.copy_abs() > limit or value.as_tuple().exponent < -SCALE_DIGITS:
        fail("numeric range or precision")
    scaled = value * SCALE
    if scaled != scaled.to_integral_value():
        fail("numeric precision")
    return int(scaled)


def validate(data):
    if not isinstance(data, dict) or set(data) != {"nodes", "edges", "source", "sink"}:
        fail("input schema")
    nodes, edges = data["nodes"], data["edges"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 2048:
        fail("node count")
    if any(not isinstance(node, str) or not node for node in nodes) or len(set(nodes)) != len(nodes):
        fail("nodes")
    if not isinstance(edges, list) or len(edges) > 16384:
        fail("edge count")
    index = {node: pos for pos, node in enumerate(nodes)}
    source, sink = data["source"], data["sink"]
    if not isinstance(source, str) or not isinstance(sink, str) or source not in index or sink not in index or source == sink:
        fail("terminals")
    parsed = []
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"u", "v", "capacity", "cost"}:
            fail("edge schema")
        u, v = edge["u"], edge["v"]
        if not isinstance(u, str) or not isinstance(v, str) or u not in index or v not in index:
            fail("edge endpoint")
        capacity = decimal_units(edge["capacity"], Decimal("1000000000"))
        cost = decimal_units(edge["cost"], Decimal("1000000"))
        if capacity < 0:
            fail("capacity")
        parsed.append((index[u], index[v], capacity, cost))
    return nodes, index[source], index[sink], parsed


def reject_negative_cycle(n, edges):
    arcs = [(u, v, cost) for u, v, capacity, cost in edges if capacity > 0]
    distance = [0] * n
    for iteration in range(n):
        changed = False
        for u, v, cost in arcs:
            candidate = distance[u] + cost
            if candidate < distance[v]:
                distance[v] = candidate
                changed = True
        if not changed:
            return
        if iteration == n - 1:
            fail("negative-cost cycle")


def add_arc(graph, u, v, capacity, cost):
    forward = [v, capacity, cost, len(graph[v])]
    reverse = [u, 0, -cost, len(graph[u])]
    graph[u].append(forward)
    graph[v].append(reverse)
    return forward


def min_cost_max_flow(n, source, sink, edges):
    graph = [[] for _ in range(n)]
    originals = []
    for u, v, capacity, cost in edges:
        arc = add_arc(graph, u, v, capacity, cost) if capacity > 0 and u != v else None
        originals.append(None if arc is None else (arc, capacity))

    # Distances from a zero-cost super-source make every initial reduced cost nonnegative.
    potential = [0] * n
    for _ in range(n - 1):
        changed = False
        for u in range(n):
            for edge in graph[u]:
                v, residual, cost, _reverse_id = edge
                if residual and potential[u] + cost < potential[v]:
                    potential[v] = potential[u] + cost
                    changed = True
        if not changed:
            break

    while True:
        distance = [None] * n
        parent = [None] * n
        distance[source] = 0
        queue = [(0, source)]
        while queue:
            dist_u, u = heapq.heappop(queue)
            if distance[u] != dist_u:
                continue
            for edge_id, edge in enumerate(graph[u]):
                v, residual, cost, _reverse_id = edge
                if residual <= 0:
                    continue
                reduced = cost + potential[u] - potential[v]
                if reduced < 0:
                    fail("infeasible reduced cost")
                candidate = dist_u + reduced
                if distance[v] is None or candidate < distance[v]:
                    distance[v] = candidate
                    parent[v] = (u, edge_id)
                    heapq.heappush(queue, (candidate, v))
        if distance[sink] is None:
            break
        for node, value in enumerate(distance):
            if value is not None:
                potential[node] += value
        path = []
        current = sink
        while current != source:
            if parent[current] is None:
                fail("residual predecessor chain")
            u, edge_id = parent[current]
            path.append((u, edge_id))
            current = u
        amount = min(graph[u][edge_id][1] for u, edge_id in path)
        if amount <= 0:
            fail("invalid augmentation")
        for u, edge_id in path:
            edge = graph[u][edge_id]
            reverse = graph[edge[0]][edge[3]]
            edge[1] -= amount
            reverse[1] += amount

    flows = [0 if original is None else original[1] - original[0][1] for original in originals]
    return graph, flows


def residual_potentials(graph):
    n = len(graph)
    distance = [0] * n
    for iteration in range(n):
        changed = False
        for u in range(n):
            for v, residual, cost, _reverse_id in graph[u]:
                if residual > 0 and distance[u] + cost < distance[v]:
                    distance[v] = distance[u] + cost
                    changed = True
        if not changed:
            return distance
        if iteration == n - 1:
            fail("negative residual cycle")
    return distance


def residual_source_side(graph, source):
    seen = {source}
    queue = [source]
    for u in queue:
        for v, residual, _cost, _reverse_id in graph[u]:
            if residual > 0 and v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def decimal_text(units, scale=SCALE):
    sign = "-" if units < 0 else ""
    units = abs(units)
    whole, fraction = divmod(units, scale)
    digits = len(str(scale)) - 1
    return f"{sign}{whole}.{fraction:0{digits}d}"


def compute(data):
    nodes, source, sink, edges = validate(data)
    n = len(nodes)
    reject_negative_cycle(n, edges)
    graph, flows = min_cost_max_flow(n, source, sink, edges)
    balances = [0] * n
    min_cost_units = 0
    for (u, v, _capacity, cost), flow in zip(edges, flows):
        balances[u] += flow
        balances[v] -= flow
        min_cost_units += flow * cost
    max_flow_units = balances[source]
    if balances[sink] != -max_flow_units or any(
        balances[i] != 0 for i in range(n) if i not in (source, sink)
    ):
        fail("flow conservation")
    source_side_set = residual_source_side(graph, source)
    cut_units = sum(capacity for u, v, capacity, _cost in edges if u in source_side_set and v not in source_side_set)
    if cut_units != max_flow_units:
        fail("flow-cut mismatch")
    potentials = residual_potentials(graph)
    for (u, v, capacity, cost), flow in zip(edges, flows):
        if capacity - flow > 0 and cost + potentials[u] - potentials[v] < 0:
            fail("negative forward reduced cost")
        if flow > 0 and -cost + potentials[v] - potentials[u] < 0:
            fail("negative reverse reduced cost")
    return {
        "max_flow": decimal_text(max_flow_units),
        "min_cost": decimal_text(min_cost_units, SCALE * SCALE),
        "edge_flows": [decimal_text(flow) for flow in flows],
        "min_cut_capacity": decimal_text(cut_units),
        "source_side": [node for i, node in enumerate(nodes) if i in source_side_set],
        "node_potentials": [decimal_text(value) for value in potentials],
    }


def publish(path, result):
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix=".network-plan-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main():
    if len(sys.argv) != 3:
        return 2
    try:
        result = compute(load(sys.argv[1]))
        publish(sys.argv[2], result)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
