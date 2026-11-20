import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from hyprtk_rec.store import (
    History,
    human_duration,
    human_size,
    make_name,
    unique_path,
)


class NameTest(unittest.TestCase):
    def test_name(self):
        name = make_name("region", ts=datetime(2026, 11, 20, 9, 5, 3))
        self.assertEqual(name, "hyprtk-2026-11-20_09-05-03-region.mp4")

    def test_container_is_whitelisted(self):
        self.assertTrue(make_name("output", ext="webm").endswith(".webm"))
        self.assertTrue(make_name("output", ext="avi").endswith(".mp4"))

    def test_source_is_sanitised(self):
        self.assertIn("-abpng.mp4", make_name("a/b png"))


class UniqueTest(unittest.TestCase):
    def test_counter(self):
        root = Path(tempfile.mkdtemp(prefix="hyprtk-rec-unique-"))
        first = root / "a.mp4"
        first.write_bytes(b"x")
        self.assertEqual(unique_path(first).name, "a-2.mp4")


class DurationTest(unittest.TestCase):
    def test_short(self):
        self.assertEqual(human_duration(0), "00:00")
        self.assertEqual(human_duration(59.6), "01:00")
        self.assertEqual(human_duration(73), "01:13")

    def test_long(self):
        self.assertEqual(human_duration(3725), "1:02:05")
        self.assertEqual(human_duration(-4), "00:00")

    def test_size(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(2048), "2.0 KB")
        self.assertEqual(human_size(3 * 1024 ** 3), "3.0 GB")


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hyprtk-rec-hist-"))
        self.history = History(self.dir / "history.jsonl", limit=3)
        self.files = []
        for index in range(4):
            path = self.dir / f"r{index}.mp4"
            path.write_bytes(b"x")
            self.files.append(path)
            self.history.add({"path": str(path), "duration": index})

    def tearDown(self):
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_newest_first_and_limited(self):
        rows = self.history.entries(10)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["path"], str(self.files[-1]))

    def test_recent_paths_skips_deleted(self):
        self.files[-1].unlink()
        paths = [row["path"] for row in self.history.recent_paths(10)]
        self.assertNotIn(str(self.files[-1]), paths)

    def test_clear(self):
        self.history.clear()
        self.assertEqual(self.history.entries(), [])


if __name__ == "__main__":
    unittest.main()
