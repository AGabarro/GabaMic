"""Tests for the pill drag-to-move functionality (app_win.start_drag).

All Win32 calls are mocked so the suite runs on macOS and Linux as well as
Windows.  The tests verify the two-step drag protocol:
  1. ReleaseCapture() — frees mouse capture from the WebView2 child window.
  2. SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0) — starts the OS drag.
"""

import ctypes
import sys
import threading
from unittest.mock import MagicMock, patch

# pywebview (import webview) is a Windows-only dependency and is absent from the
# macOS/Linux venv.  Stub it before app_win is imported so the module loads on
# all platforms.
sys.modules.setdefault("webview", MagicMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(hwnd):
    """Create a GabaMicWin instance with only _hwnd set (no full __init__)."""
    import app_win
    app = app_win.GabaMicWin.__new__(app_win.GabaMicWin)
    app._hwnd = hwnd
    return app


# ---------------------------------------------------------------------------
# No-op when HWND is not yet resolved
# ---------------------------------------------------------------------------

def test_no_win32_calls_when_hwnd_is_zero():
    """start_drag() must be a no-op before the window HWND is found."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = MagicMock()
        app = _make_app(hwnd=0)
        app.start_drag()
        mock_windll.user32.ReleaseCapture.assert_not_called()
        mock_windll.user32.SendMessageW.assert_not_called()


# ---------------------------------------------------------------------------
# Correct Win32 protocol when HWND is set
# ---------------------------------------------------------------------------

_FAKE_HWND        = 0xABCD
_WM_NCLBUTTONDOWN = 0x00A1
_HTCAPTION        = 2


def test_release_capture_called_before_send_message():
    """ReleaseCapture() must precede SendMessageW to free WebView2 mouse capture."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_user32 = MagicMock()
        mock_windll.user32 = mock_user32

        _make_app(_FAKE_HWND).start_drag()

        method_names = [c[0] for c in mock_user32.method_calls]
        assert "ReleaseCapture" in method_names, "ReleaseCapture was not called"
        assert "SendMessageW"   in method_names, "SendMessageW was not called"
        assert method_names.index("ReleaseCapture") < method_names.index("SendMessageW"), \
            "ReleaseCapture must be called before SendMessageW"


def test_send_message_uses_wm_nclbuttondown_and_htcaption():
    """SendMessageW must carry WM_NCLBUTTONDOWN (0x00A1) with HTCAPTION (2)."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_user32 = MagicMock()
        mock_windll.user32 = mock_user32

        _make_app(_FAKE_HWND).start_drag()

        mock_user32.SendMessageW.assert_called_once_with(
            _FAKE_HWND, _WM_NCLBUTTONDOWN, _HTCAPTION, 0
        )


def test_release_capture_called_exactly_once():
    """Exactly one ReleaseCapture() call per drag — no duplicates."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_user32 = MagicMock()
        mock_windll.user32 = mock_user32

        _make_app(_FAKE_HWND).start_drag()

        mock_user32.ReleaseCapture.assert_called_once()


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------

def test_win32_exception_is_silently_swallowed():
    """A Win32 error inside start_drag() must never propagate to the caller."""
    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32.ReleaseCapture.side_effect = OSError("simulated Win32 failure")
        _make_app(_FAKE_HWND).start_drag()   # must not raise


def test_concurrent_drag_calls_do_not_raise():
    """Rapid concurrent calls from multiple threads must not crash."""
    errors = []

    with patch("ctypes.windll", create=True) as mock_windll:
        mock_windll.user32 = MagicMock()
        app = _make_app(_FAKE_HWND)

        def _call():
            try:
                app.start_drag()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_call) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"Unexpected errors in concurrent drag: {errors}"


# ---------------------------------------------------------------------------
# JS → Python bridge delegation
# ---------------------------------------------------------------------------

def test_pill_api_start_drag_delegates_to_app():
    """_PillApi.start_drag() must call GabaMicWin.start_drag() exactly once."""
    import app_win
    mock_app = MagicMock()
    api = app_win._PillApi(mock_app)
    api.start_drag()
    mock_app.start_drag.assert_called_once_with()
