from __future__ import annotations

from contextlib import suppress
import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


DEFAULT_CONFIG_PATH = Path(
    os.getenv(
        "AUTO_INDEX_CONFIG_PATH",
        Path(__file__).resolve().parent / "managed-repositories.json",
    )
)
DEFAULT_SEARCH_ENGINE_DIR = Path(
    os.getenv(
        "SEARCH_ENGINE_DIR",
        r"E:\Program Files\mcp\ripgrep-treesitter-qdrant-mcp",
    )
)
DEFAULT_NODE_EXE = os.getenv("NODE_EXE", "node")
DEFAULT_INDEX_ROOT = os.getenv("INDEX_ROOT", r"E:\mcp-index-data")


def _status_prefix() -> str:
    return f"INDEX_ROOT: {DEFAULT_INDEX_ROOT}"


class RepoManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Windows Code Search Repo Manager")
        self.root.geometry("860x520")
        self.root.minsize(760, 460)

        self.config_path = DEFAULT_CONFIG_PATH
        self.repositories: list[dict[str, object]] = []
        self.selected_index: int | None = None

        self.repo_root_var = tk.StringVar()
        self.watch_var = tk.BooleanVar(value=True)
        self.auto_index_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=f"Config: {self.config_path} | {_status_prefix()}")

        self._build_ui()
        self._ensure_config_file()
        self._load_config()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=4)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=12)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        ttk.Label(left, text="Managed Repositories").grid(row=0, column=0, sticky="w")

        self.repo_list = tk.Listbox(left, exportselection=False)
        self.repo_list.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
        self.repo_list.bind("<<ListboxSelect>>", self._on_select)

        left_buttons = ttk.Frame(left)
        left_buttons.grid(row=2, column=0, sticky="ew")
        left_buttons.columnconfigure((0, 1), weight=1)

        ttk.Button(left_buttons, text="Add Folder", command=self._add_folder).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(left_buttons, text="Remove", command=self._remove_selected).grid(row=0, column=1, sticky="ew")
        ttk.Button(left_buttons, text="Open Config Folder", command=self._open_config_folder).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(8, 0))
        ttk.Button(left_buttons, text="Reload", command=self._load_config).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        right = ttk.Frame(self.root, padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Repository Settings").grid(row=0, column=0, sticky="w")

        form = ttk.Frame(right)
        form.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Repo Path").grid(row=0, column=0, sticky="w", pady=(0, 8))
        repo_entry = ttk.Entry(form, textvariable=self.repo_root_var)
        repo_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Checkbutton(form, text="Watch for file changes", variable=self.watch_var).grid(row=1, column=1, sticky="w", pady=(0, 8))
        ttk.Checkbutton(form, text="Auto-index on startup", variable=self.auto_index_var).grid(row=2, column=1, sticky="w")

        actions = ttk.Frame(right)
        actions.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        actions.columnconfigure((0, 1, 2), weight=1)

        ttk.Button(actions, text="Apply Changes", command=self._apply_selected).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Save All", command=self._save_config).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Index Selected Now", command=self._index_selected).grid(row=0, column=2, sticky="ew")

        notes = ttk.Label(
            right,
            text=(
                "Use Add Folder to pick a repo from a folder dialog.\n"
                "Remove updates managed-repositories.json and deletes indexed artifacts/vectors.\n"
                "Set INDEX_ROOT in the launcher .bat to move search data outside watched repos.\n"
                "If the MCP server is already running, restart it after edits so startup/watch settings reload."
            ),
            justify="left",
        )
        notes.grid(row=3, column=0, sticky="w", pady=(16, 0))

        status = ttk.Label(self.root, textvariable=self.status_var, padding=(12, 0, 12, 12))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _ensure_config_file(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps({"version": 1, "repositories": []}, indent=2), encoding="utf8")

    def _load_config(self) -> None:
        self._ensure_config_file()
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf8"))
            repositories = payload.get("repositories", []) if isinstance(payload, dict) else []
            self.repositories = [item for item in repositories if isinstance(item, dict)]
        except Exception as exc:
            messagebox.showerror("Load Failed", f"Could not read config:\n{exc}")
            return

        self._refresh_list()
        self.status_var.set(f"Loaded config: {self.config_path} | {_status_prefix()}")

    def _save_config(self) -> None:
        self._apply_selected(silent=True)
        if not self._write_config():
            return

        self.status_var.set(f"Saved config: {self.config_path} | {_status_prefix()}")
        messagebox.showinfo("Saved", "Repository config saved.")

    def _write_config(self) -> bool:
        payload = {
            "version": 1,
            "repositories": self.repositories,
        }
        try:
            self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf8")
        except Exception as exc:
            messagebox.showerror("Save Failed", f"Could not save config:\n{exc}")
            return False
        return True

    def _refresh_list(self) -> None:
        self.repo_list.delete(0, tk.END)
        for repo in self.repositories:
            repo_root = str(repo.get("repo_root", ""))
            flags = []
            if repo.get("watch", True):
                flags.append("watch")
            if repo.get("auto_index_on_start", True):
                flags.append("startup")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            self.repo_list.insert(tk.END, f"{repo_root}{suffix}")

        if self.repositories:
            if self.selected_index is None or self.selected_index >= len(self.repositories):
                self.selected_index = 0
            self.repo_list.selection_clear(0, tk.END)
            self.repo_list.selection_set(self.selected_index)
            self.repo_list.activate(self.selected_index)
            self._populate_form(self.selected_index)
        else:
            self.selected_index = None
            self.repo_root_var.set("")
            self.watch_var.set(True)
            self.auto_index_var.set(True)

    def _populate_form(self, index: int) -> None:
        repo = self.repositories[index]
        self.selected_index = index
        self.repo_root_var.set(str(repo.get("repo_root", "")))
        self.watch_var.set(bool(repo.get("watch", True)))
        self.auto_index_var.set(bool(repo.get("auto_index_on_start", True)))

    def _on_select(self, event: object | None = None) -> None:
        selection = self.repo_list.curselection()
        if not selection:
            return
        self._populate_form(int(selection[0]))

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Repository Folder")
        if not folder:
            return

        normalized = str(Path(folder).resolve())
        for index, repo in enumerate(self.repositories):
            if str(repo.get("repo_root", "")) == normalized:
                self.selected_index = index
                self._refresh_list()
                self.status_var.set(f"Repository already exists: {normalized}")
                return

        self.repositories.append(
            {
                "repo_root": normalized,
                "watch": True,
                "auto_index_on_start": True,
            }
        )
        self.selected_index = len(self.repositories) - 1
        self._refresh_list()
        self.status_var.set(f"Added repository: {normalized}")

    def _remove_selected(self) -> None:
        if self.selected_index is None:
            return

        repo_root = str(self.repositories[self.selected_index].get("repo_root", ""))
        if not messagebox.askyesno(
            "Remove Repository",
            (
                f"Remove this repository from managed auto-indexing and delete its indexed data?\n\n"
                f"{repo_root}"
            ),
        ):
            return

        previous_repositories = list(self.repositories)
        previous_index = self.selected_index
        del self.repositories[self.selected_index]
        self.selected_index = None
        if not self._write_config():
            self.repositories = previous_repositories
            self.selected_index = previous_index
            self._refresh_list()
            return

        self._refresh_list()
        try:
            self._run_engine_command("remove_indexed_repository", {"repoRoot": repo_root}, timeout=1800)
        except Exception as exc:
            self.status_var.set(f"Removed repository but cleanup failed: {repo_root}")
            messagebox.showwarning(
                "Cleanup Failed",
                f"Removed repository from config, but indexed cleanup failed:\n{exc}",
            )
            return

        self.status_var.set(f"Removed repository and cleaned index data: {repo_root}")

    def _apply_selected(self, silent: bool = False) -> None:
        if self.selected_index is None:
            return

        repo_root = self.repo_root_var.get().strip()
        if not repo_root:
            if not silent:
                messagebox.showwarning("Missing Path", "Choose or enter a repository path first.")
            return

        normalized = str(Path(repo_root).expanduser().resolve())
        self.repositories[self.selected_index]["repo_root"] = normalized
        self.repositories[self.selected_index]["watch"] = bool(self.watch_var.get())
        self.repositories[self.selected_index]["auto_index_on_start"] = bool(self.auto_index_var.get())
        self._refresh_list()
        self.status_var.set(f"Updated repository: {normalized}")

    def _open_config_folder(self) -> None:
        os.startfile(self.config_path.parent)

    def _index_selected(self) -> None:
        if self.selected_index is None:
            messagebox.showwarning("No Selection", "Select a repository first.")
            return

        self._apply_selected(silent=True)
        repo_root = str(self.repositories[self.selected_index].get("repo_root", "")).strip()
        if not repo_root:
            messagebox.showwarning("Missing Path", "Choose or enter a repository path first.")
            return

        try:
            completed = self._run_engine_command("index_repository", {"repoRoot": repo_root}, timeout=1800)
        except Exception as exc:
            messagebox.showerror("Index Failed", f"Could not start indexing:\n{exc}")
            return

        self.status_var.set(f"Indexed repository: {repo_root}")
        messagebox.showinfo("Index Complete", completed.stdout.strip() or "Indexing completed.")

    def _run_engine_command(self, command_name: str, payload: dict[str, object], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
        entrypoint = DEFAULT_SEARCH_ENGINE_DIR / "dist" / "cli" / "run-core.js"
        if not entrypoint.exists():
            raise FileNotFoundError(
                "Search engine build output not found. "
                f"Expected: {entrypoint}. Run the MCP launcher first or build the search engine."
            )

        completed = subprocess.run(
            [DEFAULT_NODE_EXE, str(entrypoint), command_name, json.dumps(payload)],
            cwd=str(DEFAULT_SEARCH_ENGINE_DIR),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or f"{command_name} failed."
            raise RuntimeError(details)
        return completed


def main() -> int:
    root = tk.Tk()
    style = ttk.Style()
    if sys.platform.startswith("win"):
        with suppress(Exception):
            style.theme_use("vista")
    RepoManagerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
