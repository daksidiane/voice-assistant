import queue
import logging
from typing import Optional
import sounddevice as sd

logger = logging.getLogger(__name__)


def disable_windows_audio_ducking():
    """Ensure Windows does not mute or reduce other applications' volume when microphone stream is active."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Multimedia\Audio")
        # 3 = Do nothing (disables ducking completely)
        winreg.SetValueEx(key, "UserDuckingPreference", 0, winreg.REG_DWORD, 3)
        winreg.CloseKey(key)
        logger.debug("Windows audio ducking preference set to 'Do nothing' (UserDuckingPreference=3).")
    except Exception as e:
        logger.debug(f"Could not configure Windows UserDuckingPreference: {e}")


class AudioCapture:
    """Microphone audio streamer using sounddevice."""

    def __init__(self, sample_rate: int = 16000, block_size: int = 4000):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.audio_queue: queue.Queue = queue.Queue()
        self._stream: Optional[sd.RawInputStream] = None
        self._is_running = False
        disable_windows_audio_ducking()

    def _callback(self, indata, frames, time, status):
        """Audio stream callback."""
        if status:
            logger.warning(f"Audio stream status warning: {status}")
        self.audio_queue.put(bytes(indata))

    def start(self):
        """Start microphone stream."""
        if self._is_running:
            return
        disable_windows_audio_ducking()
        try:
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                dtype="int16",
                channels=1,
                callback=self._callback
            )
            self._stream.start()
            self._is_running = True
            logger.info("Microphone stream started successfully.")
        except Exception as e:
            logger.error(f"Failed to start audio stream: {e}", exc_info=True)
            self._is_running = False
            raise

    def stop(self):
        """Stop microphone stream."""
        self._is_running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"Error closing audio stream: {e}")
            self._stream = None
        logger.info("Microphone stream stopped.")

    def is_running(self) -> bool:
        return self._is_running

    def get_chunk(self, timeout: float = 0.5) -> Optional[bytes]:
        """Fetch next audio chunk from queue."""
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear(self):
        """Drain queued audio chunks to prevent processing stale or self-spoken audio."""
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

