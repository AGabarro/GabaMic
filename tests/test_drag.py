"""Tests for the pill drag-to-move functionality (app_win.start_drag / _drag_loop).

All Win32 calls are mocked so the suite runs on macOS and Linux as well as
Windows.

The drag uses a cursor-tracking loop (not WM_NCLBUTTONDOWN) because pywebview
frameless windows are WS_POPUP without WS_CAPTION — DefWindowProc ignores
HTCAPTION and never starts its built-in drag loop.  Instead:
  1. start_drag() snapshots cursor + window position, starts _drag_loop thread.
  2. _drag_loop() polls GetCursorPos / GetAsyncKeyState and calls SetWindowPos
     until the left button is released.
"""

import ctypes
import sys
import threading
import time
from unittest.mock import MagicMock, patch

# pywebview (import webview) is a Windows-only dependency absent from the
# macOS/Linux venv.  Stub it before app_win is imported.
sys.modules.setdefault("webview", MagicMock())

import app_win
from app_win import GabaMicWin, _PillApi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_HWND = 0xABCD
_SWP_FLAGS = 0x0001 | 0x0004 | 0x0010   # NOSIZE | NOZORDER | NOACTIVATE


def _make_app(hwnd=_FAKE_HWND, dragging=False):
    """Bare GabaMicWin with only drag-relevant attributes set."""
    app = GabaMicWin.__new__(GabaMicWin)
    app._hwnd    = hwnd
    app._dragging = dragging
    return app


def _mock_user32_with_key_state(held_iterations):
    """Return a mock user32 where GetAsyncKeyState returns button-held for
    exactly `held_iterations` calls, then 0 (button released)."""
    mock_u32 = MagicMock()
    remaining = [held_iterations]

    def fake_key_state(_vk):
        if remaining[0] > 0:
            remaining[0] -= 1
            return 0x8000   # button held
        return 0            # button released

    mock_u32.GetAsyncKeyState.side_effect = fake_key_state
    return mock_u32


# ---------------------------------------------------------------------------
# start_drag() — guard conditions
# ---------------------------------------------------------------------------

def test_start_drag_no_op_when_hwnd_is_zero():
    """start_drag() must not set _dragging or spawn a thread when hwnd == 0."""
    app = _make_app(hwnd=0)
    app.start_drag()
    assert not app._dragging


def test_start_drag_no_op_when_already_dragging():
    """A second start_drag() while a drag is in progress must be ignored."""
    app = _make_app(dragging=True)
    calls = []
    app._drag_loop = lambda: calls.append(1)
    app.start_drag()
    time.sleep(0.05)
    assert calls == [], "_drag_loop must not start when _dragging is already True"


def test_start_drag_sets_dragging_flag_and_starts_loop():
    """start_drag() must set _dragging=True and run _drag_loop in a thread."""
    app = _make_app()
    loop_ran = threading.Event()

    def fake_loop():
        loop_ran.set()

    app._drag_loop = fake_loop
    app.start_drag()
    assert app._dragging, "_dragging must be True immediately after start_drag()"
    assert loop_ran.wait(timeout=1.0), "_drag_loop was not called within 1 s"


# ---------------------------------------------------------------------------
# _drag_loop() — Win32 call contract
# ---------------------------------------------------------------------------

def test_drag_loop_calls_set_window_pos_each_iteration():
    """SetWindowPos must be called once per held-button iteration."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = _mock_user32_with_key_state(held_iterations=3)
        app = _make_app()
        app._drag_loop()

    assert mock_windll.user32.SetWindowPos.call_count == 3


def test_drag_loop_set_window_pos_uses_correct_hwnd_and_flags():
    """SetWindowPos must receive the cached hwnd, nInsertAfter=0, and SWP flags."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = _mock_user32_with_key_state(held_iterations=1)
        app = _make_app(hwnd=0x5678)
        app._drag_loop()

    pos_args = mock_windll.user32.SetWindowPos.call_args[0]
    assert pos_args[0] == 0x5678, f"Wrong hwnd: {pos_args[0]:#x}"
    assert pos_args[1] == 0,      "nInsertAfter should be 0"
    assert pos_args[4] == 0,      "cx must be 0 (SWP_NOSIZE)"
    assert pos_args[5] == 0,      "cy must be 0 (SWP_NOSIZE)"
    assert pos_args[6] == _SWP_FLAGS, f"Wrong flags: {pos_args[6]:#x}"


def test_drag_loop_stops_immediately_when_button_already_released():
    """If the button is up when the loop starts, SetWindowPos is never called."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = _mock_user32_with_key_state(held_iterations=0)
        app = _make_app()
        app._drag_loop()

    mock_windll.user32.SetWindowPos.assert_not_called()


# ---------------------------------------------------------------------------
# _drag_loop() — resilience
# ---------------------------------------------------------------------------

def test_drag_loop_resets_dragging_flag_on_normal_exit():
    """_dragging must be False after _drag_loop completes normally."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = _mock_user32_with_key_state(held_iterations=0)
        app = _make_app()
        app._dragging = True
        app._drag_loop()
    assert not app._dragging


def test_drag_loop_resets_dragging_flag_on_exception():
    """_dragging must be False even when _drag_loop raises an exception."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32.GetCursorPos.side_effect = OSError("simulated Win32 error")
        app = _make_app()
        app._dragging = True
        app._drag_loop()   # must not propagate
    assert not app._dragging


# ---------------------------------------------------------------------------
# JS → Python bridge delegation
# ---------------------------------------------------------------------------

def test_pill_api_start_drag_delegates_to_app():
    """_PillApi.start_drag() must call GabaMicWin.start_drag() exactly once."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.start_drag()
    mock_app.start_drag.assert_called_once_with()


# ---------------------------------------------------------------------------
# Concurrency guard
# ---------------------------------------------------------------------------

def test_only_one_drag_loop_runs_at_a_time():
    """Concurrent start_drag() calls must result in exactly one running loop."""
    loop_starts = []
    done = threading.Event()

    def fake_loop(self_app):
        loop_starts.append(1)
        done.wait(timeout=0.5)
        self_app._dragging = False

    app = _make_app()

    with patch.object(GabaMicWin, "_drag_loop", fake_loop):
        threads = [threading.Thread(target=app.start_drag) for _ in range(6)]
        for t in threads:
            t.start()
        time.sleep(0.05)
        done.set()
        for t in threads:
            t.join()

    assert len(loop_starts) == 1, f"Expected 1 loop, got {len(loop_starts)}"
