import itertools
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

APP = os.environ.get("APP", "/app/solve.py")


def run(data, raw=None, sentinel=None):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        input_path, output_path = root / "input.json", root / "output.json"
        input_path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        if sentinel is not None:
            output_path.write_bytes(sentinel)
        process = subprocess.run(
            [sys.executable, APP, str(input_path), str(output_path)], capture_output=True, timeout=30
        )
        leftovers = sorted(path.name for path in root.iterdir() if path not in (input_path, output_path))
        output = output_path.read_bytes() if output_path.exists() else None
        return process, output, output_path.exists(), leftovers


def all_paths(start, end, lanes):
    paths = []

    def walk(node, seen, chosen):
        if node == end:
            paths.append(tuple(chosen))
            return
        for lane in lanes:
            if lane["from"] == node and lane["to"] not in seen:
                walk(lane["to"], seen | {lane["to"]}, chosen + [lane["lane_id"]])

    walk(start, {start}, [])
    return paths


def exhaustive_plan(data):
    orders = data["orders"]
    lanes = {lane["lane_id"]: lane for lane in data["lanes"]}
    choices = [[None] + all_paths(order["origin"], order["destination"], data["lanes"]) for order in orders]
    best_key = None
    best_choice = None
    for selected in itertools.product(*choices):
        loads = {lane_id: 0 for lane_id in lanes}
        counts = [0, 0, 0]
        cost = 0
        feasible = True
        for order, path in zip(orders, selected):
            if path is None:
                continue
            counts[order["priority"]] += 1
            for lane_id in path:
                lane = lanes[lane_id]
                loads[lane_id] += order["pallets"]
                if loads[lane_id] > lane["capacity"]:
                    feasible = False
                cost += order["pallets"] * lane["unit_cost"]
        if not feasible:
            continue
        cost += sum(lanes[lane_id]["open_fee"] for lane_id, load in loads.items() if load)
        by_id = sorted(range(len(orders)), key=lambda index: orders[index]["order_id"])
        descriptor = tuple(() if selected[index] is None else selected[index] for index in by_id)
        key = (-counts[0], -counts[1], -counts[2], cost, descriptor)
        if best_key is None or key < best_key:
            best_key, best_choice = key, selected
    return [-best_key[0], -best_key[1], -best_key[2]], best_key[3], best_choice


def assert_plan_consistent(data, result):
    lane_by_id = {lane["lane_id"]: lane for lane in data["lanes"]}
    order_by_id = {order["order_id"]: order for order in data["orders"]}
    loads = {lane_id: 0 for lane_id in lane_by_id}
    counts = [0, 0, 0]
    cost = 0
    assert len(result["orders"]) == len(data["orders"])
    for row in result["orders"]:
        order = order_by_id[row["order_id"]]
        path = row["path"]
        assert row["accepted"] is (len(path) > 0)
        if not row["accepted"]:
            assert path == []
            continue
        counts[order["priority"]] += 1
        current = order["origin"]
        visited = {current}
        for lane_id in path:
            lane = lane_by_id[lane_id]
            assert lane["from"] == current
            current = lane["to"]
            assert current not in visited
            visited.add(current)
            loads[lane_id] += order["pallets"]
            cost += order["pallets"] * lane["unit_cost"]
        assert current == order["destination"]
    cost += sum(lane_by_id[lane_id]["open_fee"] for lane_id, load in loads.items() if load)
    assert result["served_counts"] == {str(i): counts[i] for i in range(3)}
    assert result["total_cost"] == cost
    assert len(result["lane_loads"]) == len(data["lanes"])
    for row, lane in zip(result["lane_loads"], data["lanes"]):
        assert row == {"lane_id": lane["lane_id"], "load": loads[lane["lane_id"]], "opened": loads[lane["lane_id"]] > 0}
        assert 0 <= row["load"] <= lane["capacity"]


def test_hand_computed_dispatch_respects_priority_and_open_fee_gate():
    '''PRI-01: 先按 0、1、2 级词典序最大化接收张数，再最小化总费用。'''
    data = {
        "nodes": ["S", "A", "T"],
        "lanes": [
            {"lane_id": "SA", "from": "S", "to": "A", "capacity": 2, "open_fee": 7, "unit_cost": 1},
            {"lane_id": "AT", "from": "A", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 1},
        ],
        "orders": [
            {"order_id": "P0", "origin": "S", "destination": "T", "priority": 0, "pallets": 2},
            {"order_id": "P1", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["served_counts"] == {"0": 1, "1": 0, "2": 0}
    assert result["total_cost"] == 11 and [row["accepted"] for row in result["orders"]] == [True, False]
    assert_plan_consistent(data, result)


def test_exhaustive_small_ledgers_match_independent_joint_enumeration():
    '''CAP-02: 每张接收订单整托走一条简单路径，所有订单共同占用线路容量。'''
    rng = random.Random(287014)
    nodes = ["S", "A", "B", "T"]
    possible = [("S", "A"), ("S", "B"), ("A", "B"), ("A", "T"), ("B", "T"), ("S", "T")]
    for case in range(16):
        selected_edges = possible[:]
        rng.shuffle(selected_edges)
        lanes = [
            {"lane_id": f"L{i:02}", "from": edge[0], "to": edge[1], "capacity": rng.randint(1, 5), "open_fee": rng.randint(0, 8), "unit_cost": rng.randint(0, 5)}
            for i, edge in enumerate(selected_edges[: rng.randint(3, 6)])
        ]
        orders = [
            {"order_id": f"O{i}", "origin": "S", "destination": "T", "priority": rng.randrange(3), "pallets": rng.randint(1, 3)}
            for i in range(3)
        ]
        data = {"nodes": nodes, "lanes": lanes, "orders": orders}
        expected_counts, expected_cost, expected_paths = exhaustive_plan(data)
        process, output, exists, leftovers = run(data)
        result = json.loads(output)
        assert process.returncode == 0 and exists and leftovers == [], f"case={case}"
        assert [result["served_counts"][str(i)] for i in range(3)] == expected_counts, f"case={case}"
        assert result["total_cost"] == expected_cost, f"case={case}"
        assert [None if not row["accepted"] else tuple(row["path"]) for row in result["orders"]] == list(expected_paths), f"case={case}"
        assert_plan_consistent(data, result)


def test_shared_lane_fee_is_paid_once_for_multiple_orders():
    '''FIX-03: 一条被多张订单共用的线路，其开线费只收取一次。'''
    data = {
        "nodes": ["S", "A", "T"],
        "lanes": [
            {"lane_id": "SHARE", "from": "S", "to": "A", "capacity": 2, "open_fee": 9, "unit_cost": 0},
            {"lane_id": "END", "from": "A", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 0},
        ],
        "orders": [
            {"order_id": "A", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
            {"order_id": "B", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["served_counts"] == {"0": 0, "1": 2, "2": 0} and result["total_cost"] == 9
    assert_plan_consistent(data, result)


def test_opening_fee_can_overrule_individually_cheapest_lanes():
    '''FIX-03: 全局费用包含每条实际启用线路的一次开线费。'''
    data = {
        "nodes": ["S", "A", "T"],
        "lanes": [
            {"lane_id": "DIRECT", "from": "S", "to": "T", "capacity": 2, "open_fee": 12, "unit_cost": 0},
            {"lane_id": "SA", "from": "S", "to": "A", "capacity": 2, "open_fee": 3, "unit_cost": 0},
            {"lane_id": "AT", "from": "A", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 0},
        ],
        "orders": [
            {"order_id": "A", "origin": "S", "destination": "T", "priority": 0, "pallets": 1},
            {"order_id": "B", "origin": "S", "destination": "T", "priority": 0, "pallets": 1},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["total_cost"] == 3 and [row["path"] for row in result["orders"]] == [["SA", "AT"], ["SA", "AT"]]
    assert_plan_consistent(data, result)


def test_whole_order_cannot_be_split_across_individually_insufficient_paths():
    '''CAP-02: 每张订单不得拆分，必须有一条路径可承载该订单全部托盘。'''
    data = {
        "nodes": ["S", "A", "B", "T"],
        "lanes": [
            {"lane_id": "SA", "from": "S", "to": "A", "capacity": 2, "open_fee": 0, "unit_cost": 0},
            {"lane_id": "AT", "from": "A", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 0},
            {"lane_id": "SB", "from": "S", "to": "B", "capacity": 2, "open_fee": 0, "unit_cost": 0},
            {"lane_id": "BT", "from": "B", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 0},
        ],
        "orders": [{"order_id": "WHOLE", "origin": "S", "destination": "T", "priority": 0, "pallets": 3}],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["served_counts"] == {"0": 0, "1": 0, "2": 0} and result["orders"][0] == {"order_id": "WHOLE", "accepted": False, "path": []}
    assert_plan_consistent(data, result)


def test_partial_capacity_assignment_prefers_feasible_order_subset():
    '''CAP-02: 线路占用不得超过共用容量，并以订单优先级选择可行子集。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [{"lane_id": "ONLY", "from": "S", "to": "T", "capacity": 3, "open_fee": 1, "unit_cost": 2}],
        "orders": [
            {"order_id": "BIG", "origin": "S", "destination": "T", "priority": 1, "pallets": 3},
            {"order_id": "SMALL", "origin": "S", "destination": "T", "priority": 1, "pallets": 2},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["served_counts"] == {"0": 0, "1": 1, "2": 0}
    assert result["total_cost"] == 7 and result["lane_loads"][0]["load"] == 3
    assert_plan_consistent(data, result)


def test_tie_break_uses_lane_ids_not_input_lane_order():
    '''TIE-04: 相同服务数和总费用按线路 ID 序列 ASCII 字典序裁决。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [
            {"lane_id": "Z", "from": "S", "to": "T", "capacity": 1, "open_fee": 0, "unit_cost": 0},
            {"lane_id": "A", "from": "S", "to": "T", "capacity": 1, "open_fee": 0, "unit_cost": 0},
        ],
        "orders": [{"order_id": "O", "origin": "S", "destination": "T", "priority": 2, "pallets": 1}],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["orders"][0]["path"] == ["A"]
    assert [row["opened"] for row in result["lane_loads"]] == [False, True]


def test_tie_break_is_stable_under_order_input_permutation():
    '''TIE-04: 费用并列时订单按 ID 而非输入顺序决定路径组合。'''
    lanes = [
        {"lane_id": "A", "from": "S", "to": "T", "capacity": 1, "open_fee": 0, "unit_cost": 0},
        {"lane_id": "B", "from": "S", "to": "T", "capacity": 1, "open_fee": 0, "unit_cost": 0},
    ]
    orders = [
        {"order_id": "X", "origin": "S", "destination": "T", "priority": 0, "pallets": 1},
        {"order_id": "Y", "origin": "S", "destination": "T", "priority": 0, "pallets": 1},
    ]
    first, out_first, exists_first, _ = run({"nodes": ["S", "T"], "lanes": lanes, "orders": orders})
    second, out_second, exists_second, _ = run({"nodes": ["S", "T"], "lanes": lanes, "orders": list(reversed(orders))})
    by_id_first = {row["order_id"]: row["path"] for row in json.loads(out_first)["orders"]}
    by_id_second = {row["order_id"]: row["path"] for row in json.loads(out_second)["orders"]}
    assert first.returncode == second.returncode == 0 and exists_first and exists_second
    assert by_id_first == by_id_second == {"X": ["A"], "Y": ["B"]}


def test_unreachable_order_is_rejected_without_changing_other_service():
    '''PRI-01: 无可行路径的订单不阻止其他订单正常排程。'''
    data = {
        "nodes": ["S", "T", "X"],
        "lanes": [{"lane_id": "ST", "from": "S", "to": "T", "capacity": 1, "open_fee": 4, "unit_cost": 2}],
        "orders": [
            {"order_id": "OK", "origin": "S", "destination": "T", "priority": 2, "pallets": 1},
            {"order_id": "MISS", "origin": "X", "destination": "T", "priority": 0, "pallets": 1},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["served_counts"] == {"0": 0, "1": 0, "2": 1}
    assert [row["accepted"] for row in result["orders"]] == [True, False]


def test_output_shape_and_input_order_are_preserved():
    '''VALID-05: 输出字段集合固定，订单与线路行分别保持输入顺序。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [
            {"lane_id": "Z", "from": "S", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 1},
            {"lane_id": "A", "from": "S", "to": "T", "capacity": 2, "open_fee": 0, "unit_cost": 2},
        ],
        "orders": [
            {"order_id": "Z-ORDER", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
            {"order_id": "A-ORDER", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
        ],
    }
    process, output, exists, leftovers = run(data)
    result = json.loads(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert set(result) == {"served_counts", "total_cost", "orders", "lane_loads"}
    assert [row["order_id"] for row in result["orders"]] == ["Z-ORDER", "A-ORDER"]
    assert [row["lane_id"] for row in result["lane_loads"]] == ["Z", "A"]


def test_identical_input_produces_identical_json_bytes():
    '''VALID-05: 相同输入必须产生相同 JSON 字节。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [{"lane_id": "L", "from": "S", "to": "T", "capacity": 1, "open_fee": 3, "unit_cost": 4}],
        "orders": [{"order_id": "O", "origin": "S", "destination": "T", "priority": 0, "pallets": 1}],
    }
    first, bytes_first, exists_first, left_first = run(data)
    second, bytes_second, exists_second, left_second = run(data)
    assert first.returncode == second.returncode == 0
    assert exists_first and exists_second and left_first == left_second == []
    assert bytes_first == bytes_second


def test_rejects_duplicate_json_key_without_creating_output():
    '''VALID-05: 任意 JSON 对象出现重复键时，输入无效。'''
    raw = '{"nodes":["S","T"],"nodes":["S","X"],"lanes":[],"orders":[]}'
    process, output, exists, leftovers = run({}, raw=raw)
    assert process.returncode != 0 and output is None and not exists and leftovers == []


def test_rejects_boolean_capacity_and_preserves_sentinel():
    '''VALID-05: 布尔值不是整数容量，拒收时旧文件字节不变。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [{"lane_id": "L", "from": "S", "to": "T", "capacity": True, "open_fee": 0, "unit_cost": 0}],
        "orders": [{"order_id": "O", "origin": "S", "destination": "T", "priority": 0, "pallets": 1}],
    }
    sentinel = b"prior-dispatch\x00"
    process, output, exists, leftovers = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and exists and leftovers == []


def test_rejects_fractional_integer_field():
    '''VALID-05: 公开字段声明为整数，浮点形式的整数也不是合法整数值。'''
    raw = '{"nodes":["S","T"],"lanes":[{"lane_id":"L","from":"S","to":"T","capacity":1.0,"open_fee":0,"unit_cost":0}],"orders":[{"order_id":"O","origin":"S","destination":"T","priority":0,"pallets":1}]}'
    process, output, exists, leftovers = run({}, raw=raw)
    assert process.returncode != 0 and output is None and not exists and leftovers == []


def test_rejects_duplicate_identifier_and_late_invalid_order_atomically():
    '''VALID-05: 重复订单标识或末尾非法订单均拒收且不得留下临时文件。'''
    data = {
        "nodes": ["S", "T"],
        "lanes": [{"lane_id": "L", "from": "S", "to": "T", "capacity": 8, "open_fee": 0, "unit_cost": 0}],
        "orders": [
            {"order_id": "O", "origin": "S", "destination": "T", "priority": 0, "pallets": 1},
            {"order_id": "O", "origin": "S", "destination": "T", "priority": 1, "pallets": 1},
        ],
    }
    sentinel = b"old-version"
    process, output, exists, leftovers = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and exists and leftovers == []
    data["orders"][1]["order_id"] = "LATE"
    data["orders"][1]["priority"] = 8
    process, output, exists, leftovers = run(data)
    assert process.returncode != 0 and output is None and not exists and leftovers == []


def test_atomic_replace_failure_preserves_old_report():
    '''VALID-05: 发布替换失败必须保留原报告字节并清理临时文件。'''
    import importlib.util

    data = {
        "nodes": ["S", "T"],
        "lanes": [{"lane_id": "L", "from": "S", "to": "T", "capacity": 1, "open_fee": 0, "unit_cost": 0}],
        "orders": [{"order_id": "O", "origin": "S", "destination": "T", "priority": 0, "pallets": 1}],
    }
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        input_path, output_path = root / "input.json", root / "output.json"
        input_path.write_text(json.dumps(data), encoding="utf-8")
        sentinel = b"previous-report"
        output_path.write_bytes(sentinel)
        spec = importlib.util.spec_from_file_location("candidate_solver", APP)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = module.os.replace
        module.os.replace = lambda _src, _dst: (_ for _ in ()).throw(OSError("injected"))
        old_argv = sys.argv
        sys.argv = [APP, str(input_path), str(output_path)]
        try:
            status = module.main()
        finally:
            sys.argv = old_argv
            module.os.replace = original
        assert status != 0 and output_path.read_bytes() == sentinel
        assert sorted(path.name for path in root.iterdir()) == ["input.json", "output.json"]
