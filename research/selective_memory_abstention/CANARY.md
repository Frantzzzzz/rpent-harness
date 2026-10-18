# Canary and preflight helper

`canary.py` only audits inputs and emits commands. It does not import the
planner, start a simulator, download a checkpoint, or write the memory corpus.
Run it from the repository root (or pass `--repo`).

```bash
python research/selective_memory_abstention/canary.py preflight \
  --output-dir runs/selective_memory_abstention/R1/libero_object_swap_t0_s1 \
  --memory-root /path/to/GPT_5.5_xhigh \
  --vla-checkpoint "$PI05_CHECKPOINT_PATH" \
  --sam-checkpoint "$SAM3_CHECKPOINT_PATH" \
  --initial-state /path/to/object_swap_t0.hdf5 \
  --task 0 --seed 1
```

The command writes `preflight.json`, `memory_manifest.json`, and an
`episode_command.sh`. A missing checkpoint, initial state, memory receipt, or
dirty repository causes an `infra_failure` status and a nonzero exit; no
fallback is selected. Task-specific audit/recipe files are recorded as
present or absent in the manifest and are never substituted from another task.

To emit a resumable queue without executing it:

```bash
python research/selective_memory_abstention/canary.py queue \
  --queue runs/selective_memory_abstention/R1_queue.json \
  --output-root runs/selective_memory_abstention \
  --memory-root /path/to/GPT_5.5_xhigh \
  --tasks 0,1 --seeds 1,2
```

This creates a `<queue>_run.sh` wrapper. `queue-run` is an explicit execution
operation; it skips only a cell with a matching successful `episode_done.json`,
writes that marker atomically after the child process exits, and never retries a
failed or timed-out cell automatically.
