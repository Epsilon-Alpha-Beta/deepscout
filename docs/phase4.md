# Phase 4：Benchmark 与轨迹级评测

Phase 4 分十五批推进：第一批建立 Benchmark/trajectory 基座；第二批加入 Ablation Matrix；第三批加入重复实验与 bootstrap 统计；第四批加入配对显著性检验、效应量和多重比较校正；第五批扩充 Core Corpus 并加入 power/MDE 规划；第六批建立 Case 来源政策、人工 gold rubric 与 balance 审计；第七批把质量控制延伸到真实 Evidence 与人工双盲评审；第八批把 source compliance、human gold 与 reviewer agreement 接入 repeated/ablation 聚合，并加入 human-gold paired significance；第九批把整次实验封装为可校验 Experiment Bundle，并支持跨 bundle regression comparison；第十批建立 Experiment Registry/History、last-known-good baseline lineage 与长期趋势 dashboard；第十一批加入 Promotion/Retention 生命周期、人工 override 与安全资产保留策略；第十二批加入 policy-as-code Release Readiness/CI Gate，统一 Registry 完整性、Promotion eligibility 与 Retention preview；第十三批把 Gate 接入 artifact-driven GitHub Actions；第十四批加入 20-shard Benchmark Experiment Producer；第十五批为 Producer 增加失败 run shard 恢复、执行前预算护栏和 provenance 审计。当前仍不会在缺少真实 Provider/Tavily 凭据时伪造真实质量结论。

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

## 第八批：运行后质量聚合与 Human Gold 显著性

质量数据采用 sidecar 设计：原始 repeated run 不被人工评审结果回写。`SourceQualityObservation` 和私有 `BlindReviewAssignment` 以 `(profile, repetition, case_id)` 对齐运行单元；匿名 review packet 本身继续不包含 profile/model/provider/repetition。sidecar 若引用不存在的 run、重复绑定同一 run 或出现未知 blind item 会直接拒绝。

`RuntimeQualityAggregateReport` 同时输出 profile 与 profile×case 的 source observation coverage、source evaluable rate、source compliance rate、human review coverage、human gold pass rate、human gold score 分布以及 reviewer agreement。缺失值语义严格保留：freshness `unverifiable` 不算失败，未评审/待仲裁不填 0，失败 run 不进入 paired significance。

Human gold paired delta 按同一 `(repetition, case)` 计算。全局 `profile_across_cases` 推断先在 Case 内聚合 repetitions，再跨 Case 使用现有 sign-flip、Wilcoxon、Cohen dz、rank-biserial、Cliff delta 与 Holm/BH；因此仍以 Case 为全局统计单元。

CLI：`uv run python scripts/aggregate_runtime_quality.py --repeated <repeated.json> ...`。输出包括 `quality_aggregate.json / quality_aggregate.md / quality_observations.csv / quality_statistics.csv / human_gold_deltas.csv`、`charts/source_policy_pass.svg`、`charts/human_gold_score.svg`、`charts/delta_human_gold_score.svg`，以及有足够 paired gold 数据时的 `human_gold_significance.json/csv/md`。

## 第九批：Experiment Bundle 与 Regression Comparison

`ExperimentBundleManifest` 将 repeated artifact、Corpus、Ablation Matrix、可选 quality aggregate 和额外结果复制到 bundle 的 `artifacts/`，记录 logical role、SHA-256 与字节数，并记录 project version、Git SHA/dirty、Provider/Model、实验 identity 与运行配置。Bundle validator 会重新计算 hash，并校验 Corpus/Matrix 文件内容与 repeated identity；只要文件被篡改或 identity 漂移就判 invalid。

创建 CLI：`uv run python scripts/create_experiment_bundle.py --repeated ... --quality-aggregate ... --provider ... --model ... --output-dir ...`；校验：`--validate <bundle>`。在 Docker 等没有 `.git` 的环境中必须显式传 `--git-sha`（可选 `--git-dirty`），避免不可追溯的 `unknown` Git 身份。

`compare_experiment_bundles()` 先做 compatibility gate：Corpus name/version、Matrix name/version、baseline 和 profile set 必须一致；repetitions、Provider/Model 差异记录为 warning。只有兼容实验才比较 repeated/quality profile metrics。默认阈值使用 `max(absolute_threshold, |baseline| × relative_threshold)`，方向和两个原始 threshold 都写入 comparison artifact。

`compare_experiments.py --fail-on-regression` 在发现 regression 时 exit 1，在 identity 不兼容时 exit 2，可直接作为 CI/发布门禁。报告输出 `comparison.json / comparison.md / comparisons.csv`。

## 第十批：Experiment Registry / History 与 Last-known-good Baseline

Registry 递归发现 bundle，并先复用第九批 validator 做 SHA-256、路径和 identity 完整性检查。experiment ID 必须在 Registry 内全局唯一；tampered、重复 ID 或其它 invalid bundle 都不会进入 lineage。Compatibility key 只由 Corpus name/version、Matrix name/version、baseline 和 profile set 构成，因此 repetitions、Provider/Model 差异仍允许比较并以 warning 记录。

组内按 `created_at` 排序并维护 last-known-good：lineage root 后，每个 candidate 对比最近 accepted bundle；regression 不推进 baseline，accepted 才推进。这避免一次坏实验成为后续对比基线，也让跨多次提交的回归判断具有稳定参照。

CLI：`uv run python scripts/build_experiment_registry.py --bundles-root <root> --candidate-id <id> --fail-on-regression --output-dir <dir>`。候选 regression exit 1，不存在/invalid exit 2，accepted/baseline exit 0；可选 `--fail-on-invalid`。

输出 `registry.json / registry.md / registry_entries.csv / lineage.csv / history_metrics.csv` 与 baseline-profile SVG 趋势图。Synthetic history smoke 已验证：b2 regression 仍以 b1 为 baseline；b3 accepted 后推进 baseline；b4 随后自动以 b3 对比，即使 Provider/Model 改变也只产生 warning。

## 第十一批：Promotion / Retention Lifecycle

Promotion 与 Registry gate 分层：Registry 的 accepted 表示“可作为后续自动比较的 last-known-good”，PromotionDecision 的 promote 表示“正式发布/长期保留意义上的 promoted baseline”。默认 policy 只允许 valid + baseline/accepted + clean git + zero regression 自动晋级。Regression/dirty bundle 可以显式 override，但必须记录 actor/reason；invalid bundle 不允许 override。

Promotion decision 本身是审计 artifact，并保留 policy snapshot、blockers、eligible/action/override 状态。多个 decision 采用 latest-wins；Retention 会校验 decision compatibility key 与当前 Registry entry 一致，防止旧快照继续生效。

Retention policy 默认保留最近 3 个 accepted、2 个 regression，保护 promoted、lineage root 与显式 milestone；默认启用 lineage closure，保证 retained candidate 所依赖的 baseline 祖先链不会被裁掉。Invalid 默认进入删除候选，但真正 apply 时仍需通过路径/manifest/experiment-id 安全校验。

CLI：`uv run python scripts/manage_experiment_lifecycle.py promotion ...` 与 `... retention ...`。Retention 不带 apply 参数时只生成 plan；`--dry-run-apply` 产生 would_delete；`--apply-retention` 才真正删除。Apply 拒绝 bundles root、root 外路径、缺失/不可解析 manifest 与 experiment-id mismatch。

Synthetic lifecycle smoke 已验证 accepted promotion、regression blocked gate、manual override、latest-decision-wins、stale-decision rejection、milestone/promoted/lineage protection，以及 dry-run/apply 只删除目标 bundle。

## 第十二批：Release Readiness / CI Gate

第十二批把第十、十一批已经分层的 Registry 与 Lifecycle 能力组合为单次自动化发布判定。`ReleaseGatePolicy` 默认要求 Registry 零 invalid bundle，并复用 `PromotionPolicy` 与 `RetentionPolicy`，避免 CI 脚本重新实现一套与库代码漂移的规则。

`evaluate_release_gate()` 对候选先检查 Registry 全局完整性，再执行不可 override 的自动 Promotion 判定，并用该 decision 构造 Retention preview。Gate 通过必须同时满足“无全局 blocker”且 promotion action 为 `promote`。候选自身的 Registry warning 保留为 warning，不会被静默吞掉。

默认 policy 固化在 `benchmarks/policies/release_gate.json`。CLI：

```bash
uv run python scripts/gate_experiment_release.py   --registry benchmark-results/experiment-registry-latest/registry.json   --candidate-id <experiment-id>   --output-dir benchmark-results/release-gate-latest
```

输出 `release_gate.json/md`、`promotion_decision.json/md` 与 `retention_plan.json/md/csv`。exit 0 表示 gate passed，exit 1 表示策略阻塞，exit 2 表示输入或身份错误。

安全边界是有意设计的：Release Gate 不暴露 manual override，也不调用 `apply_retention_plan()`；因此 CI 只能判断和生成预览，不能自行绕过发布政策或删除历史 bundle。需要人工例外或真实删除时，仍必须显式使用第十一批 Lifecycle CLI，并留下 actor/reason 或 apply 审计。

## 第十三批：Artifact-driven GitHub Actions Gate

`.github/workflows/release-gate.yml` 把 Release Gate 封装为 reusable workflow，同时支持 `workflow_call` 与 `workflow_dispatch`。输入 contract 只有候选 `experiment_id`、Bundle artifact 名和可选 `source_run_id`；workflow 不接受 override 或 retention apply 参数。

当前 run 模式用于上游 benchmark/repeated job 在同一 workflow 上传 Bundle 后直接调用 Gate。历史 run 模式会显式传 `github-token + repository + run-id` 给 `actions/download-artifact`；手动触发要求 `source_run_id`，避免误以为当前空 run 自带实验资产。下载后的目录仍由 Registry 递归发现 manifest，因此 artifact 可以包含一个或多个 Bundle。

Gate runner 使用生产依赖 `uv sync --frozen --no-dev`，随后执行 `build_experiment_registry.py` 与 `gate_experiment_release.py`。候选 ID 与 actor 通过环境变量传给 shell，避免 workflow input 直接形成命令注入面。输出目录会作为 `deepscout-release-gate-audit` 上传 14 天，并把 `release_gate.md` 追加到 GitHub Step Summary。

主 `CI` 使用现有 synthetic history 做 artifact-boundary smoke：test job 生成 7 个 Bundle 并上传 1 天期 artifact，`release-gate-smoke` job 再通过 reusable workflow 下载并对 `b3` gate。这个 smoke 的目标是验证“跨 job artifact → Registry → Gate → audit artifact”的生产路径，而不是生成任何真实 Benchmark 结论。

本地还做了独立 artifact round-trip：7 个 Bundle 经 ZIP 压缩/解压后放到全新目录，再在全新的 production-only venv 中重建 Registry；结果仍为 7 valid / 1 compatibility group，`b3` 为 `passed/promote`，证明 Gate 不依赖原测试目录或 dev dependency。

远端 GitHub Actions current-run smoke 也已通过：artifact 下载校验成功，发现 7 个 manifest，Registry 为 7 valid / 0 invalid / 1 compatibility group，`b3` 输出 `passed/promote`，并成功生成 GitHub Step Summary 与 `deepscout-release-gate-audit` artifact。历史 run 下载路径已完成 workflow contract 校验，但本批未将其记为远端已调度执行。

## 第十四批：Sharded Benchmark Experiment Producer

`.github/workflows/benchmark-producer.yml` 是真实实验入口，只支持手动 `workflow_dispatch`。它先运行 Provider/Tavily/Graph staged preflight，并将诊断 JSON 上传为短期 artifact。模型使用 `DEEPSCOUT_MODEL` 输入；Anthropic/OpenAI/Google 与 Tavily 凭据只从 GitHub Secrets 注入，workflow 不接受明文 key 输入。

`smoke` 协议固定为 1 case × 6 profiles × 1 repetition = 6 runs，不消费历史 lineage，也不会调用 Release Gate。`official` 协议固定为 20 × 6 × 5 = 600 runs：continue 模式要求数值 `history_run_id` 和确认字符串 `RUN_OFFICIAL_600`；new 模式禁止历史 run ID，并要求更强的 `RUN_OFFICIAL_600_NEW_LINEAGE`。这两个 guard 用于同时控制真实 API 成本和 baseline reset 风险。

由于 GitHub-hosted job 最长运行 6 小时，official 按 `repetition=[1..5] × case_shard=[0..3]` 形成 20 个 matrix job，每片 5 cases × 6 profiles = 30 runs，`max-parallel=2`。每个 repetition 的临时 Matrix 先按目标 repetition 旋转 profile 顺序，然后 shard 内以 fixed order 执行；因此并行 case sharding 不改变原 repeated protocol 的 profile rotation 语义。

`RepeatedShardMetadata` 记录目标 repetition、case shard、case IDs 与 repeated artifact 相对路径。`load_repeated_shards()` 拒绝路径逃逸；`merge_repeated_shards()` 进一步校验 canonical Corpus/Matrix identity、case 内容、bootstrap 参数、source repetitions=1、unknown profile/case、重复 shard/unit 以及全量 coverage。合并输出按 canonical case 顺序确定性重建 execution order，再复用 `build_repeated_report()` 与现有 significance pipeline。

本地以 5 repetitions × 4 case shards 的完整 synthetic topology 验证：20 个 shard 成功合并为 600 个唯一 `(repetition, profile, case)` 单元；2-repetition focused test 同时验证 rotation；duplicate shard、缺失 coverage 与 repeated-path escape 均被拒绝。Producer 后半段的 Bundle/Registry 能力继续复用第九至十三批实现，不另造旁路规则。

正式 continue 模式在 assemble job 中下载上一条 `deepscout-experiment-bundles` artifact，先做 Registry integrity 检查，再追加本次 candidate。组合 lineage artifact 上传后，当前 run 直接调用 reusable Release Gate；new 模式必须显式确认才允许从空 lineage 开始。真实 Provider 凭据当前仍缺失，因此本批不声称真实 smoke 或 official 结果已执行。

## 第十五批：Resumable Producer、预算护栏与 Provenance

第十五批在第十四批 20-shard Producer 之上增加恢复协议。每次 workflow 都先生成不可变 `ProducerPlan`，其中包含 Git SHA、模型、Corpus/Matrix SHA-256、lineage、实验拓扑与预算上界；`compatibility_fingerprint` 不包含当前 workflow run identity，因此同一实验定义的重试可以匹配，但 Git、模型、Corpus、Matrix、lineage 或拓扑变化都会产生不同 fingerprint 并阻断 shard 复用。

手动触发新增 `resume_run_id`。它只用于失败/中断的 official producer run：preflight 下载该 run 的 `deepscout-producer-plan` 与 artifact inventory，忽略 expired artifact，并拒绝 artifact API 分页截断。若来源 run 已经包含 `deepscout-experiment-bundles`，说明该实验已经 finalized，因此禁止再作为 resume source，避免把同一完成实验重复生产。

执行成本 guard 在 live Provider/Tavily preflight 之前计算。除 `max_new_shards` 外，还加入 `max_new_search_calls` 和 `max_new_research_tokens`。上界从当前 Ablation profile settings 与 DeepScout Settings 默认值动态计算：每个 5-case shard 为 1,060 search calls / 5,250,000 Research Worker tokens，20-shard official 为 21,200 / 105,000,000。该数值只表示 DeepScout 内部预算允许的最坏工程上界，不等同于真实调用量、总 token 用量或 Provider 账单。

每个 matrix shard 下载当前 Resume Plan，并查询自己的 `(repetition, case_shard)` 决策。reuse shard 从 `resume_run_id` 下载；execute shard 才构造临时 Corpus/Matrix 并运行 30 units。两类 shard 都必须经过 `validate_repeated_shard()`，严格验证 canonical partition、profile rotation、execution order、case 内容和 30-unit shape。之后统一生成当前 run 的 `provenance.json`。

assemble 阶段首先用 `validate_shard_provenance_set()` 将 20 份 provenance 与 Resume Plan、当前 Producer fingerprint、run ID/attempt、Git SHA 和 source run ID 对齐，只有 closure 完整才允许执行 repeated merge。正式 Experiment Bundle 额外固化 `producer_plan`、`resume_plan` 与 `shard_provenance`，使恢复路径成为实验可复现证据的一部分。

本地 synthetic E2E 已验证 17 reused + 3 executed 的典型断点恢复：复用 510 run units，只新增 90 units；新执行预算上界为 3,180 searches / 15,750,000 Research Worker tokens；20 个 shard provenance 校验后仍合并为完整 600-run experiment。另有 focused tests 覆盖 fingerprint 漂移、shard/search/token budget blocking、finalized source、expired artifact、artifact pagination、provenance 篡改以及单 shard coordinate/canonical 校验。真实 Provider 凭据仍缺失，因此本批不声称远端真实恢复或真实 API 成本已经验证。

## 当前验证边界

第一批使用 synthetic final-state 与 fake streamed graph 验证指标和轨迹；第二批使用 synthetic profile graph 验证 Settings/Graph 消融语义；第三批使用可控重复 synthetic graph 验证重复统计；第四批用可手算 paired fixture 验证 exact sign-flip、Wilcoxon、Cohen’s dz、rank-biserial、Cliff’s delta、Holm/BH 与分辨率；第五批验证 20-case Corpus 多样性、exact-Holm 可达性、paired-normal power/MDE 单调性和规划报告；第六批验证 source/rubric 完整性、域名/freshness 策略与 Corpus balance guard；第七批验证 Evidence metadata、source-policy compliance、双评审 agreement 与 adjudication；第八批验证 sidecar 绑定、缺失值语义、profile/case 聚合、human-gold paired delta/significance 与报告产物；第九批验证 bundle hash/identity、tamper detection、compatibility gate、thresholded regression 与 CLI exit semantics；第十批验证多 bundle discovery、duplicate ID rejection、invalid exclusion、last-known-good lineage、history gate 与 dashboard 产物；第十一批验证 promotion policy、manual override、latest decision、stale decision rejection、retention lineage closure 与安全 apply；第十二批验证 strict/relaxed Registry integrity、accepted/regression release gate、policy-as-code、统一审计 artifact 与非破坏性 retention preview；第十三批验证 reusable workflow contract、当前/历史 run artifact 下载路径、production-only runtime、artifact round-trip 与 CI smoke orchestration；第十四批验证 producer protocol guards、20-shard/600-unit merge、profile rotation 重建、duplicate/missing/path-escape guards 与 lineage 继承 contract；第十五批验证不可变 Producer Plan、跨失败 run shard reuse、shard/search/token 三层预算、单 shard canonical validation、provenance closure、finalized source rejection 与 17-reused/3-executed 恢复管线。这些 fixture 只证明实验基础设施正确，不代表真实 Provider 的 Benchmark/Ablation/统计成绩。

真实 Provider + Tavily 仍因服务器缺少凭据而阻塞，因此当前只验证运行后质量聚合的 synthetic fixture，不提交伪造的真实来源合规率、人工 gold score、agreement 或显著性结论。

## 后续批次

真实 Provider 凭据可用后，先用低成本 Case 产生真实 Evidence，执行 source-policy compliance，并将生成的真实 Bundle 接入 Release Gate；随后生成 blind packet 做独立双评审与必要 adjudication，再按预算运行 20-case repeated/ablation，并用真实 paired variance 回填 `--paired-std`。若目标转向 `dz≈0.5` 的中等效应确认性结论，应优先继续扩充独立 Case，而不是只增加同一 Case 的 repetitions。对于 citation 消融继续保持“保留 verifier 测量、只关闭 feedback”的实验设计，避免测量口径随处理组变化。
