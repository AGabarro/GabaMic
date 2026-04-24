"""GabaMic — headless entry point.

Hold Alt+S to record, release to transcribe and inject the text.
"""

import json
import pathlib
import threading

import numpy as np

from gabamic.audio import AudioRecorder
from gabamic.hotkey import HotkeyListener
from gabamic.injector import TextInjector
from gabamic.transcriber import Transcriber

CONFIG_PATH = pathlib.Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def main() -> None:
    cfg = load_config()

    recorder = AudioRecorder(
        sample_rate=cfg.get("sample_rate", 16000),
        silence_rms_threshold=cfg.get("silence_rms_threshold", 0.01),
        min_recording_seconds=cfg.get("min_recording_seconds", 0.5),
    )
    transcriber = Transcriber(
        model_size=cfg.get("model_size", "base"),
        device=cfg.get("device", "cpu"),
        compute_type=cfg.get("compute_type", "int8"),
        language=cfg.get("language"),
    )
    injector = TextInjector()

    # Warm up: run a silent transcription so the first real one is fast
    print("Loading model…")
    transcriber.transcribe(np.zeros(16000, dtype=np.float32))
    print("Ready. Hold Alt+S to dictate.")

    def on_start() -> None:
        print("● Recording…")
        recorder.start()

    def on_stop() -> None:
        audio = recorder.stop()
        if len(audio) == 0:
            print("(silence)")
            return
        text = transcriber.transcribe(audio)
        if text:
            injector.inject(text)
            print(text)

    listener = HotkeyListener(
        on_start=on_start,
        on_stop=on_stop,
        modifier=cfg.get("hotkey_modifier", "alt"),
        key=cfg.get("hotkey_key", "s"),
    )
    listener.start()

    stop_event = threading.Event()
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
