# Phase 4：Benchmark 与轨迹级评测

Phase 4 第一批目标是建立**可复现、可审计、与 Provider 解耦**的评测基座，而不是在缺少真实 Provider/Tavily 凭据时伪造质量分数。

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

## 当前验证边界

本批次通过 synthetic final-state 与 fake streamed graph 验证指标计算、轨迹隐私、阈值判定、异常归档和 JSON/Markdown 报告生成。该 fixture 只证明评测基础设施正确，不代表真实 Provider 的 Benchmark 成绩。

真实 Provider + Tavily 仍因服务器缺少凭据而阻塞，因此 `core.json` 当前只有 Case/阈值定义，没有提交伪造的真实结果文件。

## 后续批次

下一批将加入可配置消融矩阵，例如关闭 replan、citation verifier、evidence dedup 或改变并发/预算，并在同一 Corpus 上比较质量代理、搜索量、token、延迟和成本。真实 Provider 凭据可用后，再执行多次重复实验与方差统计。
