"""Tests for the pill drag-to-move functionality (app_win.move_by).

Drag works by sending (dx, dy) deltas from JS screenX/screenY on every
mousemove event while the left button is held.  Python accumulates the
position in _win_x/_win_y and calls self._window.move(x, y) via
pywebview's own API — the only reliable way to move a WebView2-hosted
frameless window.
"""

import sys
import threading
from unittest.mock import MagicMock, call, patch

# pywebview is a Windows-only dependency absent from the macOS/Linux venv.
sys.modules.setdefault("webview", MagicMock())

import app_win
from app_win import GabaMicWin, _PillApi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(win_x=760, win_y=1000):
    """Bare GabaMicWin with only drag-relevant attributes set."""
    app = GabaMicWin.__new__(GabaMicWin)
    app._win_x  = win_x
    app._win_y  = win_y
    app._window = MagicMock()
    return app


# ---------------------------------------------------------------------------
# move_by — position accumulation
# ---------------------------------------------------------------------------

def test_move_by_updates_position():
    """move_by must accumulate dx/dy into _win_x/_win_y."""
    app = _make_app(win_x=100, win_y=200)
    app.move_by(30, -10)
    assert app._win_x == 130
    assert app._win_y == 190


def test_move_by_calls_window_move_with_new_position():
    """move_by must call window.move() with the accumulated position."""
    app = _make_app(win_x=760, win_y=1000)
    app.move_by(15, 8)
    app._window.move.assert_called_once_with(775, 1008)


def test_move_by_accumulates_across_multiple_calls():
    """Successive move_by calls must stack: total displacement equals sum of deltas."""
    app = _make_app(win_x=500, win_y=500)
    app.move_by(10, 20)
    app.move_by(-5, 30)
    app.move_by(0, -15)
    assert app._win_x == 505
    assert app._win_y == 535
    # Last call must be the final position
    app._window.move.assert_called_with(505, 535)


def test_move_by_window_move_call_count():
    """window.move() must be called once per move_by invocation."""
    app = _make_app()
    for _ in range(5):
        app.move_by(1, 1)
    assert app._window.move.call_count == 5


def test_move_by_no_op_when_window_is_none():
    """move_by must not raise when _window is None (window not yet created)."""
    app = _make_app()
    app._window = None
    app.move_by(10, 10)   # must not raise
    assert app._win_x == 770
    assert app._win_y == 1010


def test_move_by_accepts_float_deltas_from_js():
    """JS screenX/screenY differences are floats; move_by must handle them."""
    app = _make_app(win_x=0, win_y=0)
    app.move_by(int(3.7), int(-2.1))
    assert app._win_x == 3
    assert app._win_y == -2


# ---------------------------------------------------------------------------
# JS → Python bridge delegation
# ---------------------------------------------------------------------------

def test_pill_api_move_by_delegates_to_app():
    """_PillApi.move_by() must call GabaMicWin.move_by() with int-cast args."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.move_by(5.9, -3.1)
    mock_app.move_by.assert_called_once_with(5, -3)


def test_pill_api_toggle_delegates_to_app():
    """_PillApi.toggle() must call toggle_recording in a daemon thread."""
    mock_app = MagicMock()
    api = _PillApi(mock_app)
    api.toggle()
    # Give thread time to fire
    threading.Event().wait(timeout=0.05)
    mock_app.toggle_recording.assert_called_once()


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

def test_concurrent_move_by_calls_are_safe():
    """Rapid concurrent move_by calls must not corrupt _win_x/_win_y."""
    app = _make_app(win_x=0, win_y=0)
    N = 200

    def move():
        for _ in range(N):
            app.move_by(1, 1)

    threads = [threading.Thread(target=move) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each of the 4 threads calls move_by(1,1) N times → total = 4*N
    assert app._win_x == 4 * N
    assert app._win_y == 4 * N
