# DeepScout 架构（Phase 3）

DeepScout 将系统职责拆成两层：LangGraph 负责确定性全局编排、耐久状态与恢复边界，DeepAgents 负责单个研究任务内部的自主工具调用。

全局状态中 `task_results` 使用 append reducer，避免并行 Researcher 覆盖彼此结果；Plan 保持不可变，ready tasks 由 Plan 与已有结果实时推导。

当前主链路为：`Analyzer → Planner → Supervisor/Budget → Researcher(s) → Evidence Manager → Critic → Writer → Citation Verifier → Human Review`。

Supervisor 同时考虑 DAG 依赖、并发上限与 Research Worker Budget。Web Research 任务获得独立搜索额度；Synthesis 任务即使搜索额度耗尽仍可基于已有依赖结果执行。

Evidence Manager 负责 URL/正文规范化、去重、稳定 Evidence ID 与 Claim-Evidence 映射。Citation Verifier 检查事实性 claim 是否被 Evidence Store 支持，并可在预算允许时触发新的 Plan Extension。

Human Review Gate 默认自动批准；启用审批后使用 `interrupt()` 暂停，并通过 Checkpointer + `thread_id` 持久化。调用方使用 `Command(resume=...)` 批准或要求 revise。

Tool Registry 同时承载内置工具与 MCP tools；Research Agent 缓存键包含 MCP 配置指纹，避免配置变化后错误复用旧 Agent。

Checkpoint 可使用 `InMemorySaver` 或 `AsyncPostgresSaver`。PostgreSQL 路径已通过两个独立 Python 进程验证 pause/resume，并在 strict MsgPack allowlist 模式下通过。

FastAPI 服务层提供 JSON、SSE、resume 与 thread-state 接口。当前未声称完成真实 MCP Server、真实 LLM Provider/Tavily 端到端联调或长期记忆。
