# Phase 2：Evidence、Citation 与 Budget

Phase 2 在 Phase 1 的 Research DAG 与动态 Supervisor 之上增加三个生产化控制层：Evidence Manager、Citation Verifier 和 Research Worker Budget Manager。

## Evidence Manager

Evidence Manager 是确定性组件，不依赖 LLM 做去重。它负责：

- URL canonicalization：移除 fragment、`utm_*`、`fbclid`、`gclid` 等追踪参数；
- 对归一化正文计算 SHA-256 content fingerprint；
- URL 相同或正文相同的 Evidence 合并；
- 生成稳定 `evidence_id`；
- 合并重复来源的 claims 与 relevance score；
- 构建 `Claim → Evidence IDs` 映射。

这样 Writer 与 Citation Verifier 使用的是统一 Evidence Store，而不是各 Researcher 的孤立结果。

## Citation Verifier

Writer 之后增加独立的 Citation Verifier。它只允许引用 Evidence Store 中存在的 `evidence_id`，并把事实性 claim 判定为 `supported`、`partial` 或 `unsupported`。

当关键 unsupported claim 会显著影响答案质量，Verifier 将其转换为 Planner 可消费的 Critique，再走一次受预算约束的 Re-plan。

## Research Worker Budget Manager

Budget Snapshot 从已有 `TaskResult` 实际推导使用量，并约束 Supervisor 后续派发。当前硬预算包括：研究任务数、重规划次数、Evidence 数量与 Web Search 次数。

并行 Researcher 在派发时获得独立 `search_quota`。`web_search` 使用 ContextVar 维护任务级计数器；额度耗尽后直接返回 `search_budget_exhausted`，不会调用 Tavily。

Researcher 还记录模型返回的 token usage 和 Worker 耗时。token 统计依赖 Provider 是否提供 `usage_metadata`，因此不能把它描述成跨 Provider 的精确账单或成本核算。

## Phase 2 非目标

Phase 2 仍不包含 PostgreSQL checkpoint、Redis、MCP Tool Registry、FastAPI/SSE、HITL、长期记忆和完整 benchmark。这些能力留给后续阶段。
