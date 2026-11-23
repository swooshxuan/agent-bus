"""Per-task sandboxes: none / worktree / docker.

The policy is chosen by the worker (never by the task body). ``auto`` uses a
git worktree when the task directory is a git repository and falls back to
``none`` with a warning otherwise. Docker limits the blast radius to the
mounted work directory; credentials are passed as environment variables, never
by mounting the home directory.
"""

import os
import shutil
import subprocess

_DOCKER_PASS_ENV = ("ANTHROPIC_API_KEY,ANTHROPIC_BASE_URL,"
                    "ANTHROPIC_AUTH_TOKEN,ANTHROPIC_MODEL")


class SandboxError(Exception):
    """Raised when a requested sandbox cannot be prepared."""


def _run(argv, cwd=None, check=True):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise SandboxError("command failed: %s\n%s" % (
            " ".join(argv), (proc.stderr or proc.stdout).strip()))
    return proc


class Sandbox:
    def __init__(self, mode, task_dir, task_id, log=None, keep=False,
                 image=None, network="bridge"):
        self.requested = mode
        self.task_dir = os.path.abspath(os.path.expanduser(task_dir))
        self.task_id = task_id
        self.log = log or (lambda message: None)
        self.keep = keep
        self.image = image or os.environ.get("AGENT_BUS_DOCKER_IMAGE",
                                             "agent-bus-worker:latest")
        self.network = network
        self.mode, self.run_dir, self.repo = self._prepare()

    # -- preparation ----------------------------------------------------
    def _prepare(self):
        mode = self.requested
        if mode == "auto":
            if self._is_git(self.task_dir):
                mode = "worktree"
            else:
                self.log("WARN: sandbox=auto fell back to none (not a git repo): %s"
                         % self.task_dir)
                self.log("WARN: tasks can modify files and run code; see SECURITY.md")
                mode = "none"
        if mode == "none":
            return "none", self.task_dir, None
        if mode == "worktree":
            if not self._is_git(self.task_dir):
                raise SandboxError(
                    "sandbox=worktree requires a git repo: %s" % self.task_dir)
            base = os.path.join(os.path.expanduser("~"), ".agent-bus", "worktrees")
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, self.task_id)
            _run(["git", "-C", self.task_dir, "worktree", "add",
                  "--detach", path, "HEAD"])
            return "worktree", path, self.task_dir
        if mode == "docker":
            if not shutil.which("docker"):
                raise SandboxError("sandbox=docker requires the docker CLI")
            return "docker", self.task_dir, None
        raise SandboxError("unknown sandbox mode: %s" % mode)

    @staticmethod
    def _is_git(path):
        if not os.path.isdir(path):
            return False
        proc = _run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                    check=False)
        return proc.returncode == 0

    # -- execution ------------------------------------------------------
    def wrap(self, argv):
        """Wrap a command so it runs inside the sandbox (docker only)."""
        if self.mode != "docker":
            return argv
        names = os.environ.get("AGENT_BUS_DOCKER_PASS_ENV", _DOCKER_PASS_ENV)
        cmd = ["docker", "run", "--rm", "-i",
               "-v", "%s:/work" % self.task_dir, "-w", "/work",
               "--memory", os.environ.get("AGENT_BUS_DOCKER_MEMORY", "2g"),
               "--cpus", os.environ.get("AGENT_BUS_DOCKER_CPUS", "2"),
               "--pids-limit", "256",
               "--network", self.network]
        # Non-root inside the container: the CLI refuses
        # --dangerously-skip-permissions as root, and matching the caller's
        # uid keeps the mounted work directory writable.
        if hasattr(os, "getuid"):
            cmd += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
        cmd += ["-e", "HOME=/tmp"]
        for name in names.split(","):
            name = name.strip()
            if name and os.environ.get(name) is not None:
                cmd += ["-e", name]
        return cmd + [self.image] + list(argv)

    def _git_out(self, *args):
        proc = _run(["git", "-C", self.run_dir] + list(args))
        return proc.stdout or ""

    # -- teardown -------------------------------------------------------
    def finish(self):
        """Collect a diff summary and clean up. Safe to call once."""
        info = {"mode": self.mode}
        if self.mode == "worktree":
            info["repo"] = self.repo
            info["worktree"] = self.run_dir
            try:
                info["diff_stat"] = self._git_out("diff", "--stat").strip()
                diff = self._git_out("diff")
                if len(diff) > 4000:
                    diff = diff[:4000] + "\n…[diff truncated]"
                info["diff"] = diff
            except SandboxError as exc:
                info["diff_error"] = str(exc)
            if not self.keep:
                proc = _run(["git", "-C", self.repo, "worktree", "remove",
                             "--force", self.run_dir], check=False)
                if proc.returncode != 0:
                    info["cleanup_error"] = (proc.stderr or "").strip()
        elif self.mode == "docker":
            info["image"] = self.image
            info["network"] = self.network
        return info
