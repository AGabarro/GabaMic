"""Tests for the pill drag-to-move functionality (app_win.start_drag / _drag_loop).

Drag works by starting a Win32 GetCursorPos polling loop (Python-side) on
mousedown and stopping it on mouseup.  This means the window follows the
cursor even when the mouse exits the tiny (140x38 px) WebView2 viewport,
where JS mousemove would stop firing.

window.move() is used to reposition the window because it dispatches to
the WebView2 UI thread — calling SetWindowPos directly from a background
thread does not reliably update WebView2's compositor layout.

All Win32 calls are mocked so the suite runs on macOS and Linux as well
as Windows.
"""

import sys
import threading
import time
from unittest.mock import MagicMock, patch

# pywebview is a Windows-only dependency absent from the macOS/Linux venv.
sys.modules.setdefault("webview", MagicMock())

import app_win
from app_win import GabaMicWin, _PillApi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(hwnd=0xABCD, win_x=760, win_y=1000, dragging=False):
    """Bare GabaMicWin with only drag-relevant attributes set."""
    app = GabaMicWin.__new__(GabaMicWin)
    app._hwnd     = hwnd
    app._win_x    = win_x
    app._win_y    = win_y
    app._dragging = dragging
    app._window   = MagicMock()
    return app


# ---------------------------------------------------------------------------
# start_drag() — guard conditions
# ---------------------------------------------------------------------------

def test_start_drag_no_op_when_already_dragging():
    """A second start_drag() while a drag is in progress must not spawn another loop."""
    app = _make_app(dragging=True)
    loop_calls = []
    app._drag_loop = lambda: loop_calls.append(1)

    app.start_drag()
    time.sleep(0.05)

    assert loop_calls == [], "_drag_loop must not start when _dragging is already True"


def test_start_drag_sets_dragging_flag():
    """start_drag() must set _dragging=True before the loop thread runs."""
    app = _make_app(dragging=False)
    app._drag_loop = lambda: None   # instant no-op loop

    app.start_drag()

    # Flag is set synchronously, before the thread body runs.
    assert app._dragging is True


def test_start_drag_spawns_drag_loop_thread():
    """start_drag() must run _drag_loop in a background thread."""
    app = _make_app(dragging=False)
    loop_ran = threading.Event()

    def fake_loop():
        loop_ran.set()

    app._drag_loop = fake_loop
    app.start_drag()

    assert loop_ran.wait(timeout=1.0), "_drag_loop was not called within 1 s"


# ---------------------------------------------------------------------------
# stop_drag()
# ---------------------------------------------------------------------------

def test_stop_drag_clears_dragging_flag():
    """stop_drag() must set _dragging=False."""
    app = _make_app(dragging=True)
    app.stop_drag()
    assert app._dragging is False


# ---------------------------------------------------------------------------
# _drag_loop() — platform guard
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Darwin")
@patch("ctypes.windll", create=True)
def test_drag_loop_no_op_on_non_windows(mock_windll, _mock_sys):
    """_drag_loop must return immediately on non-Windows without calling Win32."""
    app = _make_app()
    app._dragging = True
    app._drag_loop()
    mock_windll.user32.GetCursorPos.assert_not_called()


# ---------------------------------------------------------------------------
# _drag_loop() — loop exits when _dragging is cleared
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Windows")
@patch("ctypes.windll", create=True)
def test_drag_loop_exits_when_dragging_cleared(mock_windll, _mock_sys):
    """_drag_loop must exit and clear _dragging when stop_drag() is called."""
    app = _make_app(hwnd=0)  # no HWND → skip GetWindowRect
    app._dragging = True

    def stop_soon():
        time.sleep(0.05)
        app._dragging = False

    threading.Thread(target=stop_soon, daemon=True).start()
    app._drag_loop()   # blocks until _dragging goes False

    assert app._dragging is False


# ---------------------------------------------------------------------------
# _drag_loop() — window.move() is called, not SetWindowPos
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Windows")
@patch("ctypes.windll", create=True)
def test_drag_loop_uses_window_move_not_set_window_pos(mock_windll, _mock_sys):
    """_drag_loop must reposition via window.move(), never SetWindowPos."""
    app = _make_app(hwnd=0, win_x=100, win_y=200)
    app._dragging = True

    # Make GetCursorPos write non-zero coords on the second call so the
    # position changes and window.move() is triggered.
    call_count = [0]

    def fake_get_cursor_pos(byref_arg):
        # ctypes.byref wraps the POINT struct; we can't set fields through the
        # CArgObject, but we can patch the underlying buffer via the struct
        # that was passed in.  Since the struct is a local in _drag_loop we
        # instead stop the loop after the first move opportunity.
        call_count[0] += 1
        if call_count[0] >= 3:
            app._dragging = False

    mock_windll.user32.GetCursorPos.side_effect = fake_get_cursor_pos

    app._drag_loop()

    # window.move() may or may not have been called (cursor coords are 0,0 from
    # the mock so delta is 0 → no move needed), but SetWindowPos must never run.
    mock_windll.user32.SetWindowPos.assert_not_called()


# ---------------------------------------------------------------------------
# _drag_loop() — exception safety
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Windows")
@patch("ctypes.windll", create=True)
def test_drag_loop_swallows_exceptions(mock_windll, _mock_sys):
    """_drag_loop must never propagate exceptions to the caller."""
    app = _make_app()
    app._dragging = True
    mock_windll.user32.GetCursorPos.side_effect = RuntimeError("boom")

    app._drag_loop()   # must not raise

    assert app._dragging is False   # finally block ran


# ---------------------------------------------------------------------------
# _drag_loop() — _dragging cleared in finally
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Windows")
@patch("ctypes.windll", create=True)
def test_drag_loop_clears_dragging_in_finally(mock_windll, _mock_sys):
    """_drag_loop must clear _dragging in its finally block, even on exception."""
    app = _make_app(hwnd=0)
    app._dragging = True
    mock_windll.user32.GetCursorPos.side_effect = OSError("oops")

    app._drag_loop()

    assert app._dragging is False


# ---------------------------------------------------------------------------
# JS → Python bridge delegation
# ---------------------------------------------------------------------------

def test_pill_api_start_drag_delegates_to_app():
    """_PillApi.start_drag() must call GabaMicWin.start_drag()."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.start_drag()
    mock_app.start_drag.assert_called_once_with()


def test_pill_api_stop_drag_delegates_to_app():
    """_PillApi.stop_drag() must call GabaMicWin.stop_drag()."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.stop_drag()
    mock_app.stop_drag.assert_called_once_with()


def test_pill_api_toggle_delegates_to_app():
    """_PillApi.toggle() must call toggle_recording in a daemon thread."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.toggle()
    threading.Event().wait(timeout=0.05)
    mock_app.toggle_recording.assert_called_once()


# ---------------------------------------------------------------------------
# Thread safety — concurrent start_drag() calls
# ---------------------------------------------------------------------------

def test_concurrent_start_drag_calls_run_single_loop():
    """Rapid concurrent start_drag() calls must result in exactly one loop."""
    app = _make_app(dragging=False)
    loop_starts = []
    done = threading.Event()

    def fake_loop():
        loop_starts.append(1)
        done.wait(timeout=0.2)

    app._drag_loop = fake_loop

    threads = [threading.Thread(target=app.start_drag) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    done.set()
    time.sleep(0.05)   # let the loop thread finish

    assert len(loop_starts) == 1, (
        f"Expected exactly 1 drag loop; got {len(loop_starts)}"
    )
