# Phase 3：工具接入与耐久执行基础设施

Phase 3 分四批推进：第一批完成 MCP Tool Registry、Checkpoint 与 Retry 基础设施；第二批加入 HITL、FastAPI/SSE 并验证 PostgreSQL 跨进程耐久恢复；第三批补齐真实 MCP 协议联调、API 安全边界、Prometheus/结构化日志与容器化部署；第四批加入 Redis 共享限流、readiness、OpenTelemetry 与可复现 Docker 依赖锁。

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

API 支持共享凭据认证、caller-scoped 进程内滑动窗口限流、`X-Request-ID`、JSON access log 与 Prometheus metrics。共享凭据启用后 `/metrics` 同样进入保护边界。

Docker 镜像使用非 root UID 10001，默认绑定 `0.0.0.0:8000` 并携带 HEALTHCHECK。

## 第四批：共享限流、readiness 与 tracing

限流后端扩展为 `memory | redis`。Redis 模式使用 Lua 原子滑动窗口，适用于多 worker/多副本共享配额；`/readyz` 会真实探测 Redis，依赖不可用时返回 503。HTTP middleware 新增 OpenTelemetry SERVER span，并支持标准 OTLP/HTTP exporter 配置。

Docker 依赖从 `uv.lock` 导出为带哈希 requirements 锁，并由测试防止漂移；构建支持可配置 `PIP_INDEX_URL`，仍通过 `--require-hashes` 校验 artifact。Compose 已升级为 PostgreSQL + Redis 双依赖；当前服务器没有 Compose frontend，因此不声称完成 Compose runtime 联调。

## 真实 Provider E2E 状态

`scripts/check_live_e2e.py` 现在采用分层诊断：先独立执行 Provider Probe，再执行 Tavily Probe，最后运行低预算完整 Research Graph；每一阶段输出状态、耗时和安全元数据，并可写入 JSON 文件。当前服务器缺少 Anthropic 与 Tavily 凭据，实际执行结果仍为 `blocked_missing_credentials`；因此 Provider + Tavily E2E 仍不是 passed。

## 当前边界

当前已完成 PostgreSQL 耐久恢复、FastAPI/HITL、真实 MCP stdio/Streamable HTTP、认证/限流/Prometheus 和容器 runtime 验证。真实 LLM Provider + Tavily 完整端到端研究仍因服务器缺少所需凭据而阻塞。

## Redis 共享限流与 OTel tracing

生产部署可将 API 限流后端切到 Redis。Lua 脚本把窗口清理、计数、判定和写入放在一个原子操作中；已使用隔离 Redis 7 实例和三个独立 Python 进程验证共享窗口。`/readyz` 会真实探测 Redis，依赖不可用时返回 503。

HTTP middleware 同时保留 Prometheus 指标和结构化日志，并新增 OpenTelemetry SERVER span。OTLP exporter 遵循标准环境变量；本地测试使用 InMemorySpanExporter 验证 request ID、route、status 已写入 span。
