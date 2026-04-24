"""GabaMic — Windows floating pill entry point.

Hold Alt+S anywhere to record. Release to transcribe and inject the text
into whatever application / text box is currently focused.

Requirements (in addition to the base requirements.txt):
    pip install pywebview>=4.0.2

Transparency requires WebView2, which ships by default on Windows 10 (since
KB4577586) and all versions of Windows 11.

Usage:
    python app_win.py
    Right-click the pill to quit.
"""

import ctypes
import json
import pathlib
import platform
import threading
import time

import numpy as np
import webview

from gabamic.audio import AudioRecorder
from gabamic.hotkey import HotkeyListener
from gabamic.injector import TextInjector
from gabamic.transcriber import Transcriber

CONFIG_PATH = pathlib.Path(__file__).parent / "config.json"
PILL_W, PILL_H = 240, 44

# ---------------------------------------------------------------------------
# Pill HTML  — self-contained, no external resources
# ---------------------------------------------------------------------------

_PILL_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  width: 240px; height: 44px;
  background: transparent;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.pill {
  width: 240px; height: 44px;
  background: rgba(10, 13, 24, 0.95);
  border: 1px solid rgba(0, 255, 239, 0.28);
  border-radius: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  -webkit-app-region: drag;
  user-select: none;
  cursor: default;
}

/* ── Idle: animated SVG G ──────────────────────────────────────────── */
.logo-stage {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; position: relative;
}
.aura {
  position: absolute; width: 48%; height: 82%; border-radius: 50%;
  background: radial-gradient(ellipse at center,
    rgba(0,255,239,.11) 0%, rgba(255,98,0,.07) 42%, transparent 70%);
  animation: aura 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes aura {
  0%,100% { transform: scale(.88); opacity: .45; }
  50%     { transform: scale(1.12); opacity: .9; }
}
.idle-logo-svg {
  position: relative; height: 68%; width: auto;
  animation: breathe 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes breathe {
  0%,100% {
    filter: drop-shadow(0 0 3px rgba(0,255,239,.2));
    transform: scale(.97);
  }
  50% {
    filter: drop-shadow(0 0 10px rgba(0,255,239,.55))
            drop-shadow(0 0 20px rgba(255,98,0,.28));
    transform: scale(1.03);
  }
}

/* ── Recording / transcribing / done: dot + text ──────────────────── */
.status-row {
  display: none;
  align-items: center;
  gap: 9px;
  padding: 0 18px;
  width: 100%;
}
.dot {
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
}
.dot.recording    { background: #FF6200; animation: pulse .9s ease-in-out infinite; }
.dot.transcribing { background: rgba(255,98,0,.70); animation: pulse .9s ease-in-out infinite; }
.dot.done         { background: #00FFEF; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

.status-text {
  font-size: 12.5px; font-weight: 500; color: #00FFEF;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
</style>
</head>
<body>
<div class="pill" id="pill">

  <div class="logo-stage" id="idle-view">
    <div class="aura"></div>
    <svg class="idle-logo-svg" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="g" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#00FFEF"/>
          <stop offset="100%" stop-color="#FF6200"/>
        </linearGradient>
      </defs>
      <path d="M148.8 30.4 A85 85 0 1 0 178.8 132
               L142.3 132  A53 53 0 1 1 130.4 56.6 Z
               M100 132 L100 100 L153 100
               A53 53 0 0 1 142.3 132 Z"
            fill="url(#g)"/>
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
  } else if (state === 'done') {
    const preview = text.length > 28 ? text.slice(0, 28) + '\u2026' : (text || 'Done');
    statusText.textContent = preview;
  }
}

// Right-click → quit
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
    """Exposed to JavaScript via window.pywebview.api."""

    def quit(self) -> None:
        if webview.windows:
            webview.windows[0].destroy()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


class GabaMicWin:

    def __init__(self) -> None:
        cfg = load_config()

        self._recorder = AudioRecorder(
            sample_rate           = cfg.get("sample_rate", 16000),
            silence_rms_threshold = cfg.get("silence_rms_threshold", 0.01),
            min_recording_seconds = cfg.get("min_recording_seconds", 0.5),
        )
        self._transcriber = Transcriber(
            model_size   = cfg.get("model_size", "base"),
            device       = cfg.get("device", "cpu"),
            compute_type = cfg.get("compute_type", "int8"),
            language     = cfg.get("language"),
        )
        self._injector = TextInjector()
        self._window: webview.Window | None = None
        self._ready = False

    # ------------------------------------------------------------------
    # UI helpers  (thread-safe — pywebview queues evaluate_js internally)
    # ------------------------------------------------------------------

    def _set_state(self, state: str, text: str = "") -> None:
        if self._window and self._ready:
            js = f"setState({json.dumps(state)}, {json.dumps(text)})"
            self._window.evaluate_js(js)

    # ------------------------------------------------------------------
    # Hotkey callbacks  (daemon threads)
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        self._recorder.start()
        self._set_state("recording")

    def _on_stop(self) -> None:
        audio = self._recorder.stop()

        if len(audio) == 0:
            self._set_state("idle")
            return

        self._set_state("transcribing")
        text = self._transcriber.transcribe(audio)

        if text:
            self._injector.inject(text)
            self._set_state("done", text)
            # Return to idle after 2.5 s
            threading.Thread(target=self._reset_idle, daemon=True).start()
        else:
            self._set_state("idle")

    def _reset_idle(self) -> None:
        time.sleep(2.5)
        self._set_state("idle")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        cfg = load_config()

        # Screen position: centre-bottom, above the taskbar
        if platform.system() == "Windows":
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
        else:
            sw, sh = 1920, 1080   # fallback for testing on other platforms

        x = (sw - PILL_W) // 2
        y = sh - PILL_H - 80

        # Warm up Whisper in background before first real use
        threading.Thread(
            target=lambda: self._transcriber.transcribe(
                np.zeros(16000, dtype=np.float32)
            ),
            daemon=True,
        ).start()

        # Hotkey listener (non-blocking background thread)
        hotkey = HotkeyListener(
            on_start = self._on_start,
            on_stop  = self._on_stop,
            modifier = cfg.get("hotkey_modifier", "alt"),
            key      = cfg.get("hotkey_key", "s"),
        )
        hotkey.start()

        # Create the pill window
        self._window = webview.create_window(
            title            = "",
            html             = _PILL_HTML,
            width            = PILL_W,
            height           = PILL_H,
            x                = x,
            y                = y,
            resizable        = False,
            frameless        = True,
            on_top           = True,
            background_color = "#00000000",
            min_size         = (PILL_W, PILL_H),
        )

        def _on_loaded():
            self._ready = True

        self._window.events.loaded += _on_loaded

        print("GabaMic pill started.  Hold Alt+S to dictate.  Right-click to quit.")

        # Start pywebview — blocks until the window is closed
        webview.start(api=_PillApi(), private_mode=False)

        hotkey.stop()


def main() -> None:
    app = GabaMicWin()
    app.run()


if __name__ == "__main__":
    main()
