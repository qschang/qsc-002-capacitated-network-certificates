#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from functools import lru_cache

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
        if not isinstance(lane, dict) or set(lane) != {"lane_id", "from", "to", "early_capacity", "late_capacity", "open_fee", "unit_cost", "transit_minutes"}:
            raise ValueError("lane schema")
        lane_id, start, end = lane["lane_id"], lane["from"], lane["to"]
        if not isinstance(lane_id, str) or not IDENTIFIER.fullmatch(lane_id) or lane_id in lane_ids:
            raise ValueError("lane id")
        if not isinstance(start, str) or not isinstance(end, str) or start not in node_index or end not in node_index or start == end:
            raise ValueError("lane endpoints")
        if not integer(lane["early_capacity"], 1, 32) or not integer(lane["late_capacity"], 1, 32):
            raise ValueError("lane wave capacity")
        if not integer(lane["open_fee"], 0, 1_000_000) or not integer(lane["unit_cost"], 0, 1_000_000):
            raise ValueError("lane costs")
        if not integer(lane["transit_minutes"], 1, 1_440):
            raise ValueError("lane transit time")
        lane_ids.add(lane_id)
        parsed = (lane_id, node_index[start], node_index[end], lane["early_capacity"], lane["late_capacity"], lane["open_fee"], lane["unit_cost"], lane["transit_minutes"])
        parsed_lanes.append(parsed)
        adjacency[parsed[1]].append(index)
    order_ids = set()
    parsed_orders = []
    for order in orders:
        if not isinstance(order, dict) or set(order) != {"order_id", "origin", "destination", "priority", "pallets", "sla_minutes", "allowed_waves"}:
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
        waves = order["allowed_waves"]
        if not isinstance(waves, list) or not waves or any(wave not in ("early", "late") for wave in waves) or len(set(waves)) != len(waves):
            raise ValueError("order waves")
        order_ids.add(order_id)
        parsed_orders.append((order_id, node_index[start], node_index[end], order["priority"], order["pallets"], order["sla_minutes"], tuple(waves)))
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
            next_elapsed = elapsed + lane[7]
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

    def better(candidate, current):
        if current is None or candidate[0] != current[0]:
            return current is None or candidate[0] > current[0]
        if candidate[1] != current[1]:
            return candidate[1] < current[1]
        return candidate[2] < current[2]

    @lru_cache(maxsize=None)
    def visit(position, loads):
        if position == len(order_sequence):
            return (0, 0, 0), 0, (), ()

        order_index = order_sequence[position]
        order = orders[order_index]
        pallets, priority = order[4], order[3]
        suffix_counts, suffix_cost, suffix_descriptor, suffix_paths = visit(position + 1, loads)
        best = (
            suffix_counts,
            suffix_cost,
            ((),) + suffix_descriptor,
            (None,) + suffix_paths,
        )

        for path in paths[order_index]:
            for wave_name in order[6]:
                wave = 0 if wave_name == "early" else 1
                wave_offset = wave * len(lanes)
                if any(loads[wave_offset + lane_index] + pallets > lanes[lane_index][3 + wave] for lane_index in path):
                    continue
                next_loads = list(loads)
                added_cost = 0
                for lane_index in path:
                    lane = lanes[lane_index]
                    if loads[lane_index] + loads[len(lanes) + lane_index] == 0:
                        added_cost += lane[5]
                    added_cost += pallets * lane[6]
                    next_loads[wave_offset + lane_index] += pallets
                tail_counts, tail_cost, tail_descriptor, tail_paths = visit(position + 1, tuple(next_loads))
                counts = list(tail_counts)
                counts[priority] += 1
                descriptor = (wave_name, tuple(lanes[lane_index][0] for lane_index in path))
                candidate = (
                    tuple(counts),
                    tail_cost + added_cost,
                    (descriptor,) + tail_descriptor,
                    ((wave_name, path),) + tail_paths,
                )
                if better(candidate, best):
                    best = candidate
        return best

    counts, total_cost, _, ordered_paths = visit(0, tuple([0] * (2 * len(lanes))))
    selected = [None] * len(orders)
    for position, order_index in enumerate(order_sequence):
        selected[order_index] = ordered_paths[position]
    return counts, total_cost, selected


def compute(data):
    nodes, lanes, orders, adjacency = validate(data)
    counts, total_cost, selected = optimize(lanes, orders, adjacency)
    loads = [0] * len(lanes)
    for order_index, path in enumerate(selected):
        if path is not None:
            wave_name, lane_path = path
            offset = 0 if wave_name == "early" else len(lanes)
            for lane_index in lane_path:
                loads[offset + lane_index] += orders[order_index][4]
    return {
        "served_counts": {str(priority): counts[priority] for priority in range(3)},
        "total_cost": total_cost,
        "orders": [
            {
                "order_id": order[0],
                "accepted": selected[index] is not None,
                "wave": None if selected[index] is None else selected[index][0],
                "path": [] if selected[index] is None else [lanes[lane_index][0] for lane_index in selected[index][1]],
            }
            for index, order in enumerate(orders)
        ],
        "lane_loads": [
            {"lane_id": lane[0], "early_load": loads[index], "late_load": loads[len(lanes) + index], "opened": loads[index] + loads[len(lanes) + index] > 0}
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
