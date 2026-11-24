import os
import tempfile
import unittest

from agent_bus.cli import _watch_events, main
from agent_bus.store import Store


class WorkersTest(unittest.TestCase):
    def test_two_workers_process_two_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "bus")
            work = os.path.join(tmp, "work")
            os.makedirs(work)
            store = Store(base)
            first = store.send("demo", "a", "echo a")
            second = store.send("demo", "b", "echo b")
            # Isolate from any ambient user config (e.g. a signing key that
            # would make these unsigned tasks fail verification).
            empty_cfg = os.path.join(tmp, "empty.toml")
            with open(empty_cfg, "w", encoding="utf-8"):
                pass
            code = main(["--config", empty_cfg, "--base", base, "work",
                         "--me", "demo", "--dir", work,
                         "--runner", "shell", "--sandbox", "none",
                         "--once", "--workers", "2"])
            self.assertEqual(code, 0)
            self.assertEqual(store.get_task(first["id"])["status"], "done")
            self.assertEqual(store.get_task(second["id"])["status"], "done")


class WatchTest(unittest.TestCase):
    def test_events_only_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(os.path.join(tmp, "bus"))
            task = store.send("lab", "t", "body")
            state = {}
            events = _watch_events(store, "lab", state)
            self.assertTrue(any("pending" in line for line in events))
            self.assertEqual(_watch_events(store, "lab", state), [])
            store.claim("lab", task["id"])
            store.complete("lab", task["id"], "ok", "done-text")
            events = _watch_events(store, "lab", state)
            self.assertTrue(any("done" in line for line in events))
            self.assertTrue(any("done-text" in line for line in events))


if __name__ == "__main__":
    unittest.main()
