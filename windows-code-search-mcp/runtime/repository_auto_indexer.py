from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import asyncio
import json
import logging
import os

from watchfiles import awatch

from server_config import (
    Config,
    ManagedRepository,
    format_index_result_summary,
    index_root_display,
    normalize_repo_root,
    parse_bool,
    parse_list,
    path_is_within,
)
from runtime.search_engine_bridge import SearchEngineBridge


logger = logging.getLogger("server_runtime")


class RepositoryAutoIndexer:
    def __init__(self, config: Config, engine: SearchEngineBridge) -> None:
        self.config = config
        self.engine = engine
        self._config_lock = asyncio.Lock()
        self._index_lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None

    async def ensure_config_file(self) -> None:
        async with self._config_lock:
            await self._ensure_config_file_unlocked()

    async def _ensure_config_file_unlocked(self) -> None:
        config_path = Path(self.config.managed_repositories_path)
        if config_path.exists():
            return
        payload = {"version": 1, "repositories": []}
        await asyncio.to_thread(config_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(config_path.write_text, json.dumps(payload, indent=2), "utf8")

    async def _repair_repositories_config_unlocked(self, raw: str, reason: str) -> None:
        config_path = Path(self.config.managed_repositories_path)
        await asyncio.to_thread(config_path.parent.mkdir, parents=True, exist_ok=True)

        backup_path = ""
        if raw.strip():
            timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            backup_file = config_path.with_name(f"{config_path.stem}.invalid-{timestamp}{config_path.suffix}")
            await asyncio.to_thread(backup_file.write_text, raw, "utf8")
            backup_path = str(backup_file)

        payload = {"version": 1, "repositories": []}
        await asyncio.to_thread(config_path.write_text, json.dumps(payload, indent=2), "utf8")

        if backup_path:
            logger.warning(
                "Managed repositories config was %s; reset to default and backed up invalid content to %s",
                reason,
                backup_path,
            )
            return

        logger.warning("Managed repositories config was %s; reset to default", reason)

    async def load_repositories(self) -> list[ManagedRepository]:
        async with self._config_lock:
            return await self._load_repositories_unlocked()

    async def _load_repositories_unlocked(self) -> list[ManagedRepository]:
        await self._ensure_config_file_unlocked()
        config_path = Path(self.config.managed_repositories_path)
        try:
            raw = await asyncio.to_thread(config_path.read_text, "utf8")
        except FileNotFoundError:
            return []
        except Exception:
            logger.exception("Failed to read managed repositories config")
            return []

        if not raw.strip():
            await self._repair_repositories_config_unlocked(raw, "empty")
            return []

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            await self._repair_repositories_config_unlocked(raw, "not valid JSON")
            return []

        if not isinstance(parsed, dict):
            await self._repair_repositories_config_unlocked(raw, "not a JSON object")
            return []

        repositories = parsed.get("repositories", [])
        items: list[ManagedRepository] = []
        for item in repositories:
            if not isinstance(item, dict):
                continue
            repo_root = item.get("repo_root")
            if not isinstance(repo_root, str) or not repo_root.strip():
                continue
            items.append(
                ManagedRepository(
                    repo_root=repo_root,
                    watch=bool(item.get("watch", True)),
                    auto_index_on_start=bool(item.get("auto_index_on_start", True)),
                    last_indexed_at=str(item.get("last_indexed_at", "")),
                    last_index_reason=str(item.get("last_index_reason", "")),
                    last_result=item.get("last_result", {}) if isinstance(item.get("last_result", {}), dict) else {},
                    last_error=str(item.get("last_error", "")),
                )
            )
        return sorted(items, key=lambda item: item.repo_root.lower())

    async def _save_repositories_unlocked(self, repositories: list[ManagedRepository]) -> None:
        payload = {
            "version": 1,
            "repositories": [asdict(repository) for repository in sorted(repositories, key=lambda item: item.repo_root.lower())],
        }
        config_path = Path(self.config.managed_repositories_path)
        await asyncio.to_thread(config_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(config_path.write_text, json.dumps(payload, indent=2), "utf8")

    async def sync_env_repositories(self) -> None:
        repo_roots = parse_list(os.getenv("AUTO_INDEX_REPOS"))
        if not repo_roots:
            return

        watch = parse_bool(os.getenv("AUTO_INDEX_REPOS_WATCH"), True)
        auto_index_on_start = parse_bool(os.getenv("AUTO_INDEX_REPOS_ON_START"), True)

        async with self._config_lock:
            repositories = await self._load_repositories_unlocked()
            by_root = {repository.repo_root: repository for repository in repositories}
            changed = False
            for repo_root in repo_roots:
                normalized = normalize_repo_root(repo_root)
                existing = by_root.get(normalized)
                if existing is None:
                    repositories.append(
                        ManagedRepository(
                            repo_root=normalized,
                            watch=watch,
                            auto_index_on_start=auto_index_on_start,
                        )
                    )
                    changed = True
                    continue
                if existing.watch != watch or existing.auto_index_on_start != auto_index_on_start:
                    existing.watch = watch
                    existing.auto_index_on_start = auto_index_on_start
                    changed = True

            if changed:
                await self._save_repositories_unlocked(repositories)

    async def start(self) -> None:
        await self.ensure_config_file()
        await self.sync_env_repositories()
        await self.run_startup_indexing()
        await self.restart_watcher()

    async def stop(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None

    async def restart_watcher(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None

        repositories = await self.load_repositories()
        watch_roots = [repository.repo_root for repository in repositories if repository.watch and Path(repository.repo_root).exists()]
        if not watch_roots:
            logger.info("No managed repositories configured for file watching")
            return

        self._watch_task = asyncio.create_task(self._watch_loop(watch_roots))

    async def _watch_loop(self, watch_roots: list[str]) -> None:
        logger.info("Watching repositories for changes: %s", ", ".join(watch_roots))
        try:
            async for changes in awatch(
                *watch_roots,
                debounce=self.config.watch_debounce_ms,
                force_polling=self.config.watch_force_polling,
            ):
                affected_roots = set()
                for _, changed_path in changes:
                    for repo_root in watch_roots:
                        if path_is_within(changed_path, repo_root):
                            affected_roots.add(repo_root)

                for repo_root in sorted(affected_roots):
                    try:
                        logger.info("Detected file changes in %s; running incremental reindex", repo_root)
                        await self.run_index(repo_root, reason="watch")
                    except Exception:
                        logger.exception("Automatic reindex failed for %s", repo_root)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Repository watcher stopped unexpectedly")

    async def run_startup_indexing(self) -> None:
        repositories = await self.load_repositories()
        for repository in repositories:
            if not repository.auto_index_on_start:
                continue
            try:
                logger.info("Startup auto-indexing %s", repository.repo_root)
                result = await self.run_index(repository.repo_root, reason="startup")
                logger.info(
                    "Startup index complete for %s: %s",
                    repository.repo_root,
                    format_index_result_summary(result),
                )
            except Exception:
                logger.exception("Startup auto-index failed for %s", repository.repo_root)

    async def log_launch_status(self) -> None:
        repositories = await self.load_repositories()
        logger.info("Search index root: %s", index_root_display())

        if not repositories:
            logger.info("Managed repositories: none configured")
            return

        watched_repositories = [repository.repo_root for repository in repositories if repository.watch]
        logger.info(
            "Managed repositories loaded: %s total, %s watched for incremental indexing",
            len(repositories),
            len(watched_repositories),
        )

        for repository in repositories:
            last_result = repository.last_result if isinstance(repository.last_result, dict) else {}
            mode_bits = []
            if repository.watch:
                mode_bits.append("watch")
            if repository.auto_index_on_start:
                mode_bits.append("startup")
            mode_text = ", ".join(mode_bits) if mode_bits else "manual-only"

            if last_result:
                logger.info(
                    "Repo status: %s | modes=%s | last_reason=%s | last_indexed_at=%s | %s",
                    repository.repo_root,
                    mode_text,
                    repository.last_index_reason or "unknown",
                    repository.last_indexed_at or "never",
                    format_index_result_summary(last_result),
                )
                continue

            if repository.last_error:
                logger.info(
                    "Repo status: %s | modes=%s | last_reason=%s | last_error=%s",
                    repository.repo_root,
                    mode_text,
                    repository.last_index_reason or "unknown",
                    repository.last_error,
                )
                continue

            logger.info(
                "Repo status: %s | modes=%s | last_indexed_at=%s | no index run recorded yet",
                repository.repo_root,
                mode_text,
                repository.last_indexed_at or "never",
            )

    async def run_index(
        self,
        repo_root: str,
        reason: str = "manual",
        options: dict[str, object] | None = None,
        record_result: bool = True,
    ) -> dict[str, object]:
        normalized = normalize_repo_root(repo_root)
        payload = dict(options or {})
        payload["repoRoot"] = normalized
        async with self._index_lock:
            try:
                result = await asyncio.to_thread(self.engine.run_tool, "index_repository", payload)
            except Exception as exc:
                if record_result:
                    await self._record_index_failure(normalized, reason, str(exc))
                raise

            if not isinstance(result, dict):
                raise RuntimeError("Search engine returned an invalid index result")

            if record_result:
                await self._record_index_success(normalized, reason, result)
            return result

    async def _record_index_success(self, repo_root: str, reason: str, result: dict[str, object]) -> None:
        async with self._config_lock:
            repositories = await self._load_repositories_unlocked()
            existing = next((repository for repository in repositories if repository.repo_root == repo_root), None)
            if existing is None:
                repositories.append(ManagedRepository(repo_root=repo_root))
                existing = repositories[-1]
            existing.last_indexed_at = str(result.get("indexedAt", "")) or existing.last_indexed_at or ""
            if not existing.last_indexed_at:
                existing.last_indexed_at = str(result.get("repoIndexedAt", "")) or existing.last_indexed_at
            if not existing.last_indexed_at:
                existing.last_indexed_at = str(result.get("updatedAt", "")) or existing.last_indexed_at
            if not existing.last_indexed_at:
                existing.last_indexed_at = str(result.get("timestamp", "")) or existing.last_indexed_at
            if not existing.last_indexed_at:
                existing.last_indexed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            existing.last_index_reason = reason
            existing.last_result = result
            existing.last_error = ""
            await self._save_repositories_unlocked(repositories)

    async def _record_index_failure(self, repo_root: str, reason: str, error: str) -> None:
        async with self._config_lock:
            repositories = await self._load_repositories_unlocked()
            existing = next((repository for repository in repositories if repository.repo_root == repo_root), None)
            if existing is None:
                repositories.append(ManagedRepository(repo_root=repo_root))
                existing = repositories[-1]
            existing.last_index_reason = reason
            existing.last_error = error
            await self._save_repositories_unlocked(repositories)

    async def add_repository(
        self,
        repo_root: str,
        *,
        watch: bool = True,
        auto_index_on_start: bool = True,
        index_now: bool = True,
    ) -> dict[str, object]:
        normalized = normalize_repo_root(repo_root)
        async with self._config_lock:
            repositories = await self._load_repositories_unlocked()
            existing = next((repository for repository in repositories if repository.repo_root == normalized), None)
            if existing is None:
                existing = ManagedRepository(repo_root=normalized)
                repositories.append(existing)
            existing.watch = watch
            existing.auto_index_on_start = auto_index_on_start
            await self._save_repositories_unlocked(repositories)

        result = None
        if index_now:
            result = await self.run_index(normalized, reason="add")

        await self.restart_watcher()
        return {
            "repoRoot": normalized,
            "watch": watch,
            "autoIndexOnStart": auto_index_on_start,
            "indexedNow": index_now,
            "indexResult": result,
        }

    async def remove_repository(self, reference: str) -> dict[str, object]:
        async with self._config_lock:
            repositories = await self._load_repositories_unlocked()
            match = self._resolve_reference(repositories, reference)
            repositories = [repository for repository in repositories if repository.repo_root != match.repo_root]
            await self._save_repositories_unlocked(repositories)

        try:
            cleanup_result = await asyncio.to_thread(self.engine.run_tool, "remove_indexed_repository", {"repoRoot": match.repo_root})
        finally:
            await self.restart_watcher()
        return {
            "removed": True,
            "repoRoot": match.repo_root,
            "cleanupResult": cleanup_result if isinstance(cleanup_result, dict) else {},
        }

    def _resolve_reference(self, repositories: list[ManagedRepository], reference: str) -> ManagedRepository:
        normalized = reference.strip()
        if not normalized:
            raise ValueError("Repository reference is required")

        normalized_path = str(Path(normalized).expanduser().resolve()) if Path(normalized).exists() else normalized

        by_root = [repository for repository in repositories if repository.repo_root == normalized_path]
        if len(by_root) == 1:
            return by_root[0]

        by_name = [
            repository for repository in repositories if Path(repository.repo_root).name == normalized or repository.repo_root == normalized
        ]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise ValueError(f"Repository reference is ambiguous: {reference}")

        raise ValueError(f"Managed repository not found: {reference}")
