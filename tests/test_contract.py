import itertools
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

APP = os.environ.get("APP", "/app/solve.py")
def run(data, sentinel=None, raw=None):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        input_path, output_path = root / "input.json", root / "output.json"
        input_path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        if sentinel is not None:
            output_path.write_bytes(sentinel)
        result = subprocess.run(
            [sys.executable, APP, str(input_path), str(output_path)],
            capture_output=True,
            timeout=30,
        )
        leftovers = sorted(p.name for p in root.iterdir() if p not in (input_path, output_path))
        output = output_path.read_bytes() if output_path.exists() else None
        return result, output, leftovers, output_path.exists()


def load_result(payload):
    result = json.loads(payload)
    assert all(isinstance(result[field], str) for field in ("max_flow", "min_cost", "min_cut_capacity"))
    assert all(isinstance(value, str) for field in ("edge_flows", "node_potentials") for value in result[field])
    for field in ("max_flow", "min_cost", "min_cut_capacity"):
        result[field] = Decimal(result[field])
    result["edge_flows"] = [Decimal(value) for value in result["edge_flows"]]
    result["node_potentials"] = [Decimal(value) for value in result["node_potentials"]]
    return result


def certificate_issues(data, result):
    nodes = data["nodes"]
    edges = data["edges"]
    index = {node: i for i, node in enumerate(nodes)}
    flows = result["edge_flows"]
    potentials = result["node_potentials"]
    if len(flows) != len(edges) or len(potentials) != len(nodes):
        return ["vector lengths"]
    balance = [Decimal(0)] * len(nodes)
    cost_terms = []
    issues = []
    for edge, flow in zip(edges, flows):
        u, v = index[edge["u"]], index[edge["v"]]
        cap, cost = Decimal(str(edge["capacity"])), Decimal(str(edge["cost"]))
        if not isinstance(flow, Decimal):
            issues.append("flow type")
            continue
        if flow < 0 or flow > cap:
            issues.append("capacity bound")
        balance[u] += flow
        balance[v] -= flow
        cost_terms.append(flow * cost)
        forward = cost + potentials[u] - potentials[v]
        reverse = -cost + potentials[v] - potentials[u]
        if cap - flow > 0 and forward < 0:
            issues.append("forward reduced cost")
        if flow > 0 and reverse < 0:
            issues.append("reverse reduced cost")
    source, sink = index[data["source"]], index[data["sink"]]
    if balance[source] != result["max_flow"]:
        issues.append("source conservation")
    if balance[sink] != -result["max_flow"]:
        issues.append("sink conservation")
    if any(balance[i] != 0 for i in range(len(nodes)) if i not in (source, sink)):
        issues.append("intermediate conservation")
    cost = sum(cost_terms, Decimal(0))
    if cost != result["min_cost"]:
        issues.append("objective recomputation")
    source_side = set(result["source_side"])
    residual_reachable = {source}
    queue = [source]
    for u in queue:
        for edge, flow in zip(edges, flows):
            if edge["u"] == nodes[u] and Decimal(str(edge["capacity"])) - flow > 0:
                v = index[edge["v"]]
                if v not in residual_reachable:
                    residual_reachable.add(v)
                    queue.append(v)
            if edge["v"] == nodes[u] and flow > 0.0:
                v = index[edge["u"]]
                if v not in residual_reachable:
                    residual_reachable.add(v)
                    queue.append(v)
    expected_side = [node for i, node in enumerate(nodes) if i in residual_reachable]
    if result["source_side"] != expected_side:
        issues.append("residual reachable side")
    cut = sum((Decimal(str(e["capacity"])) for e in edges if e["u"] in source_side and e["v"] not in source_side), Decimal(0))
    if cut != result["min_cut_capacity"]:
        issues.append("cut recomputation")
    if result["max_flow"] != cut:
        issues.append("max-flow/min-cut equality")
    return issues


def brute_force_optimum(data):
    nodes = data["nodes"]
    index = {node: i for i, node in enumerate(nodes)}
    edges = data["edges"]
    choices = [range(int(edge["capacity"]) + 1) for edge in edges]
    best_flow, best_cost = -math.inf, math.inf
    for flows in itertools.product(*choices):
        balance = [0] * len(nodes)
        for edge, flow in zip(edges, flows):
            balance[index[edge["u"]]] += flow
            balance[index[edge["v"]]] -= flow
        source, sink = index[data["source"]], index[data["sink"]]
        value = balance[source]
        if balance[sink] != -value or any(balance[i] for i in range(len(nodes)) if i not in (source, sink)):
            continue
        cost = sum(flow * edge["cost"] for edge, flow in zip(edges, flows))
        if value > best_flow or (value == best_flow and cost < best_cost):
            best_flow, best_cost = value, cost
    return best_flow, best_cost


def fixture():
    return {
        "nodes": ["s", "cheap", "dear", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "cheap", "capacity": 2, "cost": 1},
            {"u": "cheap", "v": "t", "capacity": 2, "cost": 0},
            {"u": "s", "v": "dear", "capacity": 2, "cost": 4},
            {"u": "dear", "v": "t", "capacity": 2, "cost": 0},
            {"u": "t", "v": "s", "capacity": 2, "cost": 0},
        ],
    }


def test_optimum_and_complete_primal_dual_certificate():
    '''OPT-01: "`edge_flows` 与输入边一一对应并保持原顺序。" `max_flow` is maximized before `min_cost` is minimized.'''
    data = fixture()
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == 4 and result["min_cost"] == 10
    assert len(result["edge_flows"]) == len(data["edges"])
    assert certificate_issues(data, result) == []


def test_exhaustive_small_networks_match_independent_flow_enumeration():
    '''OPT-02: "`max_flow` 必须是所有可行方案中的最大值；在所有最大流方案中，`min_cost` 必须是最低总成本。"'''
    rng = random.Random(73021)
    for case_id in range(18):
        nodes = ["s", "a", "b", "t"]
        possible = [(u, v) for i, u in enumerate(nodes) for v in nodes[i + 1 :]]
        rng.shuffle(possible)
        selected = possible[: rng.randint(3, 7)]
        edges = [
            {"u": u, "v": v, "capacity": rng.randint(0, 2), "cost": rng.randint(-4, 7)}
            for u, v in selected
        ]
        data = {"nodes": nodes, "edges": edges, "source": "s", "sink": "t"}
        expected_flow, expected_cost = brute_force_optimum(data)
        process, output, leftovers, exists = run(data)
        result = load_result(output)
        assert process.returncode == 0 and exists and leftovers == [], f"case={case_id}"
        assert result["max_flow"] == expected_flow, f"case={case_id}"
        assert result["min_cost"] == expected_cost, f"case={case_id}"
        assert certificate_issues(data, result) == [], f"case={case_id}"


def test_residual_rerouting_finds_a_full_flow():
    '''OPT-03: "`max_flow` 必须是所有可行方案中的最大值" including rerouting prior edge use.'''
    data = {
        "nodes": ["s", "a", "b", "x", "y", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "a", "capacity": 1, "cost": 0},
            {"u": "s", "v": "b", "capacity": 1, "cost": 0},
            {"u": "a", "v": "x", "capacity": 1, "cost": 0},
            {"u": "a", "v": "y", "capacity": 1, "cost": 0},
            {"u": "b", "v": "x", "capacity": 1, "cost": 0},
            {"u": "x", "v": "t", "capacity": 1, "cost": 0},
            {"u": "y", "v": "t", "capacity": 1, "cost": 0},
        ],
    }
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == 2 and result["min_cost"] == 0
    assert certificate_issues(data, result) == []


def test_parallel_edges_keep_separate_costs_and_input_positions():
    '''OPT-04: "边按数组位置区分，因此允许平行边" and `edge_flows` preserves that order.'''
    data = {
        "nodes": ["s", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "t", "capacity": 1, "cost": 9},
            {"u": "s", "v": "t", "capacity": 2, "cost": 2},
            {"u": "s", "v": "t", "capacity": 0, "cost": -100},
        ],
    }
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == 3 and result["min_cost"] == 13
    assert result["edge_flows"] == [1, 2, 0]
    assert certificate_issues(data, result) == []


def test_negative_edge_without_negative_cycle_is_optimized():
    '''OPT-02: "负成本边本身允许" and the least-cost maximum flow is required.'''
    data = {
        "nodes": ["s", "a", "b", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "a", "capacity": 1, "cost": -5},
            {"u": "a", "v": "t", "capacity": 1, "cost": 2},
            {"u": "s", "v": "b", "capacity": 1, "cost": 1},
            {"u": "b", "v": "t", "capacity": 1, "cost": 1},
        ],
    }
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == 2 and result["min_cost"] == -1
    assert certificate_issues(data, result) == []


def test_every_positive_capacity_participates_and_zero_capacity_does_not():
    '''OPT-04: 正的最小结算单位必须参与运量；零容量线路不参与。'''
    data = {
        "nodes": ["s", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "t", "capacity": 0.000001, "cost": -2},
            {"u": "s", "v": "t", "capacity": 0, "cost": -100},
        ],
    }
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == Decimal("0.000001") and result["edge_flows"] == [Decimal("0.000001"), 0]
    assert result["min_cost"] == Decimal("-0.000002000000")
    assert certificate_issues(data, result) == []


def test_unreachable_sink_has_zero_flow_and_valid_cut():
    '''OPT-01: "`source_side` ... 列出从 `source` 出发、可沿正剩余容量到达的全部节点。"'''
    data = {
        "nodes": ["s", "a", "t"],
        "source": "s",
        "sink": "t",
        "edges": [{"u": "s", "v": "a", "capacity": 2, "cost": 3}],
    }
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == 0 and result["min_cost"] == 0
    assert result["edge_flows"] == [0] and result["source_side"] == ["s", "a"]
    assert result["min_cut_capacity"] == 0 and certificate_issues(data, result) == []


def test_rejects_negative_cycle_even_when_disconnected_and_preserves_output():
    '''VALID-01: "检查范围包括所有节点，即使该环与配送源点或交付点断开。"'''
    data = {
        "nodes": ["s", "t", "x", "y"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "t", "capacity": 1, "cost": 0},
            {"u": "x", "v": "y", "capacity": 1, "cost": -2},
            {"u": "y", "v": "x", "capacity": 1, "cost": 1},
        ],
    }
    process, output, leftovers, exists = run(data)
    assert process.returncode != 0 and output is None and leftovers == [] and not exists
    sentinel = b"previous-plan\x00"
    process, output, leftovers, exists = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and leftovers == [] and exists


def test_rejects_reachable_negative_cost_self_loop():
    '''VALID-01: "自环若容量为正且成本为负，属于应拒收的负成本环。"'''
    data = {
        "nodes": ["s", "a", "t"],
        "source": "s",
        "sink": "t",
        "edges": [
            {"u": "s", "v": "a", "capacity": 1, "cost": 0},
            {"u": "a", "v": "a", "capacity": 1, "cost": -0.25},
            {"u": "a", "v": "t", "capacity": 1, "cost": 0},
        ],
    }
    sentinel = b"keep-old-plan"
    process, output, leftovers, exists = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and leftovers == [] and exists


def test_rejects_duplicate_json_keys_without_publication():
    '''VALID-02: "任意 JSON 对象出现重复键...时，输入无效。"'''
    raw = '{"nodes":["s","t"],"edges":[],"source":"s","sink":"t","source":"t"}'
    process, output, leftovers, exists = run({}, raw=raw)
    assert process.returncode != 0 and output is None and leftovers == [] and not exists


def test_late_invalid_edge_preserves_sentinel_and_leaves_no_temporary_file():
    '''VALID-03: "拒收或发布失败不得创建或改动目标文件，也不得留下临时产物。"'''
    data = fixture()
    data["edges"].append({"u": "missing", "v": "t", "capacity": 1, "cost": 0})
    sentinel = b"old-ledger-version"
    process, output, leftovers, exists = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and leftovers == [] and exists
    process, output, leftovers, exists = run(data)
    assert process.returncode != 0 and output is None and leftovers == [] and not exists


def test_atomic_replace_failure_preserves_old_plan():
    '''VALID-03: "发布失败不得创建或改动目标文件，也不得留下临时产物。"'''
    import importlib.util

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        input_path, output_path = root / "input.json", root / "output.json"
        input_path.write_text(json.dumps(fixture()), encoding="utf-8")
        sentinel = b"prior-plan\x00"
        output_path.write_bytes(sentinel)
        spec = importlib.util.spec_from_file_location("candidate_solver", APP)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = module.os.replace
        module.os.replace = lambda _src, _dst: (_ for _ in ()).throw(OSError("injected replace failure"))
        old_argv = sys.argv
        sys.argv = [APP, str(input_path), str(output_path)]
        try:
            status = module.main()
        finally:
            sys.argv = old_argv
            module.os.replace = original
        assert status != 0 and output_path.read_bytes() == sentinel
        assert sorted(p.name for p in root.iterdir()) == ["input.json", "output.json"]


def test_identical_runs_produce_semantically_identical_results():
    '''VALID-04: "相同输入的成功运行必须产生相同 JSON 结果。"'''
    data = fixture()
    first, first_bytes, first_leftovers, first_exists = run(data)
    second, second_bytes, second_leftovers, second_exists = run(data)
    assert first.returncode == second.returncode == 0
    assert first_exists and second_exists and first_leftovers == second_leftovers == []
    assert first_bytes == second_bytes


def test_public_scale_finishes_and_returns_a_checkable_optimum():
    '''PERF-05: "合法输入可达公开规模时，程序须在 20 秒内完成。"'''
    layers = [[f"L{level:04d}{label}" for label in "AB"] for level in range(1023)]
    nodes = ["S"] + [node for layer in layers for node in layer] + ["T"]
    edges = [{"u": "S", "v": node, "capacity": 1, "cost": 0} for node in layers[0]]
    for level, (previous, current) in enumerate(zip(layers, layers[1:])):
        cost = -1 if (level + 1) % 4 == 0 else 0
        edges.extend(
            {"u": u, "v": v, "capacity": 1, "cost": cost}
            for u in previous
            for v in current
            for _ in range(4)
        )
    edges.extend({"u": node, "v": "T", "capacity": 1, "cost": 0} for node in layers[-1] for _ in range(15))
    assert len(nodes) == 2048 and len(edges) == 16384
    data = {"nodes": nodes, "edges": list(reversed(edges)), "source": "S", "sink": "T"}
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        input_path, output_path = root / "input.json", root / "output.json"
        input_path.write_text(json.dumps(data), encoding="utf-8")
        started = time.monotonic()
        process = subprocess.run([sys.executable, APP, str(input_path), str(output_path)], capture_output=True, timeout=20)
        elapsed = time.monotonic() - started
        assert process.returncode == 0 and elapsed < 20 and output_path.exists()
        result = load_result(output_path.read_bytes())
        assert result["max_flow"] == 2 and result["min_cost"] == -510
        assert result["min_cut_capacity"] == 2 and result["source_side"] == ["S"]
        assert certificate_issues(data, result) == []


def test_exact_ledger_keeps_a_minimum_unit_after_large_capacity_aggregation():
    '''NUM-06: 运量按十进制定值解释，汇总不得吞掉最小结算单位。'''
    edges = [{"u": "s", "v": "t", "capacity": 1_000_000_000, "cost": 0} for _ in range(10)]
    edges.append({"u": "s", "v": "t", "capacity": 0.000001, "cost": 0})
    data = {"nodes": ["s", "t"], "edges": edges, "source": "s", "sink": "t"}
    process, output, leftovers, exists = run(data)
    result = load_result(output)
    expected = Decimal("10000000000.000001")
    assert process.returncode == 0 and exists and leftovers == []
    assert result["max_flow"] == expected and result["min_cut_capacity"] == expected
    assert result["edge_flows"][-1] == Decimal("0.000001")
    assert certificate_issues(data, result) == []


def test_rejects_more_than_six_decimal_places_without_publication():
    '''NUM-06: 超出公开定点精度的运量或单价必须拒收。'''
    data = {"nodes": ["s", "t"], "edges": [{"u": "s", "v": "t", "capacity": 0.0000001, "cost": 0}], "source": "s", "sink": "t"}
    sentinel = b"prior-exact-ledger"
    process, output, leftovers, exists = run(data, sentinel=sentinel)
    assert process.returncode != 0 and output == sentinel and leftovers == [] and exists
