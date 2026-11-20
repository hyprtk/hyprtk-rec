# hyprtk-rec — plan

Status: **v0.2.0 in progress 2026-11-20** (v0.1.0 released and wired into the
suite). Batches land here as they are finished.

## Decisions (and why)

Survey and measurements: [RESEARCH.md](RESEARCH.md).

| Decision | Rationale |
|---|---|
| Wrap `wf-recorder`/`wl-screenrec`, do not encode | ffmpeg is already there; the suite gains a controller, not a codec |
| `auto` = wl-screenrec if present, else wf-recorder | GPU encoding when available, a guaranteed baseline otherwise |
| State in `$XDG_RUNTIME_DIR/hyprtk-rec/state.json` | start and stop are often different processes (keybinding), and a stale pid must not lie |
| SIGINT to stop, then wait for the file | both encoders finalize their container on SIGINT; killing first corrupts |
| SIGSTOP/SIGCONT for pause | neither encoder supports pause; this is the only honest lever, documented as best-effort |
| Three audio choices, no "both" | one source per encoder; a fake "both" would record one and claim two |
| Window = geometry at start | Hyprland gives no follow-a-window capture to a CLI recorder; say so |
| Countdown in the bridge, not the CLI | the GUI needs a visible number, the CLI can just `sleep` |
| PySide6 + QML, same palette resolver | one wallpaper repaints the suite; no new runtime dependency |

## Architecture

```
hyprtk_rec/
  sources.py   hyprctl monitors/clients, slurp, geometry
  audio.py     pactl sources, sink monitor, default input
  recorder.py  argv builders, Recording, Recorder (state/lifecycle)
  store.py     naming, history, duration/size formatting
  settings.py  ~/.config/hyprtk-rec/config.json
  palette.py   pywal/bar theme -> state colours
  bridge.py    QML facade: countdown, 500 ms tick, notifications, recents
  cli.py       start/stop/toggle/pause/resume/status/sources
  app.py       QGuiApplication, engine
  qml/
    Main.qml              state card, options, recent list, countdown, toast
    components/           Segmented, ActionButton
```

The core has no Qt import: `recorder.py` is testable with a fake process, and
the CLI works on a box where PySide6 is missing.

## v0.1.0 — what the scaffold does

- [x] Monitor / region / window sources, resolved before recording starts
- [x] `wf-recorder` and `wl-screenrec` argv builders, CRF and bitrate mappings
- [x] Audio: off / system monitor / default mic / named device
- [x] Start, SIGINT stop with finalize, pause/resume, stale-state cleanup
- [x] JSON state file and `status`/`toggle` from a separate process
- [x] Window with live timer, source/audio/fps/codec/quality/countdown,
      output directory, recent recordings
- [x] CLI with every setting and `--json`
- [x] pywal palette, v09 icon, desktop entry, `--system`/`--uninstall`
- [x] 94 unit tests, `qmllint`, headless boot check, installer round-trip
- [x] Offscreen screenshots for the README

Not in v0.1.0, deliberately: an on-screen recording HUD, GIF output, trimming,
replay buffer, mixed system+mic audio, VAAPI selection, GPU Screen Recorder.

## v0.2 — the things a daily user will ask for

- [x] **Recording HUD** — a 240x56 frameless window with the timer, Pause and
      Stop; placed and pinned by a Hyprland rule (`move`, verified live), no
      focus, shown while a recording is active.
- [x] **Mixed audio** — null sink + two loopbacks (`audio.start_mix`), module
      ids in the state file, unloaded on stop *and* on recovery/`pactl` failure.
- [x] **GIF output** — container `gif` through wf-recorder (`-c gif -x rgb8`),
      fps capped at 30, no audio, backend falls back from wl-screenrec.
- [x] **Trim** — `trim PATH --from/--to` through ffmpeg (`-ss`/`-t -c copy`),
      `--last`, `--replace`, `--reencode` only when asked.
- [x] **VAAPI encoding** — opt-in, h264/hevc, **probed** with
      `ffmpeg -init_hw_device` (a render node can exist and still fail); the
      window shows the failure reason and a failed probe is a start error.
- [x] **Replay buffer** — `--replay N` (`wl-screenrec --history`) + Save
      (`SIGUSR1`), window/HUD buttons and a settings row. Gated on wl-screenrec;
      argv/signal-tested only, because the AUR package does not build against
      Arch ffmpeg 8.
- [x] **Named window picker** — the window source records a picked window
      (stored by client address, self-heals when it closes), `--window ADDRESS`.
- [x] **Notification actions** — "Open folder" / "Copy path" via a detached
      `hyprtk-rec notify-saved PATH` waiter (`notify-send -A`).

## v0.3 — beyond the desktop

- [ ] **GPU Screen Recorder backend** for replay/instant-replay users, with its
      root/KMS caveat stated in the UI.
- [ ] **Multi-monitor independent recordings** (two state entries) — only if
      there is a real use case; the current rule is one at a time.
- [x] **A settings sheet** — save folder, notifications, recent length, backend
      and reset, in a panel over the window (`settingsOpen`).
- [x] **Session restore** — `Recorder.recover()` adopts the partial file of a
      dead encoder on the next start (history + notification).

## Suite integration — the exact edits

1. **Repo + tag.** `git init` in `~/Projects/AI-Projects/hyprtk-rec`, push
   `hyprtk/hyprtk-rec` on `main`, tag `v0.1.0`, topics (`wayland`, `hyprland`,
   `screen-recorder`, `wf-recorder`, `qt`).
2. **Vendor into merged** (`installer/hyprtk-rec/`, payload only).
3. **`1-install.sh` step** after hyprtk-shot:

   ```sh
   _step "Installing hyprtk-rec"
   _spin "Installing hyprtk-rec..." "bash $SCRIPT_DIR/installer/hyprtk-rec/install.sh" "$LOG_FILE"
   _ok "hyprtk-rec installed (hyprtk-rec; screen recorder)"
   ```

4. **Keybindings** — replace the two script binds with one toggle:

   ```lua
   hl.bind(mainMod .. " + SHIFT + PRINT", hl.dsp.exec_cmd("sh -c 'p=$HOME/.local/bin/hyprtk-rec; [ -x \"$p\" ] && exec \"$p\" --toggle'"))
   hl.bind(mainMod .. " + ALT + PRINT",   hl.dsp.exec_cmd("sh -c 'p=$HOME/.local/bin/hyprtk-rec; [ -x \"$p\" ] && exec \"$p\" stop'"))
   ```

5. **Retire the old scripts.** `hypr/scripts/wf-record-start.sh` and
   `wf-record-stop.sh` become a one-release fallback, then go. Their notification
   and `~/Videos/Recordings/.tmp` behaviour is already reproduced (and improved:
   the file is written to its final name, so a crash cannot strand a temp file).
6. **Window rule** in `hypr/windowrules.lua`:

   ```lua
   hl.window_rule({
       name = "windowrule-hyprtk-rec",
       match = { class = "hyprtk-rec" },
       float = true,
       center = true,
       size = "560 720",
   })
   ```

7. **Docs in merged**: README app table, cheatsheet (`Super+Shift+Print`),
   suite `CHANGELOG`. ISO: `packages.hyprtk` already has `wf-recorder`; add
   `slurp` if it is not there; `customize_airootfs.sh` runs `--system`;
   `hyprtk-first-run` adds the `~/.local/bin` link.
8. **`push-all`** — the normal gate and publish.

Bar quick link: a `rec` entry in `hyprtk-bar-qt/config.json` quicklinks, with
`action: "exec"` running `hyprtk-rec --toggle`; bump the bar and re-vendor.

## Gate

`./scripts/qa.sh` stays green, and every check can fail:

| Check | Catches |
|---|---|
| `unittest discover` | wrong argv, a broken state file, audio parsing, CLI wiring |
| `compileall` | syntax drift |
| `qmllint` | QML syntax and unqualified properties |
| `bootcheck.py` | a QML load failure, a palette key the window binds to that was renamed, a start/stop that leaves the bridge recording |
| installer round-trip | `--system`/`--uninstall`, absolute desktop entry |
| CLI smoke | the `__main__` dispatch and the JSON contract |

## Open questions

- **Pause semantics.** SIGSTOP freezes the encoder, but the timeline gap is
  whatever the encoder does with the next frame's timestamp. Is it honest to
  ship it, or should pause be labelled "freeze (approximate)" in the UI?
- **Recording HUD placement** without layer-shell: a Hyprland `move` rule is
  compositor-specific, a layer-shell surface means a second Quickshell app.
- **Mixed audio** through `module-null-sink` + `module-loopback` is doable but
  creates and destroys modules in the user's session; the failure mode (a
  dangling null sink) needs a cleanup path before shipping.
- **wl-screenrec packaging**: AUR-only today. Should the installer offer it
  (explicitly, as an optional) or leave it to the user's AUR helper?
