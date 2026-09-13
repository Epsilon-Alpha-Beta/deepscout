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

> Phase 1 聚焦 Agent 编排本身。持久化、MCP 路由、引用验证、预算控制、
> FastAPI/SSE、PostgreSQL、Redis 以及完整评测体系将在后续阶段逐步实现。

## 系统架构

```text
START
  |
  v
analyze_query
  |
  v
planner  <------------------------+
  |                               |
  v                               |
supervisor                        |
  |
  +---- ready tasks ----+         |
  |                     |         |
  v                     v         |
researcher ...      researcher    |
  |                     |         |
  +----------+----------+         |
             |                    |
             v                    |
         supervisor               |
             |                    |
       DAG exhausted              |
             v                    |
           critic                 |
          /      \                |
     re-plan      sufficient -----+
        |              |
        +--------------+
                       v
                     writer
                       |
                       v
                      END
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

## 安装与环境

要求：Python 3.11+、`uv`、至少一个受支持的 LLM Provider API Key，以及 Tavily API Key。

```bash
git clone https://github.com/Epsilon-Alpha-Beta/deepscout.git
cd deepscout
cp .env.example .env
uv sync --group dev
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
```

## 当前验证状态

Phase 1 已在项目隔离环境中完成验证：

- DeepScout 专属 Python：3.11.16；
- 系统 Python：保持 3.10.12，不受影响；
- `pytest`：11/11 通过；
- `ruff check .`：通过；
- LangGraph：可成功编译为 `CompiledStateGraph`；
- GitHub Actions：Install、Ruff、Tests 全部通过。

## 后续路线

**Phase 2**：Evidence Manager、来源规范化与去重、Claim-Evidence 映射、Citation Verifier、Budget Manager。

**Phase 3**：MCP Tool Registry、PostgreSQL checkpoint、重试与故障恢复、HITL、FastAPI + SSE。

**Phase 4**：Benchmark 数据集、轨迹级评测、消融实验、成本/延迟/质量指标与可视化。
