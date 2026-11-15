import os
import tempfile
import unittest

from core.memory import Memory


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = Memory(base=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_search_forget(self):
        fid = self.mem.add("用户偏好简洁的回答", tags="偏好")
        self.assertIsNotNone(fid)
        hits = self.mem.search("简洁")
        self.assertTrue(any(h[1] == fid for h in hits))
        self.assertEqual(self.mem.forget(fid), 1)

    def test_exact_duplicate_returns_same_id(self):
        a = self.mem.add("工作区在 ~/archlot-workspace", tags="环境")
        b = self.mem.add("工作区在 ~/archlot-workspace", tags="环境")
        self.assertEqual(a, b)
        self.assertEqual(self.mem.stats()["active"], 1)

    def test_note_written(self):
        self.mem.note("会话小结：测试")
        files = os.listdir(self.mem.notes_dir)
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.mem.notes_dir, files[0])) as f:
            self.assertIn("测试", f.read())


if __name__ == "__main__":
    unittest.main()
