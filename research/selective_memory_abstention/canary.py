#!/usr/bin/env python3
"""Auditable preflight and resumable canary helpers.

This module deliberately does not import RPent or start a simulator.  It only
freezes the inputs that a later episode may use, writes an auditable memory
manifest, and emits an argv-based command/queue.  The optional ``queue-run``
subcommand is an explicit execution step for a human or an outer scheduler;
it never retries an episode.

The memory manifest hashes every file below the selected corpus root.  The
preflight records the selected files, repository state, prompt/config hashes,
checkpoint paths/hashes, and the exact command argv.  Paths and hashes are
recorded even when a required input is missing, so an invalid canary is still
diagnosable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "selective_memory_abstention.canary.v1"
DEFAULT_SUITE = "libero_object_swap"
DEFAULT_BENCHMARK = "LIBERO-Pro Object-S"
DEFAULT_MEMORY_VERSION = "GPT_5.5_xhigh"
DEFAULT_PROMPTS = (
    "robots/libero/prompts/evaluate.py",
    "robots/libero/prompts/user.py",
    "robots/libero/prompt_bundle.py",
    "rpent/memory/manager.py",
    "robots/libero/robot_spec.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    """Write JSON atomically, preserving a newline for command-line tools."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def hash_path(path: Path) -> dict[str, Any]:
    """Describe a file or directory without silently replacing missing data."""
    path = path.expanduser().resolve()
    if not path.exists():
        return {"path": str(path), "exists": False, "kind": "missing"}
    if path.is_file():
        digest, size = sha256_file(path)
        return {
            "path": str(path),
            "exists": True,
            "kind": "file",
            "bytes": size,
            "sha256": digest,
        }
    if not path.is_dir():
        return {"path": str(path), "exists": True, "kind": "other"}
    files: list[dict[str, Any]] = []
    for child in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
        digest, size = sha256_file(child)
        files.append(
            {
                "path": child.relative_to(path).as_posix(),
                "bytes": size,
                "sha256": digest,
            }
        )
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "path": str(path),
        "exists": True,
        "kind": "directory",
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": files,
    }


def command_hash(argv: Iterable[str]) -> str:
    raw = json.dumps(list(argv), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def git_state(repo: Path) -> dict[str, Any]:
    commit = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    status = _git(repo, "status", "--porcelain=v1")
    return {
        "repo": str(repo.resolve()),
        "commit": commit,
        "branch": branch or "(detached)",
        "dirty": bool(status),
        "status_porcelain": status or "",
        "git_available": commit is not None,
    }


def infer_memory_metadata(root: Path) -> dict[str, str]:
    """Read immutable cache receipt metadata when present."""
    candidates = [root.with_name(root.name + ".receipt.json")]
    # sync_version stores the commit/version receipt beside the cache key, a
    # few levels above ``snapshots/<commit>/<version>``.  Search only nearby
    # ancestors and never walk an unrelated filesystem tree.
    for ancestor in list(root.parents)[:5]:
        candidates.extend(sorted(ancestor.glob("*.json")))
    for candidate in candidates:
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("commit"):
            return {
                key: str(value[key])
                for key in ("commit", "version")
                if value.get(key)
            }
    return {}


def memory_layout(
    root: Path,
    *,
    suite: str,
    task: int,
    memory_revision: str | None,
    memory_version: str,
) -> dict[str, Any]:
    """Build a complete immutable corpus inventory plus expected Object-S files."""
    root = root.expanduser().resolve()
    inferred = infer_memory_metadata(root)
    inventory: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
            digest, size = sha256_file(path)
            inventory.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": size,
                    "sha256": digest,
                }
            )

    if suite == DEFAULT_SUITE:
        family_name = f"task-family/task-family_libero_object_swap_t{task}.md"
        task_tag = f"object_swap_t{task}_s0"
    else:
        family_name = ""
        task_tag = ""
    expected = {
        "index": ["MEMORY.md"],
        "global": [entry["path"] for entry in inventory if entry["path"].startswith("global/")],
        "task_family": [family_name] if family_name else [],
        "task_specific": (
            [
                f"task-specific/{task_tag}.json",
                f"task-specific/{task_tag}_recipe.jsonl",
            ]
            if task_tag
            else []
        ),
    }
    by_path = {entry["path"]: entry for entry in inventory}
    expected_status: dict[str, dict[str, Any]] = {}
    for scope, names in expected.items():
        expected_status[scope] = {
            name: {
                "exists": name in by_path,
                "bytes": by_path[name]["bytes"] if name in by_path else None,
                "sha256": by_path[name]["sha256"] if name in by_path else None,
            }
            for name in names
        }
    receipt_path = root.with_name(root.name + ".receipt.json")
    receipt: dict[str, Any] | None = None
    receipt_match: bool | None = None
    receipt_version_match: bool | None = None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_files = receipt.get("files", {})
        actual_files = {entry["path"]: entry["sha256"] for entry in inventory}
        receipt_match = bool(receipt_files) and receipt_files == actual_files
        prefix = str(receipt.get("prefix") or "")
        receipt_version_match = prefix.endswith(f"/{memory_version}/")
    except (OSError, ValueError, AttributeError):
        receipt_match = False if receipt_path.exists() else None
        receipt_version_match = False if receipt_path.exists() else None
    canonical = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task_specific_status = expected_status["task_specific"]
    task_family_status = expected_status["task_family"]
    task_specific_available = all(item["exists"] for item in task_specific_status.values())
    task_family_available = all(item["exists"] for item in task_family_status.values())
    return {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "root": str(root),
        "version": memory_version,
        "inferred_version": inferred.get("version"),
        "revision": memory_revision or inferred.get("commit"),
        "receipt_path": str(receipt_path),
        "receipt_prefix": receipt.get("prefix") if receipt else None,
        "receipt_matches_files": receipt_match,
        "receipt_matches_version": receipt_version_match,
        "file_count": len(inventory),
        "total_bytes": sum(entry["bytes"] for entry in inventory),
        "corpus_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "files": inventory,
        "expected_for_episode": expected,
        "expected_status": expected_status,
        "task_specific_memory_available": task_specific_available,
        "task_family_memory_available": task_family_available,
        "degradation_strategy": (
            "none"
            if task_specific_available and task_family_available
            else "memory_unavailable_task_specific_or_family; no cross-task fallback"
        ),
    }


def _arg_path(value: str | None, env_name: str) -> Path | None:
    selected = value or os.environ.get(env_name)
    return Path(selected).expanduser().resolve() if selected else None


def _path_check(path: Path | None, *, required: bool) -> dict[str, Any]:
    if path is None:
        return {
            "provided": False,
            "required": required,
            "exists": False,
            "status": "missing",
            "path": None,
        }
    info = hash_path(path)
    info["required"] = required
    info["status"] = "ok" if info.get("exists") else "missing"
    return info


def episode_argv(args: argparse.Namespace, output_dir: Path) -> list[str]:
    """Return a list argv; callers should execute it without shell interpolation."""
    python = args.python or sys.executable
    argv = [
        python,
        "-m",
        "rpent.cli.main",
        "--robot",
        "libero",
        "--suite",
        args.suite,
        "--task",
        str(args.task),
        "--seed",
        str(args.seed),
        "--planner",
        args.planner,
        "--model",
        args.planner_model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--memory-profile",
        "local",
        "--memory-dir",
        str(Path(args.memory_root).expanduser().resolve()),
        "--memory-abstention",
        args.memory_abstention,
        "--output-dir",
        str(output_dir.resolve()),
        "--max-episode-steps",
        str(args.max_steps),
        "--no-auto-merge-memory",
    ]
    if args.planner_timeout_s is not None:
        argv.extend(["--planner-timeout-s", str(args.planner_timeout_s)])
    if args.libero_type:
        argv.extend(["--libero-type", args.libero_type])
    for flag, value in (
        ("--env-endpoint", args.env_endpoint),
        ("--vla-endpoint", args.vla_endpoint),
        ("--sam3-endpoint", args.sam3_endpoint),
    ):
        if value:
            argv.extend([flag, value])
    if args.cuda_device is not None:
        argv.extend(["--cuda-device", str(args.cuda_device)])
    # Deliberately no --explore, reset, retry, or writeback flags are emitted.
    return argv


def build_preflight(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    repo = Path(args.repo).expanduser().resolve()
    output = Path(args.output_dir).expanduser().resolve()
    memory_root = Path(args.memory_root).expanduser().resolve()
    vla = _arg_path(args.vla_checkpoint, "PI05_CHECKPOINT_PATH")
    sam = _arg_path(args.sam_checkpoint, "SAM3_CHECKPOINT_PATH")
    initial = _arg_path(args.initial_state, "LIBERO_INITIAL_STATE_PATH")
    memory = memory_layout(
        memory_root,
        suite=args.suite,
        task=args.task,
        memory_revision=args.memory_revision,
        memory_version=args.memory_version,
    )
    argv = episode_argv(args, output)
    prompt_hashes: dict[str, Any] = {}
    for relative in args.prompt_file:
        path = repo / relative if not Path(relative).is_absolute() else Path(relative)
        prompt_hashes[relative] = _path_check(path.resolve(), required=True)
    git = git_state(repo)
    checks = {
        "repository": {
            "status": "ok" if git["git_available"] else "missing",
            **git,
        },
        "memory_root": {
            **_path_check(memory_root, required=True),
            "revision": memory.get("revision"),
            "version": memory.get("version"),
        },
        "vla_checkpoint": _path_check(vla, required=True),
        "sam_checkpoint": _path_check(sam, required=True),
        "initial_state": _path_check(initial, required=True),
        "prompt_files": prompt_hashes,
    }
    missing = [
        key
        for key, value in checks.items()
        if key in {"memory_root", "vla_checkpoint", "sam_checkpoint", "initial_state"}
        and value.get("status") != "ok"
    ]
    if any(value.get("status") != "ok" for value in prompt_hashes.values()):
        missing.append("prompt_files")
    if git["dirty"] and not args.allow_dirty:
        missing.append("git_dirty")
    if memory.get("receipt_matches_files") is False:
        missing.append("memory_receipt_mismatch")
    if memory.get("receipt_matches_version") is False:
        missing.append("memory_version_mismatch")
    config = {
        "benchmark": args.benchmark,
        "suite": args.suite,
        "task": args.task,
        "seed": args.seed,
        "planner": args.planner,
        "planner_model": args.planner_model,
        "planner_endpoint": args.planner_endpoint
        or os.environ.get("CODEX_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL"),
        "reasoning_effort": args.reasoning_effort,
        "vla_model": args.vla_model,
        "vla_checkpoint": str(vla) if vla else None,
        "sam_checkpoint": str(sam) if sam else None,
        "service_endpoints": {
            "env": args.env_endpoint,
            "vla": args.vla_endpoint,
            "sam3": args.sam3_endpoint,
            "cuda_device": args.cuda_device,
        },
        "memory_profile": "local",
        "memory_version": memory.get("version"),
        "memory_root": str(memory_root),
        "memory_revision": memory.get("revision"),
        "max_steps": args.max_steps,
        "retry_budget": 0,
        "exploration": False,
        "memory_writeback": False,
        "memory_abstention": args.memory_abstention,
        "prompt_files": prompt_hashes,
        "command": argv,
    }
    config_json = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    preflight = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "status": "infra_failure" if missing else "ready",
        "failure_reasons": sorted(set(missing)),
        "harness_git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "git_branch": git["branch"],
        "planner_model": args.planner_model,
        "planner": args.planner,
        "planner_endpoint_or_config": config["planner_endpoint"],
        "vla_model": args.vla_model,
        "benchmark": args.benchmark,
        "task_id": args.task,
        "task_language": args.task_language,
        "seed": args.seed,
        "memory_profile": "local",
        "memory_version": memory.get("version"),
        "memory_root": str(memory_root),
        "memory_revision": memory.get("revision"),
        "prompt_config_hash": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        "prompt_files": prompt_hashes,
        "max_steps": args.max_steps,
        "retry_budget": 0,
        "wall_clock_start": utc_now(),
        "checks": checks,
        "config": config,
        "command_hash": command_hash(argv),
    }
    return preflight, memory, argv


def write_preflight(args: argparse.Namespace) -> int:
    output = Path(args.output_dir).expanduser().resolve()
    preflight, memory, argv = build_preflight(args)
    atomic_json(output / "preflight.json", preflight)
    atomic_json(output / "memory_manifest.json", memory)
    command_text = " ".join(shlex.quote(part) for part in argv) + "\n"
    (output / "episode_command.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + command_text, encoding="utf-8")
    (output / "episode_command.sh").chmod(0o755)
    print(json.dumps({"status": preflight["status"], "output_dir": str(output), "command_hash": preflight["command_hash"]}, indent=2))
    return 0 if preflight["status"] == "ready" else 1


def queue_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    tasks = [int(value) for value in args.tasks.split(",") if value.strip()]
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    root = Path(args.output_root).expanduser().resolve()
    items: list[dict[str, Any]] = []
    for task in tasks:
        for seed in seeds:
            cell = root / args.condition / f"{args.suite}_t{task}_s{seed}"
            item = {
                "episode": f"{args.suite}_t{task}_s{seed}",
                "condition": args.condition,
                "suite": args.suite,
                "task": task,
                "seed": seed,
                "output_dir": str(cell),
                "argv": episode_argv(argparse.Namespace(**{**vars(args), "task": task, "seed": seed}), cell),
            }
            item["command_hash"] = command_hash(item["argv"])
            items.append(item)
    return items


def write_queue(args: argparse.Namespace) -> int:
    items = queue_items(args)
    path = Path(args.queue).expanduser().resolve()
    payload = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "repo": str(Path(args.repo).expanduser().resolve()),
        "condition": args.condition,
        "items": items,
        "resume_marker": "episode_done.json",
        "retry_policy": "never",
    }
    atomic_json(path, payload)
    runner = path.with_name(path.stem + "_run.sh")
    runner.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        + "exec "
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(str(Path(__file__).resolve()))
        + " queue-run --queue "
        + shlex.quote(str(path))
        + "\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    print(json.dumps({"queue": str(path), "episodes": len(items), "runner": str(runner)}, indent=2))
    return 0


def queue_run(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    failures = 0
    for item in payload.get("items", []):
        output = Path(item["output_dir"])
        marker = output / "episode_done.json"
        if marker.is_file():
            try:
                prior = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            if prior.get("status") == "completed" and prior.get("command_hash") == item.get("command_hash"):
                print(f"SKIP completed {item['episode']}")
                continue
            if prior.get("command_hash") == item.get("command_hash"):
                # A failed/timeout marker is an observed algorithm or
                # infrastructure outcome.  Do not turn queue resumption into
                # an implicit retry; remove/rename it only after an explicit
                # human decision to rerun that cell.
                print(f"HOLD {item['episode']} ({prior.get('status', 'unknown')})")
                failures += 1
                if args.stop_on_failure:
                    break
                continue
            print(f"HOLD {item['episode']} (command hash changed)")
            failures += 1
            if args.stop_on_failure:
                break
            continue
        output.mkdir(parents=True, exist_ok=True)
        started = utc_now()
        status = "completed"
        return_code = 0
        try:
            result = subprocess.run(item["argv"], cwd=payload.get("repo"), timeout=args.timeout_s)
            return_code = int(result.returncode)
            status = "completed" if return_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
            return_code = 124
        except OSError as exc:
            status = "infra_failure"
            return_code = 127
            (output / "runner_error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        # The marker is written last and atomically.  A killed process therefore
        # leaves no completed marker and can be resumed without an implicit retry.
        atomic_json(
            marker,
            {
                "schema": SCHEMA,
                "episode": item["episode"],
                "command_hash": item.get("command_hash"),
                "status": status,
                "return_code": return_code,
                "started_at": started,
                "finished_at": utc_now(),
            },
        )
        print(f"{status.upper()} {item['episode']}")
        if status != "completed":
            failures += 1
            if args.stop_on_failure:
                break
    return 1 if failures else 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight", help="write preflight.json and memory_manifest.json")
    pre.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    pre.add_argument("--output-dir", required=True)
    pre.add_argument("--memory-root", required=True)
    pre.add_argument("--memory-revision", default=None)
    pre.add_argument("--memory-version", default=DEFAULT_MEMORY_VERSION)
    pre.add_argument("--benchmark", default=DEFAULT_BENCHMARK)
    pre.add_argument("--suite", default=DEFAULT_SUITE)
    pre.add_argument("--task", type=int, required=True)
    pre.add_argument("--seed", type=int, required=True)
    pre.add_argument("--task-language", default=None)
    pre.add_argument("--planner", default="codex")
    pre.add_argument("--planner-model", default="gpt-5.6-sol")
    pre.add_argument("--planner-endpoint", default=None)
    pre.add_argument("--reasoning-effort", default="high")
    pre.add_argument("--vla-model", default="Pi0.5")
    pre.add_argument("--vla-checkpoint", default=None)
    pre.add_argument("--sam-checkpoint", default=None)
    pre.add_argument("--initial-state", default=None)
    pre.add_argument("--prompt-file", action="append", default=list(DEFAULT_PROMPTS))
    pre.add_argument(
        "--memory-abstention",
        choices=("none", "strict_identity", "scene_drift"),
        default="strict_identity",
    )
    pre.add_argument("--max-steps", type=int, default=10000)
    pre.add_argument("--planner-timeout-s", type=int, default=None)
    pre.add_argument("--libero-type", default="pro")
    pre.add_argument("--env-endpoint", default=None)
    pre.add_argument("--vla-endpoint", default=None)
    pre.add_argument("--sam3-endpoint", default=None)
    pre.add_argument("--cuda-device", type=int, default=None)
    pre.add_argument("--python", default=None)
    pre.add_argument("--allow-dirty", action="store_true")
    pre.set_defaults(func=write_preflight)

    queue = sub.add_parser("queue", help="emit an argv queue and resumable runner; does not execute")
    queue.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    queue.add_argument("--queue", required=True)
    queue.add_argument("--output-root", required=True)
    queue.add_argument("--tasks", default="0,1")
    queue.add_argument("--seeds", default="1,2")
    queue.add_argument("--condition", default="R1")
    queue.add_argument("--suite", default=DEFAULT_SUITE)
    queue.add_argument("--memory-root", required=True)
    queue.add_argument("--memory-version", default=DEFAULT_MEMORY_VERSION)
    queue.add_argument("--planner", default="codex")
    queue.add_argument("--planner-model", default="gpt-5.6-sol")
    queue.add_argument("--reasoning-effort", default="high")
    queue.add_argument(
        "--memory-abstention",
        choices=("none", "strict_identity", "scene_drift"),
        default="strict_identity",
    )
    queue.add_argument("--max-steps", type=int, default=10000)
    queue.add_argument("--planner-timeout-s", type=int, default=None)
    queue.add_argument("--libero-type", default="pro")
    queue.add_argument("--env-endpoint", default=None)
    queue.add_argument("--vla-endpoint", default=None)
    queue.add_argument("--sam3-endpoint", default=None)
    queue.add_argument("--cuda-device", type=int, default=None)
    queue.add_argument("--python", default=None)
    queue.set_defaults(func=write_queue)

    run = sub.add_parser("queue-run", help="explicitly execute a previously emitted queue")
    run.add_argument("--queue", required=True)
    run.add_argument("--timeout-s", type=int, default=3600)
    run.add_argument("--stop-on-failure", action="store_true")
    run.set_defaults(func=queue_run)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
