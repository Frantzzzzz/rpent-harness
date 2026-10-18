# Selective Memory Abstention under Scene Drift

## Research question

When a previously successful RPent recipe is absent, stale, or semantically
misrouted, can a planner abstain from that memory and re-ground the current
scene without reducing performance on genuinely matching memories?

## Goal

输入是 RPent 在 LIBERO-Pro Object-S 中可见的任务语言、当前图像/深度观测和只读的官方 `GPT_5.5_xhigh` memory。输出是一个可审计的 `match`、`mismatch` 或 `unknown` memory 适用性判定，以及在 `mismatch`/`unknown` 时的一次重新观察和重新 grounding 决策。

在固定 GPT-5.6-sol Planner、Pi0.5 checkpoint、primitive、环境和
`terminated=true` success predicate 的协议下，验证选择性拒用 memory 是否
能降低错误经验造成的计划偏离；静态 task-family 路由修复只作为实验清洁化，
不作为算法贡献。R1 必须优于原生 RPent memory baseline，并保持留出任务性能和
延迟在预设范围内。

## Task Setting

主平台为 LIBERO-Pro Object-S。开发任务为 t0、t1；留出任务为 t3、t4、t6、t8，
每个使用 s1、s2。t2、t9 的 Object-S task-family memory 不完整，只作为
`memory unavailable` 诊断，不进入主成功率。正式矩阵是
6 tasks × 2 seeds × 4 conditions = 48 个独立 episodes；canary 不计入正式结果。

比较条件：`R0` 原生 RPent memory；`R1` provenance + 当前场景适用性门控，mismatch/unknown 时最多一次重新观察；`R2` 同频率随机重新观察控制；`R3` memory-off 控制。

Evaluator 固定 harness commit/patch hash、Planner model/endpoint/request settings、Pi0.5/SAM checkpoint/hash、memory revision、prompt hash、task/seed、依赖和 success predicate。环境、initial states、VLA、SAM、primitive、Planner 模型和官方 memory corpus只读冻结。

## Objective and Metrics

- 主原始指标：`harmful_memory_rate`，方向 minimize；
- 聚合规则：每个 task–seed–condition 只运行一次；主结果按 task 分层后对
  task–seed 单元做算术平均。`terminated=true` success、延迟、Planner 调用次数
  只作诊断和安全性指标；pilot 阶段不宣称显著性。
- 归一化研究分数（仅用于比较，不替代原始指标）：

  ```text
  score = (B - harmful_memory_rate) / (B - U)
  ```

  `B` 是同一 task–seed 分层下 R0 的 harmful-memory rate（映射为 0），
  `U = 0` 是无 harmful accepted-memory 的可达上界（映射为 1）。允许分数小于
  0 或大于 1，不做裁剪。
- 随机任务的后续扩展若重复每个单元至少 5 次，则要求 R1−R0 的 bootstrap
  95% CI 不跨越 0 且点估计超过 3σ；本 48-episode pilot 删除该显著性结论。
- 次要指标：risk-coverage、abstention precision/recall、stale-memory execution rate、留出任务 `terminated=true` success rate、placement/release failure rate、Planner calls、token/API cost 和 wall-clock latency；
- 诊断指标：Planner 自述原因、memory confidence 和无法由视频确认的原因。

```text
harmful_memory_rate = harmful accepted-memory episodes / accepted-memory episodes
coverage = accepted-memory cases / eligible-memory cases
risk(c) = failures among accepted cases at coverage c / accepted cases at coverage c
stale_memory_execution_rate = stale-memory dispatches / all memory-driven dispatches
abstention_precision = correct abstentions / all abstentions
abstention_recall = correct abstentions / all human-labelled mismatch-or-unknown cases
success_rate = count(terminated=true) / count(valid episodes)
latency_overhead = (T_R1 - T_R0) / T_R0
```

风险和 coverage 使用按 task-seed 分层 bootstrap 95% confidence interval；成功率同时报告 Wilson interval。小规模 pilot 不宣称统计显著，只作 go/no-go 判断。

## Allowed Scope

只允许修改研究分支中的 memory-policy adapter、prompt 路由审计、视频复核和
汇总代码；实现 R1 的 provenance/scene-drift gate，以及最多一次重新观察和
re-grounding。R0 必须保留原生行为，R2/R3 只能改变 memory policy。禁止修改
环境、VLA、SAM、primitive、success predicate、官方 memory 正文或 Planner 模型。

必须实现：

1. 严格按 suite/regime/task identity 过滤 task-family 和 task-specific 文件；
2. 在 `memory_reads.jsonl` 中记录实际正文读取、拒用原因和降级策略；
3. 每个 episode 产生视频、结构化结果和独立 `human_review.jsonl` 记录。

模型输入输出契约：gate 读取 task language、当前 agentview/wrist 图像摘要、
memory frontmatter/正文摘要和 provenance；输出 `decision ∈ {match,mismatch,unknown}`、
置信度、依据和 `allow_memory_prior ∈ {true,false}`，不得读取 BDDL 或隐藏坐标。

模型输入为 task language、agentview/wrist 图像及 metadata、候选 memory frontmatter 和正文摘要；输出为 `decision ∈ {match,mismatch,unknown}`、置信度、触发依据和是否允许使用历史动作先验。不得输出环境坐标 oracle。

## Hard Boundaries

禁止提交环境、数据集、checkpoint、VLA/SAM、primitive、success predicate、
Planner endpoint 或 memory 正文的修改；禁止跨 suite、task-family、memory
corpus fallback；禁止 exploration、reset retry 和 memory writeback；禁止读取
BDDL 或隐藏坐标。模型参数量限制不适用（本实验只增加规则门控，不训练模型）；
import 仅使用现有标准库和仓库依赖，禁止网络访问、动态执行和序列化外传；所有
输出数值必须有限。任何接口错误、缺少 preflight、memory 路由污染、视频缺失或
人工复核缺失都将该 cell 标记为 `config_invalid`，不混入算法成功率。

## Submission Instructions

当前 RPent 仓库没有 `solution/xxx.py` 或 `xxx.sh` 接口，因此研究代码放在
`research/selective_memory_abstention/`，实验入口独立于核心 RPent 代码。实验
只写入新的 run 目录，不覆盖既有 runs 或官方 memory；目录中禁止保存 checkpoint、
二进制或额外 memory corpus。

## Workflow & Iteration

建立 clean worktree 和 immutable manifest，校验 family frontmatter、task language、
memory coverage、实际 endpoint 和 GPU；运行一个 canary 并完成视频复核后再启动
队列；运行 R0/R1/R2/R3 矩阵；每个 episode 完成后立即观看视频和关键帧，标注
memory 是否适用、是否被采用、是否产生错误计划、成功是否偶然，以及 Planner
归因是否与视频一致；生成 risk-coverage、harmful-memory、success、latency 和
human-review 汇总。队列使用 tmux、heartbeat、原子完成标记和可恢复清单；不自动
重试算法 episode。

使用 tmux、heartbeat、原子完成标记、per-episode timeout 和全局 deadline；不自动重试算法 episode。服务崩溃、checkpoint/endpoint 不一致或 memory 路由污染均标记为 `infra/config_invalid` 并停止扩展。

## Completion Criteria

clean worktree、patch hash 和固定配置可复现；canary 通过并完成人工复核；主矩阵
episode 均有 preflight、memory audit、transcript、states、video 和 human review；
R1 的 harmful-memory、risk-coverage、abstention P/R、latency 和 Planner cost 可
计算；结果按 valid、memory unavailable、config invalid、infra failure 分层；输出
继续研究、修改问题定义或停止方向的 go/no-go 报告。若 R1 的 harmful-memory
下降至少 30%、abstention recall ≥0.8、留出成功率下降不超过 5 个百分点且延迟
开销 ≤20%，才进入下一阶段。
