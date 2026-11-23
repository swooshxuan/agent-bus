import os
import tempfile
import unittest

from agent_bus.cli import _pid_alive, main


class RuntimeTest(unittest.TestCase):
    def test_pid_alive_self(self):
        self.assertTrue(_pid_alive(os.getpid()))

    def test_pid_alive_bogus(self):
        self.assertFalse(_pid_alive(999999))

    def test_doctor_local_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(main(["--base", tmp, "doctor"]), 0)


if __name__ == "__main__":
    unittest.main()
