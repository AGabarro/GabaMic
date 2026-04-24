"""GabaMic — macOS menu bar entry point.

Hold Alt+S to record, release to transcribe and inject the text.

Visual feedback:
  • Menu bar icon — 🎙 idle · 🔴 recording · ⏳ transcribing
  • Floating HUD   — always-on-top pill (turquoise / orange theme)
                     Drag it anywhere on screen to reposition.
                     Auto-hides 2.5 s after text is injected, then returns
                     to the idle animated logo.

Colour palette:
  Turquoise  #00FFEF  — idle / done indicator, text, border glow
  Orange     #FF6200  — recording / transcribing indicator
"""

import json
import pathlib
import queue
import threading
import time

import numpy as np
import rumps

from gabamic.audio import AudioRecorder
from gabamic.hotkey import HotkeyListener
from gabamic.injector import TextInjector
from gabamic.transcriber import Transcriber

CONFIG_PATH = pathlib.Path(__file__).parent / "config.json"
_ICON_PATH  = pathlib.Path(__file__).parent / "GabaMic.png"

LANGUAGE_CYCLE = [
    (None, "Auto-detect"),
    ("en", "English"),
    ("es", "Spanish"),
]

# Theme colours (normalised 0–1 for AppKit; hex for CSS)
_TEAL = (0.000, 1.000, 0.937, 1.0)   # #00FFEF


# ---------------------------------------------------------------------------
# Pill HTML — all states rendered by JavaScript; body is a drag region
# ---------------------------------------------------------------------------

_PILL_HTML_MAC = """\
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
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased;
  /* The entire pill surface initiates a window drag on macOS. */
  -webkit-app-region: drag;
  user-select: none;
}

/* ── Idle: animated G logo ──────────────────────────────────────── */
#idle-view {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 100%; position: relative;
}
.aura {
  position: absolute; width: 42%; height: 78%; border-radius: 50%;
  background: radial-gradient(ellipse at center,
    rgba(0,255,239,.13) 0%, rgba(255,98,0,.06) 45%, transparent 70%);
  animation: aura 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes aura {
  0%,100% { transform: scale(.88); opacity: .50; }
  50%     { transform: scale(1.12); opacity: .95; }
}
.logo-svg {
  position: relative; height: 64%; width: auto;
  animation: breathe 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events: none;
}
@keyframes breathe {
  0%,100% {
    filter: drop-shadow(0 0 2px rgba(0,255,239,.32));
    transform: scale(.97);
  }
  50% {
    filter: drop-shadow(0 0 7px rgba(0,255,239,.70))
            drop-shadow(0 0 16px rgba(0,255,239,.28));
    transform: scale(1.04);
  }
}

/* ── Status row (recording / transcribing / done) ────────────────── */
#status-view {
  display: none;
  align-items: center;
  gap: 8px;
  padding: 0 20px;
  width: 100%;
}

/* Waveform bars — recording */
.waveform { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.wbar {
  width: 2.5px; border-radius: 2px;
  background: #FF6200;
  box-shadow: 0 0 3px rgba(255,98,0,.85);
}
.wbar:nth-child(1) { animation: wave .88s ease-in-out -0.38s infinite; }
.wbar:nth-child(2) { animation: wave .88s ease-in-out -0.18s infinite; }
.wbar:nth-child(3) { animation: wave .88s ease-in-out  0.02s infinite; }
.wbar:nth-child(4) { animation: wave .88s ease-in-out -0.28s infinite; }
@keyframes wave {
  0%,100% { height: 4px;  opacity: .60; }
  50%     { height: 12px; opacity: 1.0; }
}

/* State dot */
.dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.dot.transcribing {
  background: rgba(255,98,0,.80);
  animation: pulse .88s ease-in-out infinite;
}
.dot.done { background: #00FFEF; box-shadow: 0 0 5px rgba(0,255,239,.65); }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.28} }

/* Status label */
.status-text {
  font-size: 12px; font-weight: 500; letter-spacing: 0.1px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: #00FFEF;
}
.status-text.rec { color: #FF7030; }
.status-text.trx { color: rgba(255,135,55,.88); }
</style>
</head>
<body>

<div id="idle-view">
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

<div id="status-view">
  <div class="waveform" id="waveform">
    <div class="wbar"></div><div class="wbar"></div>
    <div class="wbar"></div><div class="wbar"></div>
  </div>
  <div class="dot" id="dot"></div>
  <span class="status-text" id="status-text"></span>
</div>

<script>
'use strict';
const idleView   = document.getElementById('idle-view');
const statusView = document.getElementById('status-view');
const waveform   = document.getElementById('waveform');
const dot        = document.getElementById('dot');
const statusText = document.getElementById('status-text');

function setState(state, text) {
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
    waveform.style.display = 'flex';
    dot.style.display      = 'none';
    statusText.textContent = 'Recording\u2026';
    statusText.className   = 'status-text rec';
  } else if (state === 'transcribing') {
    dot.className          = 'dot transcribing';
    statusText.textContent = 'Transcribing\u2026';
    statusText.className   = 'status-text trx';
  } else if (state === 'done') {
    dot.className = 'dot done';
    const preview = text && text.length > 22
      ? text.slice(0, 22) + '\u2026' : (text || 'Done');
    statusText.textContent = preview;
    statusText.className   = 'status-text';
  }
}
</script>
</body>
</html>"""


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------------------------------------------------------------------------
# Floating HUD overlay (NSPanel — AppKit / PyObjC via rumps dependency)
# ---------------------------------------------------------------------------

class _OverlayPanel:
    """Borderless, always-on-top pill HUD that mirrors recording state.

    All public methods MUST be called from the main AppKit thread
    (i.e. inside a @rumps.timer callback or __init__).

    Drag: the WKWebView HTML body has ``-webkit-app-region: drag``, which
    forwards any drag gesture to the NSPanel as a native window move — no
    Win32-style cursor tracking needed on macOS.
    """

    W, H   = 240, 44
    CORNER = 22          # full pill = H / 2

    def __init__(self) -> None:
        from AppKit import (
            NSPanel, NSScreen, NSColor,
            NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, NSFloatingWindowLevel,
        )
        from Foundation import NSMakeRect
        from WebKit import WKWebView, WKWebViewConfiguration

        # Centre-bottom of the main screen (above the Dock)
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width  - self.W) / 2
        y = screen.origin.y + 108
        rect = NSMakeRect(x, y, self.W, self.H)

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        panel.setLevel_(NSFloatingWindowLevel + 2)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(False)
        # Fallback drag for any edge-case where WKWebView doesn't handle the event.
        panel.setMovableByWindowBackground_(True)
        self._panel = panel

        # ── Dark pill background via CALayer ──────────────────────────────
        content = panel.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        # #0A0D18 at 95 % opacity
        bg = NSColor.colorWithRed_green_blue_alpha_(0.039, 0.051, 0.094, 0.95)
        layer.setBackgroundColor_(bg.CGColor())
        layer.setCornerRadius_(self.CORNER)
        # Turquoise border
        teal_a = NSColor.colorWithRed_green_blue_alpha_(*_TEAL[:3], 0.28)
        layer.setBorderColor_(teal_a.CGColor())
        layer.setBorderWidth_(1.0)

        # ── Single WKWebView — renders all states, enables drag ───────────
        # Transparent background: the CALayer above provides the dark pill.
        wk_cfg  = WKWebViewConfiguration.alloc().init()
        wk_view = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.W, self.H), wk_cfg
        )
        wk_view.setOpaque_(False)
        wk_view.setBackgroundColor_(NSColor.clearColor())
        wk_view.loadHTMLString_baseURL_(_PILL_HTML_MAC, None)
        content.addSubview_(wk_view)
        self._wk_view = wk_view

        panel.orderFront_(None)

    # ── Public interface (main thread only) ───────────────────────────────

    def show(self, state: str, text: str = "") -> None:
        try:
            js = f"setState({json.dumps(state)}, {json.dumps(text)})"
            self._wk_view.evaluateJavaScript_completionHandler_(js, None)
        except Exception:
            pass
        self._panel.orderFront_(None)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class GabaMicApp(rumps.App):

    def __init__(self) -> None:
        icon = str(_ICON_PATH) if _ICON_PATH.exists() else None
        super().__init__("GabaMic", icon=icon, template=False, quit_button=None)

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

        # Language cycle
        current_lang     = cfg.get("language")
        self._lang_index = next(
            (i for i, (code, _) in enumerate(LANGUAGE_CYCLE) if code == current_lang),
            0,
        )

        # Menu
        self._status_item = rumps.MenuItem("Status: Idle", callback=None)
        self._lang_item   = rumps.MenuItem(
            f"Language: {LANGUAGE_CYCLE[self._lang_index][1]}",
            callback=self._cycle_language,
        )
        self.menu = [
            self._status_item,
            None,
            self._lang_item,
            None,
            rumps.MenuItem("Quit GabaMic", callback=lambda _: rumps.quit_application()),
        ]

        # Floating HUD (created on main thread — AppKit requires this)
        try:
            self._overlay: _OverlayPanel | None = _OverlayPanel()
            self._overlay.show("idle", "")
        except Exception:
            self._overlay = None   # graceful fallback when no display

        # Thread-safe command queue
        # Producer: daemon threads (_on_start / _on_stop)
        # Consumer: main-thread timer (_overlay_tick)
        self._overlay_cmds: queue.Queue = queue.Queue()
        self._hide_at: float | None     = None

        # Warm up Whisper in background before first real use
        threading.Thread(target=self._warmup, daemon=True).start()

        # Hotkey listener (non-blocking background thread)
        self._hotkey = HotkeyListener(
            on_start=self._on_start,
            on_stop=self._on_stop,
            modifier=cfg.get("hotkey_modifier", "alt"),
            key=cfg.get("hotkey_key", "s"),
        )
        self._hotkey.start()

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def _warmup(self) -> None:
        self._transcriber.transcribe(np.zeros(16000, dtype=np.float32))

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _set_status(self, label: str) -> None:
        self._status_item.title = f"Status: {label}"

    # ------------------------------------------------------------------
    # Hotkey callbacks  (daemon threads — no AppKit calls here)
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        self.title = "🔴"
        self._set_status("Recording")
        self._recorder.start()
        self._overlay_cmds.put(("recording", ""))

    def _on_stop(self) -> None:
        audio = self._recorder.stop()

        if len(audio) == 0:
            self.title = None
            self._set_status("Idle")
            self._overlay_cmds.put(("idle", ""))
            return

        self.title = "⏳"
        self._set_status("Transcribing")
        self._overlay_cmds.put(("transcribing", ""))

        text = self._transcriber.transcribe(audio)

        self.title = None
        self._set_status("Idle")

        if text:
            self._injector.inject(text)
            self._overlay_cmds.put(("done", text))
        else:
            self._overlay_cmds.put(("idle", ""))

    # ------------------------------------------------------------------
    # Overlay ticker — fires on the main AppKit thread every 100 ms
    # ------------------------------------------------------------------

    @rumps.timer(0.1)
    def _overlay_tick(self, _sender) -> None:
        if self._overlay is None:
            return

        while not self._overlay_cmds.empty():
            state, text = self._overlay_cmds.get_nowait()
            self._overlay.show(state, text)
            self._hide_at = (time.monotonic() + 2.5) if state == "done" else None

        if self._hide_at is not None and time.monotonic() >= self._hide_at:
            self._overlay.show("idle", "")
            self._hide_at = None

    # ------------------------------------------------------------------
    # Language toggle
    # ------------------------------------------------------------------

    def _cycle_language(self, _sender) -> None:
        self._lang_index       = (self._lang_index + 1) % len(LANGUAGE_CYCLE)
        code, label            = LANGUAGE_CYCLE[self._lang_index]
        self._lang_item.title  = f"Language: {label}"
        self._transcriber.language = code

        cfg = load_config()
        cfg["language"] = code
        save_config(cfg)


if __name__ == "__main__":
    GabaMicApp().run()
