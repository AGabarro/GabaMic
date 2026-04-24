# CLAUDE.md — GabaMic
> Read this fully before touching any file. Every decision here has a reason.

---

## What This Is

GabaMic is a voice-to-text dictation utility: hold **Alt+S** anywhere, speak, release — your
words appear in the focused app. No cloud, no subscription. Primary target is macOS (menu bar
icon + text injection), but `web.py` runs on Windows and Linux too.

**Pipeline:** microphone → numpy float32 buffer → faster-whisper (local CPU) → clipboard + Cmd+V paste

**Platform support summary:**
| Entry point | macOS | Windows | Linux (X11) | Linux (Wayland) |
|---|---|---|---|---|
| `app.py` — menu bar | ✅ | ✗ (AppKit/rumps) | ✗ | ✗ |
| `app_win.py` — floating pill | ✗ | ✅ (WebView2 req.) | ✗ | ✗ |
| `main.py` — terminal | ✅ | ✅ transcribes + pastes | ⚠️ transcribes, no paste | ✗ (no xlib) |
| `web.py` — browser UI | ✅ | ✅ | ✅ | ✅ |

`injector.py` uses `Key.cmd` on macOS and `Key.ctrl` on Windows/Linux — both handled automatically.

---

## Tech Stack

| Layer | Library | Notes |
|---|---|---|
| Audio capture | `sounddevice` + `numpy` | 16 kHz mono float32 — Whisper's native format |
| Speech-to-text | `faster-whisper 1.2+` | CPU int8, `base` model, auto language detect |
| Text injection | `pyperclip` + `pynput` | Copy to clipboard → Cmd+V; clipboard is saved/restored |
| Global hotkeys | `pynput.keyboard.Listener` | Hold Alt+S; works system-wide with Accessibility permission |
| Menu bar GUI | `rumps` | macOS-only; menu bar icon with status and language toggle |
| Config | `config.json` | All tunables live here — no hardcoded values in code |
| Python | 3.10 (`.venv`) | `pynput` type union syntax requires 3.10+ |

---

## Repository Layout

```
GabaMic/
├── CLAUDE.md                ← you are here
├── README.md                ← user-facing setup guide
├── requirements.txt         ← pip deps (includes pytest)
├── config.json              ← all runtime tunables (see below)
├── main.py                  ← headless entry point (terminal)
├── app.py                   ← menu bar entry point (macOS production)
├── app_win.py               ← floating pill entry point (Windows production)
├── gabamic/
│   ├── audio.py             ← AudioRecorder: start() / stop() → np.ndarray
│   ├── transcriber.py       ← Transcriber: __init__ loads model, transcribe() → str
│   ├── injector.py          ← TextInjector: inject(str) via clipboard + Cmd+V
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

Language changes made via the menu bar are persisted back to `config.json` automatically.

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
- Paste key is resolved at import time via `platform.system()`: `Key.cmd` on macOS ("Darwin"),
  `Key.ctrl` on Windows and Linux. Do NOT hardcode either key — the `_PASTE_KEY` module
  constant handles this correctly for all platforms.

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
| Windows | `web.py` | No (`main.py` transcribes but paste is broken — see injector note) |
| Linux (X11) | `web.py` or `main.py` | No for web; xlib needed for main.py |
| Linux (Wayland) | `web.py` | No (pynput has no Wayland support) |

### `main.py` — Headless (terminal)
```
cd /Users/adria.gabarro/Documents/GabaMic
source .venv/bin/activate
python main.py
```
Prints `● Recording…` / transcribed text to stdout. Quit with Ctrl+C.

### `app.py` — Menu bar (macOS only)
```
cd /Users/adria.gabarro/Documents/GabaMic
source .venv/bin/activate
python app.py
```
🎙 icon appears in the macOS menu bar. No terminal window needed after launch.
Imports `rumps`, `AppKit`, and `Foundation` — macOS system libraries only. Will not
run on Windows or Linux even if rumps is installed.

### `app_win.py` — Floating pill (Windows)
```
cd C:\path\to\GabaMic
.venv\Scripts\activate
pip install pywebview>=4.0.2   # one-time, not in base requirements
python app_win.py
```
A 240×44 pill appears at the bottom-centre of the screen. Hold **Alt+S** to record;
release to transcribe and inject text into the focused window via `Ctrl+V`.
**Right-click the pill to quit.**
Requires WebView2 (ships with Windows 10 KB4577586 and all Windows 11 versions).
No Accessibility permission needed on Windows.

### `web.py` — Browser UI (cross-platform, no system permissions required)
```
cd /Users/adria.gabarro/Documents/GabaMic
source .venv/bin/activate
python web.py
```
Opens `http://localhost:8765` automatically. Hold **Spacebar** or hold anywhere on
the widget to record. Release to transcribe. Text is shown in an editable area and
auto-copied to clipboard. Works on macOS, Windows, and Linux because audio is captured
in the browser (getUserMedia) and sent to a local HTTP server — Python never calls
sounddevice directly, no system permissions needed.

---

## Running Tests

```bash
cd /Users/adria.gabarro/Documents/GabaMic
source .venv/bin/activate
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
| Text injection is macOS-only | `injector.py` uses `Key.cmd + V`. On Windows/Linux the paste shortcut is `Ctrl+V`. Fixing this requires an OS detection branch with `Key.ctrl` — not done intentionally to keep the code simple. |
| `app.py` is macOS-only | Depends on `rumps` + `AppKit`/`Foundation` (PyObjC). No cross-platform equivalent without a GUI toolkit rewrite. |
| No Wayland support | `pynput`'s global listener uses Xlib — Linux users on Wayland must use `web.py`. |
| Clipboard clobber on crash | If the process is killed between `pyperclip.copy()` and the restore, the user's clipboard is overwritten. The `finally` block covers normal flow. |
| rumps thread safety | `self.title` and menu item titles are set from HotkeyListener daemon threads. This works in practice but is technically unsafe. A future fix would use `rumps.timers`. |
| First model download | faster-whisper downloads ~150 MB to `~/.cache/huggingface/hub/` on first run. Subsequent runs are fully offline. |
| Accessibility prompt | macOS shows a permission dialog on the first hotkey press if Accessibility is not yet granted. The app appears frozen until the user responds. |
| Single language at a time | Auto-detect handles mixed Spanish/English well, but within a single utterance only one language is detected. |

---

## What NOT to Change Without Thinking

- **`sample_rate`** — Whisper is trained at 16 kHz. Changing this breaks transcription.
- **`_PASTE_KEY` in injector.py** — uses `platform.system()` to pick `Key.cmd` (macOS) or
  `Key.ctrl` (Windows/Linux). Do not hardcode either; the OS detection must stay.
- **`vad_filter=True` in transcriber.py** — removing it causes Whisper to hallucinate text on silence.
- **`daemon=True` on hotkey callback threads** — removing this will prevent clean shutdown.
- **The `try/finally` in injector.py** — removing it will occasionally destroy the user's clipboard.
