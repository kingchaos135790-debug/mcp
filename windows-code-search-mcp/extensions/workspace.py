from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from server_runtime import ServerContext

from .common import format_tool_result


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def resolve_workspace_root(repo_root: str = "") -> Path:
    raw = repo_root.strip() or "."
    candidate = Path(raw).expanduser().resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"Repository path not found: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {candidate}")
    return candidate


def _run_git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git_text(repo_root: Path, *args: str, check: bool = True) -> str:
    completed = _run_git(repo_root, *args, check=check)
    return completed.stdout.strip()


def _ensure_git_repo(repo_root: Path) -> Path:
    completed = _run_git(repo_root, "rev-parse", "--show-toplevel", check=False)
    if completed.returncode != 0:
        raise ValueError(f"Not a git repository: {repo_root}")
    return Path(completed.stdout.strip()).resolve()


def _parse_porcelain_status(status_text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in status_text.splitlines():
        if not line:
            continue
        if len(line) >= 2 and line[1] != " ":
            status = line[:2]
            path_text = line[2:].strip()
        else:
            status = line[:1].rjust(2)
            path_text = line[1:].strip()
        old_path = ""
        new_path = path_text
        if " -> " in path_text:
            old_path, new_path = path_text.split(" -> ", 1)
        entries.append({
            "status": status,
            "path": new_path,
            "oldPath": old_path,
            "staged": status[0],
            "unstaged": status[1],
            "tracked": status != "??",
        })
    return entries


def _parse_name_status(name_status_text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in name_status_text.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if len(parts) == 1:
            continue
        if status.startswith("R") or status.startswith("C"):
            entries.append({"status": status, "path": parts[-1], "oldPath": parts[1] if len(parts) > 2 else ""})
        else:
            entries.append({"status": status, "path": parts[1], "oldPath": ""})
    return entries


def _summarize_status(entries: list[dict[str, object]]) -> dict[str, int]:
    summary = {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "renamed": 0,
        "copied": 0,
        "untracked": 0,
        "other": 0,
    }
    for entry in entries:
        status = str(entry.get("status", ""))
        path_status = status.strip()
        chars = set(path_status)
        if status == "??":
            summary["untracked"] += 1
        elif "M" in chars:
            summary["modified"] += 1
        elif "A" in chars:
            summary["added"] += 1
        elif "D" in chars:
            summary["deleted"] += 1
        elif "R" in chars:
            summary["renamed"] += 1
        elif "C" in chars:
            summary["copied"] += 1
        else:
            summary["other"] += 1
    return summary


def build_workspace_patch_summary(*, repo_root: str = "", include_diff: bool = False, max_diff_chars: int = 4000) -> dict[str, object]:
    requested_root = resolve_workspace_root(repo_root)
    git_root = _ensure_git_repo(requested_root)
    status_text = _git_text(git_root, "status", "--short")
    status_entries = _parse_porcelain_status(status_text)
    name_status_text = _git_text(git_root, "diff", "--name-status")
    staged_name_status_text = _git_text(git_root, "diff", "--cached", "--name-status")
    shortstat = _git_text(git_root, "diff", "--shortstat")
    staged_shortstat = _git_text(git_root, "diff", "--cached", "--shortstat")
    stat = _git_text(git_root, "diff", "--stat")
    staged_stat = _git_text(git_root, "diff", "--cached", "--stat")
    branch = _git_text(git_root, "branch", "--show-current", check=False)
    head = _git_text(git_root, "rev-parse", "--short", "HEAD", check=False)
    payload: dict[str, object] = {
        "status": "ok",
        "repoRoot": str(git_root),
        "branch": branch,
        "head": head,
        "dirty": bool(status_entries),
        "summary": _summarize_status(status_entries),
        "statusEntries": status_entries,
        "unstagedNameStatus": _parse_name_status(name_status_text),
        "stagedNameStatus": _parse_name_status(staged_name_status_text),
        "shortstat": shortstat,
        "stagedShortstat": staged_shortstat,
        "stat": stat,
        "stagedStat": staged_stat,
        "suggested_next_tool_call": {
            "tool": "session_edit_context",
            "arguments": {"repo_root": str(git_root)},
        },
    }
    if include_diff:
        diff_text = _git_text(git_root, "diff", f"--unified=3")
        if max_diff_chars > 0 and len(diff_text) > max_diff_chars:
            payload["diff"] = diff_text[:max_diff_chars]
            payload["diffTruncated"] = True
            payload["diffTotalChars"] = len(diff_text)
        else:
            payload["diff"] = diff_text
            payload["diffTruncated"] = False
            payload["diffTotalChars"] = len(diff_text)
    return payload


def _parse_diff_hunks(diff_text: str, *, repo_root: Path, context_lines: int, max_files: int) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current)
                if len(files) >= max_files:
                    return files
            current = {"path": "", "oldPath": "", "hunks": []}
            continue
        if current is None:
            continue
        if line.startswith("--- "):
            old_path = line[4:].strip()
            current["oldPath"] = old_path[2:] if old_path.startswith("a/") else old_path
            continue
        if line.startswith("+++ "):
            new_path = line[4:].strip()
            current["path"] = new_path[2:] if new_path.startswith("b/") else new_path
            continue
        match = _HUNK_RE.match(line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        start_line = max(1, new_start - context_lines)
        end_line = max(start_line, new_start + max(new_count, 1) + context_lines - 1)
        path_text = str(current.get("path") or current.get("oldPath") or "")
        hunks = current.setdefault("hunks", [])
        assert isinstance(hunks, list)
        hunks.append({
            "oldStart": old_start,
            "oldCount": old_count,
            "newStart": new_start,
            "newCount": new_count,
            "recommendedReadRange": {"startLine": start_line, "endLine": end_line},
            "suggested_next_tool_call": {
                "tool": "get_file_range",
                "arguments": {"repo_root": str(repo_root), "file_path": path_text, "start_line": start_line, "end_line": end_line},
            },
        })
    if current is not None and len(files) < max_files:
        files.append(current)
    return files


def build_session_edit_context(*, repo_root: str = "", context_lines: int = 3, max_files: int = 20) -> dict[str, object]:
    requested_root = resolve_workspace_root(repo_root)
    git_root = _ensure_git_repo(requested_root)
    bounded_context = max(0, min(context_lines, 20))
    bounded_max_files = max(1, min(max_files, 200))
    diff_text = _git_text(git_root, "diff", f"--unified=0")
    staged_diff_text = _git_text(git_root, "diff", "--cached", f"--unified=0")
    status_text = _git_text(git_root, "status", "--short")
    status_entries = _parse_porcelain_status(status_text)
    unstaged_files = _parse_diff_hunks(diff_text, repo_root=git_root, context_lines=bounded_context, max_files=bounded_max_files)
    staged_files = _parse_diff_hunks(staged_diff_text, repo_root=git_root, context_lines=bounded_context, max_files=bounded_max_files)
    changed_paths = []
    seen: set[str] = set()
    for entry in status_entries:
        path = str(entry.get("path") or "")
        if path and path not in seen:
            seen.add(path)
            changed_paths.append(path)
    return {
        "status": "ok",
        "repoRoot": str(git_root),
        "contextLines": bounded_context,
        "changedPathCount": len(changed_paths),
        "changedPaths": changed_paths[:bounded_max_files],
        "unstagedFiles": unstaged_files,
        "stagedFiles": staged_files,
        "untrackedFiles": [str(entry.get("path")) for entry in status_entries if entry.get("status") == "??"],
        "suggested_next_tool_call": {
            "tool": "workspace_patch_summary",
            "arguments": {"repo_root": str(git_root), "include_diff": False},
        },
    }


class WorkspaceSummaryExtension:
    def register(self, mcp: FastMCP, context: ServerContext) -> None:
        @mcp.tool(
            name="workspace_patch_summary",
            description="Summarize the current Git patch in a workspace, including status, changed files, stats, and an optional bounded diff.",
            annotations=ToolAnnotations(title="workspace_patch_summary", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        )
        def workspace_patch_summary(repo_root: str = "", include_diff: bool = False, max_diff_chars: int = 4000) -> str:
            return format_tool_result(build_workspace_patch_summary(repo_root=repo_root, include_diff=include_diff, max_diff_chars=max_diff_chars))

        @mcp.tool(
            name="session_edit_context",
            description="Return changed files and suggested fresh read ranges for a multi-step edit session from the current Git diff.",
            annotations=ToolAnnotations(title="session_edit_context", readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
        )
        def session_edit_context(repo_root: str = "", context_lines: int = 3, max_files: int = 20) -> str:
            return format_tool_result(build_session_edit_context(repo_root=repo_root, context_lines=context_lines, max_files=max_files))

    async def start(self, context: ServerContext) -> None:
        return None

    async def stop(self, context: ServerContext) -> None:
        return None

