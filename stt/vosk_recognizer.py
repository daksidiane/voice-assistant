import json
import logging
from pathlib import Path
from typing import Optional, Tuple, List

from vosk import Model, KaldiRecognizer
from core.config import config, BASE_DIR
from stt.model_loader import ensure_vosk_model

logger = logging.getLogger(__name__)


class VoskRecognizerEngine:
    """Offline STT engine using Vosk lightweight model."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.model = None
        self.recognizer = None
        self._init_model()

    def _init_model(self):
        """Load Vosk model with Windows Unicode path protection."""
        target_dir = BASE_DIR / "model"
        model_path = ensure_vosk_model(target_dir)
        str_path = str(model_path.resolve())

        # On Windows, Kaldi C++ engine fails on Cyrillic/Unicode characters in path.
        # Use Windows 8.3 short path if available.
        try:
            import win32api
            str_path = win32api.GetShortPathName(str_path)
        except Exception:
            # Fallback to relative path if short path conversion fails
            try:
                import win32api
                rel_path = str(model_path)
                str_path = win32api.GetShortPathName(rel_path)
            except Exception:
                pass

        logger.info(f"Loading Vosk model from {str_path}...")
        self.model = Model(str_path)
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
        self.recognizer.SetWords(True)
        logger.info("Vosk speech recognition engine loaded successfully.")

    def process_audio(self, audio_data: bytes) -> Tuple[bool, str]:
        """
        Process audio chunk.
        Returns: (is_final, recognized_text)
        """
        if self.recognizer is None:
            return False, ""

        if self.recognizer.AcceptWaveform(audio_data):
            res = json.loads(self.recognizer.Result())
            text = res.get("text", "").strip().lower()
            return True, text
        else:
            partial_res = json.loads(self.recognizer.PartialResult())
            partial_text = partial_res.get("partial", "").strip().lower()
            return False, partial_text

    def reset(self):
        """Reset recognizer state."""
        if self.recognizer and self.model:
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
