import os
import shutil
import subprocess
import tempfile
import unittest

from agent_bus.sandbox import Sandbox, SandboxError


def _git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True,
                   capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git required")
class WorktreeSandboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-bus-sbx-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "Test")
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("hello\n")
        _git(self.repo, "add", "a.txt")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.logs = []

    def tearDown(self):
        subprocess.run(["git", "-C", self.repo, "worktree", "prune"],
                       capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(os.path.join(os.path.expanduser("~"), ".agent-bus",
                                   "worktrees"), ignore_errors=True)

    def test_auto_uses_worktree_for_git_repo(self):
        sbx = Sandbox("auto", self.repo, "t1", log=self.logs.append)
        self.assertEqual(sbx.mode, "worktree")
        self.assertNotEqual(os.path.abspath(sbx.run_dir),
                            os.path.abspath(self.repo))
        self.assertTrue(os.path.isdir(sbx.run_dir))
        info = sbx.finish()
        self.assertIn("diff_stat", info)
        self.assertFalse(os.path.exists(sbx.run_dir))

    def test_changes_are_captured_and_isolated(self):
        sbx = Sandbox("worktree", self.repo, "t2", log=self.logs.append)
        with open(os.path.join(sbx.run_dir, "a.txt"), "w") as fh:
            fh.write("changed\n")
        info = sbx.finish()
        self.assertIn("1 file changed", info["diff_stat"])
        self.assertIn("-hello", info["diff"])
        with open(os.path.join(self.repo, "a.txt")) as fh:
            self.assertEqual(fh.read(), "hello\n")

    def test_worktree_requires_git(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        with self.assertRaises(SandboxError):
            Sandbox("worktree", plain, "t3")

    def test_auto_falls_back_to_none(self):
        plain = os.path.join(self.tmp, "plain2")
        os.makedirs(plain)
        sbx = Sandbox("auto", plain, "t4", log=self.logs.append)
        self.assertEqual(sbx.mode, "none")
        self.assertEqual(sbx.run_dir, os.path.abspath(plain))
        self.assertTrue(any("fell back" in line for line in self.logs))


class DockerWrapTest(unittest.TestCase):
    def test_wrap_builds_docker_command(self):
        sbx = Sandbox.__new__(Sandbox)
        sbx.mode = "docker"
        sbx.task_dir = "/tmp/work"
        sbx.image = "img:test"
        sbx.network = "bridge"
        argv = sbx.wrap(["claude", "-p", "hi"])
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])
        self.assertIn("/tmp/work:/work", argv)
        self.assertEqual(argv[argv.index("img:test"):],
                         ["img:test", "claude", "-p", "hi"])

    def test_wrap_is_noop_for_worktree(self):
        sbx = Sandbox.__new__(Sandbox)
        sbx.mode = "worktree"
        argv = ["claude", "-p", "hi"]
        self.assertIs(sbx.wrap(argv), argv)


if __name__ == "__main__":
    unittest.main()
