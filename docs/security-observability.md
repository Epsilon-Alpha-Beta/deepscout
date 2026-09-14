# 安全、限流与可观测性

## API 认证

DeepScout 的 `/v1/*` 接口支持两种共享密钥入口：

- `X-API-Key: <token>`；
- `Authorization: Bearer <token>`。

当 `DEEPSCOUT_API_KEY` 为空时，API 保持本地开发兼容模式；生产环境应始终配置该值。凭据比较使用 constant-time comparison，限流分区只保存不可逆 SHA-256 指纹，不保存密钥前缀或明文。

`/healthz` 保持匿名可访问，供容器编排系统做存活探针；`/metrics` 在配置 API Key 后同样需要认证。

## 限流

当前实现是 caller-scoped 的进程内滑动窗口限流器，由以下配置控制：

- `DEEPSCOUT_API_RATE_LIMIT_REQUESTS`；
- `DEEPSCOUT_API_RATE_LIMIT_WINDOW_SECONDS`。

超过配额时返回 HTTP 429，并附带 `Retry-After`。默认 memory 后端适用于单进程；生产多 worker/多实例可切换 Redis 后端，使用 Lua 原子滑动窗口共享配额。

## 请求追踪与日志

`ObservabilityMiddleware` 为每个请求生成或透传 `X-Request-ID`，并输出 JSON 结构化访问日志，字段包括 method、route、status、duration_ms 与 request_id。这样可以在反向代理、应用日志和 Agent 轨迹之间建立统一关联键。

## Prometheus 指标

`/metrics` 暴露：

- `deepscout_http_requests_total`；
- `deepscout_http_request_duration_seconds`；
- `deepscout_http_requests_active`；
- `deepscout_research_runs_total`。

如不需要暴露 metrics，可设置 `DEEPSCOUT_API_METRICS_ENABLED=false`。

## Agent 级 tracing

DeepScout 基于 LangChain/LangGraph，因此可通过运行环境开启 LangSmith tracing。建议设置 `LANGSMITH_TRACING=true`、`LANGSMITH_PROJECT=deepscout`，并从 Secret Manager 注入对应凭据。仓库不保存 tracing token。

Prometheus 负责服务级 RED 指标，LangSmith 负责 Agent/LLM/tool trajectory；两者职责互补。

## OpenTelemetry

可选启用 OpenTelemetry tracing。API 请求产生 SERVER span，并附带 request ID、HTTP route 和 status。OTLP/HTTP exporter 使用标准 OTEL 环境变量，推荐生产环境发送到 OpenTelemetry Collector。
