import json
import os
import shutil
import tempfile
import time
import unittest

from agent_bus import store as store_mod
from agent_bus.store import BusError, Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-bus-test-")
        self.store = Store(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_send_and_list(self):
        task = self.store.send("lab", "汇总 CSV", "把 data 目录汇总", sender="laptop")
        self.assertEqual(task["status"], "pending")
        pending = self.store.list_tasks("lab")
        self.assertEqual([t["id"] for t in pending], [task["id"]])
        self.assertEqual(pending[0]["sender"], "laptop")
        # other targets are isolated
        self.assertEqual(self.store.list_tasks("laptop"), [])

    def test_claim_is_atomic(self):
        task = self.store.send("lab", "t")
        self.assertTrue(self.store.claim("lab", task["id"]))
        # second claim must lose even though the task file still exists
        self.assertFalse(self.store.claim("lab", task["id"]))
        self.assertEqual(self.store.list_tasks("lab"), [])
        self.assertEqual(self.store.get_task(task["id"])["status"], "running")

    def test_complete_and_result(self):
        task = self.store.send("lab", "t", "body")
        self.store.claim("lab", task["id"])
        record = self.store.complete("lab", task["id"], "ok", "done!")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(self.store.get_result(task["id"])["result"], "done!")
        self.assertEqual(self.store.get_task(task["id"])["status"], "done")
        self.assertEqual(self.store.stats()["lab"]["done"], 1)
        self.assertEqual(self.store.stats()["lab"]["pending"], 0)

    def test_fail_status(self):
        task = self.store.send("lab", "t")
        self.store.claim("lab", task["id"])
        self.store.complete("lab", task["id"], "fail", "boom")
        self.assertEqual(self.store.get_task(task["id"])["status"], "failed")
        self.assertEqual(self.store.stats()["lab"]["failed"], 1)

    def test_requeue(self):
        task = self.store.send("lab", "t")
        self.assertTrue(self.store.claim("lab", task["id"]))
        self.store.requeue("lab", task["id"])
        self.assertEqual(self.store.get_task(task["id"])["status"], "pending")
        self.assertTrue(self.store.claim("lab", task["id"]))

    def test_invalid_target(self):
        with self.assertRaises(BusError):
            self.store.send("../etc", "t")
        with self.assertRaises(BusError):
            self.store.send("", "t")

    def test_missing_task(self):
        with self.assertRaises(BusError):
            self.store.get_task("nope")
        with self.assertRaises(BusError):
            self.store.get_result("nope")

    def test_reap_stale_running(self):
        task = self.store.send("lab", "t")
        self.assertTrue(self.store.claim("lab", task["id"]))
        path = os.path.join(self.store.tasks_dir, "lab", task["id"] + ".json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["claimed_at"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(time.time() - 7200))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.assertEqual(self.store.reap("lab", 3600), [task["id"]])
        self.assertEqual(self.store.get_task(task["id"])["status"], "pending")
        self.assertTrue(self.store.claim("lab", task["id"]))

    def test_reap_keeps_fresh_running(self):
        task = self.store.send("lab", "t")
        self.assertTrue(self.store.claim("lab", task["id"]))
        self.assertEqual(self.store.reap("lab", 3600), [])
        self.assertEqual(self.store.get_task(task["id"])["status"], "running")

    def _backdate(self, target, tid, days):
        path = os.path.join(self.store.tasks_dir, target, tid + ".json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["finished_at"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_prune_removes_only_old_finished(self):
        old = self.store.send("lab", "old")
        self.store.claim("lab", old["id"])
        self.store.complete("lab", old["id"], "ok", "x")
        new = self.store.send("lab", "new")
        self.store.claim("lab", new["id"])
        self.store.complete("lab", new["id"], "ok", "y")
        self._backdate("lab", old["id"], 10)
        self.assertEqual(self.store.prune(7 * 86400), [old["id"]])
        with self.assertRaises(BusError):
            self.store.get_task(old["id"])
        with self.assertRaises(BusError):
            self.store.get_result(old["id"])
        self.assertEqual(self.store.get_task(new["id"])["status"], "done")

    def test_prune_dry_run_keeps_files(self):
        task = self.store.send("lab", "t")
        self.store.claim("lab", task["id"])
        self.store.complete("lab", task["id"], "ok", "")
        self._backdate("lab", task["id"], 10)
        self.assertEqual(self.store.prune(86400, dry_run=True), [task["id"]])
        self.assertEqual(self.store.get_task(task["id"])["status"], "done")

    def test_result_truncated(self):
        task = self.store.send("lab", "t")
        self.store.claim("lab", task["id"])
        big = "x" * (store_mod._MAX_RESULT + 50)
        record = self.store.complete("lab", task["id"], "ok", big)
        self.assertIn("truncated 50 chars", record["result"])
        self.assertLess(len(record["result"]), len(big))


if __name__ == "__main__":
    unittest.main()
