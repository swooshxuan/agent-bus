import os
import shutil
import stat
import tempfile
import unittest

from agent_bus.remote import RemoteStore


def _write_exec(path, content):
    with open(path, "w") as fh:
        fh.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


@unittest.skipIf(os.name == "nt", "fake ssh harness requires bash")
class RemoteStoreTest(unittest.TestCase):
    """Exercise the SSH path without a network: a fake ssh that runs locally."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-bus-remote-")
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        _write_exec(os.path.join(bindir, "fakessh"),
                    '#!/bin/bash\ncmd="${@: -1}"\nexec bash -c "$cmd"\n')
        _write_exec(os.path.join(bindir, "agent-bus"),
                    '#!/bin/bash\nexec python3 -m agent_bus.cli "$@"\n')
        self.base = os.path.join(self.tmp, "bus")
        self._saved = {k: os.environ.get(k) for k in
                       ("PATH", "AGENT_BUS_SSH_BIN", "AGENT_BUS_REMOTE_CMD")}
        os.environ["PATH"] = bindir + os.pathsep + self._saved["PATH"]
        os.environ["AGENT_BUS_SSH_BIN"] = os.path.join(bindir, "fakessh")
        os.environ["AGENT_BUS_REMOTE_CMD"] = "agent-bus"
        self.store = RemoteStore("fakehost", base=self.base)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp)

    def test_full_cycle(self):
        task = self.store.send("lab", "远程任务", "echo remote-ok", sender="laptop")
        self.assertEqual(task["status"], "pending")

        pending = self.store.list_tasks("lab")
        self.assertEqual([t["id"] for t in pending], [task["id"]])

        self.assertTrue(self.store.claim("lab", task["id"]))
        self.assertFalse(self.store.claim("lab", task["id"]))

        record = self.store.complete("lab", task["id"], "ok", "remote-ok\n")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(self.store.get_result(task["id"])["result"], "remote-ok\n")

        self.assertEqual(self.store.stats()["lab"]["done"], 1)


if __name__ == "__main__":
    unittest.main()
