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

    def test_device_for_mix(self):
        self.assertEqual(audio.device_for("mix"), "hyprtk-rec-mix.monitor")

    def test_describe(self):
        self.assertEqual(audio.describe("none"), "No audio")
        self.assertEqual(audio.describe("mic"), "Microphone")
        self.assertEqual(audio.describe("mix"), "System + microphone")


class MixTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.ids = [11, 12, 13]
        self.fail_loads = 0

        def fake(*args):
            self.calls.append(args)
            if args and args[0] == "load-module":
                if self.fail_loads:
                    self.fail_loads -= 1
                    return ""
                return f"{self.ids.pop(0)}\n"
            return ""

        for patcher in (mock.patch.object(audio, "_pactl", side_effect=fake),
                        mock.patch.object(audio, "default_sink", return_value="sink0"),
                        mock.patch.object(audio, "default_source", return_value="mic0")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def loads(self):
        return [call for call in self.calls if call and call[0] == "load-module"]

    def unloads(self):
        return [call for call in self.calls if call and call[0] == "unload-module"]

    def test_mix_creates_a_null_sink_and_two_loopbacks(self):
        modules, source = audio.start_mix()
        self.assertEqual(modules, [11, 12, 13])
        self.assertEqual(source, "hyprtk-rec-mix.monitor")
        self.assertEqual(self.loads(), [
            ("load-module", "module-null-sink", "sink_name=hyprtk-rec-mix"),
            ("load-module", "module-loopback", "sink=hyprtk-rec-mix", "source=sink0.monitor"),
            ("load-module", "module-loopback", "sink=hyprtk-rec-mix", "source=mic0"),
        ])

    def test_no_default_output_is_an_error(self):
        with mock.patch.object(audio, "default_sink", return_value=""):
            with self.assertRaises(audio.AudioError):
                audio.start_mix()
        self.assertEqual(self.calls, [])

    def test_no_microphone_is_an_error(self):
        with mock.patch.object(audio, "default_source", return_value=""):
            with self.assertRaises(audio.AudioError):
                audio.start_mix()

    def test_a_failed_null_sink_creates_nothing(self):
        self.fail_loads = 1
        with self.assertRaises(audio.AudioError):
            audio.start_mix()
        self.assertEqual(self.unloads(), [])

    def test_a_failed_loopback_unloads_what_was_created(self):
        # null sink and the first loopback load; the second loopback fails.
        self.ids = [11, 12]
        loads = {"n": 0}

        def fake(*args):
            self.calls.append(args)
            if args and args[0] == "load-module":
                loads["n"] += 1
                if loads["n"] > 2:
                    return ""
                return str(self.ids.pop(0))
            return ""

        with mock.patch.object(audio, "_pactl", side_effect=fake):
            with self.assertRaises(audio.AudioError):
                audio.start_mix()
        self.assertEqual(self.unloads(), [("unload-module", "11"), ("unload-module", "12")])

    def test_stop_unloads_newest_first(self):
        audio.stop_mix([11, 12, 13])
        self.assertEqual(self.unloads(), [("unload-module", "13"),
                                          ("unload-module", "12"),
                                          ("unload-module", "11")])

    def test_stop_tolerates_an_empty_list(self):
        audio.stop_mix([])
        self.assertEqual(self.unloads(), [])


if __name__ == "__main__":
    unittest.main()
