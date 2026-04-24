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
PILL_W, PILL_H = 170, 34


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
  width: 170px; height: 34px;
  background: #080B14;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.pill {
  width: 170px; height: 34px;
  background: rgba(8, 11, 20, 0.96);
  border: 1px solid rgba(0, 255, 239, 0.25);
  border-radius: 17px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  user-select: none;
  cursor: pointer;
  transition: border-color 0.18s;
}
.pill:hover  { border-color: rgba(0, 255, 239, 0.50); }
.pill:active { border-color: rgba(0, 255, 239, 0.75); }

/* ── Idle: animated GabaMic logo ─────────────────────────────────── */
.logo-stage {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; position: relative;
}
.aura {
  position: absolute; width: 44%; height: 80%; border-radius: 50%;
  background: radial-gradient(ellipse at center,
    rgba(0,255,239,.13) 0%, rgba(255,98,0,.07) 42%, transparent 70%);
  animation: aura 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes aura {
  0%,100% { transform: scale(.88); opacity: .45; }
  50%     { transform: scale(1.12); opacity: .9; }
}
.logo-svg {
  position: relative; height: 60%; width: auto;
  animation: breathe 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes breathe {
  0%,100% {
    filter: drop-shadow(0 0 3px rgba(0,255,239,.25));
    transform: scale(.97);
  }
  50% {
    filter: drop-shadow(0 0 9px rgba(0,255,239,.55))
            drop-shadow(0 0 20px rgba(255,98,0,.28));
    transform: scale(1.04);
  }
}

/* ── Status row (recording / transcribing / loading / done) ────────── */
.status-row {
  display: none;
  align-items: center;
  gap: 7px;
  padding: 0 14px;
  width: 100%;
}
.dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.dot.recording    { background: #FF6200; animation: pulse .9s ease-in-out infinite; }
.dot.transcribing { background: rgba(255,98,0,.70); animation: pulse .9s ease-in-out infinite; }
.dot.loading      { background: rgba(0,255,239,.50); animation: pulse 1.4s ease-in-out infinite; }
.dot.done         { background: #00FFEF; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

.status-text {
  font-size: 11px; font-weight: 500; color: #00FFEF;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
</style>
</head>
<body>
<div class="pill" id="pill">

  <div class="logo-stage" id="idle-view">
    <div class="aura"></div>
    <svg class="logo-svg" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="g" x1="15" y1="185" x2="185" y2="15"
                        gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#00FFEF"/>
          <stop offset="100%" stop-color="#FF6200"/>
        </linearGradient>
      </defs>
      <circle cx="100" cy="100" r="69"
              fill="none" stroke="url(#g)" stroke-width="32"
              stroke-dasharray="361.3 72.3"/>
      <rect x="100" y="84" width="85" height="32" fill="url(#g)"/>
    </svg>
  </div>

  <div class="status-row" id="status-view">
    <div class="dot" id="dot"></div>
    <span class="status-text" id="status-text"></span>
  </div>

</div>

<script>
'use strict';

function setState(state, text) {
  const idleView   = document.getElementById('idle-view');
  const statusView = document.getElementById('status-view');
  const dot        = document.getElementById('dot');
  const statusText = document.getElementById('status-text');

  if (state === 'idle') {
    idleView.style.display   = 'flex';
    statusView.style.display = 'none';
    return;
  }

  idleView.style.display   = 'none';
  statusView.style.display = 'flex';
  dot.className = 'dot ' + state;

  if (state === 'recording') {
    statusText.textContent = 'Recording\u2026';
  } else if (state === 'transcribing') {
    statusText.textContent = 'Transcribing\u2026';
  } else if (state === 'loading') {
    statusText.textContent = text || 'Setting up\u2026';
  } else if (state === 'done') {
    const preview = text.length > 20 ? text.slice(0, 20) + '\u2026' : (text || 'Done');
    statusText.textContent = preview;
  }
}

// Left-click: toggle recording
document.getElementById('pill').addEventListener('click', () => {
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.toggle();
  }
});

// Right-click: quit
document.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.quit();
  }
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

        self._window = webview.create_window(
            title            = "",
            html             = _PILL_HTML,
            js_api           = _PillApi(self),
            width            = PILL_W,
            height           = PILL_H,
            x                = x,
            y                = y,
            resizable        = False,
            frameless        = True,
            on_top           = True,
            background_color = "#080B14",
            min_size         = (PILL_W, PILL_H),
        )

        def _on_loaded():
            self._ready = True
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
