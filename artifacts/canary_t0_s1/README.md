# RPent selective-memory canary: Object-S t0/s1

这组文件是同一任务、同一 seed、独立 reset 的 R0/R1 对照视频。Planner 为 GPT-5.6-sol，VLA 为 Pi0.5，memory corpus 为 GPT_5.5_xhigh。

- [R0 原生 memory 视频](r0_native_memory_t0_s1.mp4)：读取 task-specific audit 和 recipe；最终未触发 `terminated`。
- [R1 scene-drift abstention 视频](r1_scene_drift_abstention_t0_s1.mp4)：拒绝读取 seed-0 task-specific audit/recipe；最终未触发 `terminated`。
- [配对结果](paired_summary.json)
- [R0 人工复核](r0_human_review.jsonl)
- [R1 人工复核](r1_human_review.jsonl)

在 GitHub 网页中点击视频文件即可下载；下载后用系统视频播放器打开。R0/R1 都是单个机制演示，不能作为成功率结论。
