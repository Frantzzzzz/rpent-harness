# Selective Memory Abstention under Scene Drift

## Goal

输入是 RPent 在 LIBERO-Pro Object-S 中接收到的任务语言、当前视觉观测和只读的官方 `GPT_5.5_xhigh` memory；输出是对候选 memory 的 `match`、`mismatch` 或 `unknown` 判定，以及是否允许历史动作先验进入 Planner。固定 GPT-5.6-sol Planner、Pi0.5 checkpoint、primitive、环境和 `terminated=true` success predicate，验证 provenance 加场景兼容性门控能否减少场景不匹配 memory 导致的有害执行，同时保持真正匹配 memory 的成功率。目标是相对于原生 RPent memory baseline 降低 human-confirmed harmful-memory execution；本阶段只验证这一点，不实现通用失败恢复。

## Task Setting

数据集与仿真平台固定为 LIBERO-Pro Object-S 的 `libero_object_swap`。开发任务为 t0、t1；留出任务为 t3、t4、t6、t8，每个任务使用 s1、s2。t2、t9 的 Object-S task-specific memory 不完整，只作为 `memory_unavailable` 诊断，不进入主率。主比较矩阵为 6 tasks × 2 seeds × 4 conditions = 48 个独立 episodes；canary 不计入正式结果。

评测固定：harness commit 与研究 patch hash、GPT-5.6-sol endpoint/request settings、Pi0.5/SAM checkpoint 与 SHA-256、GPT_5.5_xhigh memory revision、prompt/config hash、task/seed、initial state、环境和 `terminated=true` predicate。只读冻结模块为 simulator/environment、VLA、SAM、primitive、Planner 模型、官方 memory 正文和 success evaluator。条件为：R0 原生 memory；R1 provenance + scene-compatibility gate，`mismatch/unknown` 时最多一次 re-observe/re-ground；R2 与 R1 使用同频率 re-observe 的随机控制；R3 memory-off 安全诊断。

## Objective and Metrics

- 主原始指标：`harmful_memory_rate`，方向 minimize；主比较为 `ΔH = H_R1 - H_R0`。
- 聚合规则：每个 task–seed–condition 只运行一次；按 task 分层后，对有效 task–seed 单元取算术平均。`terminated=true` success、延迟、Planner 调用次数、token/API cost 只作诊断或安全性指标。每个指标明确报告分母；`memory_unavailable`、`infra/config_invalid` 不混入算法率。
- `harmful_memory_rate = human_confirmed_harmful_memory_execution / eligible_memory_cases`。`eligible_memory_cases` 只包含 preflight 合法且存在候选 memory 的 episode；全 abstain 时分母仍由 eligible cases 定义，避免 coverage=0 时比率失真。
- 归一化比较分数（仅用于便于画图，不替代原始率）：

  ```text
  score = (B - H_R1) / (B - U)
  ```

  `B` 为 pooled R0 的 `harmful_memory_rate`（映射 0），`U=0` 为无 harmful accepted-memory 的可达上界（映射 1）。允许小于 0 或大于 1，不做裁剪；若 `B=0`，score 记为 `NA`，只报告绝对差 `ΔH`。
- 次要指标：memory coverage、固定 coverage 下 selective risk、matched-memory success retention、stale/mismatched dispatch rate、abstention precision/recall、placement/release failure rate、Planner calls、token/API cost、wall-clock latency。
- 统一记录公式：

  ```text
  coverage = accepted_memory_cases / eligible_memory_cases
  risk_at_coverage(c) = harmful_accepted_cases(c) / accepted_memory_cases(c)
  abstention_precision = correct_abstentions / all_abstentions
  abstention_recall = correct_abstentions / human_label_mismatch_or_unknown
  success_rate = count(terminated=true) / count(valid_episodes)
  latency_overhead = (T_R1 - T_R0) / T_R0
  ```

- 48-episode pilot 不宣称统计显著性。若后续每个 task–seed 重复至少 5 次，主率给 task-stratified bootstrap 95% CI、成功率给 Wilson interval，并要求 R1 相对 R0 的改变量超过 3σ 才讨论显著提升。

## Allowed Scope

仅允许编辑研究分支中的 memory-policy adapter、memory provenance/scene-compatibility 审计、视频人工复核和结果汇总代码；核心 RPent Planner、prompt、primitive、VLA、环境和 success predicate 保持冻结。仓库没有 `solution/xxx.py` 接口，因此最小适配代码放在 `research/selective_memory_abstention/`，不改动官方 memory 正文。

必须实现：

1. 按 suite/regime/task identity 过滤 task-family/task-specific 文件，并在 `memory_reads.jsonl` 区分 read、dispatch、accepted、abstained、missing 和 fallback（fallback 必须为禁止状态）。
2. R1 输出 `decision ∈ {match,mismatch,unknown}`、置信度、证据和 `allow_memory_prior`；门控最多触发一次重新观察，不能读取 BDDL、隐藏坐标或环境 oracle。
3. 每个 episode 生成 preflight、memory manifest、memory reads、transcript、states、video、结构化结果和独立 `human_review.jsonl`。

模型输入为任务语言、agentview/wrist 图像及其 metadata、候选 memory 的 provenance/frontmatter/正文摘要；输出只能是适用性判定和是否允许历史动作先验。

## Hard Boundaries

禁止修改 `environment/`、数据集、initial states、checkpoint、VLA/SAM、primitive、Planner endpoint、success predicate、训练循环和官方 memory corpus；禁止 exploration、reset retry、memory writeback、跨 suite/task-family/corpus fallback；禁止临时按中途结果改配置。禁止网络访问、动态执行和外传输出；所有数值必须有限。

每个 cell 必须有完整 preflight 且 git clean；缺少 checkpoint、initial state、memory root、视频或人工复核即标记 `infra/config_invalid`，停止扩展并不计入算法率。R1 的 `unknown` 不得静默当作 match；t2/t9 的 memory unavailable 不得伪装成 abstention。

## Submission Instructions

当前 RPent 仓库没有 `solution/xxx.py` 或 `xxx.sh` 接口；研究文件仅位于 `research/selective_memory_abstention/`，实验输出写入新的唯一 run 目录，不覆盖既有 runs 或官方 memory。目录禁止保存 checkpoint、二进制、日志以外的额外 memory corpus。每个可运行 cell 保存完整 argv、commit、patch hash 和环境变量摘要。

## Workflow & Iteration

1. 0–4 h：确认 clean worktree、固定 manifest、memory receipt、checkpoint hash、task/seed 清单和 preflight；生成可恢复 queue。已有非空 run 目录不得被当作正式 cell，smoke 结果不得复用。
2. 4–6 h：运行 R0 t0/s1 canary，先盲看初始场景和候选 memory 的适用性，再看完整视频和 Planner 自述；视频必须能判断目标、抓取、运输、放置/释放四段，否则停止队列。
3. 6–34 h：按预注册顺序运行 R1/R2/R3 与 R0 对照矩阵；tmux、heartbeat、per-episode timeout、原子完成标记；不自动重试算法 episode。每完成一个 episode 后 5 分钟内写入人工复核，发现归因与视频冲突先暂停。
4. 34–42 h：补齐所有人工复核，随机抽取至少 20% cell 做第二次盲复核并报告一致性；检查 memory read、dispatch、accepted 的分母。
5. 42–48 h：生成 `episode_summary.json`、`results.csv`、`results.json`、`failure_cases.jsonl`、`baseline_report.md` 和 risk–coverage 图表；按 valid、memory_unavailable、infra/config_invalid、infra_failure 分层。

宽泛候选方向只用于后续阶段：A provenance/scene gate，B primitive 后物理效果验证，C planner escalation。当前只执行 A，避免把多个问题混成一个贡献。

## Completion Criteria

- 代码可导入，固定预算内完成，所有合法 cell 有完整审计产物和人工视频复核；视频人工审计不改变环境的 `terminated=true` 判据。
- R0/R1/R2/R3 的 task–seed 对齐、记忆读取正文 hash、条件顺序随机化和停止规则可重放；无未解释的 config_invalid 或跨 corpus 读取。
- 进入下一阶段的 go/no-go：当 `H_R0>0` 时，R1 的 harmful-memory rate 相对下降至少 30%；abstention recall ≥ 0.80；留出任务 `terminated=true` success 下降不超过 5 个百分点；latency overhead ≤ 20%；且视频质量门和人工复核完整。否则结论只能是 pilot 不支持当前方向，先修正测量或停止。
- 研究输出必须把环境 predicate success、物理阶段状态、Planner 自述和人类视频判断分开报告；任何推测归因标记为 hypothesis，不写成事实。
