"""Audio capture module for GabaMic.

Provides AudioRecorder: streams from the default microphone and returns a
1-D float32 numpy array on stop(), discarding silence and clips that are
too short to be meaningful.
"""

import threading

import numpy as np
import sounddevice as sd


class AudioRecorder:
    """Records audio from the default microphone into an in-memory buffer.

    Usage::

        recorder = AudioRecorder()
        recorder.start()          # begins non-blocking capture
        ...
        audio = recorder.stop()   # returns float32 ndarray, or empty array
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_rms_threshold: float = 0.01,
        min_recording_seconds: float = 0.5,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_rms_threshold = silence_rms_threshold
        self.min_recording_seconds = min_recording_seconds

        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin streaming audio from the default microphone (non-blocking)."""
        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop the stream and return the captured audio.

        Returns:
            A 1-D float32 numpy array with values in [-1.0, 1.0], or an
            empty array (``np.array([], dtype=np.float32)``) when:
            - no audio was captured,
            - the recording RMS is below ``silence_rms_threshold``, or
            - the duration is shorter than ``min_recording_seconds``.
        """
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        with self._lock:
            chunks = list(self._chunks)

        if not chunks:
            return np.array([], dtype=np.float32)

        audio = np.concatenate(chunks)  # shape (N,), float32

        # Discard silence
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < self.silence_rms_threshold:
            return np.array([], dtype=np.float32)

        # Discard clips that are too short
        duration = len(audio) / self.sample_rate
        if duration < self.min_recording_seconds:
            return np.array([], dtype=np.float32)

        return audio

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time,  # CData struct from PortAudio — not used
        status,
    ) -> None:
        """sounddevice stream callback — appends incoming samples to the buffer."""
        with self._lock:
            self._chunks.append(indata[:, 0].copy())  # channel 0, defensive copy
