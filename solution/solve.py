#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

IDENTIFIER = re.compile(r"[A-Z0-9-]{1,16}\Z")


def pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(
            stream,
            object_pairs_hook=pairs_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate(data):
    if not isinstance(data, dict) or set(data) != {"nodes", "lanes", "orders"}:
        raise ValueError("root schema")
    nodes, lanes, orders = data["nodes"], data["lanes"], data["orders"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 10:
        raise ValueError("node count")
    if any(not isinstance(node, str) or not node for node in nodes) or len(set(nodes)) != len(nodes):
        raise ValueError("nodes")
    if not isinstance(lanes, list) or not 1 <= len(lanes) <= 20:
        raise ValueError("lane count")
    if not isinstance(orders, list) or not 1 <= len(orders) <= 24:
        raise ValueError("order count")
    node_index = {node: index for index, node in enumerate(nodes)}
    lane_ids = set()
    parsed_lanes = []
    adjacency = [[] for _ in nodes]
    for index, lane in enumerate(lanes):
        if not isinstance(lane, dict) or set(lane) != {"lane_id", "from", "to", "capacity", "open_fee", "unit_cost", "transit_minutes"}:
            raise ValueError("lane schema")
        lane_id, start, end = lane["lane_id"], lane["from"], lane["to"]
        if not isinstance(lane_id, str) or not IDENTIFIER.fullmatch(lane_id) or lane_id in lane_ids:
            raise ValueError("lane id")
        if not isinstance(start, str) or not isinstance(end, str) or start not in node_index or end not in node_index or start == end:
            raise ValueError("lane endpoints")
        if not integer(lane["capacity"], 1, 32):
            raise ValueError("lane capacity")
        if not integer(lane["open_fee"], 0, 1_000_000) or not integer(lane["unit_cost"], 0, 1_000_000):
            raise ValueError("lane costs")
        if not integer(lane["transit_minutes"], 1, 1_440):
            raise ValueError("lane transit time")
        lane_ids.add(lane_id)
        parsed = (lane_id, node_index[start], node_index[end], lane["capacity"], lane["open_fee"], lane["unit_cost"], lane["transit_minutes"])
        parsed_lanes.append(parsed)
        adjacency[parsed[1]].append(index)
    order_ids = set()
    parsed_orders = []
    for order in orders:
        if not isinstance(order, dict) or set(order) != {"order_id", "origin", "destination", "priority", "pallets", "sla_minutes"}:
            raise ValueError("order schema")
        order_id, start, end = order["order_id"], order["origin"], order["destination"]
        if not isinstance(order_id, str) or not IDENTIFIER.fullmatch(order_id) or order_id in order_ids:
            raise ValueError("order id")
        if not isinstance(start, str) or not isinstance(end, str) or start not in node_index or end not in node_index or start == end:
            raise ValueError("order endpoints")
        if not integer(order["priority"], 0, 2) or not integer(order["pallets"], 1, 8):
            raise ValueError("order terms")
        if not integer(order["sla_minutes"], 1, 10_080):
            raise ValueError("order SLA")
        order_ids.add(order_id)
        parsed_orders.append((order_id, node_index[start], node_index[end], order["priority"], order["pallets"], order["sla_minutes"]))
    return nodes, parsed_lanes, parsed_orders, adjacency


def enumerate_paths(start, end, lanes, adjacency, sla_minutes):
    paths = []
    visited = {start}
    chosen = []

    def walk(node, elapsed):
        if node == end:
            paths.append(tuple(chosen))
            return
        for lane_index in adjacency[node]:
            lane = lanes[lane_index]
            target = lane[2]
            next_elapsed = elapsed + lane[6]
            if target in visited or next_elapsed > sla_minutes:
                continue
            visited.add(target)
            chosen.append(lane_index)
            walk(target, next_elapsed)
            chosen.pop()
            visited.remove(target)

    walk(start, 0)
    paths.sort(key=lambda path: tuple(lanes[index][0] for index in path))
    return paths


def optimize(lanes, orders, adjacency):
    paths = [enumerate_paths(order[1], order[2], lanes, adjacency, order[5]) for order in orders]
    order_sequence = sorted(range(len(orders)), key=lambda index: orders[index][0])
    search_sequence = sorted(range(len(orders)), key=lambda index: (orders[index][3], orders[index][0]))
    remaining = [[0, 0, 0] for _ in range(len(search_sequence) + 1)]
    for position in range(len(search_sequence) - 1, -1, -1):
        remaining[position] = remaining[position + 1].copy()
        remaining[position][orders[search_sequence[position]][3]] += 1

    loads = [0] * len(lanes)
    opened = [False] * len(lanes)
    selected = [None] * len(orders)
    counts = [0, 0, 0]
    total_counts = tuple(sum(order[3] == priority for order in orders) for priority in range(3))
    best_key = None
    best_selected = None
    best_counts = None
    best_cost = None

    def visit(position, cost):
        nonlocal best_key, best_selected, best_counts, best_cost
        if best_key is not None:
            upper = tuple(counts[p] + remaining[position][p] for p in range(3))
            if upper < best_counts or (upper == best_counts and cost > best_cost):
                return
            if upper == best_counts == total_counts and cost == best_cost:
                descriptor_parts = []
                for index in order_sequence:
                    if selected[index] is not None:
                        descriptor_parts.append(
                            tuple(lanes[lane_index][0] for lane_index in selected[index])
                        )
                        continue
                    feasible = [
                        path for path in paths[index]
                        if all(loads[lane_index] + orders[index][4] <= lanes[lane_index][3] for lane_index in path)
                    ]
                    if not feasible:
                        return
                    descriptor_parts.append(
                        min(tuple(lanes[lane_index][0] for lane_index in path) for path in feasible)
                    )
                descriptor_floor = tuple(descriptor_parts)
                if descriptor_floor >= best_key[4]:
                    return
        if position == len(search_sequence):
            descriptor = tuple(
                () if selected[index] is None else tuple(lanes[lane_index][0] for lane_index in selected[index])
                for index in order_sequence
            )
            key = (-counts[0], -counts[1], -counts[2], cost, descriptor)
            if best_key is None or key < best_key:
                best_key = key
                best_selected = selected.copy()
                best_counts = tuple(counts)
                best_cost = cost
            return

        order_index = search_sequence[position]
        order = orders[order_index]
        pallets = order[4]
        priority = order[3]
        for path in paths[order_index]:
            if any(loads[lane_index] + pallets > lanes[lane_index][3] for lane_index in path):
                continue
            added_cost = sum(
                (0 if opened[lane_index] else lanes[lane_index][4]) + pallets * lanes[lane_index][5]
                for lane_index in path
            )
            for lane_index in path:
                loads[lane_index] += pallets
                opened[lane_index] = True
            counts[priority] += 1
            selected[order_index] = path
            visit(position + 1, cost + added_cost)
            selected[order_index] = None
            counts[priority] -= 1
            for lane_index in path:
                loads[lane_index] -= pallets
                if loads[lane_index] == 0:
                    opened[lane_index] = False
        selected[order_index] = None
        visit(position + 1, cost)

    visit(0, 0)
    return best_counts, best_cost, best_selected


def compute(data):
    nodes, lanes, orders, adjacency = validate(data)
    counts, total_cost, selected = optimize(lanes, orders, adjacency)
    loads = [0] * len(lanes)
    for order_index, path in enumerate(selected):
        if path is not None:
            for lane_index in path:
                loads[lane_index] += orders[order_index][4]
    return {
        "served_counts": {str(priority): counts[priority] for priority in range(3)},
        "total_cost": total_cost,
        "orders": [
            {
                "order_id": order[0],
                "accepted": selected[index] is not None,
                "path": [] if selected[index] is None else [lanes[lane_index][0] for lane_index in selected[index]],
            }
            for index, order in enumerate(orders)
        ],
        "lane_loads": [
            {"lane_id": lane[0], "load": loads[index], "opened": loads[index] > 0}
            for index, lane in enumerate(lanes)
        ],
    }


def publish(path, result):
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix=".dispatch-plan-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, separators=(",", ":"))
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
        publish(sys.argv[2], compute(load(sys.argv[1])))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
