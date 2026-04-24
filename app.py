"""GabaMic — macOS menu bar entry point.

Hold Alt+S to record, release to transcribe and inject the text.

Visual feedback:
  • Menu bar icon — 🎙 idle · 🔴 recording · ⏳ transcribing
  • Floating HUD   — pill overlay (turquoise / orange theme) shown on screen
                     during recording/transcription, auto-hides 2.5 s after
                     the text is injected.

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

LANGUAGE_CYCLE = [
    (None, "Auto-detect"),
    ("en", "English"),
    ("es", "Spanish"),
]

# Theme colours (normalised 0-1)
_TEAL   = (0.000, 1.000, 0.937, 1.0)   # #00FFEF
_ORANGE = (1.000, 0.384, 0.000, 1.0)   # #FF6200
_ORANGE_DIM = (1.000, 0.384, 0.000, 0.70)

# SVG G-logo rendered into a WKWebView — transparent background, no PNG artefacts.
_LOGO_SVG_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{
  margin:0;padding:0;width:100%;height:100%;
  background:transparent;overflow:hidden;
  display:flex;align-items:center;justify-content:center;
  -webkit-app-region:drag;
}
.aura{
  position:absolute;width:55%;height:85%;border-radius:50%;
  background:radial-gradient(ellipse at center,
    rgba(0,255,239,.11) 0%,rgba(255,98,0,.07) 42%,transparent 70%);
  animation:aura 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events:none;
}
@keyframes aura{0%,100%{transform:scale(.88);opacity:.45}50%{transform:scale(1.12);opacity:.9}}
svg{
  position:relative;height:68%;width:auto;
  animation:breathe 3.5s cubic-bezier(.45,0,.55,1) infinite;
  pointer-events:none;
}
@keyframes breathe{
  0%,100%{filter:drop-shadow(0 0 3px rgba(0,255,239,.2));transform:scale(.97)}
  50%{filter:drop-shadow(0 0 10px rgba(0,255,239,.55))
           drop-shadow(0 0 20px rgba(255,98,0,.28));transform:scale(1.03)}
}
</style>
</head>
<body>
<div class="aura"></div>
<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
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
    """

    W, H   = 240, 44
    CORNER = 22          # full pill = H / 2
    DOT_SZ = 10
    FONT   = 12.5

    _LABELS = {
        "recording":    "Recording…",
        "transcribing": "Transcribing…",
    }

    def __init__(self) -> None:
        from AppKit import (
            NSPanel, NSScreen, NSColor, NSTextField, NSView, NSFont,
            NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, NSFontWeightMedium, NSFloatingWindowLevel,
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
        panel.setMovableByWindowBackground_(True)   # drag anywhere to reposition
        self._panel = panel

        # ── Dark pill background via CALayer ──────────────────────────────
        content = panel.contentView()
        content.setWantsLayer_(True)
        layer = content.layer()
        # #0A0D18 at 95 % opacity
        bg = NSColor.colorWithRed_green_blue_alpha_(0.039, 0.051, 0.094, 0.95)
        layer.setBackgroundColor_(bg.CGColor())
        layer.setCornerRadius_(self.CORNER)
        # Turquoise border glow
        teal = NSColor.colorWithRed_green_blue_alpha_(*_TEAL[:3], 0.28)
        layer.setBorderColor_(teal.CGColor())
        layer.setBorderWidth_(1.0)

        # ── SVG G logo via WKWebView (idle state, transparent background) ────
        wk_cfg = WKWebViewConfiguration.alloc().init()
        wk_view = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.W, self.H), wk_cfg
        )
        wk_view.setOpaque_(False)
        wk_view.setBackgroundColor_(NSColor.clearColor())
        wk_view.loadHTMLString_baseURL_(_LOGO_SVG_HTML, None)
        wk_view.setHidden_(True)   # shown only in idle state
        content.addSubview_(wk_view)
        self._logo_view = wk_view

        # ── Coloured state dot ────────────────────────────────────────────
        dot_x = 18
        dot_y = (self.H - self.DOT_SZ) / 2
        self._dot = NSView.alloc().initWithFrame_(
            NSMakeRect(dot_x, dot_y, self.DOT_SZ, self.DOT_SZ)
        )
        self._dot.setWantsLayer_(True)
        self._dot.layer().setCornerRadius_(self.DOT_SZ / 2)
        self._dot.setHidden_(True)
        content.addSubview_(self._dot)

        # ── Status text label (vertically centred) ────────────────────────
        lbl_x = dot_x + self.DOT_SZ + 9
        lbl_h = 18
        lbl_y = (self.H - lbl_h) / 2
        self._label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(lbl_x, lbl_y, self.W - lbl_x - 14, lbl_h)
        )
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setBordered_(False)
        self._label.setDrawsBackground_(False)
        # Turquoise text
        self._label.setTextColor_(
            NSColor.colorWithRed_green_blue_alpha_(*_TEAL)
        )
        self._label.setFont_(
            NSFont.systemFontOfSize_weight_(self.FONT, NSFontWeightMedium)
        )
        self._label.setHidden_(True)
        content.addSubview_(self._label)

        # Start visible in idle state (pill is always on screen)
        panel.orderFront_(None)

    # ── Public interface (main thread only) ───────────────────────────────

    def show(self, state: str, text: str = "") -> None:
        from AppKit import NSColor

        if state == "idle":
            # Logo visible, dot + label hidden
            self._logo_view.setHidden_(False)
            self._dot.setHidden_(True)
            self._label.setHidden_(True)
            self._panel.orderFront_(None)
            return

        # All other states: hide logo, show dot + label
        self._logo_view.setHidden_(True)
        self._dot.setHidden_(False)
        self._label.setHidden_(False)

        # Dot colour: orange while working, turquoise when done
        if state == "done":
            r, g, b, a = _TEAL
        elif state == "transcribing":
            r, g, b, a = _ORANGE_DIM
        else:
            r, g, b, a = _ORANGE

        self._dot.layer().setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).CGColor()
        )

        if state == "done":
            preview = (text[:36] + "…") if len(text) > 36 else (text or "Done")
            self._label.setStringValue_(preview)
        else:
            self._label.setStringValue_(self._LABELS.get(state, ""))

        self._panel.orderFront_(None)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class GabaMicApp(rumps.App):

    def __init__(self) -> None:
        super().__init__("🎙", quit_button=None)

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

        # Floating HUD (created on main thread — safe to do AppKit ops here)
        try:
            self._overlay: _OverlayPanel | None = _OverlayPanel()
            self._overlay.show("idle", "")   # visible immediately with logo
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
            self.title = "🎙"
            self._set_status("Idle")
            self._overlay_cmds.put(("idle", ""))   # return to logo
            return

        self.title = "⏳"
        self._set_status("Transcribing")
        self._overlay_cmds.put(("transcribing", ""))

        text = self._transcriber.transcribe(audio)

        self.title = "🎙"
        self._set_status("Idle")

        if text:
            self._injector.inject(text)
            self._overlay_cmds.put(("done", text))
        else:
            self._overlay_cmds.put(("idle", ""))   # return to logo

    # ------------------------------------------------------------------
    # Overlay ticker — fires on the main AppKit thread every 100 ms
    # ------------------------------------------------------------------

    @rumps.timer(0.1)
    def _overlay_tick(self, _sender) -> None:
        if self._overlay is None:
            return

        # Drain the command queue
        while not self._overlay_cmds.empty():
            state, text = self._overlay_cmds.get_nowait()
            self._overlay.show(state, text)
            self._hide_at = (time.monotonic() + 2.5) if state == "done" else None

        # After the "done" preview window expires, return to idle (show logo)
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
