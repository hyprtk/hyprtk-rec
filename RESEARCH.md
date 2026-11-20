# hyprtk-rec — research

What actually records a Wayland desktop in late 2026, and why this app drives an
encoder instead of encoding.

## Capture protocols

| Door | Who implements it | What it means for a recorder |
|---|---|---|
| `wlr-screencopy` | wlroots, Hyprland, Sway, river | frames of an output/region, damage-tracking, no prompt; what wf-recorder and wl-screenrec use |
| `ext-image-copy-capture` | newer compositors (partial) | the successor; wl-screenrec can use it, wf-recorder does not yet |
| `xdg-desktop-portal` `ScreenCast` | GNOME, KDE, Hyprland (portal-hyprland) | a PipeWire stream plus a permission dialog; what OBS/Kooha use |

Hyprland implements `wlr-screencopy`, so the direct recorders work without a
portal. The portal path exists and is the only one on GNOME, but it costs a
dialog and a stream handshake. For a desktop that owns its compositor, the
direct protocol is the right default.

## The recorders

| Tool | Capture | Hardware encode | Audio | Region | Pause | Replay | Packaging |
|---|---|---|---|---|---|---|---|
| `wf-recorder` | wlr-screencopy | via ffmpeg VAAPI (`-c h264_vaapi -d`) | one source (`--audio`) | `-g` | no | no | distro (Arch `extra`, 0.6.0) |
| `wl-screenrec` | wlr-screencopy / ext-image-copy-capture | yes, by default (dma-buf) | one source | `-g` | no | `--history N` | not in Arch `extra` (AUR/cargo) |
| GPU Screen Recorder | portal or direct KMS | yes | device(s), app audio | yes | yes (UI) | yes | Arch `extra` 6.1.7 |
| OBS Studio | portal on Wayland | yes (VAAPI/NVENC) | full mixer | via scene | yes | yes | Arch `extra` 33.0.1 |
| Kooha | portal only | no (software) | yes | no | yes | no | Arch `extra` 2.3.2 |
| Spectacle (KDE) | KWin-internal | — | — | yes | — | — | Plasma only |
| GNOME recorder | Shell-internal | — | — | no | — | — | GNOME only |

### What each one gets right

- **`wf-recorder`** is the dependable baseline: one small binary, wlroots
  capture, `-f`/`-g`/`-o`/`--audio`/`-c`/`-p`, and it already ships in every
  distro the suite targets. It is also *not* hardware-encoded by default — that
  is the reason wl-screenrec exists.
- **`wl-screenrec`** is the performance answer: dma-buf handoff, GPU pixel
  format conversion, GPU encode. Its own benchmark (vkcube on screen) shows
  ~2.5% CPU against wf-recorder's ~500% with a software encoder and ~75% with
  VAAPI, plus no visible stutter. It also has `--history N` (a ShadowPlay-style
  replay buffer) and `--low-power`. The cost is packaging: it is not in Arch
  `extra`, so it cannot be a requirement.
- **GPU Screen Recorder** is the gaming answer (instant replay, per-app audio),
  but recording a whole monitor through KMS needs root, and its own docs note
  low portal frame rates on wlroots. Wrong default for a desktop recorder, good
  optional follow-up.
- **OBS** is a studio. A window with "start/stop" is a better product for the
  keypress case; OBS stays the answer when someone wants scenes and streaming.
- **Kooha** is the GNOME-shaped portal app: simple, software-encoded, no region
  picker. It proves the UI shape, not the capture path.

### What this app takes

1. **wf-recorder as the baseline, wl-screenrec when present** (auto, with an
   explicit choice that must be honoured or fail loudly).
2. **The mode set** — monitor / region / window — using `hyprctl` geometry, the
   same numbers grim and Hyprshot use.
3. **A one-key toggle** that works with no window, because the common case is
   "start now, stop when the thing is done".
4. **A JSON state file**, so the toggle is two processes and still correct.
5. **Countdown, audio choice and a recent list** from the desktop-app shape
   (Spectacle, Kooha, GPU Screen Recorder's UI).

### What it deliberately does not take

- **Portal capture.** A permission dialog mid-task is a worse product here.
- **Bundled encoding.** ffmpeg already exists in every install; wrapping it
  properly is the job.
- **Scenes and mixing.** OBS exists.
- **"Both audio sources" pretending to work.** wf-recorder takes one source;
  mixing system + mic is a v0.2 feature with a documented virtual-source setup.

## Measurements on this box

Hyprland 0.57.2, one 3840x1080 output at scale 1, wf-recorder 0.6.0, ffmpeg from
the distro:

| Operation | Result |
|---|---|
| wf-recorder 3.9 s at 3840x1080, 60 fps, H.264, defaults | **998 KB**, ~2.0 Mbps, `h264 yuv420p 3840x1080`, average 60.3 fps |
| `hyprctl monitors -j` / `clients -j` | ~4 ms each |
| wf-recorder's own defaults (from its log) | `crf=20`, `preset=superfast`, `tune=zerolatency`, `fps=60` filter |
| wl-screenrec upstream benchmark | ~2.5% CPU vs ~500% software / ~75% VAAPI for wf-recorder |

The file-size number is the one that shapes the UI: at 1080p ultrawide, CRF 20
is roughly 2 Mbps for a mostly-static desktop, so "quality" can be a
low/medium/high choice rather than a bitrate field. The encoder's defaults also
mean this app should override only what the user asked for.

## Design consequences

| Finding | Consequence in the code |
|---|---|
| wf-recorder is everywhere; wl-screenrec is not | `auto` prefers wl-screenrec, falls back; explicit missing → error |
| both finalize on SIGINT | `stop()` signals, waits, then checks the file — never SIGKILL first |
| neither pauses | SIGSTOP/SIGCONT, documented as best-effort, not frame-accurate |
| one audio source per encoder | three honest choices, no "both" |
| window geometry does not follow a moved window | documented; region is the answer for a moving target |
| the compositor owns placement | no floating HUD in v0.1; a persistent notification is the indicator |

## Sources

- Hyprland wiki, *Screenshots and recording* (wf-recorder, wl-screenrec,
  GPU Screen Recorder examples).
- wf-recorder man page (flags, `-p`, `--audio`, VAAPI notes); the defaults above
  were read from its own log output on this box.
- wl-screenrec README (dma-buf design, benchmark table, `--history`,
  `--capture-backend`, the Mesa VAAPI transform limitation).
- GPU Screen Recorder project page/Flathub listing (KMS/root note, portal frame
  rate caveat).
- Clevera's 2026 recorder comparison and the Zipline Wayland guide for the
  portal-vs-protocol explanation.
- `pacman -Ss` on this box for the packaging column (verified, not assumed).
- `ffprobe` on a recording made here for codec, size and frame rate.
