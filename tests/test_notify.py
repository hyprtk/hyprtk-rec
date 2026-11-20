import unittest
from types import SimpleNamespace
from unittest import mock

from hyprtk_rec import notify


class ArgvTest(unittest.TestCase):
    def test_actions_are_buttons(self):
        argv = notify.argv_for("/home/u/Videos/Recordings/a.mp4")
        self.assertEqual(argv[0], "notify-send")
        self.assertIn("open=Open folder", argv)
        self.assertIn("copy=Copy path", argv)
        self.assertIn("/home/u/Videos/Recordings/a.mp4".split("/")[-1], argv)

    def test_unknown_action_does_nothing(self):
        self.assertFalse(notify.handle("", "/tmp/a.mp4"))
        self.assertFalse(notify.handle("delete", "/tmp/a.mp4"))
        self.assertFalse(notify.handle("open", ""))


class HandleTest(unittest.TestCase):
    def test_open_gets_the_folder(self):
        seen = []
        notify.handle("open", "/home/u/Videos/a.mp4", opener=seen.append, copier=lambda p: True)
        self.assertEqual(seen, ["/home/u/Videos/a.mp4"])

    def test_copy_gets_the_path(self):
        seen = []
        notify.handle("copy", "/home/u/Videos/a.mp4", opener=lambda p: True, copier=seen.append)
        self.assertEqual(seen, ["/home/u/Videos/a.mp4"])

    def test_trailing_whitespace_from_notify_send_is_ignored(self):
        seen = []
        notify.handle("open\n", "/tmp/a.mp4", opener=seen.append, copier=lambda p: True)
        self.assertEqual(seen, ["/tmp/a.mp4"])


class RunTest(unittest.TestCase):
    def test_a_pressed_button_is_dispatched(self):
        def runner(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout=b"copy\n")

        with mock.patch.object(notify, "handle", return_value=True) as handle:
            status = notify.run("/tmp/a.mp4", runner=runner)
        self.assertEqual(status, 0)
        handle.assert_called_once()
        self.assertEqual(handle.call_args.args[0], "copy")

    def test_a_daemon_without_actions_still_gets_a_notification(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=1 if "-A" in argv else 0, stdout=b"")

        status = notify.run("/tmp/a.mp4", runner=runner)
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("-A", calls[0])
        self.assertNotIn("-A", calls[1])

    def test_no_path_is_a_usage_error(self):
        self.assertEqual(notify.run(""), 2)

    def test_a_missing_notify_send_is_not_a_crash(self):
        with mock.patch("hyprtk_rec.notify.shutil.which", return_value=None):
            self.assertEqual(notify.run("/tmp/a.mp4"), 1)


if __name__ == "__main__":
    unittest.main()
