import os
import io
import sys
import asyncio
import time
import logging
import hashlib
import threading
import queue
from pathlib import Path
from typing import Optional, Dict, Tuple, Any
import re

import soundfile as sf
import sounddevice as sd
import numpy as np

from core.config import config, TTS_CACHE_DIR
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


class Speaker:
    """High-performance, dual-engine Text-to-Speech system with in-memory streaming and caching."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._cache: Dict[str, Tuple[np.ndarray, int]] = {}
        self._cache_lock = threading.Lock()
        
        # Ensure disk cache directory exists
        try:
            TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create TTS cache dir {TTS_CACHE_DIR}: {e}")

        self._synthesis_lock = threading.Lock()
        self._interrupted = threading.Event()
        self._sapi_voice = None
        self._init_sapi()
        
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True, name="TTSWorker")
        self._worker_thread.start()

    def _get_available_sapi_voices(self) -> list:
        """Enumerate all available SAPI and OneCore voice tokens."""
        import win32com.client
        collected = []
        seen_ids = set()

        # 1. Enumerate Windows OneCore voices (including Pavel and Irina)
        try:
            cp = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
            cp.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices")
            for t in cp.EnumerateTokens():
                if t.Id not in seen_ids:
                    seen_ids.add(t.Id)
                    collected.append(t)
        except Exception as e:
            logger.debug(f"Could not enumerate OneCore voices: {e}")

        # 2. Enumerate standard SAPI 5 voices
        try:
            voice = self._sapi_voice or win32com.client.Dispatch("SAPI.SpVoice")
            for t in voice.GetVoices():
                if t.Id not in seen_ids:
                    seen_ids.add(t.Id)
                    collected.append(t)
        except Exception as e:
            logger.debug(f"Could not enumerate standard SAPI voices: {e}")

        return collected

    def _init_sapi(self):
        """Initialize Windows SAPI voice as offline engine with Pavel (male) / Irina (female)."""
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            self._sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
            voices = self._get_available_sapi_voices()
            voice_gender = config.get("voice.gender", "male").lower()
            target_kw = ["pavel", "павел"] if voice_gender == "male" else ["irina", "ирина"]
            for v in voices:
                desc = v.GetDescription().lower()
                if any(k in desc for k in target_kw):
                    self._sapi_voice.Voice = v
                    logger.info(f"Windows SAPI selected voice: '{v.GetDescription()}'")
                    break
            else:
                for v in voices:
                    desc = v.GetDescription().lower()
                    if "russian" in desc or "irina" in desc or "pavel" in desc:
                        self._sapi_voice.Voice = v
                        logger.info(f"Windows SAPI selected Russian voice: '{v.GetDescription()}'")
                        break
        except Exception as e:
            logger.warning(f"Could not initialize Windows SAPI: {e}")

    def speak(self, text: str, block: bool = False, is_interim: bool = False) -> None:
        """Queue text to be spoken by SPUTNIK."""
        if not text or not text.strip():
            return

        # Fresh speech request: reset any prior interruption state
        self._interrupted.clear()

        from core.personality import SputnikPersonality
        text = SputnikPersonality.apply_title(text.strip())
        logger.info(f"SPUTNIK speaking (interim={is_interim}): '{text}'")

        if block:
            done_event = threading.Event()
            self._queue.put((text, done_event, is_interim))
            done_event.wait(timeout=30)
        else:
            self._queue.put((text, None, is_interim))

    def interrupt(self) -> None:
        """Instantly stop ongoing speech playback and clear remaining phrases (barge-in)."""
        logger.info("Interrupting speech playback (barge-in requested)...")
        self._interrupted.set()
        try:
            sd.stop()
        except Exception as e:
            logger.debug(f"sd.stop failed: {e}")

        # Drain remaining speech items in queue
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                _, done_event, _ = item
                if done_event:
                    done_event.set()
                self._queue.task_done()
            except queue.Empty:
                break

        # Notify state machines that speech playback has terminated
        try:
            event_bus.publish("speaking_finished", "")
        except Exception as e:
            logger.debug(f"Failed to publish speaking_finished on interrupt: {e}")

    def _get_cache_key(self, text: str, voice: str, rate: str, volume: str) -> str:
        raw_key = f"{voice}:{rate}:{volume}:{text}"
        return hashlib.md5(raw_key.encode("utf-8")).hexdigest()

    def _lookup_cache(self, cache_key: str) -> Optional[Tuple[np.ndarray, int]]:
        """Look up audio in RAM cache first, then disk cache."""
        with self._cache_lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        disk_path = TTS_CACHE_DIR / f"{cache_key}.wav"
        if disk_path.exists():
            try:
                data, samplerate = sf.read(str(disk_path), dtype="float32")
                with self._cache_lock:
                    if len(self._cache) < 200:
                        self._cache[cache_key] = (data, samplerate)
                return data, samplerate
            except Exception as e:
                logger.warning(f"Failed to read disk TTS cache {disk_path}: {e}")
        return None

    def _store_cache(self, cache_key: str, data: np.ndarray, samplerate: int) -> None:
        """Store audio into RAM cache and persist to disk cache."""
        with self._cache_lock:
            if len(self._cache) < 200:
                self._cache[cache_key] = (data, samplerate)

        disk_path = TTS_CACHE_DIR / f"{cache_key}.wav"
        if not disk_path.exists():
            try:
                sf.write(str(disk_path), data, samplerate, format="WAV")
            except Exception as e:
                logger.debug(f"Could not persist TTS cache to disk: {e}")

    def _process_queue(self):
        """Worker loop processing speech queue."""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            text, done_event, is_interim = item

            # If this is an interim waiting phrase ("Секунду, сэр...") and the final answer
            # is already waiting in the queue, skip the interim phrase completely!
            if is_interim and not self._queue.empty():
                logger.info(f"Suppressed interim speech '{text}' - final response is already available.")
                if done_event:
                    done_event.set()
                self._queue.task_done()
                continue

            try:
                success = False
                engine = config.get("voice.engine", "edge_tts").lower()
                voice_gender = config.get("voice.gender", "male").lower()
                allow_female = (voice_gender == "female")

                if engine == "yandex":
                    success = self._speak_yandex(text)
                    if not success:
                        logger.warning("Yandex SpeechKit unavailable (network/key), falling back to Piper...")
                        success = self._speak_piper(text)
                        if not success:
                            success = self._speak_sapi(text, allow_female_fallback=allow_female)
                elif engine == "piper":
                    success = self._speak_piper(text)
                    if not success:
                        logger.warning("Piper TTS failed, attempting fallback to SAPI / Edge-TTS...")
                        success = self._speak_sapi(text, allow_female_fallback=allow_female)
                        if not success:
                            success = self._speak_edge_tts(text)
                elif engine in ("sapi", "onecore", "local", "pavel"):
                    success = self._speak_sapi(text, allow_female_fallback=allow_female)
                    if not success:
                        success = self._speak_edge_tts(text)
                else:
                    success = self._speak_edge_tts(text)
                    if not success:
                        success = self._speak_sapi(text, allow_female_fallback=allow_female)

                if not success:
                    logger.error(f"All TTS engines failed to speak phrase: '{text}'")
            except Exception as e:
                logger.error(f"Error during TTS execution: {e}", exc_info=True)
            finally:
                event_bus.publish("speaking_finished", text)
                if done_event:
                    done_event.set()
                self._queue.task_done()

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """Clean and normalize text for reliable TTS synthesis without token drops or glitches."""
        if not text:
            return ""
        # 1. Remove markdown formatting (*, _, `, ~, #)
        t = re.sub(r"[*_`~#]", " ", text)
        # 2. Replace markdown headers/bullets at line starts
        t = re.sub(r"^\s*[-+*]\s+", "", t, flags=re.MULTILINE)
        # 3. Replace em-dash / en-dash with comma or hyphen
        t = re.sub(r"\s*[—–]\s*", ", ", t)
        # 4. Replace multiple dots or ellipses with single period
        t = re.sub(r"\.{2,}", ".", t)
        # 5. Clean up non-breaking spaces and zero-width characters from web/RSS feeds
        t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\ufeff', '')
        # 6. Clean up decimal dots in numbers (e.g., 2.5 -> 2,5)
        t = re.sub(r"(\d+)\.(\d+)", r"\1,\2", t)
        # 7. Normalize multiple spaces
        t = re.sub(r"[ \t]+", " ", t)
        return t.strip()

    @staticmethod
    def _split_into_sentences(text: str) -> list:
        """Split text into sentences for low-latency pipelined synthesis."""
        if not text:
            return []
        parts = re.split(r'(?<=[.!?…])\s+|\n+', text)
        sentences = [p.strip() for p in parts if p.strip()]
        return sentences if sentences else [text]

    def _synthesize_sentence_audio(self, sentence: str, target_voice: str, kwargs: dict) -> Optional[Tuple[np.ndarray, int]]:
        """Synthesize a single sentence with cache lookup, resilient retry, and multi-voice fallback."""
        rate = kwargs.get("rate", "+0%")
        volume = kwargs.get("volume", "+0%")
        cache_key = self._get_cache_key(sentence, target_voice, rate, volume)

        cached = self._lookup_cache(cache_key)
        if cached is not None:
            return cached

        import edge_tts
        with self._synthesis_lock:
            cached = self._lookup_cache(cache_key)
            if cached is not None:
                return cached

            # Strict native Russian only: NEVER use foreign/accented voices (e.g. Andrew)
            for attempt in range(2):
                try:
                    call_kwargs = dict(kwargs)
                    if target_voice == "ru-RU-DmitryNeural":
                        call_kwargs.pop("rate", None)

                    async def _stream_bytes(voice_id: str) -> bytes:
                        communicate = edge_tts.Communicate(sentence, voice_id, **call_kwargs)
                        chunks = []
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                chunks.append(chunk["data"])
                        return b"".join(chunks)

                    async def _fetch_with_timeout(voice_id: str) -> bytes:
                        return await asyncio.wait_for(_stream_bytes(voice_id), timeout=8.0)

                    raw_bytes = asyncio.run(_fetch_with_timeout(target_voice))
                    if not raw_bytes:
                        continue

                    with io.BytesIO(raw_bytes) as bio:
                        data, samplerate = sf.read(bio, dtype="float32")

                    self._store_cache(cache_key, data, samplerate)
                    return data, samplerate
                except Exception as e:
                    logger.warning(f"Synthesis attempt {attempt + 1}/2 for '{sentence[:30]}...' with '{target_voice}' failed: {e}")
                    if attempt == 0:
                        time.sleep(0.5)

        return None

    def _synthesize_yandex_utterance(self, text: str, voice: str, role: str, speed: str) -> Optional[Tuple[np.ndarray, int]]:
        """Synthesize a single utterance via Yandex SpeechKit API v3 with caching and retry."""
        api_key = config.get_api_key("YANDEX_API_KEY")
        if not api_key:
            return None

        cache_key = self._get_cache_key(text, f"yandex:{voice}:{role}:{speed}", "+0%", "+0%")
        cached = self._lookup_cache(cache_key)
        if cached is not None:
            return cached

        url_v3 = "https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis"
        headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json"
        }
        folder_id = config.env.get("YANDEX_FOLDER_ID")
        if folder_id:
            headers["x-folder-id"] = folder_id

        payload = {
            "text": text,
            "hints": [
                {"voice": voice},
                {"role": role}
            ],
            "outputAudioSpec": {
                "containerAudio": {
                    "containerAudioType": "WAV"
                }
            }
        }

        try:
            import requests
            import json
            import base64
            import io

            resp = requests.post(url_v3, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                chunks = []
                for line in resp.iter_lines():
                    if line:
                        item = json.loads(line.decode("utf-8"))
                        audio_b64 = item.get("result", {}).get("audioChunk", {}).get("data", "")
                        if audio_b64:
                            chunks.append(base64.b64decode(audio_b64))
                if chunks:
                    full_wav = b"".join(chunks)
                    audio, samplerate = sf.read(io.BytesIO(full_wav), dtype="float32")
                    self._store_cache(cache_key, audio, samplerate)
                    return audio, samplerate

            logger.warning(f"Yandex SpeechKit v3 status {resp.status_code}: {resp.text[:100]}")
            return None
        except Exception as e:
            logger.warning(f"Yandex SpeechKit request failed for '{text[:40]}...': {e}")
            return None

    def _speak_yandex(self, text: str) -> bool:
        """Synthesize and play speech via Yandex SpeechKit REST API v3 (Kirill, strict)."""
        api_key = config.get_api_key("YANDEX_API_KEY")
        if not api_key:
            return False

        text = self._sanitize_text(text)
        if not text:
            return True

        voice = config.get("voice.yandex_voice", "kirill")
        role = config.get("voice.yandex_role", config.get("voice.yandex_emotion", "strict"))
        speed = str(config.get("voice.yandex_speed", "1.0"))

        # For long texts, split into individual sentences to avoid API limits and timeouts
        sentences = self._split_into_sentences(text) if len(text) > 140 else [text]

        event_bus.publish("speaking_started", text)
        for sentence in sentences:
            if self._interrupted.is_set():
                logger.info("Speech interrupted before sentence playback.")
                return True
            s_clean = sentence.strip()
            if not s_clean:
                continue
            pair = self._synthesize_yandex_utterance(s_clean, voice, role, speed)
            if self._interrupted.is_set():
                logger.info("Speech interrupted after synthesis.")
                return True
            if pair is None:
                logger.warning(f"Failed to synthesize Yandex sentence: '{s_clean[:40]}', falling back")
                return False
            data, samplerate = pair
            try:
                sd.play(data, samplerate)
                sd.wait()
            except Exception as e:
                logger.error(f"Playback error in Yandex sentence: {e}")
                return False
            if self._interrupted.is_set():
                logger.info("Speech interrupted after playback.")
                return True

        return True

    def _speak_piper(self, text: str) -> bool:
        """Synthesize and play speech using offline neural Piper TTS engine (Ruslan)."""
        if self._interrupted.is_set():
            return True
        text = self._sanitize_text(text)
        if not text:
            return True

        voice_name = config.get("voice.piper_voice", "ru_RU-ruslan-medium")
        cache_key = self._get_cache_key(text, f"piper:{voice_name}", "+0%", "+0%")

        # 1. Fast path: check RAM and disk cache
        cached = self._lookup_cache(cache_key)
        if cached is not None:
            data, samplerate = cached
            try:
                event_bus.publish("speaking_started", text)
                sd.play(data, samplerate)
                sd.wait()
                return True
            except Exception as e:
                logger.warning(f"Failed to play cached Piper audio: {e}")

        # 2. Path resolution
        base_dir = config.base_dir
        piper_exe = base_dir / "tools" / "piper" / "piper.exe"
        model_path = base_dir / "model" / "piper" / f"{voice_name}.onnx"
        config_path = base_dir / "model" / "piper" / f"{voice_name}.onnx.json"
        espeak_dir = base_dir / "tools" / "piper" / "espeak-ng-data"

        if not piper_exe.exists() or not model_path.exists():
            logger.warning(f"Piper assets missing (exe: {piper_exe.exists()}, model: {model_path.exists()})")
            return False

        # Convert to Windows 8.3 short paths to guarantee no encoding issues with Cyrillic / spaces
        try:
            import win32api
            s_piper_exe = win32api.GetShortPathName(str(piper_exe))
            s_model_path = win32api.GetShortPathName(str(model_path))
            s_config_path = win32api.GetShortPathName(str(config_path))
            s_espeak_dir = win32api.GetShortPathName(str(espeak_dir))
            s_cache_dir = win32api.GetShortPathName(str(TTS_CACHE_DIR))
            s_tmp_wav = os.path.join(s_cache_dir, f"tmp_piper_{threading.get_ident()}.wav")
        except Exception:
            s_piper_exe = str(piper_exe)
            s_model_path = str(model_path)
            s_config_path = str(config_path)
            s_espeak_dir = str(espeak_dir)
            s_tmp_wav = str(TTS_CACHE_DIR / f"tmp_piper_{threading.get_ident()}.wav")

        tmp_wav = Path(s_tmp_wav)

        cmd = [
            s_piper_exe,
            "-m", s_model_path,
            "-c", s_config_path,
            "-f", s_tmp_wav,
            "--espeak_data", s_espeak_dir
        ]

        with self._synthesis_lock:
            try:
                import subprocess
                res = subprocess.run(
                    cmd,
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=15
                )
                if res.returncode != 0 or not tmp_wav.exists():
                    logger.warning(f"Piper synthesis returned code {res.returncode}: {res.stderr.decode('utf-8', errors='ignore')}")
                    return False

                data, samplerate = sf.read(s_tmp_wav, dtype="float32")
                self._store_cache(cache_key, data, samplerate)

                event_bus.publish("speaking_started", text)
                sd.play(data, samplerate)
                sd.wait()
                return True
            except Exception as e:
                logger.error(f"Piper synthesis/playback error: {e}", exc_info=True)
                return False
            finally:
                if tmp_wav.exists():
                    try:
                        tmp_wav.unlink(missing_ok=True)
                    except Exception:
                        pass

    def _speak_edge_tts(self, text: str) -> bool:
        """Synthesize and play speech via Edge-TTS using sentence pipelining for minimum latency."""
        text = self._sanitize_text(text)
        if not text:
            return True

        voice_gender = config.get("voice.gender", "male").lower()
        default_voice = "ru-RU-SvetlanaNeural" if voice_gender == "female" else "ru-RU-DmitryNeural"
        target_voice = config.get("voice.edge_voice", default_voice)

        # Enforce consistency between voice.gender and voice.edge_voice
        if voice_gender == "female" and "dmitry" in target_voice.lower():
            target_voice = "ru-RU-SvetlanaNeural"
        elif voice_gender == "male" and "svetlana" in target_voice.lower():
            target_voice = "ru-RU-DmitryNeural"

        rate = config.get("voice.rate", "+15%")
        volume = config.get("voice.volume", "+0%")

        kwargs = {}
        if rate and rate != "+0%":
            kwargs["rate"] = rate
        if volume and volume != "+0%":
            kwargs["volume"] = volume

        # 1. Fast path: Full text already in cache (0 ms latency)
        cache_key = self._get_cache_key(text, target_voice, rate, volume)
        cached = self._lookup_cache(cache_key)
        if cached is not None:
            data, samplerate = cached
            try:
                event_bus.publish("speaking_started", text)
                sd.play(data, samplerate)
                sd.wait()
                return True
            except Exception as e:
                logger.warning(f"Failed to play cached audio: {e}")

        # 2. Single-session synthesis for complete text
        # Sending the entire text in a single Edge-TTS session ensures that Microsoft
        # synthesizes all sentences seamlessly in one go without closing/reopening sockets,
        # completely eliminating 'No audio was received' drops on subsequent sentences!
        pair = self._synthesize_sentence_audio(text, target_voice, kwargs)
        if pair is not None:
            data, samplerate = pair
            try:
                event_bus.publish("speaking_started", text)
                sd.play(data, samplerate)
                sd.wait()
                return True
            except Exception as e:
                logger.error(f"Playback error: {e}")
                return False

        return False

    def _speak_sapi(self, text: str, allow_female_fallback: bool = False) -> bool:
        """Synthesize speech via Windows SAPI strictly using Russian voices (never English David/Zira)."""
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            if self._sapi_voice is None:
                self._init_sapi()

            voice = self._sapi_voice or win32com.client.Dispatch("SAPI.SpVoice")
            voice_gender = config.get("voice.gender", "male").lower()

            try:
                voices = self._get_available_sapi_voices()
                # Strict Russian filter: only voices that explicitly support Russian
                russian_voices = []
                for v in voices:
                    desc = v.GetDescription().lower()
                    if "russian" in desc or "irina" in desc or "ирина" in desc or "pavel" in desc or "павел" in desc:
                        russian_voices.append(v)

                selected_v = None
                if voice_gender == "female":
                    for v in russian_voices:
                        if any(k in v.GetDescription().lower() for k in ["irina", "ирина", "elena"]):
                            selected_v = v
                            break
                    if selected_v is None and allow_female_fallback and russian_voices:
                        selected_v = russian_voices[0]
                else:
                    for v in russian_voices:
                        if any(k in v.GetDescription().lower() for k in ["pavel", "павел", "aleksandr", "alexander"]):
                            selected_v = v
                            break
                    if selected_v is None and allow_female_fallback and russian_voices:
                        selected_v = russian_voices[0]

                if selected_v is None:
                    logger.warning(f"No suitable Russian SAPI voice found for gender '{voice_gender}' (allow_female={allow_female_fallback}).")
                    return False

                voice.Voice = selected_v
                logger.info(f"SAPI voice set to Russian: '{selected_v.GetDescription()}'")
            except Exception as e:
                logger.warning(f"Could not filter Russian SAPI voices: {e}")
                return False

            voice.Rate = 0
            voice.Volume = 100
            event_bus.publish("speaking_started", text)
            voice.Speak(text)
            return True
        except Exception as e:
            logger.error(f"Windows SAPI speech failed: {e}")
            return False

    def stop(self):
        """Stop speaker thread."""
        self._stop_event.set()


# Global singleton speaker
speaker = Speaker()

