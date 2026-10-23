# 园区配送网络的最低成本最大供给计划

园区夜间交接时，需要核清一批物资最多能送到多少，以及在送到最大数量的前提下总运输成本最低的调度方案。请修复 `/app/solve.py`。程序从第一个命令行参数读取 UTF-8 JSON，并将结果写到第二个参数指定的文件；成功发布完整结果，遇到无效输入或计算/写入错误则以非零状态退出。

输入只能包含 `nodes`、`edges`、`source`、`sink`。`nodes` 是 2 至 2,048 个互不重复的非空字符串；`source` 和 `sink` 是其中不同的节点。每条 `edges` 记录只能包含 `u`、`v`、`capacity`、`cost`：端点必须存在，`capacity` 为 `[0, 1e9]` 内有限数，`cost` 为 `[-1e6, 1e6]` 内有限数。边按数组位置区分，因此允许平行边和自环。任意 JSON 对象出现重复键、缺键、多余键、错误类型、布尔数值或非有限数时，输入无效。边数最多为 16,384。

本批台账不接受任何由正容量边组成的负总成本有向环；检查范围包括所有节点，即使该环与配送源点或交付点断开。零容量边不参与成环、供给或成本计算。负成本边本身允许；自环若容量为正且成本为负，属于应拒收的负成本环。

输出只能包含 `max_flow`、`min_cost`、`edge_flows`、`min_cut_capacity`、`source_side`、`node_potentials`。`edge_flows` 与输入边一一对应并保持原顺序。每个流量不得小于零或超过对应容量；对 `source` 的净流出为 `max_flow`，对 `sink` 的净流入为 `max_flow`，其他节点流量守恒。`min_cost` 是所有边的 `edge_flow * cost` 之和。`max_flow` 必须是所有可行方案中的最大值；在所有最大流方案中，`min_cost` 必须是最低总成本。

`source_side` 按输入节点顺序列出从 `source` 出发、可沿正剩余容量到达的全部节点。正向剩余容量为 `capacity - edge_flow`，反向剩余容量为 `edge_flow`；`min_cut_capacity` 是从 `source_side` 指向其补集的原始边容量之和，并须与 `max_flow` 相等。`node_potentials` 与 `nodes` 一一对应。对每条边，若正向剩余容量大于零，则 `cost + potential[u] - potential[v]` 不得小于其数值容差；若反向剩余容量大于零，则 `-cost + potential[v] - potential[u]` 不得小于其数值容差。这些字段共同构成可独立检查的可行性和最优性证书。

流量、容量守恒、割容量和总成本的比较采用 `abs(a-b) <= 1e-12 + 1e-9 * max(abs(a), abs(b))`。对偶约化成本 `r` 的容差为 `1e-9 * max(1, abs(cost), abs(potential[u]), abs(potential[v]))`。不得把严格正容量或正剩余容量按固定 epsilon 当作零。相同输入的成功运行必须产生相同 JSON 结果；拒收或发布失败不得创建或改动目标文件，也不得留下临时产物。

合法输入可达公开规模时，程序须在 20 秒内完成。测试环境只提供随包 Python 运行时和离线测试依赖，不提供网络服务。
