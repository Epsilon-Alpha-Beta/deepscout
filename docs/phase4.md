# Phase 4：Benchmark 与轨迹级评测

Phase 4 分七批推进：第一批建立 Benchmark/trajectory 基座；第二批加入 Ablation Matrix；第三批加入重复实验与 bootstrap 统计；第四批加入配对显著性检验、效应量和多重比较校正；第五批扩充 Core Corpus 并加入 power/MDE 规划；第六批建立 Case 来源政策、人工 gold rubric 与 balance 审计；第七批把质量控制延伸到真实 Evidence 与人工双盲评审。当前仍不会在缺少真实 Provider/Tavily 凭据时伪造真实质量结论。

## Benchmark Corpus

`benchmarks/corpora/core.json` 当前为 v1.3.0，包含 20 个核心研究 Case、16 个 category，覆盖：

- 多智能体框架比较；
- MCP 传输模式；
- durable execution；
- Agent 可观测性；
- Redis 分布式限流；
- Human-in-the-loop 工作流；
- Prompt injection / tool safety、hybrid retrieval、幂等副作用与 Provider 路由；
- 冲突证据处理、Agent 评测、长上下文记忆与 sandbox；
- streaming backpressure、服务身份/Secrets、数据治理、结构化输出、队列公平与多地域恢复。

每个 Case 包含 category、difficulty、tags、expected keywords 和机器可校验 expectations。`case_id` 在同一 Corpus 内必须唯一。

## Trajectory Recorder

Benchmark runner 使用 LangGraph `stream_mode=["updates", "values"]` 同时获取节点更新与最终状态。轨迹只记录节点名、相对耗时和输出字段名，不持久化模型正文、Evidence 正文或 API 凭据。

## 指标体系

当前指标直接复用 DeepScout 运行状态：

- 轨迹：node visits、total node events、replan count；
- 任务：task count、task success rate；
- 证据：evidence count、unique source hosts、source diversity、平均 relevance；
- 引用：citation coverage、unsupported claims；
- 资源：search calls、research tokens、worker seconds、wall seconds；
- 输出：final report chars、expected-keyword recall；
- 成本：可选 model/search 单价估算。

`quality_proxy_score` 是 citation、task success、source diversity、relevance 与 keyword recall 的透明工程代理指标，只用于版本/消融的相对比较，不等同于人工事实正确率或学术意义上的最终质量评分。

若未显式提供 token/search 价格，美元成本字段保持 `null`，不会使用猜测价格。当前 token 成本只基于 `TaskResult.model_tokens`（Research Worker 已跟踪 token），尚未覆盖 Analyzer/Planner/Writer 等所有 LLM 节点，因此字段命名为 `tracked cost`，不能解释为完整账单成本。

## 运行方式

只校验 Corpus，不调用任何外部 Provider：

```bash
uv run python scripts/run_benchmark.py --validate-only
```

真实 Benchmark：

```bash
uv run python scripts/run_benchmark.py \
  --corpus benchmarks/corpora/core.json \
  --output-dir benchmark-results/latest
```

可选成本参数：

```bash
--research-token-usd-per-million <price>
--search-usd-per-1000-calls <price>
```

输出同时包含 `report.json` 与 `report.md`。Corpus 默认顺序执行，避免并发噪声污染 wall-time 对比。


## 第二批：Ablation Matrix

`benchmarks/ablations/core.json` 定义 6 个 profile：

| Profile | 变化 | 目的 |
| --- | --- | --- |
| `full` | 完整默认配置 | baseline |
| `no-replan` | `max_replans=0` | 测量迭代补充研究的贡献 |
| `no-citation-feedback` | Citation Verifier 仍测量，但不触发 Planner | 避免删除测量仪器导致 citation 指标失去同口径 |
| `no-evidence-dedup` | 保留重复 Evidence | 测量 URL/内容指纹去重价值 |
| `low-budget` | 收紧 task/search/token/worker-time/evidence 预算 | 观察质量—资源 trade-off |
| `serial-research` | `max_concurrency=1` | 观察并发对 wall-time/结果的影响 |

Settings override 使用 `ContextVar`，会传播到 asyncio 子任务，并在 profile 结束后自动恢复，不通过进程级环境变量临时改写实验配置。结构性变化由 `GraphOptions` 显式传入 `build_graph()`。

Ablation runner 按 profile **顺序执行**，每个 profile 内仍允许 Research Worker 按其并发上限运行。输出包括每个 profile 的完整 Benchmark report，以及相对 `full` baseline 的：pass rate、quality proxy、citation coverage、source diversity、replans/case、evidence/case、searches/case、research tokens/case、wall-time/case 和 tracked cost/case delta。

只校验矩阵和 Corpus：

```bash
uv run python scripts/run_ablation.py --validate-only
```

真实运行（完整矩阵是 6 profiles × 20 cases = 120 次研究任务）：

```bash
uv run python scripts/run_ablation.py \
  --corpus benchmarks/corpora/core.json \
  --matrix benchmarks/ablations/core.json \
  --output-dir benchmark-results/ablation-latest
```

可先用 `--limit 1` 做低成本 smoke。实验命令只有在某个 run `error/interrupted` 时返回非零；某个消融 profile 未达到 expectation 仍属于有效实验结果，不会被误判为程序执行失败。

## 第三批：重复实验与统计

`scripts/run_repeated_ablation.py` 在同一个 profile/case 上执行多次 repetition，并保留每个原始 `BenchmarkRunResult`。默认执行顺序采用 `rotate`：每轮轮转 profile 起始位置，减少固定 profile 总是先跑或后跑造成的时间漂移偏差；也可显式选择 `fixed`。

统计层计算 `mean`、sample `std`、`median`、`p50`、`p95`。均值置信区间默认使用 95% percentile bootstrap；默认 2000 次 resample，并使用稳定 seed 派生每个 scope/metric 的 bootstrap seed，因此同一输入可复现。样本数为 1 时 CI 退化为该观测值。

profile 与 baseline 的 delta 不使用“两个总体均值直接相减”，而是先按 `(repetition, case)` 配对，仅当二者都 completed 时计算 profile−baseline，再对配对差值做同样的分布统计。error/interrupted 计入 attempted/error/interrupted/completion rate，但不会以 0 值进入数值统计。

输出结构：

```text
benchmark-results/repeated-ablation-latest/
├── repeated.json
├── report.md
├── runs.csv
├── statistics.csv
├── deltas.csv
└── charts/
    ├── quality_proxy_score.svg
    ├── citation_coverage.svg
    ├── search_calls.svg
    ├── research_tokens.svg
    ├── wall_seconds.svg
    ├── delta_quality_proxy_score.svg
    ├── delta_search_calls.svg
    └── delta_wall_seconds.svg
```

`statistics.csv` 与 `deltas.csv` 都显式包含 `count / mean / std / median / p50 / p95 / ci_low / ci_high / confidence_level`。Markdown 中也展示 profile 级完整分布，不要求读者必须打开 CSV。SVG 由标准库直接生成，不增加 matplotlib 等运行时依赖。

默认完整实验是 `6 profiles × 20 cases × 5 repetitions = 600 runs`，成本可能很高。默认 5 次更适合工程 smoke；真实 LLM 的方差、p95 与 CI 若要用于正式结论，应提高 repetition 数并结合预算评估。profile 级 pooled statistics 是跨 case 的描述性汇总，严格比较时应优先检查 `profile_case_statistics` 与同一 `(repetition, case)` 的配对 delta。正式跑真实 Provider 前建议先执行：

```bash
uv run python scripts/run_repeated_ablation.py --validate-only --repetitions 5
uv run python scripts/run_repeated_ablation.py --limit 1 --repetitions 2
```

## 第四批：显著性检验与效应量

重复实验报告完成后，`run_repeated_ablation.py` 会对同一批 completed pairs 继续构建推断统计。主检验是 two-sided paired sign-flip randomization test：non-zero pairs 数不超过阈值时穷举全部符号组合，超过阈值后使用固定 seed 的 Monte Carlo sign-flip，并使用 add-one 修正避免报告零 p 值。次要稳健性检验为基于 midrank 动态规划得到 exact null distribution 的 Wilcoxon signed-rank。

效应量同时报告 Cohen’s dz 与 matched rank-biserial correlation。Cliff’s delta 也输出，但明确标记为 supplementary unpaired effect size，因为它不利用当前实验的配对结构。

全局比较采用 `profile_across_cases`：先在每个 case 内对相同 repetition 的 profile/baseline 做配对，再将每个 case 的平均 paired delta 作为统计单元。固定 Case 的 repetition-level 结果使用 `profile_case`。这样不会把 `20 cases × N repetitions` 直接当成彼此独立的 20N 个样本。

主 permutation p-value 在每个 `(scope, case, metric)` family 内对 5 个非 baseline profile 同时计算 Holm–Bonferroni 与 Benjamini–Hochberg 校正。校正不会因某个 profile 全部失败而缩小 family：无有效 pair 的计划比较保留为 `p=1`。当前校正不跨 metric；确认性分析应预先指定主 metric，或增加跨 metric 的二级校正。

第四批曾发现 6-case Core Corpus 的 two-sided exact sign-flip raw 最小 p 为 `0.03125`，5-profile Holm family 的理论最小 adjusted p 约为 `0.15625`，因此确认性结论在数学上不可达。第五批据此将 Corpus 扩到 20 cases；当前 raw exact p floor 约为 `1.91e-6`，最保守 5-way Holm floor 约为 `9.54e-6`，分辨率已不再是主要瓶颈。固定 Case 若仍只跑 5 repetitions，Case 内 raw 最小 p 仍为 `0.0625`，所以 repetition-level 显著性依然需要更多重复。

输出新增 `significance.json`、`significance.csv`、`significance.md`、`charts/significance_effect_sizes.svg` 与 `charts/significance_holm_p.svg`。报告同时写入 theoretical exact p floor、有限 Monte Carlo resamples 的 reportable p floor 与 Holm floor，避免将“检验分辨率不足”误读成“没有效应”。

## 第五批：Corpus 扩容与 Power / Detectable-effect 规划

第四批的分辨率审计说明“p-value 是否可达”和“检验是否有足够 power”是两件事。第五批首先将 Core Corpus 扩展为 20 个 Case / 16 个 category，使全局 exact sign-flip + 5-way Holm 在 `alpha=0.05` 下具备充分离散分辨率；随后新增 `scripts/plan_experiment.py` 做零 Provider 成本的实验设计规划。

Planner 同时给出：当前 N 的 exact raw p floor、worst-case Holm p floor、Holm 可达所需最小独立单元数；以及基于 paired-normal 假设的近似 power、达到目标 power 所需 N、当前 N 的 minimum detectable Cohen’s dz。Holm power 本身没有使用简单闭式近似，规划层采用 Bonferroni `alpha / family_size` 作为保守阈值；最终推断仍使用第四批实现的 permutation/Wilcoxon/Holm。

默认 `alpha=0.05`、family size=5、target power=0.8 时，当前 20-case Corpus 的 MDE 约为 `dz=0.764`。若真实 paired effect 为 `dz=0.8`，保守近似 power 约 `84.2%`，达到 80% power 约需 19 个 Case；若 `dz=0.5`，当前 power 仅约 `36.7%`，约需 47 个 Case；若 `dz=0.2`，约需 292 个 Case。因此 20-case Corpus 足以规划“大效应”确认性实验，但不能据此声称对中小效应也有充分检验能力。

只做规划、不调用 Provider：

```bash
uv run python scripts/plan_experiment.py --validate-only
uv run python scripts/plan_experiment.py \
  --effect-sizes 0.2,0.5,0.8 \
  --output-dir benchmark-results/power-plan-latest
```

输出包括 `plan.json`、`plan.md`、`sample_sizes.csv`、`power_curve.csv` 与 `charts/power_curve.svg`。若已有 pilot paired-delta 标准差，还可通过 `--paired-std` 将 standardized MDE 转换为绝对指标单位的 MDE。

## 第六批：Benchmark Case 质量控制层

`core.json` 的 20 个 Case 均新增 `topic_group`、`source_policy` 和 `gold_rubric`。`source_policy` 明确最少 primary source 数、preferred domains、primary source 类型，以及需要时的 freshness 窗口；preferred domains 是优先来源，不是全局硬 allowlist。当前 14/20 Case 要求至少一个 730 天内的近期来源。

`gold_rubric` 为每个 Case 定义至少 3 个 case-specific required points、critical errors，以及四个统一加权维度：factual correctness 0.35、required coverage 0.30、evidence quality 0.20、trade-off reasoning 0.15；权重必须总和为 1，默认 pass score=0.75。真实 Provider 结果仍需人工按 rubric 评分，不能用 `quality_proxy_score` 替代人工事实正确率。

新增 `scripts/audit_benchmark.py`，审计 source/rubric 覆盖、域名语法、freshness、topic/category/difficulty balance、preferred-domain 集中度与 Case 语义重叠。默认 strict policy 要求至少 20 Case、至少 6 个 topic group、单 topic/category 不超过 25%、medium 至少 20%、hard 不超过 80%、freshness coverage 至少 50%、单一 preferred domain 覆盖不超过 40%。当前分布为 7 个 topic group、最大 topic share=20%、hard/medium=70%/30%、freshness=70%，严格审计为 0 error / 0 warning。

只做质量审计，不调用 Provider：

```bash
uv run python scripts/audit_benchmark.py --validate-only --strict
uv run python scripts/audit_benchmark.py --strict \
  --output-dir benchmark-results/quality-audit-latest
```

输出包括 `quality.json`、`quality.md`、`cases.csv`、`charts/topic_balance.svg` 和 `charts/difficulty_balance.svg`。

## 第七批：运行后来源合规与人工双盲评审

Evidence schema 增加 `source_class / published_at / retrieved_at`。`web_search` 的 `source_class` 与 `retrieved_at` 由程序生成，`published_at` 只透传 Provider 真正提供的 metadata；Evidence Manager 对 `source_class=unknown` 和缺失 `retrieved_at` 做确定性兜底，但绝不推测发布日期。

`score_source_policy()` 按 Case 的 `source_policy` 计算 primary-source 数、preferred-domain 命中、recent-source 数与 freshness metadata 覆盖。若 freshness 必需但 Evidence 没有可靠 `published_at`，对应 check 为 `unverifiable`，整体不视为通过。CLI：`uv run python scripts/score_source_policy.py --case-id <id> --evidence <json>`。

人工层使用不携带 model/profile/provider 身份的 `HumanReviewPacket`。每位 reviewer 独立提交 0–4 ordinal criterion ratings、required-point coverage 和 critical-error flags；weighted score 归一到 0–1，critical error 是独立 veto。双评审后计算 pass/fail Cohen's κ、criterion-level quadratic weighted κ 与平均 score gap。pass/critical 分歧或 score gap 达阈值的 blind item 必须进入 adjudication。

`review_benchmark.py prepare` 生成盲评包；`review_benchmark.py audit` 汇总 reviewer/adjudicator JSON，并输出 `human_review_audit.json / human_review_audit.md / human_review_outcomes.csv`。工程 proxy、自动 source compliance 和人工 gold score 是三条独立指标轴，不相互冒充。

## 当前验证边界

第一批使用 synthetic final-state 与 fake streamed graph 验证指标和轨迹；第二批使用 synthetic profile graph 验证 Settings/Graph 消融语义；第三批使用可控重复 synthetic graph 验证重复统计；第四批用可手算 paired fixture 验证 exact sign-flip、Wilcoxon、Cohen’s dz、rank-biserial、Cliff’s delta、Holm/BH 与分辨率；第五批验证 20-case Corpus 多样性、exact-Holm 可达性、paired-normal power/MDE 单调性和规划报告；第六批验证 source/rubric 完整性、域名/freshness 策略与 Corpus balance guard；第七批验证 Evidence metadata、source-policy compliance、双评审 agreement 与 adjudication。这些 fixture 只证明实验基础设施正确，不代表真实 Provider 的 Benchmark/Ablation/统计成绩。

真实 Provider + Tavily 仍因服务器缺少凭据而阻塞，因此当前只验证运行后质量管线的 synthetic fixture，不提交伪造的真实来源合规率、人工 gold score 或 agreement 结论。

## 后续批次

真实 Provider 凭据可用后，先用低成本 Case 产生真实 Evidence，执行 source-policy compliance；随后生成 blind packet 做独立双评审与必要 adjudication，再按预算运行 20-case repeated/ablation，并用真实 paired variance 回填 `--paired-std`。若目标转向 `dz≈0.5` 的中等效应确认性结论，应优先继续扩充独立 Case，而不是只增加同一 Case 的 repetitions。对于 citation 消融继续保持“保留 verifier 测量、只关闭 feedback”的实验设计，避免测量口径随处理组变化。
