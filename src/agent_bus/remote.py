"""Client that talks to a bus host over SSH.

This is what makes agent-bus NAT-friendly: the worker only needs outbound SSH
to the bus host. Pin the key with ``command="agent-bus-gate"`` on the bus host
and the worker can do nothing else on it.
"""

import json
import os
import shlex
import subprocess

from .store import BusError


class RemoteStore:
    """Same interface as :class:`agent_bus.store.Store`, backed by SSH."""

    def __init__(self, host, base=None, key=None, ssh_bin=None, ssh_port=None,
                 ssh_proxy=None, ssh_known_hosts=None):
        self.host = host
        self.base = base
        self.key = key or os.environ.get("AGENT_BUS_SSH_KEY")
        self.cmd = os.environ.get("AGENT_BUS_REMOTE_CMD", "agent-bus")
        self.ssh_bin = ssh_bin or os.environ.get("AGENT_BUS_SSH_BIN", "ssh")
        self.ssh_port = ssh_port or os.environ.get("AGENT_BUS_SSH_PORT")
        self.ssh_proxy = ssh_proxy or os.environ.get("AGENT_BUS_SSH_PROXY_COMMAND")
        self.ssh_known_hosts = (ssh_known_hosts
                                or os.environ.get("AGENT_BUS_SSH_KNOWN_HOSTS"))

    def _ssh(self):
        argv = [self.ssh_bin, "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=accept-new"]
        if self.ssh_port:
            argv += ["-p", str(self.ssh_port)]
        if self.key:
            argv += ["-i", self.key]
        if self.ssh_proxy:
            argv += ["-o", "ProxyCommand=" + str(self.ssh_proxy)]
        if self.ssh_known_hosts:
            argv += ["-o", "UserKnownHostsFile=" + str(self.ssh_known_hosts)]
        argv.append(self.host)
        return argv

    def _run(self, args, stdin=None, ok_codes=(0,)):
        remote = self.cmd
        if self.base:
            remote += " --base " + shlex.quote(self.base)
        remote += " " + " ".join(shlex.quote(a) for a in args)
        proc = subprocess.run(self._ssh() + [remote], input=stdin,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode not in ok_codes:
            raise BusError(proc.stderr.strip() or "remote agent-bus failed")
        return proc.stdout

    def send(self, target, title, body="", sender=None, sig=None):
        args = ["send", target, title, "--json"]
        if sender:
            args += ["--from", sender]
        if sig:
            args += ["--sig", sig]
        return json.loads(self._run(args, stdin=body))

    def list_tasks(self, target, include_all=False):
        args = ["tasks", target, "--json"] + (["--all"] if include_all else [])
        return json.loads(self._run(args))

    def get_task(self, tid, target=None):
        args = ["show", tid, "--json"]
        if target:
            args += ["--target", target]
        return json.loads(self._run(args))

    def claim(self, target, tid):
        out = self._run(["claim", target, tid, "--json"], ok_codes=(0, 1))
        return json.loads(out)["claimed"]

    def requeue(self, target, tid):
        return json.loads(self._run(["requeue", target, tid, "--json"]))

    def prune(self, older_seconds, dry_run=False):
        days = max(1, int(older_seconds // 86400))
        args = ["prune", "--older-days", str(days), "--json"]
        if dry_run:
            args.append("--dry-run")
        return json.loads(self._run(args))["removed"]

    def reap(self, target, older_seconds=3600):
        minutes = max(1, int(older_seconds // 60))
        out = self._run(["reap", target, "--older", str(minutes), "--json"])
        return json.loads(out)["reaped"]

    def complete(self, target, tid, status="ok", result=""):
        return json.loads(self._run(
            ["done", target, tid, "--status", status, "--json"], stdin=result))

    def get_result(self, tid):
        return json.loads(self._run(["result", tid, "--json"]))

    def stats(self):
        return json.loads(self._run(["list", "--json"]))
