import os
import sys
import time
import argparse
import logging
import threading
import tkinter as tk
from pathlib import Path

# Ensure UTF-8 output in Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.config import config, BASE_DIR
from core.state import AssistantState
from core.event_bus import event_bus
from core.personality import SputnikPersonality
from tts.speaker import speaker
from stt.vosk_recognizer import VoskRecognizerEngine
from stt.audio_capture import AudioCapture
from commands.dispatcher import dispatcher
from modules.scheduler import scheduler
from modules.tracker import work_tracker
from ui.notifier import Notifier
from ui.tray import TrayManager
from ui.settings_window import SettingsWindow
from ui.plans_window import PlansWindow
from ui.control_window import SputnikControlWindow
from hotkey import EmergencyHotkeyListener
from utils.sound_effects import play_wake_chime

# Setup logging
log_file = BASE_DIR / "sputnik.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SPUTNIK_MAIN")


class SputnikApp:
    """Master application controller for SPUTNIK."""

    def __init__(self, cli_mode: bool = False):
        self.cli_mode = cli_mode
        self.state = AssistantState.STARTING
        self.is_paused = False
        self._is_speaking = False
        self._stop_event = threading.Event()

        # Tkinter root for GUI windows
        self.tk_root = tk.Tk()
        self.tk_root.withdraw() # Root window stays hidden, child Toplevels are displayed

        self.settings_window = SettingsWindow(self.tk_root)
        self.plans_window = PlansWindow(self.tk_root)
        self.control_window = SputnikControlWindow(
            root=self.tk_root,
            on_execute_command=self._execute_gui_command,
            on_open_settings=self.open_settings,
            on_open_plans=self.open_plans,
            on_toggle_pause=self.toggle_pause,
            on_shutdown=self.shutdown
        )

        # Tray manager
        self.tray = TrayManager(
            on_open_settings=self.open_settings,
            on_open_plans=self.open_plans,
            on_toggle_pause=self.toggle_pause,
            on_exit=self.confirm_and_shutdown_from_tray,
            on_open_control=self.open_control_window
        )

        # Hotkey listener
        self.hotkey = EmergencyHotkeyListener(on_emergency_exit=self.shutdown)

        # Speech recognition & audio
        self.stt: Optional[VoskRecognizerEngine] = None
        self.audio: Optional[AudioCapture] = None
        self._listen_thread: Optional[threading.Thread] = None

        self._setup_event_subscriptions()

    def _setup_event_subscriptions(self):
        """Wire event bus handlers."""
        event_bus.subscribe("open_control_window", lambda _: self.tk_root.after(0, self.open_control_window))
        event_bus.subscribe("open_settings_window", lambda _: self.tk_root.after(0, self.open_settings))
        event_bus.subscribe("open_plans_window", lambda _: self.tk_root.after(0, self.open_plans))
        event_bus.subscribe("request_shutdown", lambda _: self.tk_root.after(500, self.shutdown))

        
        event_bus.subscribe("speaking_started", self._handle_speaking_started)
        event_bus.subscribe("speaking_finished", self._handle_speaking_finished)
        event_bus.subscribe("reminder_alert", self._handle_reminder_alert)
        event_bus.subscribe("break_reminder", self._handle_break_reminder)

    def _handle_speaking_started(self, text: str):
        """Mute microphone handling while SPUTNIK is speaking to prevent self-triggering."""
        self._is_speaking = True
        self.set_state(AssistantState.SPEAKING)

    def _handle_speaking_finished(self, text: str):
        """Unmute microphone after speech completes (audio was drained continuously while speaking)."""
        self._is_speaking = False
        self.set_state(AssistantState.IDLE)

    def _handle_reminder_alert(self, data: dict):
        text = data.get("text", "")
        plan = data.get("plan", {})
        title = plan.get("title", "Напоминание")
        Notifier.show_toast("Спутник — Напоминание", f"{title} ({plan.get('datetime', '')})")
        speaker.speak(text)

    def _handle_break_reminder(self, data: dict):
        text = data.get("text", "")
        Notifier.show_toast("Спутник — Забота о здоровье", "Рекомендуется сделать перерыв от компьютера (3+ часа)")
        speaker.speak(text)

    def open_control_window(self):
        self.tk_root.after(0, self.control_window.show)

    def open_settings(self):
        self.settings_window.show()

    def open_plans(self):
        self.plans_window.show()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        logger.info(f"Microphone listening state toggled: is_paused={self.is_paused}")
        if hasattr(self, "control_window"):
            self.tk_root.after(0, lambda: self.control_window.update_status(self.state, self.is_paused))
        if self.is_paused:
            speaker.speak("Прослушивание приостановлено, сэр.")
        else:
            speaker.speak("Слушаю вас, сэр.")

    def confirm_and_shutdown_from_tray(self):
        """Prompt confirmation popup on Tkinter thread before shutting down via tray menu."""
        self.tk_root.after(0, self._show_tray_exit_confirmation)

    def _show_tray_exit_confirmation(self):
        from tkinter import messagebox
        if messagebox.askyesno("Подтверждение", "Вы точно хотите выйти из Спутника?"):
            logger.info("User confirmed exit from tray menu. Shutting down...")
            self.shutdown()
        else:
            logger.info("User cancelled exit from tray menu.")

    def set_state(self, new_state: AssistantState):
        self.state = new_state
        self.tray.update_state(new_state)
        if hasattr(self, "control_window"):
            self.tk_root.after(0, lambda: self.control_window.update_status(new_state, self.is_paused))

    def start(self):
        """Start all services, control window, and background listening."""
        logger.info("Starting SPUTNIK Assistant...")
        self.hotkey.start()

        if config.get("assistant.greeting_on_start", True):
            greeting = SputnikPersonality.get_startup_greeting()
            speaker.speak(greeting)
            Notifier.show_toast("Спутник", "Голосовой помощник активен. Значок в трее готов к работе.")

        # Show Control Window on launch
        self.open_control_window()

        if not self.cli_mode:
            try:
                self.stt = VoskRecognizerEngine()
                self.audio = AudioCapture(sample_rate=config.get("stt.sample_rate", 16000))
                self.audio.start()
                self._listen_thread = threading.Thread(target=self._audio_listen_loop, daemon=True, name="AudioListenLoop")
                self._listen_thread.start()
                logger.info("Audio recognition pipeline successfully launched.")
            except Exception as e:
                logger.error(f"Failed to initialize audio capture/STT: {e}", exc_info=True)
                Notifier.show_toast("Спутник — Внимание", "Не удалось запустить микрофон. Проверьте подключение.")

        self.set_state(AssistantState.IDLE)

        # Start tray icon in a dedicated background thread
        tray_thread = threading.Thread(target=self.tray.run, daemon=True, name="TrayThread")
        tray_thread.start()

        # Run Tkinter GUI event loop in main thread
        try:
            self.tk_root.mainloop()
        except KeyboardInterrupt:
            self.shutdown()

    def _audio_listen_loop(self):
        """Microphone processing loop."""
        wake_words = config.get("assistant.wake_words", ["спутник", "спутник", "ало", "алло", "привет"])
        extended_wake = list(wake_words) + ["спутник", "жарвиз", "дарвис", "ярвис", "гарвис", "чарвис"]
        active_deadline = 0.0

        while not self._stop_event.is_set():
            if self.is_paused:
                time.sleep(0.05)
                continue

            chunk = self.audio.get_chunk(timeout=0.1)
            if not chunk:
                continue

            is_final, text = self.stt.process_audio(chunk)
            if not text:
                continue

            # Barge-in: if SPUTNIK is speaking and user speaks a command or wake word, interrupt!
            if self._is_speaking:
                is_wake = any(w in text for w in extended_wake)
                is_stop = any(w in text for w in ("стоп", "хватит", "погоди", "подожди", "молчи", "тихо", "отмена", "прервись", "замолчи"))
                is_direct_cmd = any(text.startswith(w) or f" {w}" in text for w in (
                    "открой", "запусти", "включи", "сколько времени", "какая погода", "погода",
                    "курс", "новости", "добавь", "запланируй", "напомни", "запомни", "покажи", "выключи"
                ))

                if is_wake or is_stop or is_direct_cmd:
                    logger.info(f"Barge-in detected during speech: '{text}' (is_final={is_final})")
                    speaker.interrupt()
                    self._is_speaking = False

                    if is_stop and not is_direct_cmd and not is_wake:
                        logger.info("Speech halted by stop command. Returning to IDLE.")
                        self.set_state(AssistantState.IDLE)
                        self.stt.reset()
                        continue

                    command_part = dispatcher.clean_wake_word(text) if is_wake else text
                    if is_final and command_part and len(command_part.split()) >= 2:
                        logger.info(f"Immediate barge-in command finalized: '{command_part}'")
                        threading.Thread(target=self._execute_command, args=(command_part, True), daemon=True, name="VoiceCmdWorker").start()
                        self.set_state(AssistantState.IDLE)
                        self.stt.reset()
                        continue
                    else:
                        logger.info("Barge-in phrase detected. Switching to ACTIVE listening.")
                        self.set_state(AssistantState.ACTIVE)
                        timeout_sec = float(config.get("assistant.commands_timeout_sec", 8.0))
                        active_deadline = time.time() + timeout_sec
                        if is_wake and not command_part:
                            self.stt.reset()
                        continue
                else:
                    # Echo suppression: ignore microphone input from own speech
                    continue

            # Check if active listening timed out
            now = time.time()
            if self.state == AssistantState.ACTIVE and now > active_deadline:
                logger.info("Command listening timed out. Returning to IDLE.")
                self.set_state(AssistantState.IDLE)
                self.stt.reset()

            # 1. State: IDLE - Listening for wake words or continuous compound commands
            if self.state == AssistantState.IDLE:
                detected_wake = any(w in text for w in extended_wake)
                if detected_wake and is_final:
                    command_part = dispatcher.clean_wake_word(text)
                    if command_part:
                        # Full compound command spoken in one go (e.g. "спутник открой список планов")
                        logger.info(f"Continuous command detected and finalized: '{command_part}' (from '{text}')")
                        threading.Thread(target=self._execute_command, args=(command_part, True), daemon=True, name="VoiceCmdWorker").start()
                        self.stt.reset()
                    else:
                        # User spoke ONLY the wake word and paused
                        logger.info(f"Standalone wake word detected: '{text}'. Playing activation chime.")
                        self.set_state(AssistantState.ACTIVE)
                        timeout_sec = float(config.get("assistant.commands_timeout_sec", 8.0))
                        active_deadline = time.time() + timeout_sec
                        play_wake_chime()
                        time.sleep(0.18)
                        if self.audio:
                            self.audio.clear()
                        self.stt.reset()
                # If detected_wake and not is_final, user is still speaking; allow Vosk to accumulate without interruption!

            # 2. State: ACTIVE - Listening for command after activation chime
            elif self.state == AssistantState.ACTIVE:
                # Dynamically extend deadline while user is speaking so they are never interrupted mid-sentence
                active_deadline = max(active_deadline, time.time() + 5.0)
                if is_final:
                    clean_text = dispatcher.clean_wake_word(text) or text
                    if clean_text:
                        logger.info(f"Active command recognized: '{clean_text}'")
                        threading.Thread(target=self._execute_command, args=(clean_text, True), daemon=True, name="VoiceCmdWorker").start()
                    self.set_state(AssistantState.IDLE)
                    self.stt.reset()

    def _execute_gui_command(self, text: str, speak: bool = True):
        """Asynchronous execution of GUI text command in background worker."""
        threading.Thread(target=self._execute_command, args=(text, speak), daemon=True, name="GuiCmdWorker").start()

    def _execute_command(self, text: str, speak: bool = True):
        """Execute command and speak response."""
        self.set_state(AssistantState.PROCESSING)
        if hasattr(self, "control_window"):
            self.tk_root.after(0, lambda: self.control_window.append_user_message(text))

        should_continue, response_text = dispatcher.dispatch(text)

        if hasattr(self, "control_window"):
            self.tk_root.after(0, lambda: self.control_window.append_sputnik_message(response_text))

        if speak:
            self.set_state(AssistantState.SPEAKING)
            speaker.speak(response_text)
        else:
            self.set_state(AssistantState.IDLE)

        if not should_continue:
            self.tk_root.after(1000, self.shutdown)

    def shutdown(self):
        """Clean shutdown of all threads and components."""
        if threading.current_thread() is not threading.main_thread():
            self.tk_root.after(0, self.shutdown)
            return

        if self.state == AssistantState.STOPPING:
            return
        self.set_state(AssistantState.STOPPING)
        logger.info("Shutting down SPUTNIK...")
        self._stop_event.set()

        try:
            if self.audio:
                self.audio.stop()
        except Exception:
            pass

        try:
            scheduler.stop()
        except Exception:
            pass

        try:
            work_tracker.stop()
        except Exception:
            pass

        try:
            self.hotkey.stop()
        except Exception:
            pass

        try:
            self.tray.stop()
        except Exception:
            pass

        try:
            self.tk_root.quit()
            self.tk_root.destroy()
        except Exception:
            pass

        logger.info("SPUTNIK shut down successfully.")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="SPUTNIK Voice Assistant for Windows 10/11")
    parser.add_argument("--cli", action="store_true", help="Run interactive console mode for text commands")
    parser.add_argument("--test-command", type=str, help="Execute a single command string and print result")
    args = parser.parse_args()

    if args.test_command:
        print(f"[TEST COMMAND] Executing: '{args.test_command}'")
        should_continue, response = dispatcher.dispatch(args.test_command)
        print(f"[SPUTNIK RESPONSE] {response}")
        sys.exit(0)

    if args.cli:
        print("=== СПУТНИК: ТЕКСТОВЫЙ КОНСОЛЬНЫЙ РЕЖИМ ===")
        print("Введите голосовую команду (например: 'спутник сколько времени', 'открой ютуб', 'выход'):")
        while True:
            try:
                cmd = input("\nВы: ").strip()
                if not cmd:
                    continue
                should_cont, resp = dispatcher.dispatch(cmd)
                print(f"Спутник: {resp}")
                speaker.speak(resp)
                if not should_cont:
                    break
            except (KeyboardInterrupt, EOFError):
                print("\nЗавершение работы...")
                break
        sys.exit(0)

    app = SputnikApp()
    app.start()


if __name__ == "__main__":
    main()
