# Reference rationale

The reference validates the complete public schema before doing any work and publishes through a temporary file followed by an atomic replacement. It keeps parallel edges as separate residual arcs, computes a maximum flow with a residual network, derives the reachable-side cut from the final residual capacities, and checks the max-flow/min-cut equality. It computes shortest paths with repeated relaxation over the original multigraph, detects reachable negative cycles, and reconstructs the lexicographically smallest minimum-cost simple path by dynamic programming over cost and path tuples.

The independent behavior axes are:

- `FLOW-01`: parallel-edge residual accounting and the max-flow/min-cut invariant (`test_parallel_edges_and_cut_certificate`, `test_self_loop_is_neutral_to_flow_and_path`).
- `PATH-02`: negative costs, unreachable sinks, and deterministic tie-breaking (`test_negative_cost_path_and_lexicographic_tie_break`, `test_unreachable_sink_returns_null_certificates`).
- `VALID-03`: complete schema validation and atomic rejection, including late invalid records and reachable negative cycles (`test_rejects_negative_cycle_atomically`, `test_late_invalid_edge_preserves_sentinel`).
- `CERT-04`: permutation invariance, node-order projection, and numeric conservation (`test_node_order_only_changes_sorted_projection`, `test_flow_cut_values_match_on_disconnected_components`).

Expected values are independently checked by exhaustive simple-path enumeration on small graphs and a separate cut enumeration, rather than by reusing the implementation's residual state.

The implementation also has a deliberately explicit error-handling path: every malformed record is rejected before publication, temporary files are removed, and a pre-existing destination is preserved. Its set and interval reasoning is visible in the source-side reachability set, cut-edge partition, and simple-path vertex set. Numeric precision is controlled by finite-number checks and documented absolute/relative tolerances. Re-running the same input is idempotent because publication is staged and replaced only after the complete computation succeeds; a failed second run cannot leave a checkpoint or partial ledger.
