import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hyprtk_rec import cli


class FakeRecorder:
    def __init__(self):
        self.path = ""

    def active(self):
        return object() if self.path else None

    def status(self):
        if not self.path:
            return {"recording": False}
        return {"recording": True, "paused": False, "elapsed": 12.0,
                "path": self.path, "backend": "wf-recorder", "bytes": 1024}

    def start(self, **kwargs):
        self.kwargs = kwargs
        self.path = kwargs["path"]
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_bytes(b"video")
        return SimpleNamespace(path=self.path, backend="wf-recorder",
                               source=kwargs.get("source", "output"), pid=1)

    def stop(self):
        path, self.path = self.path, ""
        return path or None

    def pause(self):
        return bool(self.path)

    def resume(self):
        return bool(self.path)


class ParseTest(unittest.TestCase):
    def test_command_defaults_to_start(self):
        self.assertEqual(cli.parse([]).command, "start")

    def test_commands(self):
        for command in ("stop", "toggle", "status", "pause", "resume", "sources"):
            self.assertEqual(cli.parse([command]).command, command)

    def test_flags(self):
        opts = cli.parse(["start", "--source", "region", "--fps", "30",
                          "--codec", "hevc", "--quality", "high", "--audio", "mic",
                          "--countdown", "3", "--no-cursor", "--json"])
        self.assertEqual(opts.source, "region")
        self.assertEqual(opts.fps, 30)
        self.assertEqual(opts.codec, "hevc")
        self.assertEqual(opts.quality, "high")
        self.assertEqual(opts.audio, "mic")
        self.assertEqual(opts.countdown, 3)
        self.assertFalse(opts.cursor)
        self.assertTrue(opts.json)

    def test_shorthands(self):
        self.assertEqual(cli.parse(["-t"]).command, "toggle")
        self.assertEqual(cli.parse(["-s"]).command, "stop")

    def test_audio_equals_form(self):
        self.assertEqual(cli.parse(["--audio=system"]).audio, "system")

    def test_unknown(self):
        with self.assertRaises(ValueError):
            cli.parse(["--warp"])
        with self.assertRaises(ValueError):
            cli.parse(["explode"])


class MainTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hyprtk-rec-cli-"))
        self.saved = {key: os.environ.get(key) for key in
                      ("HYPRTK_REC_CONFIG_DIR", "HYPRTK_REC_DIR", "HYPRTK_REC_STATE")}
        os.environ["HYPRTK_REC_CONFIG_DIR"] = str(self.dir / "config")
        os.environ["HYPRTK_REC_DIR"] = str(self.dir / "videos")
        os.environ["HYPRTK_REC_STATE"] = str(self.dir / "state.json")
        self.recorder = FakeRecorder()
        patcher = mock.patch.object(cli, "Recorder", return_value=self.recorder)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = mock.patch.object(cli, "resolve_source",
                                   return_value={"source": "output", "geometry": None,
                                                 "output": "DP-1", "label": "DP-1"})
        source.start()
        self.addCleanup(source.stop)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for root, dirs, files in os.walk(self.dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.dir)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = cli.main(list(args))
        return status, out.getvalue(), err.getvalue()

    def test_version_and_help(self):
        status, out, _ = self.run_cli("--version")
        self.assertEqual(status, 0)
        self.assertRegex(out, r"^hyprtk-rec \d+\.\d+\.\d+")
        status, out, _ = self.run_cli("--help")
        self.assertIn("usage: hyprtk-rec", out)

    def test_status_idle(self):
        status, out, _ = self.run_cli("status")
        self.assertEqual(status, 0)
        self.assertEqual(out.strip(), "idle")

    def test_status_json(self):
        self.run_cli("start")
        status, out, _ = self.run_cli("status", "--json")
        payload = json.loads(out)
        self.assertTrue(payload["recording"])
        self.assertEqual(payload["backend"], "wf-recorder")

    def test_start_creates_a_file_and_prints_json(self):
        status, out, _ = self.run_cli("start", "--json")
        self.assertEqual(status, 0)
        payload = json.loads(out)
        self.assertTrue(Path(payload["path"]).is_file())
        self.assertIn("Recordings", payload["path"])

    def test_start_with_region_geometry(self):
        status, out, _ = self.run_cli("start", "--region", "0,0 640x480")
        self.assertEqual(status, 0)
        self.assertIn("recording", out)

    def test_start_twice_fails(self):
        self.run_cli("start")
        status, _, err = self.run_cli("start")
        self.assertEqual(status, 1)
        self.assertIn("already recording", err)

    def test_stop_reports_the_file(self):
        self.run_cli("start")
        status, out, _ = self.run_cli("stop", "--json")
        payload = json.loads(out)
        self.assertEqual(status, 0)
        self.assertTrue(payload["path"].endswith(".mp4"))
        self.assertGreater(payload["bytes"], 0)

    def test_stop_when_idle(self):
        status, _, err = self.run_cli("stop")
        self.assertEqual(status, 3)
        self.assertIn("not recording", err)

    def test_toggle_starts_then_stops(self):
        self.run_cli("toggle")
        self.assertTrue(self.recorder.path)
        self.run_cli("toggle")
        self.assertFalse(self.recorder.path)

    def test_pause_and_resume(self):
        self.run_cli("start")
        status, out, _ = self.run_cli("pause")
        self.assertEqual(status, 0)
        self.assertIn("paused", out)
        status, out, _ = self.run_cli("resume")
        self.assertEqual(status, 0)

    def test_pause_when_idle(self):
        status, _, err = self.run_cli("pause")
        self.assertEqual(status, 3)

    def test_container_flag_reaches_the_filename(self):
        status, out, _ = self.run_cli("start", "--container", "gif", "--json")
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(out)["path"].endswith(".gif"))

    def test_window_flag_is_passed_to_the_resolver(self):
        with mock.patch.object(cli, "resolve_source",
                               return_value={"source": "window", "geometry": "0,0 10x10",
                                             "output": None, "label": "Picked"}) as resolve:
            status, _, _ = self.run_cli("start", "--source", "window", "--window", "0x55")
        self.assertEqual(status, 0)
        self.assertEqual(resolve.call_args.kwargs.get("window"), "0x55")

    def test_trim_needs_a_file(self):
        status, _, err = self.run_cli("trim")
        self.assertEqual(status, 2)
        self.assertIn("trim needs a file", err)

    def test_trim_reports_the_output(self):
        target = self.dir / "clip.mp4"
        target.write_bytes(b"x")
        with mock.patch("hyprtk_rec.trim.run", return_value=str(self.dir / "clip-trimmed.mp4")) as run:
            status, out, _ = self.run_cli("trim", str(target), "--from", "1:05", "--to", "2:00", "--json")
        self.assertEqual(status, 0)
        self.assertIn("clip-trimmed", out)
        self.assertEqual(run.call_args.kwargs.get("start"), 65.0)
        self.assertEqual(run.call_args.kwargs.get("end"), 120.0)

    def test_trim_with_a_bad_time_exits_one(self):
        target = self.dir / "clip.mp4"
        target.write_bytes(b"x")
        status, _, err = self.run_cli("trim", str(target), "--from", "abc")
        self.assertEqual(status, 1)
        self.assertIn("not a time", err)

    def test_notify_saved_is_a_hidden_command(self):
        with mock.patch("hyprtk_rec.notify.run", return_value=0) as run:
            status = cli.main(["notify-saved", "/tmp/a.mp4"])
        self.assertEqual(status, 0)
        run.assert_called_once_with("/tmp/a.mp4")

    def test_vaapi_flag_reaches_the_recorder(self):
        status, _, _ = self.run_cli("start", "--vaapi")
        self.assertEqual(status, 0)
        self.assertTrue(self.recorder.kwargs.get("vaapi"))

    def test_bad_codec(self):
        status, _, err = self.run_cli("start", "--codec", "mpeg2")
        self.assertEqual(status, 2)
        self.assertIn("unknown codec", err)

    def test_sources_lists_monitors(self):
        from hyprtk_rec.sources import Output, Window

        with mock.patch.object(cli, "outputs", return_value=[
                Output("DP-1", 0, 0, 1920, 1080, 1.0, True, 60)]), \
                mock.patch.object(cli, "windows", return_value=[
                    Window("0x1", "Term", "hyprtk-term", 0, 0, 800, 600, 0, False, 0)]):
            status, out, _ = self.run_cli("sources")
        self.assertEqual(status, 0)
        self.assertIn("monitor DP-1", out)
        self.assertIn("window", out)


if __name__ == "__main__":
    unittest.main()
