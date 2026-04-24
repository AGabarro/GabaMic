"""GabaMic — Windows floating pill entry point.

Left-click the pill to start recording; click again to stop and paste.
Alt+S also works as a hold-to-record hotkey.
Right-click the pill to quit.

Requirements: pip install -r requirements_win.txt
Usage:        python app_win.py   (or double-click GabaMic.bat)
"""

import ctypes
import json
import pathlib
import platform
import shutil
import sys
import threading
import time

import numpy as np
import webview

from gabamic.audio import AudioRecorder
from gabamic.hotkey import HotkeyListener
from gabamic.injector import TextInjector
from gabamic.transcriber import Transcriber


# ---------------------------------------------------------------------------
# Config resolution — works for both plain script and PyInstaller onedir
# ---------------------------------------------------------------------------

def _find_config() -> pathlib.Path:
    """Locate config.json.

    PyInstaller 6+ places bundled data files in _internal/ (sys._MEIPASS),
    not next to the exe.  On the first launch we copy the default there so
    the user can edit it; every subsequent launch reads that copy.
    """
    if getattr(sys, "frozen", False):
        exe_dir = pathlib.Path(sys.executable).parent
        user_cfg = exe_dir / "config.json"
        if not user_cfg.exists():
            bundled = pathlib.Path(sys._MEIPASS) / "config.json"
            if bundled.exists():
                shutil.copy(bundled, user_cfg)
        return user_cfg
    return pathlib.Path(__file__).parent / "config.json"


CONFIG_PATH = _find_config()
PILL_W, PILL_H = 140, 38          # window (margin lets outer drop-shadow glow render)
_PILL_TITLE    = "GabaMicPill"   # window title (hidden; used by FindWindowW for icon)


# ---------------------------------------------------------------------------
# Pill HTML — self-contained, no external resources
# ---------------------------------------------------------------------------

_PILL_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  width: 140px; height: 38px;
  background: transparent;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

/* ── Outer wrapper: owns external drop-shadow glow ───────────────── */
.pill-glow {
  will-change: filter;
  filter: drop-shadow(0 0 6px rgba(0,255,239,0.42));
  transition: filter 0.38s cubic-bezier(0.4,0,0.2,1);
}
.pill-glow.is-recording {
  animation: glow-rec 1.35s ease-in-out infinite;
}
.pill-glow.is-transcribing {
  filter: drop-shadow(0 0 6px rgba(255,98,0,0.45));
}
@keyframes glow-rec {
  0%,100% { filter: drop-shadow(0 0  9px rgba(255,98,0,0.85)); }
  50%     { filter: drop-shadow(0 0 16px rgba(255,98,0,1.00)); }
}

/* ── Pill shell ──────────────────────────────────────────────────── */
.pill {
  width: 118px; height: 24px;
  background: linear-gradient(150deg, rgba(8,11,20,.98) 0%, rgba(11,15,28,.98) 100%);
  border: 1.5px solid rgba(0,255,239,0.50);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  user-select: none;
  cursor: grab;
  position: relative;
  transition:
    border-color 0.38s cubic-bezier(0.4,0,0.2,1),
    box-shadow   0.38s cubic-bezier(0.4,0,0.2,1);
  box-shadow: inset 0 0 10px rgba(0,255,239,0.05);
}
.pill:hover {
  border-color: rgba(0,255,239,0.75);
  box-shadow: inset 0 0 10px rgba(0,255,239,0.09);
}
.pill.is-recording {
  border-color: #FF6200;
  box-shadow: inset 0 0 12px rgba(255,98,0,0.12);
}
.pill.is-transcribing {
  border-color: rgba(255,98,0,0.55);
  box-shadow: inset 0 0 10px rgba(255,98,0,0.07);
}

/* ── Idle: animated GabaMic logo ─────────────────────────────────── */
.logo-stage {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; position: relative;
}
.aura {
  position: absolute; width: 44%; height: 80%; border-radius: 50%;
  background: radial-gradient(ellipse at center,
    rgba(0,255,239,.14) 0%, rgba(255,98,0,.06) 45%, transparent 70%);
  animation: aura 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes aura {
  0%,100% { transform: scale(.88); opacity: .50; }
  50%     { transform: scale(1.12); opacity: .95; }
}
.logo-svg {
  position: relative; height: 60%; width: auto;
  animation: breathe 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes breathe {
  0%,100% {
    filter: drop-shadow(0 0 2px rgba(0,255,239,.32));
    transform: scale(.97);
  }
  50% {
    filter: drop-shadow(0 0 6px  rgba(0,255,239,.72))
            drop-shadow(0 0 14px rgba(0,255,239,.28));
    transform: scale(1.04);
  }
}

/* ── Status row ──────────────────────────────────────────────────── */
.status-row {
  display: none;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  width: 100%;
}

/* Waveform bars — recording only */
.waveform {
  display: flex; align-items: center; gap: 1.5px; flex-shrink: 0;
}
.wbar {
  width: 2px; border-radius: 2px;
  background: #FF6200;
  box-shadow: 0 0 3px rgba(255,98,0,0.85);
}
.wbar:nth-child(1) { animation: wave .88s ease-in-out -0.38s infinite; }
.wbar:nth-child(2) { animation: wave .88s ease-in-out -0.18s infinite; }
.wbar:nth-child(3) { animation: wave .88s ease-in-out  0.02s infinite; }
.wbar:nth-child(4) { animation: wave .88s ease-in-out -0.28s infinite; }
@keyframes wave {
  0%,100% { height: 3px;  opacity: .60; }
  50%     { height: 10px; opacity: 1.0; }
}

/* Status dot */
.dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.dot.transcribing {
  background: rgba(255,98,0,.80);
  box-shadow: 0 0 4px rgba(255,98,0,.65);
  animation: pulse .88s ease-in-out infinite;
}
.dot.loading { background: rgba(0,255,239,.55); animation: pulse 1.4s ease-in-out infinite; }
.dot.done    { background: #00FFEF; box-shadow: 0 0 5px rgba(0,255,239,.65); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.28} }

/* Status label */
.status-text {
  font-size: 10px; font-weight: 500; letter-spacing: 0.1px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: #00FFEF;
  transition: color 0.32s ease;
}
.status-text.rec { color: #FF7030; }
.status-text.trx { color: rgba(255,135,55,.88); }
</style>
</head>
<body>

<!-- Outer wrapper: owns the external glow via filter: drop-shadow -->
<div class="pill-glow" id="pill-glow">
<div class="pill" id="pill">

  <!-- Idle view: breathing logo -->
  <div class="logo-stage" id="idle-view">
    <div class="aura"></div>
    <svg class="logo-svg" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="g" x1="15" y1="185" x2="185" y2="15"
                        gradientUnits="userSpaceOnUse">
          <stop offset="0%"   stop-color="#00FFEF"/>
          <stop offset="100%" stop-color="#FF6200"/>
        </linearGradient>
      </defs>
      <circle cx="100" cy="100" r="69"
              fill="none" stroke="url(#g)" stroke-width="32"
              stroke-dasharray="361.3 72.3"/>
      <rect x="100" y="84" width="85" height="32" fill="url(#g)"/>
    </svg>
  </div>

  <!-- Status view: recording / transcribing / loading / done -->
  <div class="status-row" id="status-view">
    <div class="waveform" id="waveform">
      <div class="wbar"></div>
      <div class="wbar"></div>
      <div class="wbar"></div>
      <div class="wbar"></div>
    </div>
    <div class="dot" id="dot"></div>
    <span class="status-text" id="status-text"></span>
  </div>

</div><!-- .pill -->
</div><!-- .pill-glow -->

<script>
'use strict';

const pillGlow   = document.getElementById('pill-glow');
const pill       = document.getElementById('pill');
const idleView   = document.getElementById('idle-view');
const statusView = document.getElementById('status-view');
const waveform   = document.getElementById('waveform');
const dot        = document.getElementById('dot');
const statusText = document.getElementById('status-text');

function setState(state, text) {
  pill.classList.remove('is-recording', 'is-transcribing');
  pillGlow.classList.remove('is-recording', 'is-transcribing');

  if (state === 'idle') {
    idleView.style.display   = 'flex';
    statusView.style.display = 'none';
    return;
  }

  idleView.style.display   = 'none';
  statusView.style.display = 'flex';
  waveform.style.display   = 'none';
  dot.style.display        = 'block';

  if (state === 'recording') {
    pill.classList.add('is-recording');
    pillGlow.classList.add('is-recording');
    waveform.style.display = 'flex';
    dot.style.display      = 'none';
    statusText.textContent = 'Recording\u2026';
    statusText.className   = 'status-text rec';

  } else if (state === 'transcribing') {
    pill.classList.add('is-transcribing');
    pillGlow.classList.add('is-transcribing');
    dot.className          = 'dot transcribing';
    statusText.textContent = 'Transcribing\u2026';
    statusText.className   = 'status-text trx';

  } else if (state === 'loading') {
    dot.className          = 'dot loading';
    statusText.textContent = text || 'Setting up\u2026';
    statusText.className   = 'status-text';

  } else if (state === 'done') {
    dot.className = 'dot done';
    const preview = text && text.length > 14 ? text.slice(0, 14) + '\u2026' : (text || 'Done');
    statusText.textContent = preview;
    statusText.className   = 'status-text';
  }
}

// ── Drag to move ───────────────────────────────────────────────────
let _dragX, _dragY, _dragged = false;
const DRAG_PX = 3;   // pixels of movement before a drag is recognised

pill.addEventListener('mousedown', (e) => {
  if (e.button !== 0) return;
  _dragX = e.screenX; _dragY = e.screenY; _dragged = false;
  document.body.style.cursor = 'grabbing';
  e.preventDefault();
});

document.addEventListener('mousemove', (e) => {
  if (e.buttons !== 1 || _dragX === undefined) return;
  const dx = e.screenX - _dragX, dy = e.screenY - _dragY;
  if (!_dragged && Math.abs(dx) < DRAG_PX && Math.abs(dy) < DRAG_PX) return;
  _dragged = true;
  window.pywebview?.api?.move_by(dx, dy);
  _dragX = e.screenX; _dragY = e.screenY;
});

document.addEventListener('mouseup', () => {
  _dragX = undefined;
  document.body.style.cursor = '';
});

// Left-click: toggle recording (suppressed if the gesture was a drag)
pill.addEventListener('click', () => {
  if (_dragged) { _dragged = false; return; }
  window.pywebview?.api?.toggle();
});

// Right-click: quit
document.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  window.pywebview?.api?.quit();
});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# JS → Python bridge
# ---------------------------------------------------------------------------

class _PillApi:
    """Methods exposed to JavaScript via window.pywebview.api."""

    def __init__(self, app: "GabaMicWin") -> None:
        self._app = app

    def toggle(self) -> None:
        """Left-click: start or stop recording."""
        threading.Thread(target=self._app.toggle_recording, daemon=True).start()

    def quit(self) -> None:
        """Right-click: close the pill."""
        if webview.windows:
            webview.windows[0].destroy()

    def move_by(self, dx: float, dy: float) -> None:
        """Drag: shift the pill window by (dx, dy) pixels."""
        self._app.move_by(int(round(dx)), int(round(dy)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        _show_error("GabaMic — Config Error",
                    f"config.json is not valid JSON:\n\n{exc}\n\n"
                    "Delete config.json and restart to restore defaults.")
        raise
    except FileNotFoundError:
        _show_error("GabaMic — Config Error",
                    f"config.json not found:\n{CONFIG_PATH}")
        raise


def _model_is_cached(model_size: str) -> bool:
    """Return True if the Whisper model already exists in the HuggingFace cache."""
    import os
    hf_home = os.getenv("HF_HOME")
    cache_dir = (pathlib.Path(hf_home) / "hub") if hf_home else (
        pathlib.Path.home() / ".cache" / "huggingface" / "hub"
    )
    if not cache_dir.exists():
        return False
    return any(cache_dir.glob(f"models--Systran--faster-whisper-{model_size}*"))


def _show_error(title: str, message: str) -> None:
    """Show a Windows error dialog; fall back to stderr on non-Windows."""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        print(f"ERROR — {title}\n{message}", file=sys.stderr)


def _find_icon() -> pathlib.Path | None:
    """Locate GabaMic.ico next to the exe (frozen) or script (source)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles GabaMic.ico into _internal/ (sys._MEIPASS) AND
        # also copies it next to the exe via the datas entry — prefer the one
        # next to the exe so it's easy for users to find.
        exe_dir = pathlib.Path(sys.executable).parent
        candidates = [exe_dir / "GabaMic.ico",
                      pathlib.Path(sys._MEIPASS) / "GabaMic.ico"]
    else:
        candidates = [pathlib.Path(__file__).parent / "GabaMic.ico"]
    for p in candidates:
        if p.exists():
            return p
    return None


def _set_window_icon(win_title: str) -> None:
    """Stamp the G-logo onto the pywebview window via Win32 LoadImage/WM_SETICON.

    This makes the GabaMic icon appear in the Windows taskbar, Alt-Tab
    switcher, and Task Manager for source builds (where there is no embedded
    exe icon).  For PyInstaller builds the embedded exe icon already serves
    this role, but calling this doesn't hurt — it keeps both paths consistent.
    """
    if platform.system() != "Windows":
        return
    ico_path = _find_icon()
    if ico_path is None:
        return
    try:
        WM_SETICON      = 0x0080
        ICON_SMALL      = 0
        ICON_BIG        = 1
        IMAGE_ICON      = 1
        LR_LOADFROMFILE = 0x00000010

        user32  = ctypes.windll.user32
        hwnd    = user32.FindWindowW(None, win_title)
        if not hwnd:
            return
        ico_str = str(ico_path)
        hicon_big = user32.LoadImageW(None, ico_str, IMAGE_ICON, 32, 32,
                                       LR_LOADFROMFILE)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        hicon_small = user32.LoadImageW(None, ico_str, IMAGE_ICON, 16, 16,
                                         LR_LOADFROMFILE)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
    except Exception:
        pass  # icon is cosmetic — never crash on failure


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class GabaMicWin:

    def __init__(self) -> None:
        cfg = load_config()
        self._cfg = cfg

        self._recorder = AudioRecorder(
            sample_rate           = cfg.get("sample_rate", 16000),
            silence_rms_threshold = cfg.get("silence_rms_threshold", 0.01),
            min_recording_seconds = cfg.get("min_recording_seconds", 0.5),
        )
        self._transcriber: Transcriber | None = None
        self._injector = TextInjector()
        self._window: webview.Window | None = None
        self._ready = False
        self._hotkey: HotkeyListener | None = None
        self._recording = False           # shared between click-toggle and hotkey
        self._win_x = 0                   # tracked position for drag-to-move
        self._win_y = 0

    # ------------------------------------------------------------------
    # UI helpers  (thread-safe — pywebview queues evaluate_js internally)
    # ------------------------------------------------------------------

    def _set_state(self, state: str, text: str = "") -> None:
        if self._window and self._ready:
            self._window.evaluate_js(
                f"setState({json.dumps(state)}, {json.dumps(text)})"
            )

    # ------------------------------------------------------------------
    # Background initialisation — runs after the window has loaded
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        cfg = self._cfg
        model_size = cfg.get("model_size", "base")

        self._set_state(
            "loading",
            "Downloading model\u2026" if not _model_is_cached(model_size)
            else "Loading model\u2026",
        )

        try:
            self._transcriber = Transcriber(
                model_size   = model_size,
                device       = cfg.get("device", "cpu"),
                compute_type = cfg.get("compute_type", "int8"),
                language     = cfg.get("language"),
            )
        except Exception as exc:
            self._set_state("loading", "Load failed!")
            _show_error(
                "GabaMic — Model Error",
                f"Failed to load the Whisper model:\n\n{exc}\n\n"
                "Check your internet connection and restart.",
            )
            return

        self._set_state("loading", "Warming up\u2026")
        self._transcriber.transcribe(np.zeros(16000, dtype=np.float32))

        self._hotkey = HotkeyListener(
            on_start = self._on_hotkey_start,
            on_stop  = self._on_hotkey_stop,
            modifier = cfg.get("hotkey_modifier", "alt"),
            key      = cfg.get("hotkey_key", "s"),
        )
        self._hotkey.start()

        self._set_state("idle")

    # ------------------------------------------------------------------
    # Shared recording logic
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        """Begin capturing audio and update the UI."""
        self._recording = True
        self._recorder.start()
        self._set_state("recording")

    def _stop_recording(self) -> None:
        """Stop capturing, transcribe, inject, and update the UI."""
        self._recording = False
        audio = self._recorder.stop()

        if len(audio) == 0:
            self._set_state("idle")
            return

        self._set_state("transcribing")
        text = self._transcriber.transcribe(audio)

        if text:
            self._injector.inject(text)
            self._set_state("done", text)
            threading.Thread(target=self._reset_idle, daemon=True).start()
        else:
            self._set_state("idle")

    def _reset_idle(self) -> None:
        time.sleep(2.5)
        self._set_state("idle")

    def move_by(self, dx: int, dy: int) -> None:
        """Shift the window by (dx, dy) pixels relative to its current position."""
        self._win_x += dx
        self._win_y += dy
        if self._window:
            self._window.move(self._win_x, self._win_y)

    # ------------------------------------------------------------------
    # Click-to-toggle (called from JS via _PillApi.toggle)
    # ------------------------------------------------------------------

    def toggle_recording(self) -> None:
        """Left-click handler: start if idle, stop if recording."""
        if self._transcriber is None:
            return  # still initialising
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()

    # ------------------------------------------------------------------
    # Hotkey callbacks  (hold Alt+S to record, release to transcribe)
    # ------------------------------------------------------------------

    def _on_hotkey_start(self) -> None:
        if self._transcriber is None or self._recording:
            return
        self._start_recording()

    def _on_hotkey_stop(self) -> None:
        if not self._recording:
            return
        self._stop_recording()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        if platform.system() == "Windows":
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
        else:
            sw, sh = 1920, 1080

        x = (sw - PILL_W) // 2
        y = sh - PILL_H - 80
        self._win_x, self._win_y = x, y   # seed position tracker for drag-to-move

        self._window = webview.create_window(
            title        = _PILL_TITLE,   # hidden (frameless); used by FindWindowW for icon
            html         = _PILL_HTML,
            js_api       = _PillApi(self),
            width        = PILL_W,
            height       = PILL_H,
            x            = x,
            y            = y,
            resizable    = False,
            frameless    = True,
            on_top       = True,
            transparent  = True,          # pywebview native transparency (all platforms)
            min_size     = (PILL_W, PILL_H),
        )

        def _on_loaded():
            self._ready = True
            _set_window_icon(_PILL_TITLE)
            threading.Thread(target=self._setup, daemon=True).start()

        self._window.events.loaded += _on_loaded

        print("GabaMic starting.  Click the pill or hold Alt+S to dictate.  "
              "Right-click to quit.")

        webview.start(private_mode=False)

        if self._hotkey:
            self._hotkey.stop()


def main() -> None:
    try:
        app = GabaMicWin()
        app.run()
    except Exception as exc:
        _show_error(
            "GabaMic — Startup Error",
            f"GabaMic failed to start:\n\n{exc}\n\n"
            "Make sure all requirements are installed:\n"
            "  pip install -r requirements_win.txt",
        )
        raise


if __name__ == "__main__":
    main()
