# CLAUDE.md — GabaMic
> Read this fully before touching any file. Every decision here has a reason.

---

## What This Is

GabaMic is a voice-to-text dictation utility: hold **Alt+S** anywhere, speak, release — your
words appear in the focused app. No cloud, no subscription. Primary target is macOS (menu bar
icon + text injection via Cmd+V), with a full-featured Windows UI (`app_win.py`) and a
cross-platform browser fallback (`web.py`).

**Pipeline:** microphone → numpy float32 buffer → faster-whisper (local CPU) → clipboard + paste

**Platform support summary:**
| Entry point | macOS | Windows | Linux (X11) | Linux (Wayland) |
|---|---|---|---|---|
| `app.py` — menu bar | ✅ | ✗ (AppKit/rumps) | ✗ | ✗ |
| `app_win.py` — floating pill | ✗ | ✅ (WebView2 req.) | ✗ | ✗ |
| `main.py` — terminal | ✅ | ✅ transcribes + pastes | ⚠️ transcribes, no paste | ✗ (no xlib) |
| `web.py` — browser UI | ✅ | ✅ | ✅ | ✅ |

`injector.py` resolves the paste key at import time: `Key.cmd` on macOS, `Key.ctrl` on
Windows/Linux — both platforms work correctly without any code changes.

---

## Tech Stack

| Layer | Library | Notes |
|---|---|---|
| Audio capture | `sounddevice` + `numpy` | 16 kHz mono float32 — Whisper's native format |
| Speech-to-text | `faster-whisper 1.0+` | CPU int8, `base` model, auto language detect |
| Text injection | `pyperclip` + `pynput` | Copy to clipboard → paste shortcut; clipboard is saved/restored |
| Global hotkeys | `pynput.keyboard.Listener` | Hold Alt+S; Accessibility permission required on macOS |
| Menu bar GUI | `rumps` | macOS-only; menu bar icon with status and language toggle |
| Windows pill UI | `pywebview 4.x` | Edge WebView2 backend; `js_api=` on `create_window()` — see gotchas below |
| Build (Windows) | `PyInstaller 6+` | onedir layout; all data files land in `_internal/` (`sys._MEIPASS`) |
| Config | `config.json` | All tunables live here — no hardcoded values in code |
| Python | 3.10–3.12 | macOS: any 3.10+. Windows: **3.10, 3.11, or 3.12 only** — `pythonnet` (pywebview dep) has no pre-built wheel for 3.13/3.14 |

---

## Repository Layout

```
GabaMic/
├── CLAUDE.md                ← you are here
├── README.md                ← user-facing setup guide (Windows + macOS)
├── requirements.txt         ← macOS pip deps (includes pytest; no pywebview)
├── requirements_win.txt     ← Windows pip deps (same as above + pywebview; no rumps)
├── config.json              ← all runtime tunables (see below)
├── main.py                  ← headless entry point (terminal, all platforms)
├── app.py                   ← menu bar entry point (macOS production)
├── app_win.py               ← floating pill entry point (Windows production)
├── web.py                   ← browser UI entry point (cross-platform)
├── GabaMic.bat              ← Windows daily launcher (silent, no console window)
├── setup_windows.bat        ← Windows one-time setup (venv + deps + optional launch)
├── build_windows.bat        ← Windows local build script (calls pyinstaller)
├── GabaMic.spec             ← PyInstaller spec (produces dist\GabaMic\GabaMic.exe)
├── .github/
│   └── workflows/
│       └── build_windows.yml  ← CI: builds exe on tag push or manual dispatch
├── gabamic/
│   ├── audio.py             ← AudioRecorder: start() / stop() → np.ndarray
│   ├── transcriber.py       ← Transcriber: __init__ loads model, transcribe() → str
│   ├── injector.py          ← TextInjector: inject(str) via clipboard + paste key
│   └── hotkey.py            ← HotkeyListener: fires on_start/on_stop callbacks
└── tests/
    ├── test_audio.py        ← 5 tests (silence, duration, valid audio, idempotent stop)
    └── test_transcriber.py  ← 4 tests (empty, capitalise, no speech, language param)
```

---

## config.json Reference

```json
{
  "model_size": "base",          // "tiny"|"base"|"small"|"medium" — larger = slower + better
  "language": null,              // null = auto-detect; "en" or "es" = forced
  "device": "cpu",               // "cpu" only on Mac (no CUDA)
  "compute_type": "int8",        // int8 is fastest on CPU; "float32" for accuracy testing
  "sample_rate": 16000,          // do not change — Whisper native rate
  "hotkey_modifier": "alt",      // "alt"|"ctrl"|"shift"|"cmd" — passed to HotkeyListener
  "hotkey_key": "s",             // any single character — passed to HotkeyListener
  "silence_rms_threshold": 0.01, // audio quieter than this is discarded
  "min_recording_seconds": 0.5   // recordings shorter than this are discarded
}
```

Language changes made via the macOS menu bar are persisted back to `config.json`
automatically. On Windows, edit the file directly next to `GabaMic.exe`.

---

## Module Contracts

### `gabamic/audio.py` — AudioRecorder

```python
recorder = AudioRecorder(sample_rate=16000)
recorder.start()           # opens sounddevice.InputStream, non-blocking
audio = recorder.stop()    # closes stream; returns 1-D float32 ndarray
                           # returns np.array([], dtype=np.float32) if:
                           #   RMS < silence_rms_threshold OR duration < min_recording_seconds
```

- Thread-safe: start/stop may be called from different threads.
- `stop()` is safe to call even if `start()` was never called (returns empty array).

### `gabamic/transcriber.py` — Transcriber

```python
t = Transcriber(model_size="base", device="cpu", compute_type="int8", language=None)
# Model is loaded ONCE in __init__ — this takes 2-4 s on first call.
text = t.transcribe(audio_np)   # "" if empty/silent; first letter capitalised
t.language = "es"               # can be changed at runtime (menu bar toggle)
```

- Accepts the numpy array directly — no temp files.
- `vad_filter=True` is set: Whisper's internal VAD silently skips non-speech segments.

### `gabamic/injector.py` — TextInjector

```python
injector = TextInjector()
injector.inject("Hola mundo")   # no-op if text is empty string
```

- Saves clipboard before, restores it after (via `try/finally`).
- Paste key is resolved at **import time** via `platform.system()`: `Key.cmd` on macOS
  ("Darwin"), `Key.ctrl` on Windows and Linux. Do NOT hardcode either key — the
  `_PASTE_KEY` module constant handles this correctly for all platforms.

### `gabamic/hotkey.py` — HotkeyListener

```python
listener = HotkeyListener(on_start=fn, on_stop=fn)
listener.start()   # non-blocking background thread
listener.stop()    # clean shutdown
```

- Detects `Key.alt`, `Key.alt_l`, `Key.alt_r` as the modifier (covers all keyboards).
- Callbacks are fired in **daemon threads** — they must not block indefinitely.
- All key exceptions are swallowed silently (pynput emits unknown keys on some keyboards).

---

## Entry Points

| Platform | Entry point | Requires Accessibility permission? |
|---|---|---|
| macOS (production) | `app.py` or `main.py` | Yes — grant in System Settings |
| macOS (no permission yet) | `web.py` | **No** |
| Windows (production) | `app_win.py` via `GabaMic.bat` | No |
| Windows (setup from source) | `setup_windows.bat` → `GabaMic.bat` | No |
| Linux (X11) | `web.py` or `main.py` | No for web; xlib needed for main.py |
| Linux (Wayland) | `web.py` | No (pynput has no Wayland support) |

### `main.py` — Headless (terminal)
```bash
cd /path/to/GabaMic
source .venv/bin/activate        # macOS/Linux
python main.py
```
Prints `● Recording…` / transcribed text to stdout. Quit with Ctrl+C.

### `app.py` — Menu bar (macOS only)
```bash
cd /path/to/GabaMic
source .venv/bin/activate
python app.py
```
🎙 icon appears in the macOS menu bar. No terminal window needed after launch.
Imports `rumps`, `AppKit`, and `Foundation` — macOS system libraries only. Will not
run on Windows or Linux even if rumps is installed.

### `app_win.py` — Floating pill (Windows)

**Normal launch (from source):**
```bat
GabaMic.bat    :: silent, no console window
```

**Manual launch (debugging):**
```bat
.venv\Scripts\python.exe app_win.py
```

A 170×34 pill appears at the bottom-centre of the screen. **Left-click** to toggle
recording on/off; **Alt+S** (hold) also works as a secondary hotkey. **Right-click** to quit.
Requires WebView2 (ships with Windows 10 KB4577586 and all Windows 11 versions).
No Accessibility permission needed on Windows.

### `web.py` — Browser UI (cross-platform, no system permissions required)
```bash
cd /path/to/GabaMic
source .venv/bin/activate
python web.py
```
Opens `http://localhost:8765` automatically. Hold **Spacebar** or hold anywhere on
the widget to record. Release to transcribe. Text is shown in an editable area and
auto-copied to clipboard. Works on macOS, Windows, and Linux because audio is captured
in the browser (getUserMedia) and sent to a local HTTP server — Python never calls
sounddevice directly, no system permissions needed.

---

## `app_win.py` Architecture

This file is the Windows production entry point and the most complex in the repo.
Read this section fully before modifying it.

### Config resolution — `_find_config()`

PyInstaller 6+ places all bundled data files in `_internal/` (= `sys._MEIPASS`), **not**
next to the exe. Users must be able to edit `config.json` (hotkey, model, language), so
on first launch the bundled copy is copied from `_internal/` to the exe directory:

```python
def _find_config() -> pathlib.Path:
    if getattr(sys, "frozen", False):          # running inside PyInstaller exe
        exe_dir = pathlib.Path(sys.executable).parent
        user_cfg = exe_dir / "config.json"
        if not user_cfg.exists():
            bundled = pathlib.Path(sys._MEIPASS) / "config.json"
            if bundled.exists():
                shutil.copy(bundled, user_cfg)
        return user_cfg
    return pathlib.Path(__file__).parent / "config.json"   # running from source
```

- `sys.executable.parent` = the folder with `GabaMic.exe`
- `sys._MEIPASS` = the `_internal/` folder with all bundled packages

### JS ↔ Python bridge — `_PillApi`

pywebview 4.x exposes Python methods to JavaScript via `js_api=` on `create_window()`
(the `api=` argument was removed from `webview.start()` in 4.x):

```python
class _PillApi:
    def __init__(self, app: "GabaMicWin") -> None:
        self._app = app

    def toggle(self) -> None:        # called by JS: window.pywebview.api.toggle()
        threading.Thread(target=self._app.toggle_recording, daemon=True).start()

    def quit(self) -> None:          # called by JS: window.pywebview.api.quit()
        if webview.windows:
            webview.windows[0].destroy()

# In GabaMicWin.run():
self._window = webview.create_window(..., js_api=_PillApi(self))
webview.start(private_mode=False)   # NO api= argument
```

### Recording state machine

The `_recording` boolean is shared between click-toggle and hotkey paths. Both call the
same internal methods to prevent conflicts:

```python
def _start_recording(self) -> None:
    self._recording = True
    self._recorder.start()
    self._set_state("recording")

def _stop_recording(self) -> None:
    self._recording = False
    audio = self._recorder.stop()          # always call stop() first
    if len(audio) == 0:
        self._set_state("idle"); return
    self._set_state("transcribing")
    text = self._transcriber.transcribe(audio)
    if text:
        self._injector.inject(text)
        self._set_state("done", text)
        threading.Thread(target=self._reset_idle, daemon=True).start()
    else:
        self._set_state("idle")

def toggle_recording(self) -> None:        # click path (via _PillApi)
    if self._transcriber is None: return   # still initialising
    if not self._recording: self._start_recording()
    else: self._stop_recording()

def _on_hotkey_start(self) -> None:        # pynput hold-to-record path
    if self._transcriber is None or self._recording: return
    self._start_recording()

def _on_hotkey_stop(self) -> None:
    if not self._recording: return
    self._stop_recording()
```

### Lazy model loading

The Whisper model is loaded in a background daemon thread (`_setup()`) that starts only
after the pywebview window fires `events.loaded`. This prevents the UI from freezing
during the multi-second (or multi-minute on first launch) download/load:

```
window.events.loaded → _setup() thread → show "Downloading…" or "Loading…"
                                       → Transcriber.__init__()  (blocks thread)
                                       → show "Warming up…"
                                       → transcribe(zeros)       (warms up model)
                                       → HotkeyListener.start()
                                       → show "idle" (animated logo)
```

Until `_transcriber is not None`, all `toggle_recording()` and `_on_hotkey_*` calls
return early — the hotkey and click do nothing while the model is loading.

### Pill states

| State | Dot color | Dot animation | Text shown |
|---|---|---|---|
| `idle` | — | — | Animated G logo |
| `recording` | Orange `#FF6200` | Pulsing 0.9s | "Recording…" |
| `transcribing` | Dim orange (70%) | Pulsing 0.9s | "Transcribing…" |
| `loading` | Teal (50%) | Pulsing 1.4s | "Downloading model…" or custom text |
| `done` | Teal `#00FFEF` | Solid | First 20 chars of transcription |

### Design system

| Token | Value | Usage |
|---|---|---|
| Background | `#080B14` | Pill body, window background |
| Teal | `#00FFEF` | Idle glow, done state, border hover |
| Orange | `#FF6200` | Recording state, logo gradient end |
| Gradient | `x1=15,y1=185 → x2=185,y2=15` | Bottom-left teal → top-right orange |

**G logo SVG** (circle with gap forming "G" + horizontal crossbar, same as `web.py`):
```xml
<circle cx="100" cy="100" r="69"
        fill="none" stroke="url(#g)" stroke-width="32"
        stroke-dasharray="361.3 72.3"/>   <!-- 83% visible, gap at top-right -->
<rect x="100" y="84" width="85" height="32" fill="url(#g)"/>
```

---

## pywebview 4.x Gotchas

These caused real runtime errors on Windows — do not repeat them:

| Mistake | Error | Correct approach |
|---|---|---|
| `webview.start(api=_PillApi())` | `TypeError: start() got unexpected keyword argument 'api'` | Use `js_api=` on `create_window()` only |
| `background_color="#00000000"` (8-digit hex) | `ValueError: #00000000 is not a valid hex triplet color` | Use 6-digit hex only: `"#080B14"` |
| `-webkit-app-region: drag` on the pill div | Left-click events never reach JS | Remove drag region; dragging is not needed |

---

## PyInstaller 6+ Onedir Layout

PyInstaller 6+ changed the onedir output structure:

```
dist\GabaMic\
├── GabaMic.exe          ← the launcher stub
└── _internal\           ← ALL bundled packages and data files land here
    ├── config.json      ← bundled default config (do not edit — use the one next to .exe)
    ├── gabamic\
    ├── ctranslate2\
    └── ...
```

`sys._MEIPASS` points to `_internal\`. Code that assumes data files are next to the exe
will break. The `_find_config()` function handles this correctly.

**The Whisper model is NOT bundled.** It downloads to `%USERPROFILE%\.cache\huggingface\hub\`
on first launch and is then fully offline. The `_model_is_cached()` helper checks for an
existing cache entry to show "Downloading…" vs "Loading…" in the pill.

---

## Windows Build and Release

### CI (recommended — runs on a real Windows machine)

Triggered by:
- Pushing a tag matching `v*` (e.g. `git tag v1.0.1 && git push --tags`)
- Manually via **Actions → Build Windows Executable → Run workflow**

Workflow at `.github/workflows/build_windows.yml`:
1. Checks out code on `windows-latest`
2. Sets up Python 3.10
3. Installs `requirements_win.txt` + `pyinstaller pyinstaller-hooks-contrib`
4. Runs `pyinstaller GabaMic.spec --noconfirm`
5. Zips `dist\GabaMic\` → `GabaMic-Windows.zip` (folder included in zip, not just contents)
6. Uploads as workflow artifact (always, 30-day retention)
7. Attaches to GitHub Release (only on tag pushes)

### Local build (requires a physical Windows machine)

```bat
setup_windows.bat   :: one-time: creates .venv, installs requirements_win.txt
build_windows.bat   :: installs pyinstaller, runs GabaMic.spec, outputs dist\GabaMic\
```

Zip `dist\GabaMic\` and distribute. No Python required for end users.

---

## Running Tests

```bash
cd /path/to/GabaMic
source .venv/bin/activate        # macOS/Linux
python -m pytest tests/ -v
```

9 tests, all pass. Tests use `unittest.mock` to patch `WhisperModel` and inject audio
buffers directly — no microphone or GPU required.

---

## macOS Permissions (Required Once)

pynput needs **Accessibility** permission to read global keystrokes:

1. Run the app once (it will appear to hang on the first hotkey press)
2. Go to **System Settings → Privacy & Security → Accessibility**
3. Add **Terminal** (for `main.py`) or the app bundle (for `app.py`) and toggle it on
4. Restart the script

---

## Known Limitations

| Limitation | Detail |
|---|---|
| `app.py` is macOS-only | Depends on `rumps` + `AppKit`/`Foundation` (PyObjC). No cross-platform equivalent without a GUI toolkit rewrite. |
| No Wayland support | `pynput`'s global listener uses Xlib — Linux users on Wayland must use `web.py`. |
| Clipboard clobber on crash | If the process is killed between `pyperclip.copy()` and the restore, the user's clipboard is overwritten. The `finally` block covers normal flow. |
| rumps thread safety | `self.title` and menu item titles are set from HotkeyListener daemon threads. This works in practice but is technically unsafe. A future fix would use `rumps.timers`. |
| First model download | faster-whisper downloads ~150 MB to `~/.cache/huggingface/hub/` (macOS/Linux) or `%USERPROFILE%\.cache\huggingface\hub\` (Windows) on first run. |
| Accessibility prompt | macOS shows a permission dialog on the first hotkey press if Accessibility is not yet granted. The app appears frozen until the user responds. |
| Single language at a time | Auto-detect handles mixed Spanish/English well, but within a single utterance only one language is detected. |
| Windows Python version | Python 3.10–3.12 only. `pythonnet` (a pywebview dependency) has no pre-built wheel for 3.13/3.14; building from source requires .NET SDK + NuGet. |
| Hotkey unreliable on Windows | Some security software blocks `WH_KEYBOARD_LL` (pynput's hook). Left-click toggle is the recommended primary interaction on Windows. |

---

## What NOT to Change Without Thinking

- **`sample_rate`** — Whisper is trained at 16 kHz. Changing this breaks transcription.
- **`_PASTE_KEY` in injector.py** — uses `platform.system()` to pick `Key.cmd` (macOS) or
  `Key.ctrl` (Windows/Linux). Do not hardcode either; the OS detection must stay.
- **`vad_filter=True` in transcriber.py** — removing it causes Whisper to hallucinate text on silence.
- **`daemon=True` on hotkey callback threads** — removing this will prevent clean shutdown.
- **The `try/finally` in injector.py** — removing it will occasionally destroy the user's clipboard.
- **`js_api=` on `create_window()` in app_win.py** — do NOT move it to `webview.start()`. pywebview 4.x removed `api=` from `start()`.
- **`background_color` in app_win.py** — must be a 6-digit hex string (`"#080B14"`). pywebview rejects 8-digit (alpha) hex values.
- **`_find_config()` in app_win.py** — the exe/`_internal` split is intentional; this function is the only correct way to locate config in both frozen and source modes.
- **`console=False` in GabaMic.spec** — removes the terminal window. Errors surface via `_show_error()` (Windows `MessageBoxW`). Do not enable the console in production builds.
- **The zip command in build_windows.yml** — `Compress-Archive -Path dist\GabaMic` (not `dist\GabaMic\*`) preserves the parent folder in the zip so extracting it gives users a clean `GabaMic\` folder.
