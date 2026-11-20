#!/usr/bin/env python3
"""Dev-only: load the recorder QML headlessly and drive a fake session.

The unit tests cover argv, state files and the CLI. This covers what only a real
QML load finds: a renamed slot, an unknown property, a palette key the window
binds to, a status binding that throws when a recording starts.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

_SANDBOX = tempfile.mkdtemp(prefix="hyprtk-rec-boot-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_SANDBOX, "cache")
os.environ["HYPRTK_WAL_HOME"] = _SANDBOX
os.environ["HYPRTK_REC_CONFIG_DIR"] = os.path.join(_SANDBOX, "config", "hyprtk-rec")
os.environ["HYPRTK_REC_DIR"] = os.path.join(_SANDBOX, "videos")
os.environ["HYPRTK_REC_STATE"] = os.path.join(_SANDBOX, "state.json")
# The suite must not pop real notifications while a dev gate runs.
os.environ["HYPRTK_REC_NOTIFY"] = "0"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, qInstallMessageHandler  # noqa: E402

from hyprtk_rec import app as app_module  # noqa: E402
from hyprtk_rec import bridge as bridge_module  # noqa: E402

problems: list[str] = []

IGNORED = (
    "QStandardPaths",
    "This plugin does not support",
    "Failed to create",
    "propagateSizeHints",
    "qt.qpa.wayland",
)


def handler(mode, context, message: str) -> None:
    if any(fragment in message for fragment in IGNORED):
        return
    problems.append(message)


def fail(message: str) -> None:
    problems.append(message)


class FakeRecorder:
    """Stands in for the encoder: no process, but the same state surface."""

    def __init__(self) -> None:
        self.state: dict = {}
        self._started = 0.0

    def status(self) -> dict:
        return dict(self.state)

    def active(self):
        return object() if self.state.get("recording") else None

    def start(self, **kwargs):
        self._started = time.time()
        self.state = {
            "recording": True,
            "paused": False,
            "elapsed": 0.0,
            "path": kwargs["path"],
            "backend": "wf-recorder",
            "source": kwargs.get("source", "output"),
            "audio": kwargs.get("audio", "none"),
            "container": kwargs.get("container", "mp4"),
            "codec": kwargs.get("codec", "h264"),
            "fps": kwargs.get("fps", 60),
            "bytes": 0,
            "pid": 4242,
        }
        Path(kwargs["path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kwargs["path"]).write_bytes(b"fake-video")
        return SimpleNamespace(path=kwargs["path"], backend="wf-recorder",
                               source=kwargs.get("source", "output"), pid=4242)

    def stop(self):
        if not self.state.get("recording"):
            return None
        path = self.state["path"]
        self.state = {}
        return path

    def pause(self) -> bool:
        if not self.state.get("recording") or self.state.get("paused"):
            return False
        self.state["paused"] = True
        return True

    def resume(self) -> bool:
        if not self.state.get("paused"):
            return False
        self.state["paused"] = False
        return True


def main() -> int:
    qInstallMessageHandler(handler)

    # A crash leaves a state file and a partial file; the window must adopt it
    # instead of silently forgetting an hour of recording.
    partial = Path(os.environ["HYPRTK_REC_STATE"]).parent / "crash-videos" / "hyprtk-crash-partial.mp4"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"partial-video")
    Path(os.environ["HYPRTK_REC_STATE"]).write_text(json.dumps({
        "pid": 999999, "backend": "wf-recorder", "source": "output",
        "path": str(partial), "started": time.time() - 45,
    }), encoding="utf-8")

    app_module.backends_available = lambda: ["wf-recorder"]
    bridge_module.backends_available = lambda: ["wf-recorder"]
    bridge_module.resolve_source = lambda source, **kw: {
        "source": "output", "geometry": None, "output": "DP-1", "label": "DP-1",
    }

    app, engine, bridge = app_module.create([sys.argv[0]])
    root = engine.rootObjects()[0]
    bridge.recorder = FakeRecorder()

    if not any("partial" in str(row.get("name", "")) for row in bridge.recentRecordings):
        fail("the crashed recording was not salvaged into the recent list")

    palette = bridge.palette
    for key in ("background", "foreground", "accent", "accent2", "panel", "panelAlt",
                "panelHover", "textOnAccent", "muted", "mutedText", "border",
                "danger", "record", "paused", "live", "idle"):
        if key not in palette:
            fail(f"palette is missing {key!r}")

    for key in ("source", "window", "fps", "codec", "quality", "audio", "countdown",
                "dir", "backend", "container", "cursor"):
        if key not in bridge.config:
            fail(f"config is missing {key!r}")

    # The window picker: a chosen address labels the source, and an address
    # that is not in the list falls back to the focused window.
    bridge._windows = [{"address": "0x1", "title": "Picked window", "class": "hyprtk-term"}]
    if bridge.windowLabel != "Focused window":
        fail(f"empty window pick should say focused: {bridge.windowLabel!r}")
    bridge.pickWindow("0x1")
    if bridge.windowLabel != "Picked window":
        fail(f"the picked window is not labelled: {bridge.windowLabel!r}")
    bridge.pickWindow("0xdoesnotexist")
    if bridge.settings.get("window") != "":
        fail("an unknown address was stored instead of clearing the pick")

    bridge.setConfig("source", "output")
    bridge.setConfig("container", "gif")
    bridge.setConfig("countdown", 0)
    bridge.startSource("output")

    if not bridge.recording:
        fail("startSource did not put the bridge into the recording state")
    if bridge.status.get("elapsedText") != "00:00":
        fail(f"elapsed text is wrong: {bridge.status.get('elapsedText')!r}")
    if not str(bridge.status.get("path", "")).endswith(".gif"):
        fail(f"the gif container did not reach the file name: {bridge.status.get('path')!r}")
    if bridge.status.get("container") != "gif":
        fail(f"the status does not report the container: {bridge.status!r}")

    bridge.togglePause()
    if not bridge.paused:
        fail("pause did not register")
    bridge.togglePause()
    if bridge.paused:
        fail("resume did not clear the pause")

    bridge.stop()
    if bridge.recording:
        fail("stop left the bridge recording")
    if not bridge.history.recent_paths(1):
        fail("the finished recording was not written to the history")
    if not bridge.recentRecordings:
        fail("the recent list is empty after a recording")

    bridge.refreshSources()

    def finish() -> None:
        app.quit()

    QTimer.singleShot(200, finish)
    app.exec()

    if problems:
        for message in problems:
            print("PROBLEM:", message, file=sys.stderr)
        return 1
    print("bootcheck OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
