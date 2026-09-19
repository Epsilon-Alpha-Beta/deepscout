# DeepScout

**基于 LangGraph + DeepAgents 的生产级多智能体深度研究系统。**

DeepScout 参考 LangChain `deepagents/examples/deep_research` 的架构思路，但将高层研究编排显式实现为 LangGraph 工作流：

- 结构化查询分析；
- 依赖感知 Research DAG 规划；
- 确定性的 DAG 校验；
- 基于 LangGraph `Send` 的动态并行派发；
- 基于 DeepAgents 的自主研究 Worker；
- 结构化 `TaskResult` 与 `Evidence` 输出；
- Critic 驱动的信息缺口分析与有界重规划；
- 仅基于已收集证据生成最终报告。

> 当前版本为 **v0.5.4 / Phase 4 第十五批 Resumable Producer / Budget & Provenance**：保留前十四批完整 Benchmark/Quality/Statistics/Bundle/Registry/Lifecycle/Release Gate/Producer 基座，
> 新增官方实验断点恢复、不可变 Producer Plan、分片 provenance 与执行前预算护栏：兼容 shard 可跨失败/中断 run 复用，只有缺失 shard 才重新调用真实 Provider。
> 真实 LLM Provider + Tavily 仍缺少凭据，因此当前只验证恢复/预算/provenance 的 synthetic 管线，不把离线 fixture 当作真实实验结论。

## 系统架构

```text
START
  |
  v
analyze_query
  |
  v
planner <----------------------------------+
  |                                        |
  v                                        |
supervisor + budget                        |
  |                                        |
  +---- ready tasks ----+                  |
  |                     |                  |
  v                     v                  |
researcher ...      researcher             |
  |                     |                  |
  +----------+----------+                  |
             |                             |
             v                             |
        supervisor                         |
             |                             |
        DAG exhausted                      |
             v                             |
      evidence_manager                     |
             |                             |
             v                             |
           critic                          |
          /      \                         |
      gap /        \ sufficient            |
        v           v                      |
     planner       writer                  |
                     |                     |
                     v                     |
             citation_verifier             |
                 /       \                 |
          evidence gap     sufficient       |
               |               |           |
            planner       human_review      |
                              /   \         |
                           revise approve    |
                              |     |        |
                              +-----+------->END
```

核心设计原则是：

> **LangGraph 负责确定性编排，DeepAgents 负责局部自主研究。**

这样可以避免把任务依赖、失败恢复边界和全局控制流完全交给 LLM Prompt 自行决定。

## 上游基线与项目归属
参考项目：

- https://github.com/langchain-ai/deepagents
- `examples/deep_research`

Phase 1 固定使用 `deepagents==0.7.13`，以保证实验结果可复现。

DeepScout 是独立实现，不会把 DeepAgents 上游能力描述成自己的原创工作。详细归属与基线说明见 [`docs/baseline.md`](docs/baseline.md)。

## Phase 1 已实现能力

### 1. 结构化 Research DAG

Planner 输出带类型的研究任务，DeepScout 会拒绝重复任务 ID、未知依赖、自依赖和循环依赖。

### 2. 依赖感知并行调度

Supervisor 不直接修改任务状态，而是根据不可变 Plan 和 append-only 的结果集合推导 ready tasks。相互独立的任务通过 LangGraph `Send` 并行派发。

### 3. DeepAgents Research Worker

每个研究任务都交给缓存后的 DeepAgent 执行，并显式配置模型、Web Search 工具、研究 Prompt 和结构化响应 Schema。

### 4. Critic 与有界重规划

当前 DAG 执行完毕后，Critic 会检查研究覆盖度、缺失维度、冲突信息与失败任务；已有任务保持不可变，只允许新增任务 ID，并通过 `DEEPSCOUT_MAX_REPLANS` 限制重规划次数。


## Phase 2 已实现能力

### 1. Evidence Manager

Researcher 返回的原始 Evidence 会先经过确定性处理：规范化 URL、移除常见追踪参数、计算内容 SHA-256 指纹、按 URL/内容双重去重，并生成稳定的 `evidence_id`。Researcher 提取的原子化 claims 会进一步形成 `Claim → Evidence IDs` 映射。

### 2. Citation Verifier

Writer 生成报告后，Citation Verifier 使用结构化 Schema 对事实性 claim 做 `supported / partial / unsupported` 判断，并输出 coverage、unsupported claims 与是否需要继续研究。只有引用缺口会实质影响答案质量时，才触发新的有界 Re-plan。

### 3. Research Worker Budget Manager

Supervisor 会同时考虑 DAG frontier、并发上限与剩余预算。当前硬约束包括研究任务数、重规划次数、Evidence 数量与 Web Search 次数；并记录 Researcher 的模型 token usage（Provider 提供 usage metadata 时）与 Worker 耗时。并行任务会在派发时分配独立 `search_quota`，额度耗尽后 `web_search` 不再访问 Tavily。

### 4. 可复现的控制边界

Evidence 去重、ID 生成、Claim-Evidence 映射和预算计算均为确定性逻辑；LLM 主要负责局部研究、Critic、Writer 与引用语义判断。这样后续可以分别对 DAG、Evidence、Citation 和 Budget 做消融实验，而不是把全部行为隐藏在 Prompt 中。

## Phase 3 第一批已实现能力

### 1. MCP Tool Registry

Researcher 不再直接依赖固定工具列表，而是通过统一 `ToolRegistry` 聚合内置工具和 MCP 工具。MCP 配置使用 `DEEPSCOUT_MCP_SERVERS` JSON 注入，并支持工具名前缀和名称冲突检测；Research Agent 缓存会随着 MCP 配置指纹变化自动失效。

### 2. Durable Checkpoint 基础设施

`build_graph(checkpointer=...)` 支持注入任意 LangGraph Checkpointer。本地开发可使用 `InMemorySaver`；生产持久化提供 `AsyncPostgresSaver` 工厂，并通过 `postgres` optional extra 安装 PostgreSQL 依赖。

### 3. Retry 与故障隔离

Analyzer、Planner、Critic、Writer 和 Citation Verifier 使用 LangGraph 原生 `RetryPolicy` 对瞬时 Provider/网络故障做指数退避。Researcher 保持任务级故障隔离：单个研究任务失败会形成结构化 `TaskResult(status="failed")`，不会直接破坏整个 DAG。

### 4. Checkpoint CLI

命令行支持 `--checkpoint none|memory|postgres` 与 `--thread-id`。PostgreSQL DSN 可以通过 `--postgres-dsn` 或 `DEEPSCOUT_POSTGRES_DSN` 提供。

## Phase 3 第二批已实现能力

### 1. HITL 人工审核

Citation Verifier 之后增加 Human Review Gate。启用 `require_approval` 时，Graph 使用 LangGraph `interrupt()` 持久化暂停，并通过同一 `thread_id` 下的 `Command(resume=...)` 接收 `approve` 或 `revise`。`revise` 会转换为新的 Critique，在预算允许时回到 Planner。

### 2. FastAPI + SSE 服务层

新增 JSON 与 SSE API，支持创建研究任务、流式更新、查询 thread state，以及对暂停任务执行 resume。API 默认使用 Memory Checkpointer，也可通过配置切换 PostgreSQL。

### 3. PostgreSQL 跨进程耐久恢复

已使用临时 PostgreSQL 16 实例真实验证：进程 A 在 Human Review 处 `interrupt` 后退出，进程 B 重新创建 Python 进程与 PostgreSQL 连接，再使用相同 `thread_id` + `Command(resume=...)` 成功恢复到 END。严格 `LANGGRAPH_STRICT_MSGPACK=true` 模式下也验证通过。

### 4. Checkpoint 序列化白名单

PostgreSQL 与 Memory Checkpointer 使用显式 `JsonPlusSerializer` 白名单，仅允许 DeepScout Graph State 中需要持久化的模型模块进行 MsgPack 反序列化，避免依赖 LangGraph 当前的宽松兼容模式。

## Phase 3 第三、四批已实现能力

### 1. 真实 MCP Server 双传输联调

新增基于 FastMCP 的确定性研究工具服务，并真实验证 stdio 与 Streamable HTTP 两种传输。DeepScout 通过 `MultiServerMCPClient` 完成独立 MCP Server 的工具发现与实际调用，测试不再只依赖 FakeClient。

### 2. API 认证与限流

`/v1/*` 支持 `X-API-Key` 与 Bearer 两种共享凭据入口；配置共享凭据后缺失或错误凭据返回 401。凭据比较使用 constant-time 比较，限流分区使用不可逆 SHA-256 指纹。限流后端支持 memory 与 Redis；memory 适合单 worker，本批次新增的 Redis Lua 滑动窗口用于多 worker/多副本共享配额。

### 3. 可观测性

HTTP 层生成/透传 `X-Request-ID`，输出 JSON 结构化 access log，并暴露 Prometheus 请求计数、请求延迟、活跃请求与研究任务结果指标。配置共享凭据后 `/metrics` 同样需要认证。LangSmith tracing 可通过标准环境变量按需启用。

### 4. 容器与部署

新增非 root Dockerfile、PostgreSQL + Redis Compose 模板与部署文档。Docker 依赖由 `uv.lock` 导出的带哈希 requirements 锁驱动，并由自动化测试校验同步。真实 Podman smoke 用于验证镜像构建、容器启动、readiness、受保护 metrics、UID 10001 非 root 运行和 Docker HEALTHCHECK 元数据；当前服务器没有 Compose 前端，因此 Compose 只做 YAML/关键字段校验。

### 5. Live Provider E2E Harness

`scripts/check_live_e2e.py` 提供低预算真实 Provider + Tavily 全图 smoke test。当前服务器未配置 Anthropic/Tavily 凭据，实际执行状态为 `blocked_missing_credentials`，因此不会将真实 Provider E2E 标记为已通过。

## 安装与环境

要求：Python 3.11+、`uv`、至少一个受支持的 LLM Provider API Key，以及 Tavily API Key。

```bash
git clone https://github.com/Epsilon-Alpha-Beta/deepscout.git
cd deepscout
cp .env.example .env
uv sync --group dev

# 如需 PostgreSQL durable checkpoint
uv sync --group dev --extra postgres
```
运行测试与静态检查：

```bash
uv run pytest
uv run ruff check .
```

运行研究任务：

```bash
uv run python scripts/run_research.py \
  "比较 LangGraph、AutoGen 和 CrewAI 在生产级多智能体系统中的差异。"

# 开启进程内 checkpoint
uv run python scripts/run_research.py --checkpoint memory --thread-id demo-001 \
  "研究长运行 Agent 的故障恢复机制。"

# 启动 FastAPI/SSE 服务
uv run python scripts/run_api.py
```


### 6. Redis 分布式限流与 OpenTelemetry

限流后端新增 `memory | redis`。Redis 路径用 Lua 脚本原子执行窗口清理、计数与写入，已用三个独立 Python 进程共享同一 Redis key 验证 `allowed / allowed / limited`。新增 `/readyz`，Redis 不可用时返回 503。

API request middleware 新增 OpenTelemetry SERVER span，携带 request ID、route 与 status；OTLP/HTTP exporter 使用标准 `OTEL_EXPORTER_OTLP_*` 环境变量配置。测试使用官方 InMemorySpanExporter 验证 span 实际生成。

## Phase 4 第一批：Benchmark 与轨迹级评测

新增 `benchmarks/corpora/core.json`，当前 v1.3.0 Corpus 包含 20 个核心研究 Case / 16 个 category，并为每个 Case 定义来源政策、时效要求与人工 gold rubric；`scripts/run_benchmark.py --validate-only` 可在不调用任何外部 Provider 的情况下校验 Corpus。真实运行时，runner 使用 LangGraph `updates + values` stream，同时记录节点轨迹并计算 citation coverage、task success、source diversity、search calls、research tokens、worker/wall time 等指标。

Trajectory 只记录节点名、相对耗时和输出字段名，不保存模型正文或 Evidence 正文。`quality_proxy_score` 是透明的工程代理指标，仅用于版本/消融相对比较，不等同于人工事实正确率。成本估算只有显式传入 Research Worker token 与搜索单价时才产生，否则美元成本保持 `null`；当前 tracked cost 不覆盖 Analyzer/Planner/Writer 等尚未记录 token 的节点，因此不能当作完整账单成本。

Benchmark 输出为 `report.json` 与 `report.md`；当前 synthetic fixture 只证明指标、阈值、异常归档和报告管线正确，不代表真实 Provider Benchmark 分数。详见 `docs/phase4.md`。

## Phase 4 第二批：Ablation Matrix

新增 `benchmarks/ablations/core.json` 与 `scripts/run_ablation.py`。默认矩阵包含 `full`、`no-replan`、`no-citation-feedback`、`no-evidence-dedup`、`low-budget`、`serial-research` 六个 profile，并在同一 Corpus 上顺序运行，避免 profile 间资源竞争污染 wall-time。

`no-citation-feedback` 保留 Citation Verifier 作为统一测量仪器，只禁止引用缺口触发重规划；这样 citation coverage 仍可与 baseline 同口径比较。Settings override 基于 `ContextVar`，会传播到 asyncio 子任务但在 profile 结束后自动恢复；GraphOptions 则显式控制 citation feedback 与 evidence dedup。

Ablation 报告输出 quality/citation/source-diversity 与 replan/evidence/search/token/wall-time/tracked-cost 的 baseline delta，同时保留每个 profile 的独立 Benchmark report。验证矩阵可运行 `uv run python scripts/run_ablation.py --validate-only`。

## Phase 4 第三批：重复实验与统计层

新增 `scripts/run_repeated_ablation.py`。默认按 repetition-major 执行实验，并轮转每轮 profile 的起始顺序，降低固定时间顺序带来的系统性偏差；原始 run 按 `(repetition, profile, case)` 保留。

每个数值指标计算 `mean / sample std / median / p50 / p95`，均值置信区间使用确定性 percentile bootstrap；confidence level、resample 次数和 bootstrap seed 都写入报告。profile 与 baseline 的差异按同一 `(repetition, case)` 配对后再统计，避免把非配对样本直接相减。error/interrupted run 计入完成率，但不会以 0 值混入数值分布。

输出包括 `repeated.json`、`runs.csv`、`statistics.csv`、`deltas.csv`、`report.md`，以及 quality/citation/search/token/wall-time 的均值+CI SVG 和 quality/search/wall-time 的配对 delta SVG。默认 5 次重复的完整矩阵是 `6 profiles × 20 cases × 5 = 600` 次研究运行；建议先用 `--limit 1 --repetitions 2` 做低成本 smoke。

只校验计划而不调用 Provider：`uv run python scripts/run_repeated_ablation.py --validate-only --repetitions 5`。真实运行可使用 `uv run python scripts/run_repeated_ablation.py --repetitions 5 --output-dir benchmark-results/repeated-ablation-latest`；默认 5 次更适合 smoke，正式统计结论应提高重复次数并优先检查 profile×case 与配对 delta。

## Phase 4 第四批：显著性检验与效应量

重复实验完成后，同一 CLI 会自动生成 `significance.json / significance.csv / significance.md`，主检验采用配对 sign-flip randomization/permutation test，辅以 exact dynamic-programming Wilcoxon signed-rank。配对效应量包括 Cohen’s dz 与 matched rank-biserial；Cliff’s delta 明确作为忽略配对结构的补充效应量。

多重比较以“同一 scope + case + metric 下的非 baseline profiles”为 family，对主 permutation p-value 同时计算 Holm–Bonferroni（FWER）和 Benjamini–Hochberg（FDR）。全局 `profile_across_cases` 不把 case×repetition 当成独立样本，而是先对每个 case 的重复配对差求均值，再以 case 为统计单元。

第四批曾通过分辨率审计发现：6-case Corpus 在 5-profile Holm family 下理论最小 adjusted p 约为 `0.15625`，无法达到 `alpha=0.05`；这一发现直接驱动第五批扩容。当前 20-case Corpus 的 two-sided exact sign-flip raw 最小 p 约为 `1.91e-6`，最保守的 5-way Holm 下限约为 `9.54e-6`，因此 exact/Holm 分辨率已不再是当前瓶颈。

新增 SVG 包括 `significance_effect_sizes.svg` 和 `significance_holm_p.svg`。p-value 只描述与零效应的一致程度，正式判断仍应结合 paired delta CI、效应量、完成率和原始 run。当前多重校正只覆盖同一 metric 内的 profile family；跨 metric 的确认性声明应预注册主指标或进一步校正。

## Phase 4 第五批：Corpus 扩容与 Power / MDE 规划

Core Corpus 从 6 个扩展到 20 个 Case，覆盖 16 个 category；新增安全、检索、幂等副作用、Provider 路由、冲突证据、评测方法、长上下文记忆、sandbox、streaming backpressure、服务身份/Secrets、数据治理、结构化输出、队列公平和多地域恢复等主题。Corpus 在第五批扩到 `1.2.0`，第六批质量控制元数据升级为 `1.3.0`。

新增 `scripts/plan_experiment.py`，在不调用任何 Provider 的情况下读取 Corpus Case 数和 Ablation family size，输出 exact sign-flip/Holm 可达性，以及基于 paired-normal + Bonferroni `alpha / family_size` 的保守 power 规划。默认 `alpha=0.05`、family size=5、target power=0.8 时，20 cases 的 MDE 约为 `Cohen dz=0.764`；假设真实效应 `dz=0.8`，近似 power 约 `84.2%`，而 `dz=0.5` 只有约 `36.7%`，达到 80% power 约需 47 个独立 Case。

规划结果输出 `plan.json / plan.md / sample_sizes.csv / power_curve.csv / charts/power_curve.svg`。这是一层**实验设计近似**：Holm 没有使用简单闭式 power，而是用 Bonferroni 阈值做保守规划；最终显著性仍以真实 repeated 数据上的 permutation/Wilcoxon/Holm 分析为准。只校验规划可运行 `uv run python scripts/plan_experiment.py --validate-only`。

## Phase 4 第六批：Benchmark Case 质量控制层

Core Corpus v1.3.0 为 20/20 Case 新增 `topic_group`、`source_policy` 与 `gold_rubric`。来源政策包含最少 primary source 数、preferred domains、primary-source 类型以及可选 freshness 窗口；preferred domains 是来源优先级而不是硬 allowlist，避免研究被过度锁死。14/20 Case 要求至少一个近 730 天来源。

人工 gold rubric 为每个 Case 定义至少 3 个 case-specific required points、critical error guard，以及 factual correctness / required coverage / evidence quality / trade-off reasoning 四个加权维度；权重必须精确归一为 1，默认 pass score 为 0.75。工程 `quality_proxy_score` 仍不替代人工 gold 评分。

新增 `scripts/audit_benchmark.py --validate-only --strict`，静态审计 source/rubric 覆盖、域名合法性、freshness、topic/category/difficulty balance、单一来源域集中度和 Case 标签/关键词重叠。当前 20 Case 被归入 7 个 topic group，最大 topic share=20%，difficulty=70% hard/30% medium，freshness coverage=70%，严格审计为 0 error / 0 warning。完整报告输出 `quality.json / quality.md / cases.csv / charts/topic_balance.svg / charts/difficulty_balance.svg`。

## Phase 4 第七批：运行后来源合规与人工盲评

Evidence 新增 `source_class / published_at / retrieved_at`。`web_search` 程序化写入检索时间和已知权威域名的 source class；只有 Provider 真返回日期时才透传 `published_at`。Evidence Manager 在模型遗漏时确定性补 source class 与入库时间，但绝不猜测发布时间。

新增 `scripts/score_source_policy.py`：对真实 `evidence_store` 检查最少 primary sources 与 freshness。freshness 缺可靠 `published_at` 时状态为 `unverifiable`，不会把未知日期伪装成近期或过期。输出 `source_compliance.json / source_compliance.md`。

新增 `scripts/review_benchmark.py`：`prepare` 生成不含 model/profile/provider 身份的 blind packet；两个 reviewer 分别按 0–4 ordinal rubric 独立评分。系统计算 pass/fail Cohen's κ、criterion-level quadratic weighted κ 与 score gap；pass 分歧、critical-error 分歧或超过阈值的 score gap 必须 adjudication，不能用自动平均掩盖。输出 `human_review_audit.json / human_review_audit.md / human_review_outcomes.csv`。

工程 `quality_proxy_score`、自动 source-policy compliance 与人工 gold score 始终保持三条独立指标轴。真实运行后的合规率和人工评分仍需等真实 Provider Evidence 产生后执行。

## Phase 4 第八批：运行后质量聚合与 Human Gold 显著性

原始 `BenchmarkRunResult` 与 `RepeatedRunRecord` 保持不可变；来源合规和人工盲评作为 sidecar 通过 `(profile, repetition, case_id)` 绑定。`BlindReviewAssignment` 是私有映射，只负责把匿名 `blind_item_id` 映射回实验单元，不进入 reviewer packet，因此 packet 仍不暴露 profile/model/provider/repetition。

新增 `RuntimeQualityAggregateReport`，按 profile 与 profile×case 聚合 source observation coverage、freshness 可评估率、source compliance rate、human review coverage、human gold mean/CI/pass rate，以及 reviewer pass agreement、Cohen κ 与 quadratic weighted κ。`unverifiable` freshness 不会计为 source failure；未评审、待仲裁或失败 run 也不会被填成 0。

Human gold paired delta 使用与 repeated 层一致的同 `(repetition, case)` 配对规则；全局显著性先在每个 Case 内对 repetitions 求 paired mean，再跨 Case 做 sign-flip / Wilcoxon / Cohen dz / Holm-BH，避免把 case×repetition 误当成独立样本。只使用 `status=completed` 且 profile/baseline 都有 resolved final gold score 的配对单元。

新增 `scripts/aggregate_runtime_quality.py`，读取 `repeated.json`、source observation sidecar、private review assignment 与 human review audit，输出 `quality_aggregate.json / quality_aggregate.md / quality_observations.csv / quality_statistics.csv / human_gold_deltas.csv`、SVG 图表以及可选 `human_gold_significance.*`。

第八批还修复了显著性 Markdown 的一个历史边界：当 raw exact p 已可达但 Holm 分辨率仍不可达时，报告现在正确使用 `minimum_reportable_holm_p`，不会访问不存在的旧字段。

## Phase 4 第九批：Experiment Bundle 与跨批次 Regression Comparison

新增 `ExperimentBundleManifest`：一次实验会把 repeated result、Corpus、Ablation Matrix、可选 runtime quality aggregate 与额外 artifact 复制到独立 bundle，并记录每个文件的 SHA-256、字节数和 logical role；manifest 同时记录项目版本、Git SHA/dirty、Provider/Model 标识、Corpus/Matrix/baseline/profile set/repetitions 以及 bootstrap/实验配置。密钥不进入 manifest。

Bundle 创建和校验不仅检查文件 hash，还核对 Corpus name/version 与 Matrix name/version/baseline/profile set 是否与 repeated identity 一致。任何 artifact 被篡改、文件缺失、路径越界或 identity 漂移都会使 bundle invalid。Docker/无 `.git` 环境可显式传 `--git-sha` 与 `--git-dirty`，不会静默写 `unknown`。

新增 `scripts/create_experiment_bundle.py` 和 `scripts/compare_experiments.py`。Comparator 先执行 compatibility gate：Corpus/Matrix/baseline/profile set 不一致直接 `incomparable`；repetitions、Provider 或 Model 不同只给 warning，允许做有意识的跨模型/跨重复次数对比。

默认 regression rules 显式区分 higher-is-better 的 `quality_proxy_score/citation_coverage/source_diversity_ratio/source_compliance_rate/human_gold_score/human_gold_pass_rate` 与 lower-is-better 的 `search_calls/research_tokens/worker_seconds/wall_seconds/estimated_tracked_cost_usd`。每条比较同时保存 absolute threshold、relative threshold 和最终 effective threshold；`--fail-on-regression` 可用于 CI 门禁。

比较报告输出 `comparison.json / comparison.md / comparisons.csv`。Synthetic CLI smoke 已验证 candidate 同时出现 quality/human-gold 下降和 wall/worker 上升时会返回 regression，并且 `--fail-on-regression` exit 1。

## Phase 4 第十批：Experiment Registry / History 与 Baseline Lineage

新增 `ExperimentRegistryReport`：递归扫描 bundle root 下的 `manifest.json`，逐个执行完整 Bundle validation，并按 Corpus/Matrix/baseline/profile set 生成稳定 compatibility key。Registry 会拒绝被篡改、identity 不一致或 experiment ID 重复的 bundle；invalid bundle 不会进入 lineage 或 baseline 候选。

每个 compatibility group 按 `created_at` 排序：第一份 valid bundle 作为 lineage root；之后 candidate 始终与“最近一个兼容且已通过 gate 的 bundle”比较。若 candidate 出现 regression，它会记录为 `regression`，但不会推进 baseline；下一次实验仍与 last-known-good 比较。只有零 regression 的 candidate 才标 `accepted` 并成为新的 baseline。

新增 `scripts/build_experiment_registry.py`。`--candidate-id ... --fail-on-regression` 可直接作为 history CI gate：candidate regression 时 exit 1；candidate 不存在或 invalid 时 exit 2；accepted/baseline 时 exit 0。`--fail-on-invalid` 可进一步阻止 Registry 中存在坏 bundle。

Dashboard 输出 `registry.json / registry.md / registry_entries.csv / lineage.csv / history_metrics.csv`，并按 compatibility group + baseline profile 生成 `quality_proxy_score / wall_seconds / human_gold_score / source_compliance_rate` SVG 趋势图。历史 metric 使用 long-form 结构，后续可直接接 Pandas/BI。

第十批同时修复第九批一个未覆盖路径：自动生成 experiment ID 时现在正确使用解析后的 `resolved_sha`；Git metadata 读取失败会明确要求显式 `git_sha/git_dirty`，不会在无 Git 上下文时产生不可追溯 ID。

## Phase 4 第十一批：Promotion / Retention Lifecycle

Registry 的 `baseline/accepted/regression/invalid` 是自动历史 gate 状态；第十一批新增独立 `PromotionDecision`，用于表达发布/资产生命周期上的正式晋级。默认 `PromotionPolicy` 要求 bundle valid、Registry 状态为 `baseline` 或 `accepted`、Git worktree clean 且 regression_count=0。`regression` 或 dirty bundle 默认 hold；只有显式 override 才能晋级，并必须记录 actor + reason。`invalid` bundle 永远不可 override 晋级。

Promotion decision 是可审计 artifact：记录 experiment/group、Registry status、eligible、action、blockers、actor、override 标记、policy snapshot 与决定时间。同一 experiment 有多次 decision 时只取最新一条；旧 compatibility key 的 decision 在 Retention 中会被拒绝，避免 Registry identity 变化后继续误保护。

新增 `RetentionPolicy`：默认保留每个 compatibility group 最近 3 个 accepted、最近 2 个 regression，保护 lineage root 与所有当前 promoted bundle，invalid 默认不保留。支持显式 milestone IDs；同时默认执行 lineage closure——只要 retained bundle 引用某 baseline，就递归保护整条审计祖先链。

Retention 默认只生成 `retention_plan.json/md/csv`，不会删除。`--dry-run-apply` 输出 `would_delete`；只有显式 `--apply-retention` 才真正删除。Apply 前会再次检查目标仍位于 bundles root 下、拒绝删除 bundles root 本身、要求 manifest 可解析且 experiment_id 匹配，从而避免路径漂移或误删。

新增 `scripts/manage_experiment_lifecycle.py`：`promotion` 子命令生成 promotion decision；`retention` 子命令生成/模拟/应用 retention plan。Synthetic CLI 已验证：accepted `b3` 自动 promote；regression `b2` 默认 hold 并 exit 1；带 actor/reason 的 override 可 promote；Retention dry-run 只报告 `b4` would_delete，apply 后仅删除 `b4`。

## Phase 4 第十二批：Release Readiness / CI Gate

新增 `benchmarks/policies/release_gate.json`，将发布规则显式版本化：默认要求 Registry 中没有 invalid bundle，候选满足 valid + baseline/accepted + clean git + zero regression，并沿用第十一批 RetentionPolicy 生成资产保留预览。

新增 `scripts/gate_experiment_release.py`。它读取已有 `registry.json` 和 policy，对候选实验执行统一门禁，并一次输出 `release_gate.json/md`、`promotion_decision.json/md` 与 `retention_plan.json/md/csv`。通过时 exit 0，策略阻塞时 exit 1，输入/身份错误时 exit 2，适合接入 CI 或发布流水线。

该 Gate 有两条刻意的安全边界：**不提供 manual override 参数**，因此自动化流水线不能绕过 promotion policy；**永远不执行 retention apply**，只生成 keep/delete preview。真正的人工 override 与删除仍必须走 `manage_experiment_lifecycle.py` 的显式命令。

Synthetic CLI smoke 已验证：accepted `b3` 得到 `passed/promote`；regression `b2` 得到 `blocked/hold`；严格 policy 会因 Registry 中任一 invalid bundle 阻塞候选，而显式放宽 `require_zero_invalid_registry` 时只降级为 warning。

## Phase 4 第十三批：Artifact-driven GitHub Actions Gate

新增 `.github/workflows/release-gate.yml`，作为可复用 `workflow_call` + 手动 `workflow_dispatch` 发布门禁。上游实验 job 只需把一个或多个完整 Experiment Bundle 上传为 Actions artifact，Gate 会在独立 runner 下载 artifact、检查 `manifest.json` 数量、重新构建 Registry，再执行第十二批的 policy-as-code Release Gate。

同一 workflow 内调用时直接读取当前 run 的 artifact；手动审计历史实验时必须显式提供 `source_run_id`，并使用 `GITHUB_TOKEN` 的 `actions: read` 权限从指定 run 下载。输入只通过 Action 参数或环境变量传递，候选 experiment ID 不直接拼接进 shell 命令。

Gate 无论成功还是被策略阻塞，都会尽可能把 Registry、`release_gate.json/md`、Promotion decision 和 Retention preview 上传为 `deepscout-release-gate-audit` artifact；Markdown 同时写入 GitHub Step Summary。Gate 仍然不暴露 manual override，也不会执行 retention apply。

主 `CI` 增加 artifact-boundary smoke：测试 job 生成现有 synthetic bundle history，并以 1 天保留期上传 `deepscout-experiment-bundles-smoke`；随后通过 reusable workflow 对 accepted `b3` 执行真实 artifact 下载 → Registry rebuild → Release Gate。该 smoke 验证的是流水线与 artifact 边界，不代表真实 Provider 质量结果。

## Phase 4 第十四批：Sharded Benchmark Experiment Producer

新增 `.github/workflows/benchmark-producer.yml`，仅通过 `workflow_dispatch` 手动触发，不会在普通 push/PR 时消耗真实 Provider 配额。Producer 将真实凭据只注入需要调用 LLM/Tavily 的 job；缺少对应 Provider key 或 `TAVILY_API_KEY` 时，现有 staged live preflight 会明确失败并留下诊断 artifact，不会继续生成伪造 Bundle。

Producer 提供两个彼此隔离的协议。`smoke` 固定执行 1 case × 6 profiles × 1 repetition = 6 runs，产出独立的 `deepscout-live-smoke-bundle-*`，明确不进入 Release Gate；`official` 固定执行 Core Corpus 20 cases × 6 profiles × 5 repetitions = 600 runs，并要求显式确认字符串。继续既有 lineage 时必须提供数值型 `history_run_id` + `RUN_OFFICIAL_600`；新建 lineage 时必须明确选择 `new` 并输入 `RUN_OFFICIAL_600_NEW_LINEAGE`，从而避免因漏填历史 run 而静默把 candidate 变成新的 baseline root。

GitHub-hosted runner 单 job 存在 6 小时执行上限，因此 official 不把 600 runs 串在单 job 中。工作流按 5 repetitions × 4 个 case shard 拆成 20 个 matrix job，每个 shard 恰好执行 5 cases × 6 profiles = 30 runs，`max-parallel=2`。每个 repetition 的 profile 顺序通过临时 Matrix 预先轮转，shard 内使用 `order_strategy=fixed`，避免并行分片破坏原先 repetition-level rotation 设计。

新增 `src/deepscout/evaluation/repeated_merge.py` 与 `scripts/merge_repeated_ablation.py`。汇总阶段递归发现 shard metadata，校验 canonical Corpus/Matrix identity、bootstrap 配置、case 内容、profile 集合、路径边界、重复 shard、重复运行单元和完整 coverage，再按 canonical case 顺序与目标 profile rotation 重建全局 `execution_order`。只有 600 个 `(repetition, profile, case)` 单元恰好各出现一次才会生成最终 `repeated.json`、显著性报告与正式 Experiment Bundle。

`official/continue` 会从指定历史 producer run 下载 `deepscout-experiment-bundles`，先对旧 lineage 执行完整 Registry validation，再追加当前 candidate；`official/new` 则显式从空 lineage 启动。最终组合 artifact 上传后直接复用第十三批 Release Gate，因此 Registry comparison、Promotion eligibility、Retention preview 与 audit artifact 不需要在 Producer 中重复实现。

本地已用 20 个 synthetic shard 验证与正式协议同形的合并路径：20 shards → 600 runs，600 个运行 identity 全部唯一，最终 `repetitions=5`、`order_strategy=rotate`；同时验证 duplicate shard、缺失 coverage 和 repeated-path 越界均被拒绝。这些验证只证明分片生产管线正确，不代表真实 Provider 的质量或性能结果。

## Phase 4 第十五批：Resumable Producer、预算护栏与 Provenance

第十五批为正式 600-run Producer 增加分片级断点恢复。每次运行都会先生成不可变 `ProducerPlan`，记录 Git SHA、模型、Corpus/Matrix SHA-256、lineage、20-shard 拓扑、并发和实验预算上界，并计算 compatibility fingerprint。恢复时可提供失败/中断 run 的 `resume_run_id`；只有 fingerprint 完全一致且仍有效的 shard artifact 才允许复用。已产生 `deepscout-experiment-bundles` 的 finalized run 会被拒绝作为恢复源，避免重复完成同一正式实验。

恢复预算在真实 Provider/Tavily preflight **之前**执行。工作流提供 `max_new_shards`、`max_new_search_calls` 与 `max_new_research_tokens` 三层 guard；当前 Core Matrix 动态计算出的上界为：每个 5-case shard 最多 1,060 次 search calls / 5,250,000 Research Worker tokens，完整 official 最多 21,200 / 105,000,000。它们是基于 DeepScout 预算配置的工程上界，不是 Provider 账单或实际消耗。

每个 matrix shard 先读取 Resume Plan。可复用 shard 从旧 run 下载后仍通过与新执行 shard完全相同的 canonical 校验；不可复用 shard 才真正执行 30 个 Agent run。随后统一写入当前 run 的 `provenance.json`，记录 reused/executed、来源 run、当前 run/attempt、Git SHA 与 Producer fingerprint。assemble 阶段要求 20 份 provenance 与 Resume Plan 逐一匹配，之后才允许执行 600-run merge。

新增 `src/deepscout/evaluation/producer_plan.py` 与 `scripts/plan_benchmark_producer.py`，将 Plan、artifact inventory、resume decision、预算判定、单 shard 决策和 provenance 汇总作为可测试的库/CLI，而不是只写在 Actions YAML 中。正式 Bundle 同时固化 `producer_plan`、`resume_plan` 与 `shard_provenance`，便于之后审计一个实验究竟复用了哪些 shard。

Synthetic E2E 已验证典型恢复场景：旧 run 保留 17/20 个兼容 shard，本次仅允许 3 个新 shard，则得到 510 个复用 run units + 90 个新 run units；对应新执行上界为 3,180 searches / 15,750,000 Research Worker tokens。20 个 provenance 全部校验后仍确定性合并为完整 600-run repeated experiment。模型/Git/Corpus/Matrix/lineage 指纹漂移、预算超限、artifact 分页截断/过期、finalized resume source 和 provenance 篡改都会被拒绝。

## 当前验证状态

Phase 4 第十五批当前代码已在项目隔离环境中完成验证：

- DeepScout 专属 Python：3.11.16；
- 系统 Python：保持 3.10.12，不受影响；
- `pytest`：138/138 通过（真实 Redis，无 skip；新增覆盖 Producer Plan/Resume、三层预算、单 shard validation 与 provenance closure）；
- `ruff check .`：通过；
- LangGraph：可成功编译为 `CompiledStateGraph`；
- PostgreSQL：真实跨进程 pause/resume 与严格 MsgPack 模式恢复通过；
- FastAPI/HITL：真实 InMemorySaver interrupt/resume 集成测试通过；
- MCP：真实 stdio 与 Streamable HTTP Server 工具发现/调用通过；
- API：认证、限流、Request ID 与 Prometheus 指标测试通过；
- 容器：真实构建与运行 smoke 通过，非 root 运行；
- Live Provider：当前因缺少 Provider/Tavily 凭据而阻塞；
- Live E2E 诊断：已拆分为 Provider Probe → Tavily Probe → Full Graph 三阶段，并支持 JSON 结果输出与阶段级故障定位；
- GitHub Actions：CI 在每次 push/PR 后执行 Install、Ruff、Tests，并通过 Actions artifact 运行 Release Gate smoke；远端已验证 7 Bundle 下载、Registry rebuild、`b3 passed/promote` 与 audit artifact 上传链路。
- Experiment Producer：20-shard/600-run 基础生产链路继续通过；第十五批新增不可变 Plan 指纹、失败 run shard 复用、三层预算 guard 与 provenance 审计，synthetic 17 reused + 3 executed → 600-run merge 已通过；真实 smoke/official 仍等待 Provider/Tavily 凭据后手动触发。

## 后续路线

**Phase 3 剩余**：补齐真实 LLM Provider + Tavily 端到端联调；可选继续做真实 OpenTelemetry Collector 网络链路与 Compose runtime 联调。

**Phase 4 后续**：真实 Provider/Tavily 凭据可用后，先运行 `smoke` producer；首条 official lineage 显式使用 `new`。若 official run 中断，可将该失败 run 作为 `resume_run_id` 并设置 `max_new_shards/search_calls/research_tokens` 预算，仅重跑缺失 shard；成功完成后再用其 run ID 作为后续 `history_run_id` 延续 lineage，并用真实 paired variance 回填 power/MDE。
