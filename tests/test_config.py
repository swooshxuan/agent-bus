import os
import tempfile
import unittest

from agent_bus.config import load_config
from agent_bus.store import BusError


class ConfigTest(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "agent-bus.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('remote = "ubuntu@host"\nme = "lab"\npoll = 5\n')
            cfg, used = load_config(path)
            self.assertEqual(cfg["remote"], "ubuntu@host")
            self.assertEqual(cfg["me"], "lab")
            self.assertEqual(cfg["poll"], 5)
            self.assertEqual(used, path)

    def test_missing_explicit_file(self):
        with self.assertRaises(BusError):
            load_config("/nonexistent/agent-bus.toml")

    def test_invalid_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("remote = [unterminated\n")
            with self.assertRaises(BusError):
                load_config(path)

    def test_main_uses_config_base(self):
        from agent_bus.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "bus")
            cfg = os.path.join(tmp, "agent-bus.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('base = "%s"\n' % base)
            self.assertEqual(main(["--config", cfg, "list"]), 0)


if __name__ == "__main__":
    unittest.main()
