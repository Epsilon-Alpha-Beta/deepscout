# Phase 3：工具接入与耐久执行基础设施

Phase 3 分两批推进：第一批完成 MCP Tool Registry、Checkpoint 与 Retry 基础设施；第二批继续加入 HITL、FastAPI/SSE，并验证 PostgreSQL 跨进程耐久恢复。

## MCP Tool Registry

`ToolRegistry` 同时加载内置工具和 `langchain-mcp-adapters` 提供的 MCP 工具。MCP Server 通过 `DEEPSCOUT_MCP_SERVERS` JSON 配置，不把具体 Server 写死在代码中。

设计约束：

- 内置 `web_search` 始终可用；
- MCP 工具按运行配置动态加载；
- 可开启 Server 名称前缀避免同名工具冲突；
- Registry 会再次检查最终工具名唯一性；
- Research Agent 缓存键包含 MCP 配置指纹，配置改变后不会复用旧 Agent。

当前没有在仓库中内置或提交任何真实 MCP 凭据。

## Checkpoint 与耐久执行

`build_graph(checkpointer=...)` 可以注入任意 LangGraph `BaseCheckpointSaver`。本地调试使用 `InMemorySaver`；生产持久化通过可选依赖 `postgres` 提供 `AsyncPostgresSaver`。

PostgreSQL extra 使用 `psycopg[binary]`，避免要求服务器预装系统 `libpq`。首次连接时工厂会执行 `setup()` 创建 LangGraph 所需表结构。

```bash
uv sync --group dev --extra postgres
```

CLI 支持：

```bash
uv run python scripts/run_research.py --checkpoint memory --thread-id demo-001 "..."
uv run python scripts/run_research.py --checkpoint postgres --thread-id job-001 "..."
```

生产环境的 DSN 不写入仓库，应通过环境变量或 Secret Manager 注入。

## 节点级 RetryPolicy

Analyzer、Planner、Critic、Writer 与 Citation Verifier 使用 LangGraph 原生 `RetryPolicy`。
默认策略只针对框架判定为可重试的瞬时故障执行指数退避，不会把所有 Python 异常都机械重试。
重试次数与间隔通过 `DEEPSCOUT_NODE_RETRY_*` 配置。

## HITL 人工审核

最终报告通过 Citation Verifier 后进入 Human Review Gate。`require_approval=false` 时自动批准；开启审批时使用 LangGraph `interrupt()` 暂停，并要求调用方使用同一 `thread_id` 和 `Command(resume=...)` 恢复。人工选择 `revise` 时，反馈会转换为新的 Critique，并在预算允许时重新进入 Planner。

## FastAPI + SSE

服务层提供 `/v1/research`、`/v1/research/stream`、`/resume`、`/resume/stream` 和 thread state 查询接口。SSE 事件包括 `metadata`、`update`、`interrupt`、`paused` 与 `done`。默认使用 Memory Checkpointer，生产环境可切换 PostgreSQL。

## PostgreSQL 真实恢复验证

使用 Podman 启动隔离 PostgreSQL 16 实例并进行两个独立 Python 进程的恢复测试：进程 A 在 Human Review 处持久化 interrupt 后退出；进程 B 重新连接数据库，根据相同 `thread_id` 读取 checkpoint 并执行 `Command(resume={"action": "approve"})`，最终恢复到 END。

同一流程在 `LANGGRAPH_STRICT_MSGPACK=true` 下再次通过。Checkpoint 工厂使用显式 `JsonPlusSerializer` allowlist，仅允许 DeepScout 状态模型反序列化，不依赖宽松的“允许所有类型”策略。

## 当前边界

当前已完成本地/隔离 PostgreSQL 实例上的耐久恢复与 FastAPI/HITL 集成验证。尚未完成真实 MCP Server 联调和真实 LLM Provider + Tavily 的完整端到端研究，因此不会把这些能力标记为已验证。
