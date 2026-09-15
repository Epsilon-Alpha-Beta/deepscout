# Phase 4：Benchmark 与轨迹级评测

Phase 4 分三批推进：第一批建立可复现 Benchmark/trajectory 基座；第二批加入可复现 Ablation Matrix；第三批加入重复实验、描述统计、bootstrap 置信区间和 CSV/Markdown/SVG 报告。当前仍不会在缺少真实 Provider/Tavily 凭据时伪造质量、消融或统计显著性结论。

## Benchmark Corpus

`benchmarks/corpora/core.json` 当前包含 6 个核心研究 Case，覆盖：

- 多智能体框架比较；
- MCP 传输模式；
- durable execution；
- Agent 可观测性；
- Redis 分布式限流；
- Human-in-the-loop 工作流。

每个 Case 包含 category、difficulty、tags、expected keywords 和机器可校验 expectations。`case_id` 在同一 Corpus 内必须唯一。

## Trajectory Recorder

Benchmark runner 使用 LangGraph `stream_mode=["updates", "values"]` 同时获取节点更新与最终状态。轨迹只记录节点名、相对耗时和输出字段名，不持久化模型正文、Evidence 正文或 API 凭据。

## 指标体系

当前指标直接复用 DeepScout 运行状态：

- 轨迹：node visits、total node events、replan count；
- 任务：task count、task success rate；
- 证据：evidence count、unique source hosts、source diversity、平均 relevance；
- 引用：citation coverage、unsupported claims；
- 资源：search calls、research tokens、worker seconds、wall seconds；
- 输出：final report chars、expected-keyword recall；
- 成本：可选 model/search 单价估算。

`quality_proxy_score` 是 citation、task success、source diversity、relevance 与 keyword recall 的透明工程代理指标，只用于版本/消融的相对比较，不等同于人工事实正确率或学术意义上的最终质量评分。

若未显式提供 token/search 价格，美元成本字段保持 `null`，不会使用猜测价格。当前 token 成本只基于 `TaskResult.model_tokens`（Research Worker 已跟踪 token），尚未覆盖 Analyzer/Planner/Writer 等所有 LLM 节点，因此字段命名为 `tracked cost`，不能解释为完整账单成本。

## 运行方式

只校验 Corpus，不调用任何外部 Provider：

```bash
uv run python scripts/run_benchmark.py --validate-only
```

真实 Benchmark：

```bash
uv run python scripts/run_benchmark.py \
  --corpus benchmarks/corpora/core.json \
  --output-dir benchmark-results/latest
```

可选成本参数：

```bash
--research-token-usd-per-million <price>
--search-usd-per-1000-calls <price>
```

输出同时包含 `report.json` 与 `report.md`。Corpus 默认顺序执行，避免并发噪声污染 wall-time 对比。


## 第二批：Ablation Matrix

`benchmarks/ablations/core.json` 定义 6 个 profile：

| Profile | 变化 | 目的 |
| --- | --- | --- |
| `full` | 完整默认配置 | baseline |
| `no-replan` | `max_replans=0` | 测量迭代补充研究的贡献 |
| `no-citation-feedback` | Citation Verifier 仍测量，但不触发 Planner | 避免删除测量仪器导致 citation 指标失去同口径 |
| `no-evidence-dedup` | 保留重复 Evidence | 测量 URL/内容指纹去重价值 |
| `low-budget` | 收紧 task/search/token/worker-time/evidence 预算 | 观察质量—资源 trade-off |
| `serial-research` | `max_concurrency=1` | 观察并发对 wall-time/结果的影响 |

Settings override 使用 `ContextVar`，会传播到 asyncio 子任务，并在 profile 结束后自动恢复，不通过进程级环境变量临时改写实验配置。结构性变化由 `GraphOptions` 显式传入 `build_graph()`。

Ablation runner 按 profile **顺序执行**，每个 profile 内仍允许 Research Worker 按其并发上限运行。输出包括每个 profile 的完整 Benchmark report，以及相对 `full` baseline 的：pass rate、quality proxy、citation coverage、source diversity、replans/case、evidence/case、searches/case、research tokens/case、wall-time/case 和 tracked cost/case delta。

只校验矩阵和 Corpus：

```bash
uv run python scripts/run_ablation.py --validate-only
```

真实运行（完整矩阵是 6 profiles × 6 cases = 36 次研究任务）：

```bash
uv run python scripts/run_ablation.py \
  --corpus benchmarks/corpora/core.json \
  --matrix benchmarks/ablations/core.json \
  --output-dir benchmark-results/ablation-latest
```

可先用 `--limit 1` 做低成本 smoke。实验命令只有在某个 run `error/interrupted` 时返回非零；某个消融 profile 未达到 expectation 仍属于有效实验结果，不会被误判为程序执行失败。

## 第三批：重复实验与统计

`scripts/run_repeated_ablation.py` 在同一个 profile/case 上执行多次 repetition，并保留每个原始 `BenchmarkRunResult`。默认执行顺序采用 `rotate`：每轮轮转 profile 起始位置，减少固定 profile 总是先跑或后跑造成的时间漂移偏差；也可显式选择 `fixed`。

统计层计算 `mean`、sample `std`、`median`、`p50`、`p95`。均值置信区间默认使用 95% percentile bootstrap；默认 2000 次 resample，并使用稳定 seed 派生每个 scope/metric 的 bootstrap seed，因此同一输入可复现。样本数为 1 时 CI 退化为该观测值。

profile 与 baseline 的 delta 不使用“两个总体均值直接相减”，而是先按 `(repetition, case)` 配对，仅当二者都 completed 时计算 profile−baseline，再对配对差值做同样的分布统计。error/interrupted 计入 attempted/error/interrupted/completion rate，但不会以 0 值进入数值统计。

输出结构：

```text
benchmark-results/repeated-ablation-latest/
├── repeated.json
├── report.md
├── runs.csv
├── statistics.csv
├── deltas.csv
└── charts/
    ├── quality_proxy_score.svg
    ├── citation_coverage.svg
    ├── search_calls.svg
    ├── research_tokens.svg
    ├── wall_seconds.svg
    ├── delta_quality_proxy_score.svg
    ├── delta_search_calls.svg
    └── delta_wall_seconds.svg
```

`statistics.csv` 与 `deltas.csv` 都显式包含 `count / mean / std / median / p50 / p95 / ci_low / ci_high / confidence_level`。Markdown 中也展示 profile 级完整分布，不要求读者必须打开 CSV。SVG 由标准库直接生成，不增加 matplotlib 等运行时依赖。

默认完整实验是 `6 profiles × 6 cases × 5 repetitions = 180 runs`，成本可能很高。默认 5 次更适合工程 smoke；真实 LLM 的方差、p95 与 CI 若要用于正式结论，应提高 repetition 数并结合预算评估。profile 级 pooled statistics 是跨 case 的描述性汇总，严格比较时应优先检查 `profile_case_statistics` 与同一 `(repetition, case)` 的配对 delta。正式跑真实 Provider 前建议先执行：

```bash
uv run python scripts/run_repeated_ablation.py --validate-only --repetitions 5
uv run python scripts/run_repeated_ablation.py --limit 1 --repetitions 2
```

## 当前验证边界

第一批使用 synthetic final-state 与 fake streamed graph 验证指标和轨迹；第二批使用 synthetic profile graph 验证 Settings/Graph 消融语义；第三批使用可控重复 synthetic graph 验证 profile 顺序轮转、失败样本语义、mean/std/median/p50/p95、确定性 bootstrap CI、配对 delta、CSV/Markdown/SVG 输出。这些 fixture 只证明实验基础设施正确，不代表真实 Provider 的 Benchmark/Ablation/统计成绩。

真实 Provider + Tavily 仍因服务器缺少凭据而阻塞，因此 `core.json` 当前只有 Case/阈值定义，没有提交伪造的真实结果文件。

## 后续批次

真实 Provider 凭据可用后，优先用同一套 repeated runner 生成真实重复实验数据，再补充跨 run 显著性检验、真实 Provider 完整成本、人工或外部事实正确率评审与更完整可视化。对于 citation 消融继续保持“保留 verifier 测量、只关闭 feedback”的实验设计，避免测量口径随处理组变化。
