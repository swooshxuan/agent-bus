"""File-based task store. Zero dependencies, human-readable on disk.

Layout::

    <base>/tasks/<target>/<id>.json   one task per file (pending/running/done/failed)
    <base>/results/<id>.json          one result per file

Claiming is atomic: a ``<id>.json.lock`` file is created with O_EXCL, so two
workers racing for the same task cannot both win.
"""

import json
import os
import time
import uuid

# Results larger than this are truncated before being stored.
_MAX_RESULT = int(os.environ.get("AGENT_BUS_MAX_RESULT", "100000"))


class BusError(Exception):
    """Raised for expected, user-facing failures (bad id, not found, ...)."""


class Store:
    def __init__(self, base=None):
        self.base = base or os.environ.get("AGENT_BUS_DIR") or os.path.expanduser("~/.agent-bus")
        self.tasks_dir = os.path.join(self.base, "tasks")
        self.results_dir = os.path.join(self.base, "results")
        os.makedirs(self.tasks_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _now():
        return time.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _new_id():
        return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write(path, obj):
        tmp = "%s.%s.tmp" % (path, uuid.uuid4().hex[:6])
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _task_path(self, target, tid):
        return os.path.join(self.tasks_dir, target, tid + ".json")

    @staticmethod
    def _check_target(target):
        if not target or "/" in target or "\\" in target or target in (".", ".."):
            raise BusError("invalid target name: %r" % (target,))

    # -- operations -----------------------------------------------------
    def send(self, target, title, body="", sender=None, sig=None):
        """Create a pending task and return it."""
        self._check_target(target)
        os.makedirs(os.path.join(self.tasks_dir, target), exist_ok=True)
        tid = self._new_id()
        task = {
            "id": tid,
            "target": target,
            "title": title,
            "body": body,
            "sender": sender or os.environ.get("USER", "unknown"),
            "status": "pending",
            "created_at": self._now(),
        }
        if sig:
            task["sig"] = sig
        self._write(self._task_path(target, tid), task)
        return task

    def list_tasks(self, target, include_all=False):
        """Return pending tasks for ``target`` (all statuses if include_all)."""
        self._check_target(target)
        folder = os.path.join(self.tasks_dir, target)
        out = []
        if not os.path.isdir(folder):
            return out
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            task = self._read(os.path.join(folder, name))
            if include_all or task.get("status") == "pending":
                out.append(task)
        return out

    def get_task(self, tid, target=None):
        if target is not None:
            path = self._task_path(target, tid)
            if not os.path.exists(path):
                raise BusError("task not found: %s" % tid)
            return self._read(path)
        for name in sorted(os.listdir(self.tasks_dir)):
            path = self._task_path(name, tid)
            if os.path.exists(path):
                return self._read(path)
        raise BusError("task not found: %s" % tid)

    def claim(self, target, tid):
        """Atomically claim a pending task. Returns True on success."""
        self._check_target(target)
        path = self._task_path(target, tid)
        lock = path + ".lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.close(fd)
        if not os.path.exists(path):
            return False
        task = self._read(path)
        if task.get("status") != "pending":
            return False
        task["status"] = "running"
        task["claimed_at"] = self._now()
        self._write(path, task)
        return True

    def requeue(self, target, tid):
        """Put a stuck/running task back to pending (crash recovery)."""
        path = self._task_path(target, tid)
        if not os.path.exists(path):
            raise BusError("task not found: %s" % tid)
        task = self._read(path)
        task["status"] = "pending"
        task.pop("claimed_at", None)
        self._write(path, task)
        lock = path + ".lock"
        if os.path.exists(lock):
            os.unlink(lock)
        return task

    def reap(self, target, older_seconds=3600):
        """Requeue tasks stuck in 'running' for longer than older_seconds."""
        self._check_target(target)
        folder = os.path.join(self.tasks_dir, target)
        reaped = []
        if not os.path.isdir(folder):
            return reaped
        cutoff = time.time() - older_seconds
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(folder, name)
            task = self._read(path)
            if task.get("status") != "running":
                continue
            try:
                claimed = time.mktime(time.strptime(task.get("claimed_at", ""),
                                                    "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                claimed = 0
            if claimed and claimed < cutoff:
                task["status"] = "pending"
                task.pop("claimed_at", None)
                self._write(path, task)
                lock = path + ".lock"
                if os.path.exists(lock):
                    os.unlink(lock)
                reaped.append(task["id"])
        return reaped

    def prune(self, older_seconds, dry_run=False):
        """Remove done/failed tasks and their results older than a cutoff."""
        removed = []
        cutoff = time.time() - older_seconds
        for target in sorted(os.listdir(self.tasks_dir)):
            folder = os.path.join(self.tasks_dir, target)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(folder, name)
                task = self._read(path)
                if task.get("status") not in ("done", "failed"):
                    continue
                stamp = task.get("finished_at") or task.get("created_at") or ""
                try:
                    when = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    continue
                if when >= cutoff:
                    continue
                removed.append(task["id"])
                if dry_run:
                    continue
                for extra in (path, path + ".lock",
                              os.path.join(self.results_dir, task["id"] + ".json")):
                    if os.path.exists(extra):
                        os.unlink(extra)
        return removed

    def complete(self, target, tid, status="ok", result=""):
        path = self._task_path(target, tid)
        if not os.path.exists(path):
            raise BusError("task not found: %s" % tid)
        if status not in ("ok", "fail"):
            raise BusError("invalid status: %r" % (status,))
        if len(result) > _MAX_RESULT:
            dropped = len(result) - _MAX_RESULT
            result = result[:_MAX_RESULT] + "\n…[truncated %d chars]" % dropped
        task = self._read(path)
        task["status"] = "done" if status == "ok" else "failed"
        task["finished_at"] = self._now()
        self._write(path, task)
        record = {
            "id": tid,
            "target": target,
            "status": status,
            "result": result,
            "finished_at": task["finished_at"],
        }
        self._write(os.path.join(self.results_dir, tid + ".json"), record)
        return record

    def get_result(self, tid):
        path = os.path.join(self.results_dir, tid + ".json")
        if not os.path.exists(path):
            raise BusError("result not ready: %s" % tid)
        return self._read(path)

    def stats(self):
        out = {}
        for target in sorted(os.listdir(self.tasks_dir)):
            folder = os.path.join(self.tasks_dir, target)
            if not os.path.isdir(folder):
                continue
            counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
            for name in os.listdir(folder):
                if name.endswith(".json"):
                    status = self._read(os.path.join(folder, name)).get("status", "?")
                    counts[status] = counts.get(status, 0) + 1
            out[target] = counts
        return out
