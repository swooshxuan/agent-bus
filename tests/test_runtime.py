import contextlib
import io
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

    def test_heartbeat_roundtrip(self):
        from agent_bus.cli import _heartbeat_path, _read_heartbeat, _write_heartbeat
        me = "hb-test-%d" % os.getpid()
        path = _heartbeat_path(me)
        try:
            _write_heartbeat(me, {"workers": 2})
            hb = _read_heartbeat(me)
            self.assertEqual(hb["workers"], 2)
            self.assertIn("ts", hb)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_config_show_masks_signing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "agent-bus.toml")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('signing_key = "abcdef1234567890"\n')
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--config", cfg, "config", "show"])
            self.assertEqual(code, 0)
            out = buf.getvalue()
            self.assertIn("abcd…7890", out)
            self.assertNotIn("abcdef1234567890", out)

    def test_remote_ssh_options(self):
        from agent_bus.remote import RemoteStore
        store = RemoteStore("user@host", key="/tmp/k", ssh_bin="ssh-custom",
                            ssh_port="2222", ssh_proxy="nc proxy 22",
                            ssh_known_hosts="/tmp/known")
        argv = store._ssh()
        self.assertEqual(argv[0], "ssh-custom")
        self.assertIn("2222", argv)
        self.assertIn("-i", argv)
        self.assertTrue(any(a.startswith("ProxyCommand=") for a in argv))
        self.assertTrue(any(a.startswith("UserKnownHostsFile=") for a in argv))

    def test_shell_runner_roundtrip(self):
        from agent_bus.cli import _run_shell
        proc = _run_shell("echo hello-shell", [], os.getcwd(), 30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("hello-shell", proc.stdout)


if __name__ == "__main__":
    unittest.main()
