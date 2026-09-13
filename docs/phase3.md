# Phase 3：工具接入与耐久执行基础设施

本阶段第一批目标是把 DeepScout 从“单一 Web 工具 + 无持久化执行”升级为可扩展的工具层和可恢复的 LangGraph 执行基础设施。

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

## 当前边界

本批次只完成耐久执行基础设施，不声称已经完成生产 PostgreSQL 联调。
仓库测试覆盖 MCP Registry、工具名冲突、Memory Checkpointer 注入和 RetryPolicy；
真实 MCP Server、真实 PostgreSQL 实例和 Provider 故障注入将在后续集成测试中验证。
