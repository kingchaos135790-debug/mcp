from __future__ import annotations

from pathlib import Path
import json
import logging
import os
import subprocess

from server_config import Config


logger = logging.getLogger("server_runtime")


class SearchEngineBridge:
    def __init__(self, config: Config) -> None:
        self.config = config

    @property
    def search_engine_dir(self) -> Path:
        return Path(self.config.search_engine_dir)

    @property
    def entrypoint(self) -> Path:
        return self.search_engine_dir / "dist" / "cli" / "run-core.js"

    @staticmethod
    def _clip_output(value: str | None, limit: int = 600) -> str:
        normalized = (value or "").strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit]}..."

    def _log_command_result(
        self,
        level: int,
        message: str,
        command_name: str,
        payload: dict[str, object],
        *,
        returncode: int | str,
        stdout: str | None,
        stderr: str | None,
    ) -> None:
        logger.log(
            level,
            "%s: command=%s payload=%s returncode=%s stdout_none=%s stderr_none=%s stdout=%r stderr=%r",
            message,
            command_name,
            payload,
            returncode,
            stdout is None,
            stderr is None,
            self._clip_output(stdout),
            self._clip_output(stderr),
        )

    def _parse_json_output(self, stdout: str | None) -> object:
        normalized = (stdout or "").strip()
        if not normalized:
            return {}

        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            pass

        for index, char in enumerate(normalized):
            if char not in "[{":
                continue
            candidate = normalized[index:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        snippet = normalized if len(normalized) <= 600 else f"{normalized[:600]}..."
        raise RuntimeError(f"Invalid JSON returned by search engine: {snippet}")

    def run_tool(self, command_name: str, payload: dict[str, object]) -> object:
        if not self.search_engine_dir.exists():
            raise FileNotFoundError(f"Search engine directory not found: {self.search_engine_dir}")
        if not self.entrypoint.exists():
            raise FileNotFoundError(
                "Search engine build output not found. "
                f"Expected: {self.entrypoint}. Run npm run build in {self.search_engine_dir}."
            )

        try:
            completed = subprocess.run(
                [self.config.node_exe, str(self.entrypoint), command_name, json.dumps(payload)],
                cwd=str(self.search_engine_dir),
                capture_output=True,
                text=True,
                timeout=self.config.engine_timeout_seconds,
                check=False,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            self._log_command_result(
                logging.ERROR,
                "Search engine command timed out",
                command_name,
                payload,
                returncode="timeout",
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
            raise RuntimeError(f"{command_name} timed out after {self.config.engine_timeout_seconds}s") from exc

        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""

        if completed.returncode != 0:
            self._log_command_result(
                logging.ERROR,
                "Search engine command failed",
                command_name,
                payload,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            details = stderr_text.strip() or stdout_text.strip() or f"{command_name} failed"
            raise RuntimeError(details)

        if not stdout_text.strip():
            self._log_command_result(
                logging.WARNING,
                "Search engine returned empty stdout",
                command_name,
                payload,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            return {}

        try:
            return self._parse_json_output(stdout_text)
        except RuntimeError:
            self._log_command_result(
                logging.ERROR,
                "Search engine returned invalid JSON",
                command_name,
                payload,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            raise
