import numpy as np
import pytest
import queue
import threading
from tts.speaker import Speaker


def test_speaker_cache_storage_and_lookup():
    speaker = Speaker()
    key = "test_cache_key_123"
    fake_data = np.zeros((100, 2), dtype=np.float32)
    sr = 24000

    speaker._store_cache(key, fake_data, sr)
    cached = speaker._lookup_cache(key)

    assert cached is not None
    data, sample_rate = cached
    assert sample_rate == 24000
    assert len(data) == 100


def test_speaker_interim_suppression(monkeypatch):
    """Test that interim waiting phrases are skipped if a final response is already queued."""
    speaker = Speaker()
    spoken = []
    monkeypatch.setattr(speaker, "_speak_yandex", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_piper", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_edge_tts", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_sapi", lambda text, **kwargs: spoken.append(text) or True)

    # Put an interim phrase, followed immediately by a final response
    speaker.speak("Секунду, сэр...", block=False, is_interim=True)
    speaker.speak("В городе Москва сейчас +18 градусов, сэр.", block=False, is_interim=False)

    # Wait briefly for worker thread to process
    speaker._queue.join()

    # The interim phrase should have been suppressed!
    assert "Секунду, сэр..." not in spoken
    assert any("Москва" in s for s in spoken)


def test_speaker_piper_routing(monkeypatch):
    """Test that Piper engine is dispatched when configured."""
    from core.config import config
    speaker = Speaker()
    spoken = []
    monkeypatch.setattr(speaker, "_speak_piper", lambda text: spoken.append(text) or True)

    orig_engine = config.get("voice.engine")
    try:
        config.set("voice.engine", "piper")
        speaker.speak("Тест Piper движка", block=True)
        assert any("Тест Piper движка" in s for s in spoken)
    finally:
        config.set("voice.engine", orig_engine)


def test_speaker_interrupt(monkeypatch):
    """Test that speaker.interrupt() sets interrupted flag and flushes queue."""
    speaker = Speaker()
    # Suppress actual speech output during test
    monkeypatch.setattr(speaker, "_speak_yandex", lambda text: True)
    monkeypatch.setattr(speaker, "_speak_piper", lambda text: True)
    monkeypatch.setattr(speaker, "_speak_edge_tts", lambda text: True)
    monkeypatch.setattr(speaker, "_speak_sapi", lambda text, **kwargs: True)

    speaker.speak("Первая фраза", block=False)
    speaker.speak("Вторая фраза", block=False)
    speaker.interrupt()
    assert speaker._interrupted.is_set()
    assert speaker._queue.empty()


def test_speaker_subsequent_speech_after_interrupt(monkeypatch):
    """Test that after interrupt(), the next speak() call is NOT skipped and plays normally."""
    speaker = Speaker()
    spoken = []
    monkeypatch.setattr(speaker, "_speak_yandex", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_piper", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_edge_tts", lambda text: spoken.append(text) or True)
    monkeypatch.setattr(speaker, "_speak_sapi", lambda text, **kwargs: spoken.append(text) or True)

    speaker.speak("Старая фраза", block=False)
    speaker.interrupt()
    assert speaker._interrupted.is_set()

    # User speaks new command: speaker should clear _interrupted and speak it!
    speaker.speak("Новая фраза после прерывания", block=True)
    assert not speaker._interrupted.is_set()
    assert any("Новая фраза после прерывания" in s for s in spoken)

