import shutil
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
