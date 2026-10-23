#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sys
import tempfile


def fail(message: str) -> None:
    raise ValueError(message)


def pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate JSON key")
        result[key] = value
    return result


def finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=pairs_no_duplicates)


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
    if source not in index or sink not in index or source == sink:
        fail("terminals")
    parsed = []
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"u", "v", "capacity", "cost"}:
            fail("edge schema")
        u, v, capacity, cost = edge["u"], edge["v"], edge["capacity"], edge["cost"]
        if u not in index or v not in index:
            fail("edge endpoint")
        if not finite_number(capacity) or not 0 <= capacity <= 1e9:
            fail("capacity")
        if not finite_number(cost) or abs(cost) > 1e6:
            fail("cost")
        parsed.append((index[u], index[v], float(capacity), float(cost)))
    return nodes, index[source], index[sink], parsed


def reject_negative_cycle(n, edges):
    distance = [0.0] * n
    active = [(u, v, cost) for u, v, capacity, cost in edges if capacity > 0.0]
    for iteration in range(n):
        changed = False
        for u, v, cost in active:
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
    reverse = [u, 0.0, -cost, len(graph[u])]
    graph[u].append(forward)
    graph[v].append(reverse)
    return forward


def shortest_residual_path(graph, source, sink):
    n = len(graph)
    distance = [math.inf] * n
    parent = [None] * n
    distance[source] = 0.0
    for _ in range(n - 1):
        changed = False
        for u in range(n):
            if distance[u] == math.inf:
                continue
            for edge_id, edge in enumerate(graph[u]):
                v, residual, cost, _reverse_id = edge
                if residual <= 0.0:
                    continue
                candidate = distance[u] + cost
                if candidate < distance[v]:
                    distance[v] = candidate
                    parent[v] = (u, edge_id)
                    changed = True
        if not changed:
            break
    if distance[sink] == math.inf:
        return None, None
    path = []
    current = sink
    seen = set()
    while current != source:
        if current in seen or parent[current] is None:
            fail("residual predecessor chain")
        seen.add(current)
        u, edge_id = parent[current]
        path.append((u, edge_id))
        current = u
    path.reverse()
    return path, distance[sink]


def min_cost_max_flow(n, source, sink, edges):
    graph = [[] for _ in range(n)]
    originals = []
    for u, v, capacity, cost in edges:
        if capacity > 0.0 and u != v:
            originals.append(add_arc(graph, u, v, capacity, cost))
        else:
            originals.append(None)
    while True:
        path, _path_cost = shortest_residual_path(graph, source, sink)
        if path is None:
            break
        amount = math.inf
        for u, edge_id in path:
            amount = min(amount, graph[u][edge_id][1])
        if not amount > 0.0 or not math.isfinite(amount):
            fail("invalid augmentation")
        for u, edge_id in path:
            edge = graph[u][edge_id]
            reverse = graph[edge[0]][edge[3]]
            edge[1] -= amount
            reverse[1] += amount
    flows = []
    for edge, original in zip(edges, originals):
        flows.append(0.0 if original is None else edge[2] - original[1])
    return graph, flows


def residual_potentials(graph):
    n = len(graph)
    distance = [0.0] * n
    for iteration in range(n):
        changed = False
        for u in range(n):
            for v, residual, cost, _reverse_id in graph[u]:
                if residual <= 0.0:
                    continue
                candidate = distance[u] + cost
                if candidate < distance[v]:
                    distance[v] = candidate
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
            if residual > 0.0 and v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def compute(data):
    nodes, source, sink, edges = validate(data)
    n = len(nodes)
    reject_negative_cycle(n, edges)
    graph, flows = min_cost_max_flow(n, source, sink, edges)
    balances = [0.0] * n
    for (u, v, _capacity, _cost), flow in zip(edges, flows):
        balances[u] += flow
        balances[v] -= flow
    max_flow = math.fsum(flow for (u, v, _capacity, _cost), flow in zip(edges, flows) if u == source) - math.fsum(
        flow for (u, v, _capacity, _cost), flow in zip(edges, flows) if v == source
    )
    min_cost = math.fsum(flow * edge[3] for edge, flow in zip(edges, flows))
    source_side_set = residual_source_side(graph, source)
    cut = math.fsum(capacity for u, v, capacity, _cost in edges if u in source_side_set and v not in source_side_set)
    if abs(balances[source] - max_flow) > 1e-12 + 1e-9 * max(abs(balances[source]), abs(max_flow)):
        fail("source balance")
    if abs(balances[sink] + max_flow) > 1e-12 + 1e-9 * max(abs(balances[sink]), abs(max_flow)):
        fail("sink balance")
    if abs(max_flow - cut) > 1e-12 + 1e-9 * max(abs(max_flow), abs(cut)):
        fail("flow-cut mismatch")
    potentials = residual_potentials(graph)
    return {
        "max_flow": max_flow,
        "min_cost": min_cost,
        "edge_flows": flows,
        "min_cut_capacity": cut,
        "source_side": [node for i, node in enumerate(nodes) if i in source_side_set],
        "node_potentials": potentials,
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
