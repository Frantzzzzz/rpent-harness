# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cross-session memory corpus management."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from rpent.utils.config import get_repo_root
from rpent.utils.logging import get_logger

logger = get_logger("memory")

SCOPES = {"global", "task-family"}
KINDS = {"primitive", "perception", "strategy", "failure", "infra"}
CONFIDENCE = {"single-shot", "probable", "verified"}
_PREFIXES = ("new_global_", "new_task-family_", "new_", "task-family_")
_KINDS = tuple(f"{kind}_" for kind in sorted(KINDS))


def _split_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("unterminated YAML frontmatter")
    try:
        metadata = yaml.safe_load(text[3:end])
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a mapping")
    return metadata, text[end + 4 :]


def _validate(metadata: dict[str, Any]) -> None:
    scope = metadata.get("scope")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {sorted(SCOPES)}, got {scope!r}")
    if scope == "task-family":
        for field in ("suite", "regime", "task_id", "task_language"):
            if metadata.get(field) in (None, ""):
                raise ValueError(f"task-family memory requires {field!r}")
    else:
        if metadata.get("kind") not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        for field in ("title", "applies_when"):
            if not str(metadata.get(field, "")).strip():
                raise ValueError(f"global memory requires {field!r}")
    if metadata.get("confidence") not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE)}")
    evidence = metadata.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a mapping")
    if not isinstance(evidence.get("cells"), list) or not evidence["cells"]:
        raise ValueError("evidence.cells must be a non-empty list")


def _canonical_id(path: Path, metadata: dict[str, Any]) -> str:
    if metadata["scope"] == "task-family":
        return f"task-family_{metadata['suite']}_{metadata['regime']}_t{metadata['task_id']}"
    stem = re.sub(r"_draft$", "", path.stem)
    for prefix in (*_PREFIXES, *_KINDS):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    return str(metadata.get("id") or stem).strip()


def _render(metadata: dict[str, Any], body: str) -> str:
    return (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
        + "---\n"
        + body
    )


def _merge_evidence(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_evidence = old.get("evidence") or {}
    new_evidence = new.get("evidence") or {}
    cells = sorted({*old_evidence.get("cells", []), *new_evidence.get("cells", [])})
    evidence = {
        **old_evidence,
        "cells": cells,
        "attempts": int(old_evidence.get("attempts") or 0)
        + int(new_evidence.get("attempts") or 0),
    }
    for key in ("solved_seeds", "failed_seeds", "contradicted_by"):
        if key in old_evidence or key in new_evidence:
            evidence[key] = sorted(
                {*old_evidence.get(key, []), *new_evidence.get(key, [])}
            )
    tasks = {str(cell).rsplit("_s", 1)[0] for cell in cells}
    confidence = (
        "verified"
        if len(cells) >= 3 and len(tasks) >= 2
        else "probable"
        if len(cells) >= 2
        else "single-shot"
    )
    return {**old, "evidence": evidence, "confidence": confidence}


def _has_local_memory(root: Path) -> bool:
    return root.is_dir() and any(path.is_file() for path in root.rglob("*"))


class MemoryManager:
    """Manage merge, validation, and synchronization for one memory corpus.

    root is the corpus root. It is stored resolved and created lazily by
    mutating operations.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        memory_access: str = "read_only",
        inbox_cell_tag: str | None = None,
        memory_abstention: str = "none",
        task_context: dict[str, Any] | None = None,
        read_log_path: str | Path | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        self._memory_access = memory_access
        self._inbox_cell_tag = inbox_cell_tag
        if memory_abstention not in {"none", "strict_identity"}:
            raise ValueError(
                "memory_abstention must be one of 'none' or 'strict_identity'"
            )
        self._memory_abstention = memory_abstention
        self._task_context = dict(task_context or {})
        self._read_log_path = (
            Path(read_log_path).resolve() if read_log_path is not None else None
        )
        self._read_log_lock = threading.Lock()
        # authorize_read stores the original path so record_read can prove
        # which request delivered a file to the planner.
        self._requested_paths: dict[Path, str] = {}

    @property
    def root(self) -> Path:
        """Resolved corpus root."""
        return self._root

    def check_layout(self) -> None:
        """Reject an unmigrated corpus instead of silently omitting its layers.

        A sync may leave old cached directories beside their replacements.
        Only the current directories are exposed by the memory file tools.
        """
        for old, current in (("task_only", "task-specific"), ("suite", "task-family")):
            if (self._root / old).exists() and not (self._root / current).is_dir():
                raise ValueError(
                    f"legacy memory directory {self._root / old}: download the "
                    f"updated corpus with {current}/ into a fresh directory"
                )

    file_tool_description = ""

    def authorize_read(self, path: str | Path) -> Path:
        """Resolve a path and enforce the current run's memory read permissions."""
        return self._authorize(path, write=False)

    def list_directory(self, path: str | Path) -> tuple[Path, list[str] | None]:
        """Authorize a listing and return the entries visible to this run."""
        resolved = self._authorize(path, write=False)
        if not resolved.exists():
            self._record_event(
                event="memory_read_failure",
                requested_path=str(path),
                resolved_path=str(resolved),
                scope=self._scope_for(resolved),
                reason="path_missing",
                exists=False,
                read_success=False,
            )
            return resolved, None
        entries = sorted(os.listdir(resolved))
        # Do not expose task-specific artifacts from another task to a strict
        # planner.  The exact pair remains discoverable when it exists.
        if self._memory_abstention == "strict_identity":
            try:
                relative = resolved.relative_to(self._root)
            except ValueError:
                relative = None
            if relative is not None and relative.parts == ("task-specific",):
                allowed = set(self._expected_task_specific_names())
                for name in entries:
                    if name not in allowed:
                        self._record_event(
                            event="memory_abstention",
                            requested_path=str(resolved / name),
                            resolved_path=str(resolved / name),
                            scope="task-specific",
                            kind=self._kind_for(resolved / name),
                            exists=True,
                            read_success=False,
                            reason="task_specific_identity_mismatch",
                            expected_files=sorted(allowed),
                            task_context=dict(self._task_context),
                        )
                entries = [name for name in entries if name in allowed]
            elif relative is not None and relative.parts == ("task-family",):
                allowed: list[str] = []
                for name in entries:
                    candidate = resolved / name
                    if not candidate.is_file():
                        allowed.append(name)
                        continue
                    check = self._family_identity_check(candidate)
                    if check is None:
                        allowed.append(name)
                        continue
                    reason, extra = check
                    self._record_event(
                        event="memory_abstention"
                        if reason != "task_family_frontmatter_unreadable"
                        else "memory_read_failure",
                        requested_path=str(candidate),
                        resolved_path=str(candidate),
                        scope="task-family",
                        kind=self._kind_for(candidate),
                        exists=True,
                        read_success=False,
                        reason=reason,
                        task_context=dict(self._task_context),
                        **extra,
                    )
                entries = allowed
        return resolved, entries

    def record_read(self, path: Path, content: str) -> None:
        """Record the content delivered by a file tool, when audit is required."""
        requested = self._requested_paths.pop(path, str(path))
        self._record_event(
            event="memory_read",
            requested_path=requested,
            resolved_path=str(path),
            scope=self._scope_for(path),
            kind=self._kind_for(path),
            exists=True,
            read_success=True,
            content_bytes=len(content.encode("utf-8")),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def set_task_context(self, **context: Any) -> None:
        """Update identity fields learned after simulator initialization.

        LIBERO exposes the verbatim task language only after the environment is
        constructed.  The CLI supplies suite/task before construction and the
        toolkit adds task_language immediately afterwards.
        """
        self._task_context.update({k: v for k, v in context.items() if v is not None})

    @property
    def memory_abstention(self) -> str:
        return self._memory_abstention

    def _record_event(self, *, event: str, **fields: Any) -> None:
        """Append one structured memory event without touching the corpus."""
        if self._read_log_path is None:
            return
        record = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self._memory_abstention,
            **fields,
        }
        self._read_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._read_log_lock, self._read_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _scope_for(self, path: Path) -> str:
        try:
            parts = path.relative_to(self._root).parts
        except ValueError:
            return "external"
        if not parts:
            return "root"
        if parts[0] in {"global", "task-family", "task-specific"}:
            return parts[0]
        return "index" if path.name == "MEMORY.md" else "other"

    def _kind_for(self, path: Path) -> str:
        name = path.name
        if name.endswith("_recipe.jsonl"):
            return "recipe"
        if name.endswith(".json"):
            return "audit"
        if name.endswith(".md"):
            return "markdown"
        return "file"

    def _expected_task_specific_names(self) -> tuple[str, ...]:
        suite = str(self._task_context.get("suite") or "")
        task = self._task_context.get("task")
        if task is None:
            return ()
        # Object-S is the corpus covered by this gate.  Keep the basename
        # exact, including the seed-0 suffix, so another task/seed cannot be
        # silently used as a fallback.
        if suite != "libero_object_swap":
            return ()
        try:
            task_id = int(task)
        except (TypeError, ValueError):
            return ()
        tag = f"object_swap_t{task_id}_s0"
        return (f"{tag}.json", f"{tag}_recipe.jsonl")

    def _expected_family_identity(self) -> dict[str, Any]:
        suite = str(self._task_context.get("suite") or "")
        if suite == "libero_object_swap":
            return {"suite": "libero_object", "regime": "swap"}
        # A strict gate is deliberately conservative for suites outside
        # Object-S: no family leaf is accepted unless its suite/regime is
        # exactly represented by the task identity.
        if suite.startswith("libero_"):
            pieces = suite.removeprefix("libero_").rsplit("_", 1)
            if len(pieces) == 2:
                return {"suite": pieces[0], "regime": pieces[1]}
        return {"suite": None, "regime": None}

    def _identity_failure(self, requested: str, resolved: Path, reason: str, **extra: Any) -> None:
        self._record_event(
            event="memory_abstention",
            requested_path=requested,
            resolved_path=str(resolved),
            scope=self._scope_for(resolved),
            kind=self._kind_for(resolved),
            exists=resolved.exists(),
            read_success=False,
            reason=reason,
            task_context=dict(self._task_context),
            **extra,
        )
        raise PermissionError(
            f"memory abstention ({reason}): refusing {requested!r} under strict_identity"
        )

    def _family_identity_check(
        self, resolved: Path
    ) -> tuple[str, dict[str, Any]] | None:
        """Return an auditable mismatch for a task-family leaf, if any."""
        try:
            metadata, _ = _split_frontmatter(resolved)
        except (OSError, ValueError) as exc:
            return "task_family_frontmatter_unreadable", {"error": str(exc)}
        expected = self._expected_family_identity()
        observed = {
            key: metadata.get(key)
            for key in ("suite", "regime", "task_id", "task_language")
        }
        if observed.get("suite") != expected.get("suite"):
            return "task_family_suite_mismatch", {
                "expected_identity": expected,
                "observed_identity": observed,
            }
        if observed.get("regime") != expected.get("regime"):
            return "task_family_regime_mismatch", {
                "expected_identity": expected,
                "observed_identity": observed,
            }
        task = self._task_context.get("task")
        if task is not None and str(observed.get("task_id")) != str(task):
            return "task_family_task_id_mismatch", {
                "expected_task_id": task,
                "observed_task_id": observed.get("task_id"),
            }
        expected_language = self._task_context.get("task_language")
        if expected_language is not None:
            if str(observed.get("task_language") or "").strip() != str(expected_language).strip():
                return "task_family_task_language_mismatch", {
                    "expected_task_language": expected_language,
                    "observed_task_language": observed.get("task_language"),
                }
        return None

    def _guard_identity(self, requested: str, resolved: Path) -> None:
        if self._memory_abstention != "strict_identity":
            return
        try:
            relative = resolved.relative_to(self._root)
        except ValueError:
            return
        parts = relative.parts
        if not parts or parts[0] not in {"task-family", "task-specific"}:
            return
        if parts[0] == "task-specific":
            # Listing the layer is allowed; the returned entries are filtered
            # by list_directory to the exact task pair.
            if len(parts) != 2:
                return
            expected = self._expected_task_specific_names()
            if parts[1] not in expected:
                self._identity_failure(
                    requested,
                    resolved,
                    "task_specific_identity_mismatch",
                    expected_files=list(expected),
                )
            return
        # A directory listing is permitted; only a leaf read is checked.
        if len(parts) != 2 or not resolved.is_file():
            return
        check = self._family_identity_check(resolved)
        if check is not None:
            reason, extra = check
            self._identity_failure(requested, resolved, reason, **extra)

    def authorize_write(self, path: str | Path) -> Path:
        """Resolve a path and enforce the current run's memory write permissions."""
        return self._authorize(path, write=True)

    def _authorize(self, path: str | Path, *, write: bool) -> Path:
        repo_root = get_repo_root()
        resolved = (repo_root / path).resolve()
        if not resolved.is_relative_to(self._root):
            if resolved.is_relative_to((repo_root / "memory").resolve()):
                raise PermissionError(
                    f"access to another robot's memory is denied: {path}"
                )
            return resolved

        parts = resolved.relative_to(self._root).parts
        if self._memory_access == "inbox_write" and parts[:3] == (
            "_internal",
            "inbox",
            self._inbox_cell_tag,
        ):
            return resolved
        if write:
            raise PermissionError(f"writing to memory is denied in this mode: {path}")
        # Keep published results and root-level Markdown readable, including
        # hand-maintained notes without frontmatter.
        if (
            not parts
            or parts[0] in {"global", "task-family", "task-specific", "results"}
            or (len(parts) == 1 and parts[0].endswith(".md"))
        ):
            requested = str(path)
            self._requested_paths[resolved] = requested
            if not resolved.exists() and parts and parts[0] in {"task-family", "task-specific"}:
                self._record_event(
                    event="memory_read_failure",
                    requested_path=requested,
                    resolved_path=str(resolved),
                    scope=parts[0],
                    kind=self._kind_for(resolved),
                    exists=False,
                    read_success=False,
                    reason="path_missing",
                    task_context=dict(self._task_context),
                )
            self._guard_identity(requested, resolved)
            return resolved
        raise PermissionError(f"reading this memory path is denied: {path}")

    def merge_memory(
        self,
        *,
        cell_tag: str,
        run_state_dir: str | Path,
        solved: bool,
    ) -> dict[str, Any]:
        """Publish one cell's inbox drafts and solved task artifacts.

        Drafts merge into global/task-family; conflicting prose is
        archived under _internal/conflicts. Solved audit/recipe pairs are
        copied to task-specific/. MEMORY.md is refreshed at the end.
        """
        self.check_layout()
        root = self._root
        run_dir = Path(run_state_dir).resolve()
        internal = root / "_internal"
        inbox = internal / "inbox" / cell_tag
        conflicts = internal / "conflicts"
        merged = internal / "merged"
        tiers = {
            "global": root / "global",
            "task-family": root / "task-family",
            "task": root / "task-specific",
        }
        for directory in (*tiers.values(), conflicts, merged, inbox.parent):
            directory.mkdir(parents=True, exist_ok=True)

        result: dict[str, Any] = {
            "cell": cell_tag,
            "global": 0,
            "task-family": 0,
            "task": 0,
            "evidence": 0,
            "conflicts": 0,
            "skipped": [],
        }
        lock_path = internal / "merge.lock"
        lock_path.touch(exist_ok=True)
        with lock_path.open("r+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            published_draft = False
            for source in sorted(inbox.glob("*.md")):
                try:
                    metadata, body = _split_frontmatter(source)
                    _validate(metadata)
                except ValueError as exc:
                    result["skipped"].append(f"{source.name}: {exc}")
                    continue
                memory_id = _canonical_id(source, metadata)
                metadata["id"] = memory_id
                destination = tiers[metadata["scope"]] / f"{memory_id}.md"
                published_draft = True
                if not destination.exists():
                    destination.write_text(_render(metadata, body))
                    result[metadata["scope"]] += 1
                    continue
                try:
                    old_metadata, old_body = _split_frontmatter(destination)
                except ValueError:
                    # Archive the incoming draft as a conflict.
                    conflict = conflicts / f"{memory_id}__from_{cell_tag}.md"
                    conflict.write_text(_render(metadata, body))
                    result["conflicts"] += 1
                    result["skipped"].append(
                        f"{source.name}: existing non-mergeable note "
                        f"{destination.name} left untouched"
                    )
                    continue
                credited = cell_tag in (
                    (old_metadata.get("evidence") or {}).get("cells") or []
                )
                if credited:
                    continue
                merged_metadata = _merge_evidence(old_metadata, metadata)
                destination.write_text(_render(merged_metadata, old_body))
                result["evidence"] += 1
                if body.strip() != old_body.strip():
                    conflict = conflicts / f"{memory_id}__from_{cell_tag}.md"
                    conflict.write_text(_render(metadata, body))
                    result["conflicts"] += 1

            if published_draft:
                archive = merged / cell_tag
                if archive.exists():
                    shutil.rmtree(archive)
                shutil.move(str(inbox), str(archive))

            audit = run_dir / f"{cell_tag}.json"
            recipe = run_dir / f"{cell_tag}_recipe.jsonl"
            if solved and audit.exists() and recipe.exists():
                audit_target = tiers["task"] / audit.name
                recipe_target = tiers["task"] / recipe.name
                if not audit_target.exists() and not recipe_target.exists():
                    shutil.copy2(audit, audit_target)
                    shutil.copy2(recipe, recipe_target)
                    result["task"] = 1
                elif audit_target.exists() != recipe_target.exists():
                    result["skipped"].append(
                        "incomplete existing task audit/recipe pair"
                    )

            self.rebuild_index()
        return result

    def rebuild_index(self) -> Path | None:
        """Regenerate MEMORY.md from global and task-family leaves.

        Leaves without parseable frontmatter are skipped individually; the
        index is rebuilt from the rest. Returns None and writes nothing when
        there are no leaves with parseable frontmatter.
        """
        self.check_layout()
        root = self._root
        groups: dict[str, list[tuple[str, dict[str, Any]]]] = {
            "global": [],
            "task-family": [],
        }
        for scope in groups:
            for path in sorted((root / scope).glob("*.md")):
                text = path.read_text(errors="replace")
                if not text.startswith("---"):
                    continue
                try:
                    metadata, _ = _split_frontmatter(path)
                except ValueError:
                    continue
                groups[scope].append((path.name, metadata))
        index = root / "MEMORY.md"
        if not any(groups.values()):
            return None
        lines = [
            "# Layered memory index",
            "",
            "Generated from memory leaf frontmatter.",
        ]
        for scope, title in (("global", "Global"), ("task-family", "Task-family")):
            lines.extend(("", f"## {title}", ""))
            if not groups[scope]:
                lines.append("_(none)_")
                continue
            for filename, metadata in groups[scope]:
                label = metadata.get("title") or metadata.get("id") or filename
                applies = metadata.get("applies_when") or ""
                suffix = f" — {applies}" if applies else ""
                lines.append(f"- [{label}]({scope}/{filename}){suffix}")
        index = root / "MEMORY.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text("\n".join(lines) + "\n")
        return index

    def validate(self) -> list[str]:
        """Return validation problems for global and task-family leaves.

        Only frontmatter-bearing leaves are schema-validated; plain Markdown
        is allowed silently.
        """
        try:
            self.check_layout()
        except ValueError as exc:
            return [str(exc)]
        root = self._root
        problems: list[str] = []
        ids: dict[str, Path] = {}
        for scope in ("global", "task-family"):
            for path in sorted((root / scope).glob("*.md")):
                text = path.read_text(errors="replace")
                if not text.startswith("---"):
                    continue
                try:
                    metadata, _ = _split_frontmatter(path)
                    _validate(metadata)
                except ValueError as exc:
                    problems.append(f"{path.relative_to(root)}: {exc}")
                    continue
                memory_id = str(metadata.get("id") or "")
                if memory_id != path.stem:
                    problems.append(
                        f"{path.relative_to(root)}: id {memory_id!r} does not match filename"
                    )
                if memory_id in ids:
                    problems.append(
                        f"{path.relative_to(root)}: duplicate id also in "
                        f"{ids[memory_id].relative_to(root)}"
                    )
                ids[memory_id] = path
        return problems

    def sync(
        self,
        *,
        remote_repo: str,
        allow_patterns: tuple[str, ...] | None = None,
    ) -> Path:
        """Sync this memory corpus from its Hugging Face dataset."""
        robot_name = self._root.name
        repo_id = os.environ.get(
            "RPENT_MEMORY_HF_REPO",
            remote_repo,
        )

        if os.environ.get("HF_HUB_OFFLINE") == "1":
            if not _has_local_memory(self._root):
                logger.warning(
                    "HF_HUB_OFFLINE=1 but no local memory was found under %s",
                    self._root,
                )
            return self._root

        try:
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id=repo_id,
                repo_type="dataset",
                local_dir=str(self._root.parent),
                allow_patterns=list(allow_patterns or (f"{robot_name}/**",)),
            )
        except Exception as exc:
            if _has_local_memory(self._root):
                logger.warning(
                    "could not sync '%s' from '%s': %s; "
                    "continuing with local memory under %s",
                    robot_name,
                    repo_id,
                    exc,
                    self._root,
                )
            else:
                logger.warning(
                    "could not sync '%s' from '%s': %s; "
                    "no local memory was found under %s",
                    robot_name,
                    repo_id,
                    exc,
                    self._root,
                )

        return self._root


__all__ = ["MemoryManager"]
