# Phase 3：工具接入与耐久执行基础设施

Phase 3 分三批推进：第一批完成 MCP Tool Registry、Checkpoint 与 Retry 基础设施；第二批加入 HITL、FastAPI/SSE 并验证 PostgreSQL 跨进程耐久恢复；第三批补齐真实 MCP 协议联调、服务安全边界、可观测性与容器化部署。

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

## 第三批：真实 MCP 与生产硬化

真实 MCP 联调不再使用 FakeClient：仓库内 FastMCP 测试服务分别通过 stdio 与 Streamable HTTP 启动，`MultiServerMCPClient` 已真实完成工具发现和调用。

API 支持共享凭据认证、caller-scoped 滑动窗口限流、`X-Request-ID`、JSON access log 与 Prometheus metrics。共享凭据启用后 `/metrics` 同样进入保护边界。当前限流状态保存在单进程内存中，多 worker/多副本部署需要 Redis、API Gateway 等共享后端。

Docker 镜像使用非 root UID 10001，默认绑定 `0.0.0.0:8000` 并携带 HEALTHCHECK。已真实完成镜像构建和容器 runtime smoke；Compose 文件完成 YAML 与关键依赖字段校验，但当前服务器没有 Compose frontend，因此不声称完成 Compose runtime 联调。

## 真实 Provider E2E 状态

`scripts/check_live_e2e.py` 会检测当前模型对应的 Provider Key 与 Tavily Key，并运行低预算完整 Research Graph smoke。当前服务器缺少 Anthropic 与 Tavily 凭据，实际执行结果为 `blocked_missing_credentials`；因此 Provider + Tavily E2E 仍不是 passed。

## 当前边界

当前已完成 PostgreSQL 耐久恢复、FastAPI/HITL、真实 MCP stdio/Streamable HTTP、认证/限流/Prometheus 和容器 runtime 验证。真实 LLM Provider + Tavily 完整端到端研究仍因服务器缺少所需凭据而阻塞。
