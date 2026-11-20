import os
import tempfile
import unittest
from pathlib import Path

from hyprtk_rec.settings import DEFAULTS, Settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hyprtk-rec-settings-"))
        self.path = self.dir / "config.json"

    def tearDown(self):
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def test_defaults(self):
        settings = Settings(self.path)
        self.assertEqual(settings.get("source"), "output")
        self.assertEqual(settings.get("fps"), 60)
        self.assertEqual(settings.get("backend"), "auto")
        self.assertEqual(settings.get("window"), "")
        self.assertEqual(settings.get("container"), "mp4")

    def test_vaapi_is_off_by_default(self):
        settings = Settings(self.path)
        self.assertFalse(settings.get("vaapi"))
        settings.set("vaapi", True)
        self.assertTrue(settings.get("vaapi"))

    def test_gif_is_a_container(self):
        settings = Settings(self.path)
        settings.set("container", "gif")
        self.assertEqual(settings.get("container"), "gif")

    def test_window_address_is_kept_verbatim(self):
        settings = Settings(self.path)
        settings.set("window", " 0x55b1 ")
        self.assertEqual(settings.get("window"), "0x55b1")

    def test_persist(self):
        settings = Settings(self.path)
        settings.set("codec", "hevc")
        settings.save()
        self.assertEqual(Settings(self.path).get("codec"), "hevc")

    def test_clamping(self):
        settings = Settings(self.path)
        settings.set("fps", 500)
        self.assertEqual(settings.get("fps"), 240)
        settings.set("fps", 1)
        self.assertEqual(settings.get("fps"), 5)
        settings.set("countdown", 99)
        self.assertEqual(settings.get("countdown"), 30)

    def test_bad_enums(self):
        settings = Settings(self.path)
        for key, value in (("source", "galaxy"), ("codec", "mpeg2"),
                           ("quality", "insane"), ("container", "avi"),
                           ("backend", "ffmpeg"), ("audio", "both")):
            settings.set(key, value)
            self.assertEqual(settings.get(key), DEFAULTS[key])

    def test_dir_tilde_and_default(self):
        settings = Settings(self.path)
        settings.set("dir", "~/Videos/Rec")
        self.assertEqual(settings.get("dir"), os.path.expanduser("~/Videos/Rec"))
        settings.set("dir", "")
        self.assertTrue(settings.as_dict()["dir"].endswith("Recordings"))

    def test_unknown_keys_are_dropped(self):
        self.path.write_text('{"fps": 30, "turbo": true}', encoding="utf-8")
        settings = Settings(self.path)
        self.assertEqual(settings.get("fps"), 30)
        self.assertNotIn("turbo", settings.as_dict())

    def test_broken_file(self):
        self.path.write_text("[", encoding="utf-8")
        self.assertEqual(Settings(self.path).get("fps"), 60)


if __name__ == "__main__":
    unittest.main()
