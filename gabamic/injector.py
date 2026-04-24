"""Text injection module for GabaMic.

Pastes text into the currently focused application by temporarily
replacing the clipboard and simulating the OS paste shortcut.
"""

import platform
import time

import pyperclip
from pynput.keyboard import Controller, Key

# macOS uses Cmd+V; Windows and Linux use Ctrl+V.
_PASTE_KEY = Key.cmd if platform.system() == "Darwin" else Key.ctrl


class TextInjector:
    """Injects text into the focused application via clipboard + paste shortcut.

    Works on macOS (Cmd+V), Windows (Ctrl+V), and Linux (Ctrl+V).
    """

    def __init__(self) -> None:
        self._keyboard = Controller()

    def inject(self, text: str) -> None:
        """Paste *text* into the currently focused application.

        Copies text to the clipboard, simulates the OS paste shortcut, then
        leaves the transcribed text in the clipboard so the user can paste it
        again wherever they like.

        Args:
            text: The string to inject. If empty, returns immediately.
        """
        if not text:
            return

        pyperclip.copy(text)
        time.sleep(0.05)
        self._keyboard.press(_PASTE_KEY)
        self._keyboard.press("v")
        self._keyboard.release("v")
        self._keyboard.release(_PASTE_KEY)
        time.sleep(0.1)
        # text intentionally left in clipboard so the user can paste it again
