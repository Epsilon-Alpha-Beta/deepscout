# 部署指南

## 本地 API

默认使用 Memory Checkpointer：

```bash
uv sync --group dev
uv run python scripts/run_api.py
```

服务默认监听 `127.0.0.1:8000`。生产部署应设置 API Key，并使用 PostgreSQL Checkpointer。

## Docker

仓库根目录提供 `Dockerfile`。镜像内使用 Python 3.11、项目隔离虚拟环境，并以非 root 用户运行 API。

构建示例：

```bash
podman build -t deepscout:0.3.2 .
```

运行时只通过环境变量注入 Provider、Tavily、数据库和 API 凭据，不将任何 secret 写入镜像层。

## Compose + PostgreSQL

`deploy/compose.yml` 提供 API + PostgreSQL 16 的示例拓扑。PostgreSQL 使用持久卷，API 等待数据库 healthcheck 通过后启动，并通过 `DEEPSCOUT_API_CHECKPOINT=postgres` 使用 durable checkpoint。

部署前至少提供：

- `DEEPSCOUT_POSTGRES_PASSWORD`；
- `DEEPSCOUT_API_KEY`；
- 当前模型 Provider 对应的 Key；
- `TAVILY_API_KEY`。

如启用 LangSmith，再注入其 tracing 凭据。

## 健康检查

容器镜像内置 `/healthz` 探针。该端点不依赖 API Key，避免编排系统因认证配置无法判断进程存活。

## MCP

本地进程型 MCP 可使用 stdio；独立服务型 MCP 可使用 Streamable HTTP。`scripts/mcp_research_server.py` 同时支持两种模式，可作为部署 smoke test 与自定义 MCP Server 接入范例。

## 生产边界

当前 Compose 是单 API 实例参考部署。进程内限流不适用于水平扩容后的全局配额；多副本部署时应把限流迁移到共享后端，并在入口层配置 TLS、反向代理和网络访问控制。
