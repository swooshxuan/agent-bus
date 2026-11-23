import unittest

from agent_bus.cli import _split_workdir


class SplitWorkdirTest(unittest.TestCase):
    def test_no_directive(self):
        body = "# 任务\n做点事"
        self.assertEqual(_split_workdir(body), (None, body))

    def test_directive(self):
        workdir, body = _split_workdir("@workdir: /tmp/proj\n# 任务\n做点事")
        self.assertEqual(workdir, "/tmp/proj")
        self.assertEqual(body, "# 任务\n做点事")

    def test_directive_with_spaces_and_blank_line(self):
        workdir, body = _split_workdir("@workdir:   C:\\work\\proj  \n\n任务")
        self.assertEqual(workdir, "C:\\work\\proj")
        self.assertEqual(body, "任务")

    def test_only_directive(self):
        workdir, body = _split_workdir("@workdir: /tmp")
        self.assertEqual(workdir, "/tmp")
        self.assertEqual(body, "")

    def test_directive_must_be_first_line(self):
        workdir, body = _split_workdir("# 任务\n@workdir: /tmp")
        self.assertIsNone(workdir)
        self.assertEqual(body, "# 任务\n@workdir: /tmp")


if __name__ == "__main__":
    unittest.main()
