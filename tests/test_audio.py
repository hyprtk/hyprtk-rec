import unittest
from unittest import mock

from hyprtk_rec import audio

SOURCES = """\
60\talsa_input.usb-Mic-00.mono-fallback\tPipeWire\ts16le 1ch 48000Hz\tSUSPENDED
62\talsa_output.pci-0000_0f_00.4.analog-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tIDLE
63\talsa_input.pci-0000_0f_00.4.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED
"""


class AudioTest(unittest.TestCase):
    def test_sources_are_parsed(self):
        with mock.patch.object(audio, "_pactl", return_value=SOURCES):
            rows = audio.sources()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["name"], "alsa_output.pci-0000_0f_00.4.analog-stereo.monitor")
        self.assertTrue(rows[1]["monitor"])
        self.assertFalse(rows[0]["monitor"])

    def test_default_sink_and_source(self):
        with mock.patch.object(audio, "_pactl", side_effect=lambda *a: {
            ("get-default-sink",): "alsa_output.pci.analog-stereo",
            ("get-default-source",): "alsa_input.usb-Mic-00.mono-fallback",
        }.get(a, "")):
            self.assertEqual(audio.default_sink(), "alsa_output.pci.analog-stereo")
            self.assertEqual(audio.default_source(), "alsa_input.usb-Mic-00.mono-fallback")

    def test_system_monitor_comes_from_the_default_sink(self):
        with mock.patch.object(audio, "_pactl", side_effect=lambda *a: {
            ("get-default-sink",): "sink1",
        }.get(a, "")):
            self.assertEqual(audio.system_monitor(), "sink1.monitor")

    def test_system_monitor_falls_back_to_any_monitor(self):
        calls = {"n": 0}

        def fake(*args):
            if args == ("get-default-sink",):
                return ""
            if args == ("list", "short", "sources"):
                return SOURCES
            return ""

        with mock.patch.object(audio, "_pactl", side_effect=fake):
            self.assertTrue(audio.system_monitor().endswith(".monitor"))

    def test_device_for(self):
        with mock.patch.object(audio, "system_monitor", return_value="s.monitor"), \
                mock.patch.object(audio, "default_source", return_value="mic0"):
            self.assertIsNone(audio.device_for("none"))
            self.assertEqual(audio.device_for("system"), "s.monitor")
            self.assertEqual(audio.device_for("mic"), "mic0")
            with self.assertRaises(ValueError):
                audio.device_for("both")

    def test_apply_wf(self):
        with mock.patch.object(audio, "device_for", return_value="dev"):
            argv = audio.apply(["wf-recorder"], "system")
        self.assertEqual(argv, ["wf-recorder", "--audio=dev"])

    def test_apply_wl(self):
        with mock.patch.object(audio, "device_for", return_value="dev"):
            argv = audio.apply(["wl-screenrec"], "mic", backend="wl-screenrec")
        self.assertEqual(argv, ["wl-screenrec", "--audio", "--audio-device", "dev"])

    def test_apply_none_is_a_no_op(self):
        self.assertEqual(audio.apply(["wf-recorder"], "none"), ["wf-recorder"])

    def test_explicit_device_overrides_the_mode(self):
        argv = audio.apply(["wf-recorder"], "system", device="custom.monitor")
        self.assertEqual(argv, ["wf-recorder", "--audio=custom.monitor"])

    def test_no_pactl_is_empty_not_a_crash(self):
        with mock.patch.object(audio.shutil, "which", return_value=None):
            self.assertEqual(audio.sources(), [])
            self.assertEqual(audio.default_sink(), "")
            self.assertEqual(audio.system_monitor(), "")

    def test_describe(self):
        self.assertEqual(audio.describe("none"), "No audio")
        self.assertEqual(audio.describe("mic"), "Microphone")


if __name__ == "__main__":
    unittest.main()
