import json
import os
import signal
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hyprtk_rec import recorder as R


class FakeProc:
    def __init__(self, pid=4242, exit_code=0):
        self.pid = pid
        self._exit = exit_code
        self.signals = []
        self.killed = False
        self.waited = False

    def poll(self):
        return self._exit

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        self.waited = True
        return 0

    def kill(self):
        self.killed = True


def which_all(program):
    return f"/usr/bin/{program}"


class StateMixin(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hyprtk-rec-state-"))
        self.state = self.dir / "state.json"
        self.process = FakeProc()

    def tearDown(self):
        for child in self.dir.iterdir():
            child.unlink()
        self.dir.rmdir()

    def recorder(self, **kw):
        kw.setdefault("which", which_all)
        kw.setdefault("spawn", lambda argv: self.process)
        kw.setdefault("alive_fn", lambda pid: True)
        kw.setdefault("signal_fn", lambda pid, sig: None)
        return R.Recorder(str(self.state), **kw)


class ArgvTest(unittest.TestCase):
    def recording(self, **kw):
        base = dict(pid=1, backend="wf-recorder", source="output", path="/tmp/a.mp4")
        base.update(kw)
        return R.Recording(**base)

    def test_wf_recorder_output(self):
        argv = R.build_argv(self.recording(output="DP-1", codec="h264", quality="medium", fps=60))
        self.assertEqual(argv[0], "wf-recorder")
        self.assertIn("-f", argv)
        self.assertIn("/tmp/a.mp4", argv)
        self.assertIn("libx264", argv)
        self.assertIn("crf=23", argv)
        self.assertIn("preset=veryfast", argv)
        self.assertIn("-o", argv)
        self.assertIn("DP-1", argv)
        self.assertIn("60", argv)

    def test_wf_recorder_geometry_wins_over_output(self):
        argv = R.build_argv(self.recording(output="DP-1", geometry="10,10 100x100"))
        self.assertIn("-g", argv)
        self.assertNotIn("-o", argv)

    def test_wf_recorder_quality_maps_to_crf(self):
        for quality, crf in (("low", 30), ("high", 18)):
            argv = R.build_argv(self.recording(quality=quality, codec="h264"))
            self.assertIn(f"crf={crf}", argv)

    def test_wf_recorder_hevc_uses_x265(self):
        argv = R.build_argv(self.recording(codec="hevc"))
        self.assertIn("libx265", argv)

    def test_wf_recorder_no_cursor(self):
        argv = R.build_argv(self.recording(cursor=False))
        self.assertIn("--no-cursor", argv)
        self.assertNotIn("--no-cursor", R.build_argv(self.recording(cursor=True)))

    def test_wl_screenrec_output(self):
        argv = R.build_argv(self.recording(backend="wl-screenrec", output="DP-1", codec="hevc"))
        self.assertEqual(argv[0], "wl-screenrec")
        self.assertIn("--codec", argv)
        self.assertIn("hevc", argv)
        self.assertIn("-b", argv)
        self.assertIn("-o", argv)

    def test_wl_screenrec_geometry(self):
        argv = R.build_argv(self.recording(backend="wl-screenrec", geometry="0,0 640x480"))
        self.assertIn("-g", argv)
        self.assertIn("0,0 640x480", argv)

    def test_audio_flags_wf(self):
        rec = self.recording(audio="system", audio_device="sink.monitor")
        argv = R.with_audio(R.build_argv(rec), rec)
        self.assertIn("--audio=sink.monitor", argv)

    def test_audio_flags_wl(self):
        rec = self.recording(backend="wl-screenrec", audio="mic", audio_device="mic0")
        argv = R.with_audio(R.build_argv(rec), rec)
        self.assertIn("--audio-device", argv)
        self.assertIn("mic0", argv)

    def test_no_audio_adds_nothing(self):
        rec = self.recording(audio="none")
        self.assertEqual(R.with_audio(R.build_argv(rec), rec), R.build_argv(rec))


    # -- GIF ---------------------------------------------------------
    def test_gif_uses_the_gif_codec_and_rgb8(self):
        argv = R.build_argv(self.recording(container="gif", path="/tmp/a.gif", backend="wf-recorder"))
        self.assertEqual(argv[0], "wf-recorder")
        self.assertIn("gif", argv)
        self.assertIn("rgb8", argv)
        self.assertNotIn("libx264", argv)
        self.assertNotIn("crf=23", argv)

    def test_gif_keeps_geometry_and_cursor_flags(self):
        argv = R.build_argv(self.recording(container="gif", path="/tmp/a.gif",
                                           geometry="0,0 640x480", cursor=False))
        self.assertIn("-g", argv)
        self.assertIn("0,0 640x480", argv)
        self.assertIn("--no-cursor", argv)

    def test_vaapi_argv(self):
        argv = R.build_argv(self.recording(vaapi=True, vaapi_device="/dev/dri/renderD128",
                                          codec="h264", quality="high"))
        self.assertIn("h264_vaapi", argv)
        self.assertIn("/dev/dri/renderD128", argv)
        self.assertIn("qp=20", argv)
        self.assertNotIn("libx264", argv)

    def test_vaapi_hevc(self):
        argv = R.build_argv(self.recording(vaapi=True, codec="hevc"))
        self.assertIn("hevc_vaapi", argv)

    def test_gif_never_asks_for_audio(self):
        rec = self.recording(container="gif", audio="system", audio_device="sink.monitor")
        self.assertEqual(R.with_audio(R.build_argv(rec), rec), R.build_argv(rec))

class VaapiProbeTest(unittest.TestCase):
    def test_a_working_device_is_reported(self):
        ok, reason = R.vaapi_probe("/dev/dri/renderD128",
                                   runner=lambda *a, **k: SimpleNamespace(returncode=0, stderr=b""))
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_a_failing_device_names_the_vaapi_error(self):
        ok, reason = R.vaapi_probe(
            "/dev/dri/renderD128",
            runner=lambda *a, **k: SimpleNamespace(
                returncode=1,
                stderr=(b"[VAAPI] Failed to initialise VAAPI connection: -1\n"
                        b"Error parsing global options: Input/output error\n")))
        self.assertFalse(ok)
        self.assertIn("Failed to initialise", reason)

    def test_a_failure_without_a_vaapi_line_uses_the_last_line(self):
        ok, reason = R.vaapi_probe(
            "/dev/dri/renderD128",
            runner=lambda *a, **k: SimpleNamespace(returncode=1, stderr=b"one\ntwo\n"))
        self.assertEqual(reason, "two")

    def test_a_missing_node_never_runs_ffmpeg(self):
        calls = []
        ok, reason = R.vaapi_probe("/dev/dri/renderD999",
                                   runner=lambda *a, **k: calls.append(a))
        self.assertFalse(ok)
        self.assertEqual(calls, [])

    def test_status_picks_the_first_working_device(self):
        result = {"returncode": 1, "stderr": b"bad"}
        with mock.patch.object(R, "render_devices", return_value=["/dev/dri/renderD128", "/dev/dri/renderD129"]), \
                mock.patch.object(R.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                mock.patch.object(R, "vaapi_probe", side_effect=[(False, "bad"), (True, "")]):
            ok, device, reason = R.vaapi_status()
        self.assertTrue(ok)
        self.assertEqual(device, "/dev/dri/renderD129")
        self.assertEqual(reason, "")

    def test_status_without_a_device(self):
        with mock.patch.object(R, "render_devices", return_value=[]):
            ok, device, reason = R.vaapi_status()
        self.assertFalse(ok)
        self.assertIn("renderD", reason)


class BackendTest(unittest.TestCase):
    def test_auto_prefers_wl_screenrec(self):
        self.assertEqual(R.pick_backend("auto", which_all), "wl-screenrec")

    def test_auto_falls_back_to_wf_recorder(self):
        only = lambda program: "/usr/bin/wf-recorder" if program == "wf-recorder" else None
        self.assertEqual(R.pick_backend("auto", only), "wf-recorder")

    def test_auto_with_nothing_installed(self):
        with self.assertRaises(R.RecorderError):
            R.pick_backend("auto", lambda program: None)

    def test_explicit_backend_missing_is_an_error(self):
        with self.assertRaises(R.RecorderError):
            R.pick_backend("wl-screenrec", lambda program: None)

    def test_unknown_backend(self):
        with self.assertRaises(R.RecorderError):
            R.pick_backend("ffmpeg", which_all)


    def test_gif_forces_wf_recorder(self):
        # wl-screenrec has no GIF encoder; the fallback is explicit, not silent.
        self.assertEqual(R.pick_backend("auto", which_all, container="gif"), "wf-recorder")
        self.assertEqual(R.pick_backend("wl-screenrec", which_all, container="gif"), "wf-recorder")

    def test_gif_without_wf_recorder_is_an_error(self):
        with self.assertRaises(R.RecorderError):
            R.pick_backend("auto", lambda program: None, container="gif")

class LifecycleTest(StateMixin):
    def test_start_writes_state(self):
        recorder = self.recorder()
        rec = recorder.start(path=str(self.dir / "a.mp4"), output="DP-1")
        self.assertEqual(rec.backend, "wl-screenrec")
        self.assertTrue(self.state.is_file())
        data = json.loads(self.state.read_text())
        self.assertEqual(data["path"], str(self.dir / "a.mp4"))
        self.assertEqual(data["pid"], 4242)

    def test_mix_creates_the_sink_and_records_its_monitor(self):
        captured = {}
        with mock.patch("hyprtk_rec.audio.start_mix",
                        return_value=([7, 8, 9], "hyprtk-rec-mix.monitor")):
            recorder = R.Recorder(
                str(self.state), which=which_all,
                spawn=lambda argv: (captured.setdefault("argv", argv), self.process)[1],
                alive_fn=lambda pid: True)
            rec = recorder.start(path=str(self.dir / "a.mp4"), audio="mix")
        self.assertEqual(rec.audio_modules, [7, 8, 9])
        self.assertEqual(rec.audio_device, "hyprtk-rec-mix.monitor")
        self.assertIn("hyprtk-rec-mix.monitor", captured["argv"])
        data = json.loads(self.state.read_text())
        self.assertEqual(data["audio_modules"], [7, 8, 9])

    def test_a_failed_mix_is_a_start_error(self):
        from hyprtk_rec import audio as audio_module

        with mock.patch("hyprtk_rec.audio.start_mix",
                        side_effect=audio_module.AudioError("no microphone")):
            with self.assertRaises(R.RecorderError):
                self.recorder().start(path=str(self.dir / "a.mp4"), audio="mix")

    def test_stop_unloads_the_mix(self):
        target = self.dir / "a.mp4"
        with mock.patch("hyprtk_rec.audio.start_mix", return_value=([7, 8], "mix.monitor")), \
                mock.patch("hyprtk_rec.audio.stop_mix") as stop:
            recorder = self.recorder()
            recorder.start(path=str(target), audio="mix")
            target.write_bytes(b"video")
            recorder.stop()
        stop.assert_called_once_with([7, 8])

    def test_recover_unloads_the_mix_of_a_crashed_recording(self):
        target = self.dir / "partial.mp4"
        target.write_bytes(b"half")
        self.state.write_text(json.dumps({
            "pid": 999999, "backend": "wf-recorder", "source": "output",
            "path": str(target), "started": time.time(),
            "audio": "mix", "audio_modules": [7, 8, 9],
        }))
        recorder = R.Recorder(str(self.state), which=which_all,
                              alive_fn=lambda pid: False)
        with mock.patch("hyprtk_rec.audio.stop_mix") as stop:
            self.assertIsNotNone(recorder.recover())
        stop.assert_called_once_with([7, 8, 9])

    def test_gif_clamps_the_frame_rate(self):
        recorder = self.recorder()
        rec = recorder.start(path=str(self.dir / "a.gif"), container="gif", fps=120)
        self.assertEqual(rec.container, "gif")
        self.assertEqual(rec.fps, R.GIF_MAX_FPS)
        self.assertEqual(rec.backend, "wf-recorder")

    def test_vaapi_is_probed_before_starting(self):
        recorder = self.recorder()
        with mock.patch.object(R, "vaapi_status", return_value=(True, "/dev/dri/renderD128", "")):
            rec = recorder.start(path=str(self.dir / "a.mp4"), vaapi=True,
                                 backend="wf-recorder")
        self.assertTrue(rec.vaapi)
        self.assertEqual(rec.vaapi_device, "/dev/dri/renderD128")

    def test_vaapi_that_does_not_work_is_a_start_error(self):
        recorder = self.recorder()
        with mock.patch.object(R, "vaapi_status", return_value=(False, "", "Failed to initialise VAAPI connection")):
            with self.assertRaises(R.RecorderError) as caught:
                recorder.start(path=str(self.dir / "a.mp4"), vaapi=True,
                               backend="wf-recorder")
        self.assertIn("VAAPI is not available", str(caught.exception))
        self.assertIn("Failed to initialise", str(caught.exception))

    def test_vaapi_with_vp9_is_rejected(self):
        with self.assertRaises(R.RecorderError) as caught:
            self.recorder().start(path=str(self.dir / "a.mp4"), vaapi=True,
                                  codec="vp9", backend="wf-recorder")
        self.assertIn("h264 or hevc", str(caught.exception))

    def test_container_is_persisted_in_the_state(self):
        recorder = self.recorder()
        recorder.start(path=str(self.dir / "a.gif"), container="gif")
        data = json.loads(self.state.read_text())
        self.assertEqual(data["container"], "gif")

    def test_start_refuses_a_second_recording(self):
        recorder = self.recorder()
        recorder.start(path=str(self.dir / "a.mp4"))
        with self.assertRaises(R.RecorderError):
            recorder.start(path=str(self.dir / "b.mp4"))

    def test_stop_signals_int_and_returns_the_file(self):
        target = self.dir / "a.mp4"
        recorder = self.recorder()
        recorder.start(path=str(target))
        target.write_bytes(b"video")
        self.assertEqual(recorder.stop(), str(target))
        self.assertEqual(self.process.signals, [signal.SIGINT])
        self.assertFalse(self.state.exists())

    def test_stop_without_a_recording_returns_none(self):
        self.assertIsNone(self.recorder().stop())

    def test_stop_deletes_an_empty_file(self):
        target = self.dir / "a.mp4"
        recorder = self.recorder()
        recorder.start(path=str(target))
        target.write_bytes(b"")
        self.assertIsNone(recorder.stop())
        self.assertFalse(target.exists())

    def test_pause_and_resume(self):
        recorder = self.recorder()
        recorder.start(path=str(self.dir / "a.mp4"))
        self.assertTrue(recorder.pause())
        self.assertFalse(recorder.pause())
        self.assertTrue(recorder.resume())
        self.assertFalse(recorder.resume())

    def test_pause_without_a_recording(self):
        self.assertFalse(self.recorder().pause())
        self.assertFalse(self.recorder().resume())

    def test_status_reports_size_and_elapsed(self):
        target = self.dir / "a.mp4"
        recorder = self.recorder()
        recorder.start(path=str(target))
        target.write_bytes(b"12345")
        status = recorder.status()
        self.assertTrue(status["recording"])
        self.assertEqual(status["bytes"], 5)
        self.assertIn("elapsed", status)
        self.assertEqual(status["backend"], "wl-screenrec")

    def test_recover_keeps_a_crashed_recording(self):
        target = self.dir / "partial.mp4"
        target.write_bytes(b"half a video")
        self.state.write_text(json.dumps({
            "pid": 999999, "backend": "wf-recorder", "source": "output",
            "path": str(target), "started": time.time() - 30,
        }))
        recorder = R.Recorder(str(self.state), which=which_all,
                              alive_fn=lambda pid: False)
        rec = recorder.recover()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.path, str(target))
        self.assertFalse(self.state.exists())

    def test_recover_ignores_an_empty_file(self):
        target = self.dir / "empty.mp4"
        target.write_bytes(b"")
        self.state.write_text(json.dumps({
            "pid": 999999, "backend": "wf-recorder", "source": "output",
            "path": str(target), "started": time.time(),
        }))
        recorder = R.Recorder(str(self.state), which=which_all,
                              alive_fn=lambda pid: False)
        self.assertIsNone(recorder.recover())
        self.assertFalse(self.state.exists())

    def test_recover_leaves_a_live_recording_alone(self):
        target = self.dir / "live.mp4"
        target.write_bytes(b"recording")
        self.state.write_text(json.dumps({
            "pid": 4242, "backend": "wf-recorder", "source": "output",
            "path": str(target), "started": time.time(),
        }))
        recorder = R.Recorder(str(self.state), which=which_all,
                              alive_fn=lambda pid: True)
        self.assertIsNone(recorder.recover())
        self.assertTrue(self.state.exists())

    def test_stale_state_is_cleaned(self):
        self.state.write_text(json.dumps({
            "pid": 999999, "backend": "wf-recorder", "source": "output",
            "path": "/tmp/gone.mp4", "started": time.time(),
        }))
        recorder = R.Recorder(str(self.state), which=which_all,
                              alive_fn=lambda pid: False)
        self.assertIsNone(recorder.active())
        self.assertFalse(self.state.exists())

    def test_corrupt_state_is_ignored(self):
        self.state.write_text("{not json")
        self.assertIsNone(self.recorder().active())

    def test_status_when_idle(self):
        self.assertEqual(self.recorder().status(), {"recording": False})


class ElapsedTest(unittest.TestCase):
    def test_elapsed_excludes_paused_time(self):
        rec = R.Recording(pid=1, backend="wf-recorder", source="output",
                          path="/tmp/a.mp4", started=100.0, paused_total=10.0)
        self.assertEqual(rec.elapsed(130.0), 20.0)

    def test_elapsed_freezes_while_paused(self):
        rec = R.Recording(pid=1, backend="wf-recorder", source="output",
                          path="/tmp/a.mp4", started=100.0, paused_at=110.0)
        self.assertEqual(rec.elapsed(500.0), 10.0)

    def test_roundtrip(self):
        rec = R.Recording(pid=7, backend="wf-recorder", source="region",
                          path="/tmp/x.mkv", geometry="0,0 10x10", audio="mic")
        again = R.Recording.from_dict(rec.as_dict())
        self.assertEqual(again.path, "/tmp/x.mkv")
        self.assertEqual(again.geometry, "0,0 10x10")
        self.assertEqual(again.audio, "mic")


if __name__ == "__main__":
    unittest.main()
