#!/usr/bin/env python3
"""Dev-only: render the recorder window offscreen to a PNG.

    python3 scripts/screenshot.py docs/rec-window.png
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

_SANDBOX = tempfile.mkdtemp(prefix="hyprtk-rec-shot-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_SANDBOX, "config")
os.environ["XDG_CACHE_HOME"] = os.path.join(_SANDBOX, "cache")
os.environ["HYPRTK_WAL_HOME"] = _SANDBOX
os.environ["HYPRTK_REC_CONFIG_DIR"] = os.path.join(_SANDBOX, "config", "hyprtk-rec")
os.environ["HYPRTK_REC_DIR"] = os.path.join(_SANDBOX, "videos")
os.environ["HYPRTK_REC_STATE"] = os.path.join(_SANDBOX, "state.json")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402
from shiboken6 import getCppPointer, wrapInstance  # noqa: E402

from bootcheck import FakeRecorder  # noqa: E402
from hyprtk_rec import app as app_module  # noqa: E402
from hyprtk_rec import bridge as bridge_module  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "rec-window.png"

    app_module.backends_available = lambda: ["wf-recorder"]
    bridge_module.backends_available = lambda: ["wf-recorder"]
    bridge_module.resolve_source = lambda source, **kw: {
        "source": "output", "geometry": None, "output": "DP-1", "label": "DP-1",
    }

    app, engine, bridge = app_module.create([sys.argv[0]])
    root = engine.rootObjects()[0]
    recorder = FakeRecorder()
    bridge.recorder = recorder

    # Idle window first.
    QTimer.singleShot(250, lambda: grab(root, out))

    def recording_state() -> None:
        bridge.startSource("output")
        recorder.state["elapsed"] = 73.0
        recorder.state["bytes"] = 48 * 1024 * 1024
        recorder.state["path"] = str(Path(_SANDBOX) / "videos" / "Recordings" /
                                      "hyprtk-2026-11-20_11-42-07-output.mp4")
        bridge._set_status()
        QTimer.singleShot(250, lambda: grab(root, out.with_name(out.stem + "-recording.png"), done))

    def done(_p=None) -> None:
        app.quit()

    QTimer.singleShot(600, recording_state)
    app.exec()
    return 0


def qquick(window):
    """engine.rootObjects() hands back a bare QWindow under PySide6; re-wrap it."""
    if hasattr(window, "grabWindow"):
        return window
    return wrapInstance(getCppPointer(window)[0], QQuickWindow)


def grab(window, path: Path, done=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shot = qquick(window).grabWindow()
    if not shot.save(str(path)):
        raise SystemExit(f"could not write {path}")
    print(f"wrote {path} ({shot.width()}x{shot.height()})", flush=True)
    if callable(done):
        done()


if __name__ == "__main__":
    raise SystemExit(main())
