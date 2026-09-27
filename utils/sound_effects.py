import logging
import threading
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

_PRECOMPUTED_CHIME: Optional[np.ndarray] = None
_SAMPLE_RATE = 22050


def _generate_chime_waveform(sample_rate: int = _SAMPLE_RATE) -> np.ndarray:
    """Generate pleasant, soft two-tone high-tech chime (D5 -> A5, ~180ms)."""
    duration1 = 0.08
    duration2 = 0.10
    t1 = np.linspace(0, duration1, int(sample_rate * duration1), endpoint=False)
    t2 = np.linspace(0, duration2, int(sample_rate * duration2), endpoint=False)

    tone1 = np.sin(2 * np.pi * 587.33 * t1) * np.hanning(len(t1))
    tone2 = np.sin(2 * np.pi * 880.00 * t2) * np.hanning(len(t2))

    chime = np.concatenate([tone1, tone2]).astype(np.float32) * 0.25
    return chime


def play_wake_chime():
    """Play brief activation chime asynchronously without blocking the listener thread."""
    def _play():
        global _PRECOMPUTED_CHIME
        try:
            import sounddevice as sd
            if _PRECOMPUTED_CHIME is None:
                _PRECOMPUTED_CHIME = _generate_chime_waveform()
            sd.play(_PRECOMPUTED_CHIME, samplerate=_SAMPLE_RATE, blocking=False)
        except Exception as e:
            logger.debug(f"sounddevice chime failed: {e}. Falling back to winsound.")
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass

    threading.Thread(target=_play, daemon=True, name="WakeChimeWorker").start()
