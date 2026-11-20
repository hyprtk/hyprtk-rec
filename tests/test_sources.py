import unittest
from unittest import mock

from hyprtk_rec import sources as S


class GeometryTest(unittest.TestCase):
    def test_output_geometry_is_logical(self):
        out = S.Output("DP-1", 0, 0, 3840, 2160, 2.0, True, 60.0)
        self.assertEqual(out.geometry, "0,0 1920x1080")
        self.assertEqual(out.fps, 60)

    def test_output_fps_is_rounded(self):
        out = S.Output("DP-1", 0, 0, 1920, 1080, 1.0, True, 59.94)
        self.assertEqual(out.fps, 60)

    def test_window_geometry(self):
        win = S.Window("0x1", "Doc", "app", 12, 34, 800, 600, 0, False, 1)
        self.assertEqual(win.geometry, "12,34 800x600")
        self.assertTrue(win.contains(12, 34))
        self.assertFalse(win.contains(11, 34))


class ParseTest(unittest.TestCase):
    def test_outputs(self):
        data = [{"name": "DP-1", "x": 0, "y": 0, "width": 1920, "height": 1080,
                 "scale": 1.0, "focused": True, "refreshRate": 144.0}]
        with mock.patch.object(S, "_hyprctl_json", return_value=data):
            rows = S.outputs()
        self.assertEqual(rows[0].name, "DP-1")
        self.assertEqual(rows[0].fps, 144)

    def test_windows(self):
        data = [{"address": "0x1", "at": [0, 38], "size": [1200, 800],
                 "class": "hyprtk-term", "title": "Terminal", "focusHistoryID": 0}]
        with mock.patch.object(S, "_hyprctl_json", return_value=data):
            rows = S.windows()
        self.assertEqual(rows[0].geometry, "0,38 1200x800")
        self.assertEqual(rows[0].app_class, "hyprtk-term")

    def test_hidden_windows_are_dropped(self):
        data = [{"address": "0x1", "at": [0, 0], "size": [10, 10], "hidden": True},
                {"address": "0x2", "at": [0, 0], "size": [10, 10], "hidden": False}]
        with mock.patch.object(S, "_hyprctl_json", return_value=data):
            self.assertEqual([row.address for row in S.windows()], ["0x2"])


class ResolveTest(unittest.TestCase):
    def test_output_uses_the_focused_monitor(self):
        monitor = S.Output("DP-1", 0, 0, 1920, 1080, 1.0, True, 60)
        with mock.patch.object(S, "focused_output", return_value=monitor):
            target = S.resolve_source("output")
        self.assertEqual(target["output"], "DP-1")
        self.assertIsNone(target["geometry"])

    def test_output_without_a_monitor(self):
        with mock.patch.object(S, "focused_output", return_value=None):
            with self.assertRaises(S.SourceError):
                S.resolve_source("output")

    def test_region_uses_slurp(self):
        with mock.patch.object(S, "select_region", return_value="10,20 300x200"):
            target = S.resolve_source("region")
        self.assertEqual(target["geometry"], "10,20 300x200")

    def test_region_cancelled(self):
        with mock.patch.object(S, "select_region", return_value=None):
            with self.assertRaises(S.SourceError):
                S.resolve_source("region")

    def test_window_uses_the_active_window(self):
        win = S.Window("0x1", "Doc", "app", 0, 0, 400, 300, 0, False, 0)
        with mock.patch.object(S, "active_window", return_value=win):
            target = S.resolve_source("window")
        self.assertEqual(target["geometry"], "0,0 400x300")
        self.assertEqual(target["label"], "Doc")

    def test_window_picker_address_wins_over_focus(self):
        picked = S.Window("0x2", "Picked", "app", 10, 20, 500, 400, 0, False, 3)
        focused = S.Window("0x1", "Focused", "app", 0, 0, 400, 300, 0, False, 0)
        with mock.patch.object(S, "windows", return_value=[focused, picked]), \
                mock.patch.object(S, "active_window", return_value=focused):
            target = S.resolve_source("window", window="0x2")
        self.assertEqual(target["geometry"], "10,20 500x400")
        self.assertEqual(target["label"], "Picked")
        self.assertEqual(target["address"], "0x2")

    def test_closed_window_falls_back_to_the_focused_one(self):
        focused = S.Window("0x1", "Focused", "app", 0, 0, 400, 300, 0, False, 0)
        with mock.patch.object(S, "windows", return_value=[focused]), \
                mock.patch.object(S, "active_window", return_value=focused):
            target = S.resolve_source("window", window="0xdead")
        self.assertEqual(target["geometry"], "0,0 400x300")
        self.assertEqual(target["address"], "0x1")

    def test_unknown_source(self):
        with self.assertRaises(S.SourceError):
            S.resolve_source("hologram")

    def test_named_output_override(self):
        target = S.resolve_source("output", output="HDMI-A-1")
        self.assertEqual(target["output"], "HDMI-A-1")


if __name__ == "__main__":
    unittest.main()
