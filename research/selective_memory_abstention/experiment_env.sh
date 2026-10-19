#!/usr/bin/env bash
# Fixed, non-secret paths for the RPent selective-memory experiments.
#
# Load once in the shell that starts an episode:
#   source research/selective_memory_abstention/experiment_env.sh
#
# Keep this file limited to reproducibility paths and runtime switches. API
# keys and other credentials must remain outside the repository.

export RPENT_RESEARCH_REPO=/mnt/nas-data/lpy/Agentic_Policy/user/wzh/rpent-harness-abstention
export RPENT_REPRO_REPO=/mnt/nas-data/lpy/Agentic_Policy/user/wzh/rpent-harness-repro
export RPENT_PYTHON=/mnt/nas-data/lpy/Agentic_Policy/user/wzh/rpent-harness-repro/.venv/bin/python
export RPENT_PLANNER_MODEL=gpt-5.6-sol
export RPENT_REASONING_EFFORT=low
export RPENT_MAX_EPISODE_STEPS=10000
export RPENT_PLANNER_TIMEOUT_S=1200
export RPENT_EVAL_SEEDS=1,2,3

export PI05_CHECKPOINT_PATH=/mnt/nas-data/fanlr/model2026/RLinf/RLinf-Pi05-LIBERO-130-fullshot-SFT/6222623f635769bfc73c9472e29fab9b7fd8e027
export SAM3_CHECKPOINT_PATH=/mnt/nas-data/lpy/Model/sam3/sam3.pt
export RPENT_MEMORY_ROOT=/mnt/nas-data/lpy/Agentic_Policy/user/wzh/rpent-harness-repro/memory/libero/.versions/f28629ca24f291ca6d95/snapshots/47f301ef33bf8d0e8c770342f16b3c39c6a0e8c1/GPT_5.5_xhigh
export RPENT_MEMORY_VERSION=GPT_5.5_xhigh
export RPENT_MEMORY_REVISION=47f301ef33bf8d0e8c770342f16b3c39c6a0e8c1

export LIBERO_TYPE=pro
export RPENT_CUDA_DEVICE=3
export LIBERO_INITIAL_STATE_T0=/opt/sim2real/runtime-harness/lib/python3.12/site-packages/liberopro/liberopro/init_files/libero_object_swap/pick_up_the_alphabet_soup_and_place_it_in_the_basket.pruned_init
export RPENT_OUTPUT_ROOT="$RPENT_RESEARCH_REPO/runs/research_canary"

# Cross-platform resources are intentionally unset until their official
# versions are located and hashed. Do not substitute local or cross-platform
# checkpoints automatically.
# export ROBOCASA_ASSETS_PATH=/path/to/official/robocasa-assets
# export ROBOCASA_VLA_MODEL_PATH=/path/to/official/RLDX-1-FT-RC365
# export ROBOCASA_MEMORY_ROOT=/path/to/official/robocasa/GPT_5.5_xhigh
# export ROBOTWIN_ASSETS_PATH=/path/to/official/robotwin-assets
# export LINGBOT_MODEL_PATH=/path/to/official/LingBot-VLA-RoboTwin-EEF-ckpt1500
# export ROBOTWIN_MEMORY_ROOT=/path/to/official/robotwin/GPT_5.5_xhigh

# Integrity values checked during preflight.
export RPENT_PI05_SHA256=4d9089c941793f170b625c2ed0ac7a3aa09b6f103e52dbbc82e67301529d6683
export RPENT_SAM3_SHA256=9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e
