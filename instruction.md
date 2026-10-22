# Capacitated network certificates

Implement `/app/solve.py` so that it reads UTF-8 JSON from the first command-line path and atomically writes UTF-8 JSON to the second path.

The input object has exactly `nodes`, `edges`, `source`, and `sink`. `nodes` is a non-empty array of unique non-empty strings. `source` and `sink` are distinct node names. Each edge has exactly `u`, `v`, `capacity`, and `cost`; endpoints are existing nodes, capacities are finite numbers greater than or equal to zero, costs are finite numbers, and parallel edges and self-loops are allowed. A negative-cost cycle reachable from `source` is invalid. All numbers must be finite and booleans are not numbers.

Return an object with exactly `max_flow`, `min_cut_capacity`, `source_side`, `shortest_path_cost`, and `shortest_path`. `max_flow` is the maximum feasible flow from `source` to `sink`, using each edge separately. `min_cut_capacity` is the capacity of the cut induced by `source_side`; the two values must agree within `1e-9` relative error and `1e-12` absolute error. `source_side` contains every node reachable from `source` by positive residual capacity after the reported flow and is sorted in the input node order.

`shortest_path` is a node sequence from `source` to `sink` with no repeated node and `shortest_path_cost` is the sum of the listed original-edge costs. If the sink is unreachable, use `null` for both. When multiple shortest paths have the same cost, choose the lexicographically smallest node sequence. Negative edge costs are valid when the input has no reachable negative-cost cycle. Self-loops must not change either certificate.

This contract has three independent correctness obligations: (1) resource accounting must preserve the max-flow/min-cut invariant for a directed multigraph, including parallel-edge and zero-capacity/self-loop boundaries; (2) shortest-path certification must handle signed costs, reachable-cycle rejection, unreachable terminals, and deterministic tie-breaking; and (3) the published certificate must be a stable, permutation-aware projection whose repeated valid runs are byte-stable and whose rejected runs never expose a partial result. Satisfying only one obligation is incomplete.

Invalid input, a reachable negative-cost cycle, a disagreement between the certificates, or any internal failure must exit nonzero and must not create or modify the destination. Valid output is published only after all validation and computation have completed.
