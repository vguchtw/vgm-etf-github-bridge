from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitRepository:
    def __init__(self, root: Path, repository: str, branch: str, auth_mode: str):
        self.root = root
        self.repository = repository
        self.branch = branch
        self.auth_mode = auth_mode

    def _url(self) -> str:
        if self.auth_mode == "ssh":
            return f"git@github.com:{self.repository}.git"
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise GitError("GITHUB_TOKEN is required in HTTPS mode")
        return f"https://x-access-token:{token}@github.com/{self.repository}.git"

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = os.environ.get("GIT_AUTHOR_NAME", "VGM ETF Bridge")
        env["GIT_AUTHOR_EMAIL"] = os.environ.get("GIT_AUTHOR_EMAIL", "automation@localhost")
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"]
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"]
        result = subprocess.run(
            ["git", *args],
            cwd=self.root if self.root.exists() else self.root.parent,
            env=env,
            text=True,
            capture_output=True,
        )
        if check and result.returncode != 0:
            safe_err = result.stderr.replace(os.environ.get("GITHUB_TOKEN", ""), "***")
            raise GitError(f"git {' '.join(args)} failed: {safe_err.strip()}")
        return result

    def ensure_clone(self) -> None:
        if (self.root / ".git").exists():
            return
        self.root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", self.branch, self._url(), str(self.root)],
            check=True,
            text=True,
        )

    def pull(self) -> None:
        self._run("pull", "--ff-only", "origin", self.branch)

    def add_commit_push(self, message: str) -> bool:
        self._run("add", "-A")
        status = self._run("status", "--porcelain").stdout.strip()
        if not status:
            return False
        self._run("commit", "-m", message)
        self._run("push", "origin", self.branch)
        return True
