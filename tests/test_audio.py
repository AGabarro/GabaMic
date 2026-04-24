"""Unit tests for gabamic.audio.AudioRecorder.

These tests exercise the silence-detection and minimum-duration logic
without requiring a real microphone or sounddevice installation.  The
stream is never started — chunks are injected directly into ``_chunks``
so that ``stop()`` only runs its post-processing path.
"""

import numpy as np
import pytest

from gabamic.audio import AudioRecorder


def test_silence_detection():
    """Near-zero audio (RMS < threshold) must be discarded."""
    r = AudioRecorder(
        sample_rate=16000,
        silence_rms_threshold=0.01,
        min_recording_seconds=0.5,
    )
    # 1 second of silence — long enough, but too quiet
    r._chunks = [np.zeros(16000, dtype=np.float32)]

    audio = r.stop()

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 0


def test_short_audio_discarded():
    """Loud but very short audio (< min_recording_seconds) must be discarded."""
    r = AudioRecorder(
        sample_rate=16000,
        silence_rms_threshold=0.01,
        min_recording_seconds=0.5,
    )
    # 0.1 s of full-scale audio — loud enough, but too short
    r._chunks = [np.ones(1600, dtype=np.float32)]  # 1600 / 16000 = 0.1 s

    audio = r.stop()

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 0


def test_valid_audio_returned():
    """Audio that passes both checks must be returned as-is."""
    r = AudioRecorder(
        sample_rate=16000,
        silence_rms_threshold=0.01,
        min_recording_seconds=0.5,
    )
    # 1 second of mid-level signal — loud and long enough
    signal = np.full(16000, 0.5, dtype=np.float32)
    r._chunks = [signal]

    audio = r.stop()

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 16000
    np.testing.assert_array_equal(audio, signal)


def test_empty_chunks_returns_empty():
    """With no captured chunks stop() must return an empty array."""
    r = AudioRecorder()
    r._chunks = []

    audio = r.stop()

    assert isinstance(audio, np.ndarray)
    assert len(audio) == 0


def test_stop_is_idempotent():
    """Calling stop() twice (no stream) must not raise."""
    r = AudioRecorder()
    r._chunks = []

    r.stop()
    r.stop()  # second call must be safe
