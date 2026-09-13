# DeepScout

**基于 LangGraph + DeepAgents 的生产级多智能体深度研究系统。**

DeepScout 参考 LangChain `deepagents/examples/deep_research` 的架构思路，但将高层研究编排显式实现为 LangGraph 工作流：

- 结构化查询分析；
- 依赖感知 Research DAG 规划；
- 确定性的 DAG 校验；
- 基于 LangGraph `Send` 的动态并行派发；
- 基于 DeepAgents 的自主研究 Worker；
- 结构化 `TaskResult` 与 `Evidence` 输出；
- Critic 驱动的信息缺口分析与有界重规划；
- 仅基于已收集证据生成最终报告。

> 当前版本为 **v0.3.0 / Phase 3 第一批**：在 Research DAG、Evidence/Citation 与预算控制之上，
> 新增统一 Tool Registry、MCP 工具接入、可注入 LangGraph Checkpointer 和节点级 RetryPolicy。
> HITL、FastAPI/SSE 与更完整的生产部署能力将在 Phase 3 后续批次继续实现。

## 系统架构

```text
START
  |
  v
analyze_query
  |
  v
planner <----------------------------------+
  |                                        |
  v                                        |
supervisor + budget                        |
  |                                        |
  +---- ready tasks ----+                  |
  |                     |                  |
  v                     v                  |
researcher ...      researcher             |
  |                     |                  |
  +----------+----------+                  |
             |                             |
             v                             |
        supervisor                         |
             |                             |
        DAG exhausted                      |
             v                             |
      evidence_manager                     |
             |                             |
             v                             |
           critic                          |
          /      \                         |
      gap /        \ sufficient            |
        v           v                      |
     planner       writer                  |
                     |                     |
                     v                     |
             citation_verifier             |
                 /       \                 |
          evidence gap     supported       |
               |               |           |
               +---------------+---------->END
```

核心设计原则是：

> **LangGraph 负责确定性编排，DeepAgents 负责局部自主研究。**

这样可以避免把任务依赖、失败恢复边界和全局控制流完全交给 LLM Prompt 自行决定。

## 上游基线与项目归属
参考项目：

- https://github.com/langchain-ai/deepagents
- `examples/deep_research`

Phase 1 固定使用 `deepagents==0.7.13`，以保证实验结果可复现。

DeepScout 是独立实现，不会把 DeepAgents 上游能力描述成自己的原创工作。详细归属与基线说明见 [`docs/baseline.md`](docs/baseline.md)。

## Phase 1 已实现能力

### 1. 结构化 Research DAG

Planner 输出带类型的研究任务，DeepScout 会拒绝重复任务 ID、未知依赖、自依赖和循环依赖。

### 2. 依赖感知并行调度

Supervisor 不直接修改任务状态，而是根据不可变 Plan 和 append-only 的结果集合推导 ready tasks。相互独立的任务通过 LangGraph `Send` 并行派发。

### 3. DeepAgents Research Worker

每个研究任务都交给缓存后的 DeepAgent 执行，并显式配置模型、Web Search 工具、研究 Prompt 和结构化响应 Schema。

### 4. Critic 与有界重规划

当前 DAG 执行完毕后，Critic 会检查研究覆盖度、缺失维度、冲突信息与失败任务；已有任务保持不可变，只允许新增任务 ID，并通过 `DEEPSCOUT_MAX_REPLANS` 限制重规划次数。


## Phase 2 已实现能力

### 1. Evidence Manager

Researcher 返回的原始 Evidence 会先经过确定性处理：规范化 URL、移除常见追踪参数、计算内容 SHA-256 指纹、按 URL/内容双重去重，并生成稳定的 `evidence_id`。Researcher 提取的原子化 claims 会进一步形成 `Claim → Evidence IDs` 映射。

### 2. Citation Verifier

Writer 生成报告后，Citation Verifier 使用结构化 Schema 对事实性 claim 做 `supported / partial / unsupported` 判断，并输出 coverage、unsupported claims 与是否需要继续研究。只有引用缺口会实质影响答案质量时，才触发新的有界 Re-plan。

### 3. Research Worker Budget Manager

Supervisor 会同时考虑 DAG frontier、并发上限与剩余预算。当前硬约束包括研究任务数、重规划次数、Evidence 数量与 Web Search 次数；并记录 Researcher 的模型 token usage（Provider 提供 usage metadata 时）与 Worker 耗时。并行任务会在派发时分配独立 `search_quota`，额度耗尽后 `web_search` 不再访问 Tavily。

### 4. 可复现的控制边界

Evidence 去重、ID 生成、Claim-Evidence 映射和预算计算均为确定性逻辑；LLM 主要负责局部研究、Critic、Writer 与引用语义判断。这样后续可以分别对 DAG、Evidence、Citation 和 Budget 做消融实验，而不是把全部行为隐藏在 Prompt 中。

## Phase 3 第一批已实现能力

### 1. MCP Tool Registry

Researcher 不再直接依赖固定工具列表，而是通过统一 `ToolRegistry` 聚合内置工具和 MCP 工具。MCP 配置使用 `DEEPSCOUT_MCP_SERVERS` JSON 注入，并支持工具名前缀和名称冲突检测；Research Agent 缓存会随着 MCP 配置指纹变化自动失效。

### 2. Durable Checkpoint 基础设施

`build_graph(checkpointer=...)` 支持注入任意 LangGraph Checkpointer。本地开发可使用 `InMemorySaver`；生产持久化提供 `AsyncPostgresSaver` 工厂，并通过 `postgres` optional extra 安装 PostgreSQL 依赖。

### 3. Retry 与故障隔离

Analyzer、Planner、Critic、Writer 和 Citation Verifier 使用 LangGraph 原生 `RetryPolicy` 对瞬时 Provider/网络故障做指数退避。Researcher 保持任务级故障隔离：单个研究任务失败会形成结构化 `TaskResult(status="failed")`，不会直接破坏整个 DAG。

### 4. Checkpoint CLI

命令行支持 `--checkpoint none|memory|postgres` 与 `--thread-id`。PostgreSQL DSN 可以通过 `--postgres-dsn` 或 `DEEPSCOUT_POSTGRES_DSN` 提供。

## 安装与环境

要求：Python 3.11+、`uv`、至少一个受支持的 LLM Provider API Key，以及 Tavily API Key。

```bash
git clone https://github.com/Epsilon-Alpha-Beta/deepscout.git
cd deepscout
cp .env.example .env
uv sync --group dev

# 如需 PostgreSQL durable checkpoint
uv sync --group dev --extra postgres
```
运行测试与静态检查：

```bash
uv run pytest
uv run ruff check .
```

运行研究任务：

```bash
uv run python scripts/run_research.py \
  "比较 LangGraph、AutoGen 和 CrewAI 在生产级多智能体系统中的差异。"

# 开启进程内 checkpoint
uv run python scripts/run_research.py --checkpoint memory --thread-id demo-001 \
  "研究长运行 Agent 的故障恢复机制。"
```

## 当前验证状态

Phase 3 第一批当前代码已在项目隔离环境中完成本地验证：

- DeepScout 专属 Python：3.11.16；
- 系统 Python：保持 3.10.12，不受影响；
- `pytest`：29/29 通过；
- `ruff check .`：通过；
- LangGraph：可成功编译为 `CompiledStateGraph`；
- GitHub Actions：Install、Ruff、Tests 全部通过。

## 后续路线

**Phase 3 后续**：HITL、FastAPI + SSE、生产级 PostgreSQL 联调与端到端故障恢复测试。

**Phase 4**：Benchmark 数据集、轨迹级评测、消融实验、成本/延迟/质量指标与可视化。
