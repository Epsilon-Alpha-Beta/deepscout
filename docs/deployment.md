# 部署指南

## 本地 API

默认使用 Memory Checkpointer：

```bash
uv sync --group dev
uv run python scripts/run_api.py
```

服务默认监听 `127.0.0.1:8000`。生产部署应设置共享 API 凭据，并使用 PostgreSQL Checkpointer；多 worker/多副本应启用 Redis 限流后端。

## Docker

仓库根目录提供 `Dockerfile`。镜像使用 Python 3.11，并以非 root UID 10001 运行 API。

容器依赖不是在构建时临时安装 uv，而是由 `uv.lock` 导出的 `deploy/requirements.lock.txt` 驱动，并使用 `pip --require-hashes` 安装。`tests/test_deploy_lock.py` 会校验两份锁保持同步。

构建示例：

```bash
podman build --format docker -t deepscout:0.4.2 .
```

运行时只通过环境变量注入 Provider、Tavily、数据库、Redis 和 API 凭据，不将任何 secret 写入镜像层。

## Compose：PostgreSQL + Redis

`deploy/compose.yml` 提供 API + PostgreSQL 16 + Redis 7 的参考拓扑。PostgreSQL 使用持久卷保存 LangGraph checkpoint；Redis 仅保存短生命周期限流窗口，不承担业务持久化。

API 等待 PostgreSQL 与 Redis healthcheck 均通过后启动，并配置：

- PostgreSQL durable checkpoint；
- Redis Lua 原子滑动窗口限流；
- 可选 OpenTelemetry OTLP exporter；
- 可选 LangSmith tracing。

部署前至少提供 PostgreSQL 密码、API 凭据、当前模型 Provider Key 和 Tavily Key。生产环境还应在入口层配置 TLS、反向代理、网络访问控制与 Secret Manager。

## 健康与就绪检查

`/healthz` 是不依赖外部组件的 liveness probe；`/readyz` 是 readiness probe。Redis 限流启用时，`/readyz` 会真实执行 Redis `PING`，不可用时返回 503。PostgreSQL checkpoint 在应用 lifespan 启动阶段建立连接，连接失败时应用不会正常进入 serving 状态。

Docker 镜像内置 `/healthz` HEALTHCHECK。该端点无需 API 凭据，避免编排系统因认证配置无法判断进程是否存活。

## MCP

本地进程型 MCP 可使用 stdio；独立服务型 MCP 可使用 Streamable HTTP。`scripts/mcp_research_server.py` 同时支持两种模式，可作为部署 smoke test 与自定义 MCP Server 接入范例。

## 可观测性

Prometheus `/metrics`、JSON access log 与 `X-Request-ID` 默认可用；配置共享 API 凭据后 `/metrics` 同样进入认证边界。OpenTelemetry tracing 可通过标准 OTLP 环境变量发送到 Collector；当前自动化测试已验证 SERVER span 与关键属性生成。

## 生产边界

Redis 解决应用层多 worker/多副本共享限流，但生产入口仍建议使用 API Gateway / Ingress 提供 TLS、连接级限流、IP 策略和 DDoS 防护。当前服务器没有 Compose frontend，因此仓库只验证 Compose YAML/依赖结构，不声称已经运行整套 Compose 拓扑。
