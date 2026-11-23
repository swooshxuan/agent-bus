import unittest
from types import SimpleNamespace

from agent_bus.cli import _check_signature
from agent_bus.signing import sign_task, verify_task
from agent_bus.store import Store


def _task(sig=None):
    task = {"target": "lab", "title": "t", "body": "body", "sender": "me"}
    if sig:
        task["sig"] = sig
    return task


class SigningTest(unittest.TestCase):
    def test_sign_then_verify(self):
        key = "secret"
        sig = sign_task(key, "lab", "t", "body", "me")
        self.assertEqual(verify_task(key, _task(sig)), (True, "ok"))

    def test_tampering_is_detected(self):
        key = "secret"
        sig = sign_task(key, "lab", "t", "body", "me")
        for field, value in (("body", "evil"), ("title", "x"),
                             ("sender", "other"), ("target", "laptop")):
            task = _task(sig)
            task[field] = value
            ok, reason = verify_task(key, task)
            self.assertFalse(ok, field)
            self.assertEqual(reason, "invalid signature")

    def test_wrong_key(self):
        sig = sign_task("a", "lab", "t", "body", "me")
        self.assertFalse(verify_task("b", _task(sig))[0])

    def test_missing_signature(self):
        self.assertEqual(verify_task("k", _task()), (False, "missing signature"))

    def test_worker_policy(self):
        key = "secret"
        sig = sign_task(key, "lab", "t", "body", "me")
        strict = SimpleNamespace(signing_key=key, require_signature=True)
        self.assertTrue(_check_signature(strict, _task(sig))[0])
        self.assertFalse(_check_signature(strict, _task())[0])
        no_key = SimpleNamespace(signing_key=None, require_signature=True)
        self.assertFalse(_check_signature(no_key, _task())[0])
        lax = SimpleNamespace(signing_key=None, require_signature=False)
        self.assertTrue(_check_signature(lax, _task())[0])

    def test_store_persists_signature(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            store = Store(tmp)
            task = store.send("lab", "t", "b", "me", sig="abc")
            self.assertEqual(store.get_task(task["id"])["sig"], "abc")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
