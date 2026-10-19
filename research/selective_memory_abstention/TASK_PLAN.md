# Selective Memory Abstention under Scene Drift — Long-Horizon Generalization and Continual Rollout

## Goal

输入是具身 agent 在当前任务语言、视觉观测、机器人状态和只读历史 memory 下的候选经验；输出是对该经验的 `match`、`mismatch` 或 `unknown` 判定，以及是否允许历史动作先验进入 Planner。研究问题是：当历史经验与当前场景发生变化时，选择性拒绝是否能减少人类视频复核确认的有害 memory 执行，同时保持匹配经验的成功率、coverage 和时延。短 canary 只验证审计链路；论文结论必须来自跨套件、跨 seed、跨任务类型和跨仿真平台的长时间 rollout。

## Task Setting

实验分为 calibration、冻结 holdout、跨域泛化和 longitudinal 四阶段。冻结评测与持续 rollout 使用独立的 memory 目录、run ID、队列和结果表；持续 rollout 的新写回不能进入冻结评测。

### 平台和完整矩阵

1. **LIBERO-PRO 主平台（Pi0.5 + SAM3）**：按照 RPent 的长期协议覆盖 8 个完整套件：`libero_object_task`、`libero_object_swap`、`libero_goal_task`、`libero_goal_swap`、`libero_spatial_task`、`libero_spatial_swap`、`libero_10_task`、`libero_10_swap`。每套件 10 个任务，官方 manifest 为每个任务提供 seed 0–9，共 800 个 task–seed 单元。s0 单独作为 memory-source/reference 或官方对照层；scene-drift 主率使用 s1–s9，避免把生成 seed-0 memory 的场景和漂移场景混在一起。R0/R1 在完整 s0–s9 矩阵各运行一次；R2 random re-observe control 和 R3 memory-off 诊断至少覆盖 8 套件的 s1–s3 子集。官方 800 结果和 scene-drift s1–s9 结果分开报告。

2. **LIBERO-PRO 扩展压力集**：对应 BDDL、initial states、memory manifest 全部通过 preflight 后，再覆盖支持的 `*_lan` 与 `*_object` 扰动套件。它们单独报告，不与官方 8 套件主率混合；缺文件只记为 `memory_unavailable` 或 `infra/config_invalid`，不能跨套件补齐。

3. **RoboCasa365 Target50**：使用官方完整 340 runs：Atomic 18 个任务 × 10 seeds = 180，Composite-Seen 16 × 5 = 80，Composite-Unseen 16 × 5 = 80。使用 RoboCasa 原生 RLDX-1、对应官方 memory 和 `state.success`，不能把该判据转换成 LIBERO 的 `terminated`。

4. **RoboTwin C2R**：使用 `demo_randomized` 的完整 50 个任务 × 每任务 5 个 official verified seeds = 250 runs。经验来自预先冻结的 `demo_clean`/官方 memory；评测使用随机化场景、LingBot-VLA 和原生 `TASK_ENV.eval_success`。每个任务使用自身 manifest 的 seed，不能给所有任务套同一 seed 列表。

LIBERO、RoboCasa、RoboTwin 的 Planner、VLA、primitive、memory corpus、success predicate 和资源版本分别冻结，结果按 benchmark 单独报告，最后只做 benchmark-macro average，不能把不同 VLA 或不同 success predicate 的 episode 直接池化为一个“总体成功率”。完整冻结评测至少包含 LIBERO 1600 个主对比 episodes、RoboCasa 680 个 R0/R1 episodes 和 RoboTwin 500 个 R0/R1 episodes，另加控制条件；它不是一个 48 小时内必须结束的单次命令，而是多个可恢复 48 小时窗口。

### 开发、验证、测试和 longitudinal 切分

- **Calibration**：只使用预注册的 Object-S t0、t1 指定 seeds，检查日志、视频、memory 链路并冻结 adapter 阈值。结果不进入主表，不能修改官方 memory 正文。
- **Validation**：使用 Object-S t2、t3 和一个跨 family 套件的固定任务子集，检查 `memory_unavailable`、`unknown`、误归因和失败分类。完成后锁定代码、prompt/config hash、threshold、memory snapshot 和 queue；不得看主留出结果后调参。
- **Main holdout**：使用 Object-S 其余任务、完整 Goal/Spatial/LIBERO-10 套件，以及跨平台的 RoboCasa Composite-Unseen、RoboTwin randomized scenes。主留出集中的 task/seed/initial state/memory snapshot 在测试前冻结。
- **Longitudinal stream**：每个平台另建 run-local corpus。探索或写回只允许发生在 calibration/validation stream；每个 epoch 保存不可变 snapshot、revision、文件 hash、增长量、stale entry 和 contaminated entry。最终 test stream 只读预注册 snapshot，不写回。若另测 online adaptation，单列为 R4，记录严格时间顺序，不能和冻结 R0/R1 主率合并。

当前代码的 `scene_drift` 规则只在 `libero_object_swap && seed>0` 下隐藏 seed-0 task-specific artifacts，属于 **known-drift stress test**，不是通用视觉 scene gate。在完整 8 套件或跨平台主跑之前，必须把 gate 改为只依赖当前图像/状态、任务语言和 memory provenance/frontmatter；不得读取数值 seed、BDDL、隐藏坐标或用 suite/seed 硬编码判定。若保留硬编码实现，其他套件只能作为外推失败诊断，不能声称泛化成功。

### evaluator 固定项和只读冻结模块

每个 cell 冻结并记录 harness commit、branch、工作区状态、Planner model/endpoint/reasoning effort、VLA/SAM 或平台原生 checkpoint、checkpoint hash、memory corpus/version/revision/root、task language、suite/task/seed、initial-state hash、prompt/config hash、CUDA/服务端点、max steps、timeout、retry budget 和墙钟时间。只读冻结模块包括 simulator/environment、VLA、SAM 或平台原生 perception、primitive/tool implementation、Planner prompt/策略、训练循环、数据集、官方 memory corpus 和 success evaluator。冻结评测关闭 exploration、reset retry 和 memory writeback；longitudinal 只在独立协议中打开，并且写回必须 append-only 审计。

## Objective and Metrics

- 主原始指标：`human_confirmed_harmful_accepted_memory_rate`，方向 minimize。只有形成“memory read → Planner dispatch/accepted → primitive 执行 → 视频确认有害物理后果”的链路才计 harmful；只读取但没有影响动作的 memory 单列为 exposure。
- 聚合规则：先对每个 task 求 task-seed 算术平均，再对 suite 求 macro average，最后对 benchmark 求 macro average；禁止用大 benchmark 的 episode 数量支配总体数值。R0/R1 使用相同 task–seed 配对和独立 reset；R2 精确匹配 R1 的 re-observe 次数、时序和额外预算。
- 主要比较：`ΔH = H_R1 - H_R0`、risk–coverage curve/AURC、fixed-coverage selective risk、matched-memory success retention 和 worst-suite generalization gap。
- 归一化公式：`score_b = (B_b - H_R1,b) / (B_b - U_b)`。
  - `B_b = H_R0,b`，同一 benchmark 的 R0 harmful rate，映射 0。
  - `U_b = 0`，无 harmful accepted-memory execution，映射 1。
  - 允许小于 0 或大于 1，不做裁剪；若 `B_b=0`，score 为 `NA`，只报告 `ΔH`。
- 另外报告 exposure、accepted-memory coverage、abstention precision/recall、`unknown` rate、success-after-accepted、环境原生 success、失败阶段、Planner calls、token/API cost、wall-clock latency 和 R1 overhead。全 abstain 不能凭 H=0 获得好结果；要求 `coverage_R1 >= 0.70 * coverage_R0`，否则标记 `abstention_collapse`。
- Longitudinal 另外报告每个 epoch 的 success、harmful replay、stale reference rate、memory contamination rate、memory growth、entry retention、forgetting、time-to-first-harm、time-to-first-success 和 snapshot-to-snapshot 变化。
- 统计：pilot 不做显著性声明；正式结果使用 task-cluster bootstrap/permutation CI。随机任务至少每 task 5 个独立 verified seeds 且改变量超过预注册 3σ 才讨论显著提升；确定性任务删除 3σ 条件。报告 worst-quartile suite，不只报 macro mean。
- 视频复核：主 LIBERO 中所有失败、timeout、memory accepted 和疑似 harmful episode 必须人工复核；成功 episode 至少随机双盲复核 20%。外部平台至少复核所有失败/harm 和每个 split 的固定成功样本，并报告 Cohen κ 或 Krippendorff α。Planner 自述只是证据源，不能替代视频和环境结果。

## Allowed Scope

仅可修改 `research/selective_memory_abstention/` 中的 memory-policy adapter、provenance/scene-compatibility 审计、可恢复 queue、视频人工复核工具和结果汇总代码；必要的最小接口接入必须保持输入输出契约。不得修改核心 Planner、prompt、VLA、SAM、primitive、环境、数据集、训练循环或官方 memory 正文。

必须实现：

1. policy 只接收当前任务语言、agentview/wrist 或平台原生视觉观测及 metadata、候选 memory provenance/frontmatter/正文摘要；输出 `match|mismatch|unknown`、置信度、证据、`allow_memory_prior` 和结构化 abstention 事件。不得读取 seed、BDDL、隐藏坐标或 environment oracle。
2. 每个 episode 写出 preflight、memory manifest、逐文件 `memory_reads.jsonl`、dispatch/accepted/abstained/missing/fallback 事件、transcript、states、video、结构化结果和独立 `human_review.jsonl`。
3. Longitudinal 使用独立 run-local corpus、不可变 snapshot 和 revision hash；测试 snapshot 只读，任何 writeback 都带 episode、时间顺序、来源和审计 hash。

## Hard Boundaries

禁止跨 benchmark、跨 suite、跨 task-family 或跨 memory corpus 静默补齐；禁止用 test episode 修改 policy、阈值、prompt、memory 或 seed 清单；禁止把 `unknown` 静默当作 match；禁止把 `memory_unavailable`、`infra/config_invalid` 或无效 success predicate 混入算法率。禁止用组合 shell 命令的 exit code 推断所有文件读取成功。所有失败原因分为 observed fact 和 hypothesis 两层。

缺少 checkpoint、initial state、task manifest、memory root、服务端点、视频、states、transcript 或人工复核时标记 `infra/config_invalid`，暂停对应队列；只允许在新的唯一 run 目录和新 preflight 下重跑。48 小时只是可恢复执行窗口，不是到点即算完成。

## Submission Instructions

研究代码只提交 `research/selective_memory_abstention/` 的审计和 adapter 文件，以及固定路径文件 `experiment_env.sh`；禁止提交 checkpoint、二进制、额外 memory corpus、未审计日志或覆盖旧 runs。每个 queue 和 episode 保存完整 argv、环境变量摘要、commit、patch hash、memory revision、condition、task/seed 和输出目录。当前仓库没有通用 `solution/xxx.py` 接口，不得伪造该接口。

## Workflow & Iteration

1. **Preflight 和资源冻结**：source `experiment_env.sh`，核验路径、hash、官方 task/seed manifest、memory layout、服务端点和 clean worktree；生成 immutable preflight/manifest，且记录环境文件自身 hash。
2. **短 canary**：每个平台最多一个开发 canary，先盲看初始场景，再看完整视频，5 分钟内完成复核。canary 只验证服务、审计、memory-read 和视频质量，不进入主率。
3. **开发/验证 stream**：在预注册开发任务上运行 R0/R1；可在独立 R4 exploration stream 中写回 run-local memory；锁定通用 adapter、阈值、snapshot 和队列后禁止修改。
4. **长时间冻结评测**：按 LIBERO 800、RoboCasa 340、RoboTwin 250 的官方 manifest 运行 R0/R1；LIBERO 的 R2/R3 诊断子集按计划运行。用 tmux、heartbeat、原子完成标记断点续跑；失败 episode 不自动重试，基础设施失败只在新目录和新 preflight 下重跑。
5. **及时人工复核**：每个 episode 完成后检查视频、状态、transcript 和 memory 链路；若视频与 Planner 归因冲突，暂停对应队列并记录冲突，不继续盲跑。
6. **汇总和外推检查**：生成 `episode_summary.json`、`results.csv`、`results.json`、`failure_cases.jsonl`、`baseline_report.md`、risk–coverage 图、memory snapshot 对比和人工一致性报告。按 benchmark、suite、split、memory availability、valid/infra 分层，不能只输出一个 pooled success rate。

每个 48 小时窗口只执行预先生成的不可变 queue；完整性由 expected cells、valid cells、memory receipts、视频和人工复核共同决定。若资源不足以完成完整矩阵，报告 partial coverage，不把部分结果写成完整泛化结论。

## Completion Criteria

- 三个平台的固定资源、模型、memory、task/seed manifest 和 success predicate 均有可重放 receipt；主 LIBERO 800、RoboCasa 340、RoboTwin 250 的 expected cells 按预注册条件完成，或明确报告缺失及原因。
- 每个合法 cell 具备完整审计、真实 memory 正文读取证据、视频、states、transcript、环境结果和人工复核；无跨 corpus fallback、无未解释 config failure、无 test-to-memory leakage。
- 研究结论同时给出 harmful-memory risk、coverage、匹配 memory retention、environment success、latency、worst-suite gap 和 longitudinal 的 contamination/staleness 轨迹。只有跨 suite/seed 的留出结果稳定，才讨论泛化。
- 若当前硬编码 `scene_drift` gate 未替换为观测+provenance adapter，结论只能是 LIBERO Object-S known-drift stress test，不得宣称跨 LIBERO suite、RoboCasa 或 RoboTwin 的通用 scene gate。
- 进入下一阶段的条件：在 R0 harmful rate 非零的 benchmark 上，R1 harmful rate 至少下降 30%；coverage 不低于预注册下限；matched-memory success retention ≥ 95%；留出 success 下降不超过 5 个百分点；latency overhead ≤ 20%；视频复核一致性达标。否则停止方法扩展，只报告 pilot/negative result。
