# Selective Memory Abstention under Scene Drift

## Goal

输入是 RPent 在 LIBERO-Pro Object-S `libero_object_swap` 中接收到的任务语言、当前视觉观测以及官方 `GPT_5.5_xhigh` memory；输出是对候选历史 memory 的适用性判定和是否允许其动作先验进入 Planner。固定 GPT-5.6-sol Planner、Pi0.5/SAM3、primitive、仿真环境、initial states 和 `terminated=true` success predicate，比较原生 RPent memory 与 scene-drift selective abstention。目标是在不改变匹配场景表现的前提下，降低人类视频复核确认的有害陈旧 memory 执行；本阶段只验证这一研究问题，不实现通用失败恢复。

## Task Setting

数据集和仿真平台固定为 LIBERO-Pro Object-S 的 `libero_object_swap`。主评测任务为 t0、t1、t3、t4、t6、t8，每个任务使用 s1、s2；t2、t9 的 task-specific memory 不完整，只做 `memory_unavailable` 诊断，不进入主率。正式矩阵为 6 tasks × 2 seeds × 4 conditions = 48 个独立 episodes；canary 不计入正式统计。

evaluator 固定：harness git commit、GPT-5.6-sol endpoint/request 配置、Pi0.5 checkpoint、SAM3 checkpoint、官方 `GPT_5.5_xhigh` memory revision、prompt/config hash、task/seed、initial state、环境和 `terminated=true` 判据。只读冻结模块为环境、VLA、SAM3、primitive、Planner、官方 memory 正文和 success evaluator。四个条件为：R0 原生 memory；R1 provenance + scene-drift gate；R2 与 R1 使用同频率 re-observe 的随机控制；R3 memory-off 诊断。所有条件关闭 exploration、reset retry 和 memory writeback。

## Objective and Metrics

- 主原始指标：`harmful_memory_rate`，方向 minimize。
- 聚合规则：每个 task–seed–condition 只运行一次；按 task 分层后对有效 task–seed 单元取算术平均。`terminated=true` success、wall-clock latency、Planner 调用次数和 token/API cost 作为诊断指标。
- 归一化公式：`score = (B - H_R1) / (B - U)`。
  - `B = H_R0`，即同一有效 episode 集合上的 R0 harmful-memory rate，映射 0。
  - `U = 0`，即没有 harmful accepted-memory execution，映射 1。
  - 允许 score 小于 0 或大于 1，不做裁剪；若 `B=0`，score 为 `NA`，只报告绝对差 `ΔH = H_R1 - H_R0`。
- `harmful_memory_rate = human_confirmed_harmful_memory_execution / eligible_memory_cases`；分母只含 preflight 合法且存在候选 memory 的 episode。另报 memory coverage、fixed-coverage selective risk、matched-memory success retention、abstention precision/recall、失败阶段、延迟开销和环境 success rate。
- 48-episode pilot 不宣称统计显著性。若后续每个 task–seed 至少重复 5 次，才计算 task-stratified bootstrap 95% CI；随机任务只有在 R1 相对 R0 的改变量超过 3σ 时才称为统计提升，确定性任务删除该条件。

## Allowed Scope

本仓库没有 `solution/xxx.py` 接口；对应的唯一可改范围是 `research/selective_memory_abstention/` 中的审计、memory-policy adapter、视频人工复核和结果汇总代码，以及为接入该 adapter 所需的最小接口改动。必须实现：

1. 对 task-family/task-specific memory 做 provenance 和 scene-drift 决策，结构化记录 `match|mismatch|unknown`、证据、置信度、`allow_memory_prior`、read/dispatch/accepted/abstained/missing/fallback 事件；禁止 fallback。
2. 每个 episode 输出 `preflight.json`、`memory_manifest.json`、`memory_reads.jsonl`、transcript、states、video、结构化结果和独立 `human_review.jsonl`；视频人工复核必须在 episode 完成后及时执行。

输入输出契约：policy adapter 只接收任务语言、agentview/wrist 图像及 metadata、候选 memory provenance/frontmatter/正文摘要；只输出适用性判定和是否允许历史动作先验。不得读取 BDDL、隐藏坐标或环境 oracle。

## Hard Boundaries

禁止修改 `environment/`、数据集、initial states、checkpoint、VLA/SAM3、primitive、Planner prompt/策略、训练循环、seed、success predicate 和官方 memory corpus；禁止 exploration、reset retry、memory writeback、跨 suite/task-family/corpus fallback 或依据中途结果改实验配置。禁止网络访问、动态执行和外传实验内容；数值输出必须有限。

每个 cell 必须有 clean-worktree preflight。缺少 checkpoint、initial state、memory root、视频、memory-read 证据或人工复核时，标记 `infra/config_invalid`，停止扩展且不计入算法率。`unknown` 不得静默转为 `match`；t2/t9 的 `memory_unavailable` 不得伪装为 abstention。人工复核必须区分环境返回、物理阶段事实、Planner 自述和人类推断；推测只能标为 hypothesis。

## Submission Instructions

当前任务的提交面是本研究分支和审计产物，而非通用 benchmark 的 `solution/xxx.py`。代码改动只放在 `research/selective_memory_abstention/` 及已明确的 memory-policy 接口；每个实验使用新的唯一 run 目录，不覆盖既有 runs。禁止提交 checkpoint、额外 memory corpus、二进制或未经审计的结果文件。每个 run 保存完整 argv、commit、patch hash、配置摘要和人工视频复核记录。

## Workflow & Iteration

1. 先检查代码、配置、memory revision、checkpoint hash、initial states 和 clean worktree；生成 preflight 与 memory manifest。
2. 运行新的 R1 scene-drift t0/s1 canary；完成后 5 分钟内人工看视频，并核对 memory-read 日志、视频、states、transcript 和环境结果。发现审计或视频冲突立即停止。
3. canary 通过后，按固定顺序运行 R0/R1/R2/R3 的 48-cell paired pilot；tmux、heartbeat、每 episode timeout 和原子完成标记只用于可恢复执行，不自动重试失败 episode。
4. 每个 episode 结束后及时完成人工盲复核，标注目标识别、抓取、运输、放置/释放、恢复动作和 harmful memory execution；至少 20% cell 做第二次盲复核。
5. 完成后生成 `episode_summary.json`、`results.csv`、`results.json`、`failure_cases.jsonl`、`baseline_report.md` 和 risk–coverage 图；按 valid、memory_unavailable、infra/config_invalid、infra_failure 分层。

单轮迭代资源：固定服务器上的现有 GPU/服务；每个 episode 使用当前官方 timeout 和 `max_episode_steps=10000`，总运行窗口不超过 48 小时。宽泛方向 A（scene gate）、B（primitive 后物理验证）、C（Planner escalation）只作为后续候选，本任务只执行 A。

## Completion Criteria

- 代码可导入，固定预算内完成；每个合法 cell 都有完整 preflight、memory 正文读取证据、视频、states、transcript、结构化结果和人工复核。
- R0/R1/R2/R3 的 task–seed 对齐、memory hashes、条件配置、停止规则可重放；无跨 corpus 读取、无 memory 写回、无未解释的 config_invalid。
- 进入下一阶段的 go/no-go：当 `H_R0>0` 时，R1 harmful-memory rate 相对下降至少 30%，abstention recall ≥ 0.80，留出任务 `terminated=true` success 下降不超过 5 个百分点，latency overhead ≤ 20%，且视频质量门和人工复核完整。否则只报告 pilot 不支持当前方向，不在本任务内继续改方法。
- 最终报告将环境 predicate success、物理阶段状态、Planner 自述和人类视频判断分开；只提出一个后续研究问题，不把推测写成事实。
