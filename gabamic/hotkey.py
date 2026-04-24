"""Global hotkey listener for GabaMic.

Listens for a configurable modifier+key combination and fires start/stop
callbacks without requiring focus on any particular window.
"""

import threading

from pynput.keyboard import Key, Listener

# Maps config string names to the set of pynput Key variants to watch.
# Left/right variants are included so any physical key triggers the combo.
_MODIFIER_MAP: dict[str, tuple] = {
    "alt":   (Key.alt,   Key.alt_l,   Key.alt_r),
    "ctrl":  (Key.ctrl,  Key.ctrl_l,  Key.ctrl_r),
    "shift": (Key.shift, Key.shift_l, Key.shift_r),
    "cmd":   (Key.cmd,   Key.cmd_l,   Key.cmd_r),
}


class HotkeyListener:
    """Listens for a modifier+key hotkey and fires start/stop callbacks.

    Args:
        on_start:  Called (in a daemon thread) when the hotkey is pressed.
        on_stop:   Called (in a daemon thread) when the hotkey is released.
        modifier:  Modifier key: ``"alt"``, ``"ctrl"``, ``"shift"``, or ``"cmd"``.
                   Defaults to ``"alt"``.
        key:       Trigger key character, e.g. ``"s"`` or ``"r"``.
                   Defaults to ``"s"``.
    """

    def __init__(
        self,
        on_start,
        on_stop,
        modifier: str = "alt",
        key: str = "s",
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._modifier_variants = _MODIFIER_MAP.get(modifier.lower(), _MODIFIER_MAP["alt"])
        self._trigger_char = key.lower()
        self._held: set = set()
        self._recording = False
        self._listener: Listener | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background keyboard listener (non-blocking)."""
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.start()

    def stop(self) -> None:
        """Stop the background keyboard listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_modifier(self, key) -> bool:
        return key in self._modifier_variants

    def _is_trigger(self, key) -> bool:
        return (
            hasattr(key, "char")
            and key.char is not None
            and key.char.lower() == self._trigger_char
        )

    def _combo_active(self) -> bool:
        return any(self._is_modifier(k) for k in self._held) and any(
            self._is_trigger(k) for k in self._held
        )

    def _on_press(self, key) -> None:
        try:
            self._held.add(key)
            if self._combo_active() and not self._recording:
                self._recording = True
                threading.Thread(target=self._on_start, daemon=True).start()
        except Exception:
            pass

    def _on_release(self, key) -> None:
        try:
            self._held.discard(key)
            if self._recording and not self._combo_active():
                self._recording = False
                threading.Thread(target=self._on_stop, daemon=True).start()
        except Exception:
            pass
