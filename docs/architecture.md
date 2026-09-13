# DeepScout 架构（Phase 2）

DeepScout 将系统职责拆成两层：LangGraph 负责确定性全局编排，DeepAgents 负责单个研究任务内部的自主工具调用。

全局状态中 `task_results` 使用 append reducer，避免并行 Researcher 覆盖彼此结果；Plan 保持不可变，ready tasks 由 Plan 与已有结果实时推导。

Phase 2 的主链路为：`Analyzer → Planner → Supervisor/Budget → Researcher(s) → Evidence Manager → Critic → Writer → Citation Verifier`。

Supervisor 同时考虑 DAG 依赖、并发上限与 Research Worker Budget。Web Research 任务获得独立搜索额度；Synthesis 任务即使搜索额度耗尽仍可基于已有依赖结果执行。

Evidence Manager 负责 URL/正文规范化、去重、稳定 Evidence ID 与 Claim-Evidence 映射。Citation Verifier 在 Writer 之后检查事实性 claim 是否被 Evidence Store 支持，并可在预算允许时触发新的 Plan Extension。

失败任务属于 attempted 但不属于 completed，其下游依赖不会被错误解锁。已有任务在 Re-plan 中保持不可变，只允许追加全新任务 ID。

当前仍未实现 PostgreSQL checkpoint、Redis、MCP、FastAPI/SSE、HITL 和长期记忆。