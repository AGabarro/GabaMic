"""Unit tests for gabamic.transcriber."""

from unittest.mock import MagicMock, patch

import numpy as np


def test_empty_audio_returns_empty_string():
    with patch("gabamic.transcriber.WhisperModel") as MockModel:
        from gabamic.transcriber import Transcriber

        t = Transcriber()
        result = t.transcribe(np.array([], dtype=np.float32))
        assert result == ""
        MockModel.return_value.transcribe.assert_not_called()


def test_transcribe_capitalises_first_letter():
    with patch("gabamic.transcriber.WhisperModel") as MockModel:
        from gabamic.transcriber import Transcriber

        mock_segment = MagicMock()
        mock_segment.text = "hello world"
        MockModel.return_value.transcribe.return_value = ([mock_segment], MagicMock())

        t = Transcriber()
        result = t.transcribe(np.ones(16000, dtype=np.float32))
        assert result == "Hello world"


def test_no_speech_returns_empty_string():
    with patch("gabamic.transcriber.WhisperModel") as MockModel:
        from gabamic.transcriber import Transcriber

        MockModel.return_value.transcribe.return_value = ([], MagicMock())

        t = Transcriber()
        result = t.transcribe(np.ones(16000, dtype=np.float32))
        assert result == ""


def test_language_passed_to_model():
    with patch("gabamic.transcriber.WhisperModel") as MockModel:
        from gabamic.transcriber import Transcriber

        mock_segment = MagicMock()
        mock_segment.text = "hola mundo"
        MockModel.return_value.transcribe.return_value = ([mock_segment], MagicMock())

        t = Transcriber(language="es")
        t.transcribe(np.ones(16000, dtype=np.float32))

        call_kwargs = MockModel.return_value.transcribe.call_args[1]
        assert call_kwargs["language"] == "es"
