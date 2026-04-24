"""Speech-to-text engine using faster-whisper."""

import os

import numpy as np
from faster_whisper import WhisperModel

os.environ.setdefault("HF_HUB_VERBOSITY", "error")


class Transcriber:
    """Wraps faster-whisper for local, offline transcription.

    The model is loaded once at instantiation to eliminate cold-start latency
    on the first dictation. Expect 2-4 seconds at startup on CPU.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        self.language = language  # None = auto-detect; "en" or "es" = forced
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=os.cpu_count() or 4,
        )

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a 1-D float32 numpy audio array to text.

        Args:
            audio: 1-D float32 array at 16 kHz, values in [-1.0, 1.0].

        Returns:
            Transcribed text with the first letter capitalised, or "" if
            the audio is empty or no speech was detected.
        """
        if len(audio) == 0:
            return ""

        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=2,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
        )

        text = "".join(seg.text for seg in segments).strip()

        if not text:
            return ""

        return text[0].upper() + text[1:]
