import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hyprtk_rec import trim


class ParseTimeTest(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(trim.parse_time("12"), 12.0)
        self.assertEqual(trim.parse_time("12.5"), 12.5)
        self.assertEqual(trim.parse_time(7), 7.0)

    def test_clock_forms(self):
        self.assertEqual(trim.parse_time("1:05"), 65.0)
        self.assertEqual(trim.parse_time("0:01:05.5"), 65.5)
        self.assertEqual(trim.parse_time("2:00:00"), 7200.0)

    def test_empty_is_no_bound(self):
        self.assertIsNone(trim.parse_time(""))
        self.assertIsNone(trim.parse_time(None))
        self.assertIsNone(trim.parse_time(0))

    def test_garbage_is_an_error(self):
        for text in ("abc", "1:xx", "-3", "1:2:3:4"):
            with self.assertRaises(trim.TrimError):
                trim.parse_time(text)


class PlanTest(unittest.TestCase):
    def test_start_only_seeks(self):
        job = trim.plan("/v/a.mp4", start=5.0)
        argv = job["argv"]
        self.assertEqual(argv[argv.index("-ss") + 1], "5.000")
        self.assertNotIn("-t", argv)
        self.assertLess(argv.index("-ss"), argv.index("-i"))

    def test_both_ends_use_an_explicit_duration(self):
        argv = trim.plan("/v/a.mp4", start=10.0, end=14.5)["argv"]
        self.assertEqual(argv[argv.index("-ss") + 1], "10.000")
        self.assertEqual(argv[argv.index("-t") + 1], "4.500")

    def test_end_only_stops_the_output(self):
        argv = trim.plan("/v/a.mp4", end=8.0)["argv"]
        self.assertNotIn("-ss", argv)
        self.assertEqual(argv[argv.index("-t") + 1], "8.000")
        self.assertGreater(argv.index("-t"), argv.index("-i"))

    def test_copy_is_the_default(self):
        argv = trim.plan("/v/a.mp4", start=1.0)["argv"]
        self.assertIn("-c", argv)
        self.assertIn("copy", argv)
        self.assertNotIn("libx264", argv)

    def test_reencode_is_explicit(self):
        argv = trim.plan("/v/a.mp4", start=1.0, reencode=True)["argv"]
        self.assertIn("libx264", argv)
        self.assertNotIn("copy", argv)

    def test_output_is_a_sibling(self):
        self.assertTrue(trim.plan("/v/a.mp4", start=1.0)["output"].endswith("/v/a-trimmed.mp4"))

    def test_replace_uses_a_temporary_sibling(self):
        job = trim.plan("/v/a.mp4", start=1.0, replace=True)
        self.assertTrue(job["output"].endswith("/v/a.trim.mp4"))
        self.assertEqual(job["source"], "/v/a.mp4")

    def test_end_before_start_is_an_error(self):
        with self.assertRaises(trim.TrimError):
            trim.plan("/v/a.mp4", start=10.0, end=4.0)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hyprtk-rec-trim-"))
        self.source = self.dir / "a.mp4"
        self.source.write_bytes(b"original")

    def tearDown(self):
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_writes_the_trimmed_sibling(self):
        def runner(argv, **kwargs):
            Path(argv[-1]).write_bytes(b"trimmed")
            return SimpleNamespace(returncode=0, stderr=b"")

        out = trim.run(self.source, start=1.0, end=2.0,
                       program="ffmpeg", runner=runner)
        self.assertTrue(out.endswith("a-trimmed.mp4"))
        self.assertEqual(Path(out).read_bytes(), b"trimmed")
        self.assertEqual(self.source.read_bytes(), b"original")

    def test_replace_swaps_the_original(self):
        def runner(argv, **kwargs):
            Path(argv[-1]).write_bytes(b"short")
            return SimpleNamespace(returncode=0, stderr=b"")

        out = trim.run(self.source, start=1.0, replace=True,
                       program="ffmpeg", runner=runner)
        self.assertEqual(out, str(self.source))
        self.assertEqual(self.source.read_bytes(), b"short")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["a.mp4"])

    def test_a_failed_ffmpeg_leaves_nothing_behind(self):
        def runner(argv, **kwargs):
            Path(argv[-1]).write_bytes(b"")
            return SimpleNamespace(returncode=1, stderr=b"[error] bad\n")

        with self.assertRaises(trim.TrimError) as caught:
            trim.run(self.source, start=1.0, program="ffmpeg", runner=runner)
        self.assertIn("bad", str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["a.mp4"])

    def test_missing_source_is_an_error(self):
        with self.assertRaises(trim.TrimError):
            trim.run(self.dir / "nope.mp4", start=1.0, program="ffmpeg",
                     runner=lambda *a, **k: SimpleNamespace(returncode=0, stderr=b""))


if __name__ == "__main__":
    unittest.main()
