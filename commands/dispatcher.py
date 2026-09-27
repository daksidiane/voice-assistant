import re
import time
import logging
from typing import Tuple, Optional

from tts.speaker import speaker
from core.config import config
from core.personality import SputnikPersonality
from core.event_bus import event_bus
from commands.system_commands import SystemCommands
from commands.custom_commands import custom_command_manager
from modules.info_services import InfoServices
from modules.scheduler import scheduler, parse_dt_safe
from modules.ai_agent import AIAgent

logger = logging.getLogger(__name__)


class CommandDispatcher:
    """Dispatches recognized phrases to proper handlers."""

    def __init__(self):
        self.personality = SputnikPersonality
        self._pending_plan: Optional[dict] = None

    def clean_wake_word(self, text: str) -> str:
        """Remove leading wake words ('спутник', 'спутник', 'спутник', 'ало', 'привет'...) from utterance."""
        cleaned = text.strip().lower()
        wake_words = config.get("assistant.wake_words", ["спутник", "спутник", "ало", "алло", "привет"])
        # Add phonetic variations for robust STT matching
        extended_wake = list(wake_words) + ["спутник", "жарвиз", "дарвис", "ярвис", "гарвис", "чарвис"]
        # Sort by length descending to match longest prefix first
        extended_wake = sorted(list(set(extended_wake)), key=len, reverse=True)
        for w in extended_wake:
            pattern = rf'^{re.escape(w)}\b[:\s,]*'
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    @staticmethod
    def normalize_command_text(text: str) -> str:
        """
        Normalize and repair phonetic/STT misrecognitions from Vosk/Whisper.
        E.g. 'ко времени' -> 'сколько времени', 'с погоды' -> 'погода', etc.
        """
        norm = text.strip().lower()

        replacements = [
            # Time corrections
            (r'\b(?:ко\s+времени|ко\s+время|скажи\s+время|сколько\s+время)\b', 'сколько времени'),
            # Weather corrections
            (r'\b(?:с\s+погоды|прогноз\s+погоды|че\s+там\s+с\s+погодой|что\s+с\s+погодой)\b', 'погода'),
            # Currency corrections
            (r'\b(?:курс\s+доллара|курс\s+валюты|курсы\s+валют|курсы)\b', 'курс валют'),
            (r'\b(?:доллара|доллар)\b', 'курс доллара'),
            (r'\b(?:евро)\b', 'курс евро'),
            (r'\b(?:юаня|юань)\b', 'курс юаня'),
            # News corrections
            (r'\b(?:свежие\s+новости|новостей|сводка\s+новостей)\b', 'новости'),
            # Sites / Applications
            (r'\b(?:ютьюб|ютуп|в\s+ютубе)\b', 'ютуб'),
            (r'\b(?:в\s+контакте|вконтакте)\b', 'вк'),
            (r'\b(?:телеграмм|в\s+телеграме)\b', 'telegram'),
            (r'\b(?:калькулятора)\b', 'калькулятор'),
            (r'\b(?:блокнота)\b', 'блокнот'),
        ]

        for pat, repl in replacements:
            norm = re.sub(pat, repl, norm, flags=re.IGNORECASE)

        return norm

    def dispatch(self, text: str) -> Tuple[bool, str]:
        """
        Process user voice or text input and format response title.
        Returns: (should_continue_running: bool, speech_response: str)
        """
        should_continue, response = self._dispatch_internal(text)
        return should_continue, self.personality.apply_title(response)

    def _dispatch_internal(self, text: str) -> Tuple[bool, str]:
        raw_cleaned = self.clean_wake_word(text)
        if not raw_cleaned:
            return True, self.personality.get_wake_greeting()

        command_text = self.normalize_command_text(raw_cleaned)
        user_title = self.personality.get_user_title()
        logger.info(f"Processing command: '{command_text}' (raw: '{raw_cleaned}')")

        # 0. Check if user is replying to pending reminder time inquiry
        if self._pending_plan:
            now_ts = time.time()
            if now_ts <= self._pending_plan.get("expires_at", 0):
                parsed = scheduler.parse_natural_datetime(command_text)
                if parsed:
                    target_dt, remaining_title = parsed
                    base_title = self._pending_plan.get("title", "")
                    title = base_title if base_title and base_title not in ("Напоминание", "Событие") else (remaining_title or "Напоминание")
                    scheduler.add_plan(title, target_dt)
                    self._pending_plan = None
                    date_part = target_dt.strftime("%d.%m")
                    time_part = target_dt.strftime("%H:%M")
                    time_str = f"{date_part} в {time_part}"
                    return True, f"Запланировано, {user_title}: событие '{title}' на {time_str}."
            else:
                self._pending_plan = None

        # 1. Voice exit commands (F2.5) - require explicit phrase to prevent accidental false triggers
        if re.search(r'^\s*(выход|заверши работу|завершить работу|выключись|отключись|до свидания)\b', command_text, re.IGNORECASE):
            farewell = self.personality.get_exit()
            event_bus.publish("request_shutdown")
            return False, farewell

        # 2. Custom commands from custom_commands.json (F8.0, F8.2)
        match_result = custom_command_manager.match_command(command_text)
        if match_result:
            phrase, cmd_def = match_result
            success, response_msg = custom_command_manager.execute_custom_command(cmd_def)
            return True, response_msg

        # 3. Voice addition of custom command (F8.1)
        voice_add = custom_command_manager.parse_voice_add_command(command_text)
        if voice_add:
            phrase, action, target = voice_add
            saved = custom_command_manager.add_command(phrase, action, target)
            if saved:
                return True, f"Команда '{phrase}' успешно сохранена, {user_title}."
            return True, f"Не удалось сохранить команду '{phrase}', {user_title}. Параметры не прошли проверку безопасности."

        # 4. GUI window triggers (F3.2, F3.3)
        if re.search(r'\b(настройк\w*|окно настроек|открой настройки)\b', command_text, re.IGNORECASE):
            event_bus.publish("open_settings_window")
            return True, f"Открываю окно настроек, {user_title}."

        # 4.1 Voice change of owner gender / title
        if re.search(r'\b(я женщина|пол женский|обращайся как к девушке|обращайся госпожа|обращайся ко мне госпожа)\b', command_text, re.IGNORECASE):
            config.set("assistant.user_gender", "female")
            config.set("assistant.user_title", "госпожа")
            return True, "Принято, госпожа. Настройки обновлены, буду обращаться исключительно госпожа."

        if re.search(r'\b(я мужчина|пол мужской|обращайся сэр|обращайся ко мне сэр)\b', command_text, re.IGNORECASE):
            config.set("assistant.user_gender", "male")
            config.set("assistant.user_title", "сэр")
            return True, "Принято, сэр. Настройки обновлены, буду обращаться сэр."

        if re.search(r'\b(покажи планы|список планов|мои планы|какие планы|открой планы|планы)\b', command_text, re.IGNORECASE):
            event_bus.publish("open_plans_window")
            upcoming = scheduler.get_upcoming_plans()
            if upcoming:
                from datetime import datetime, timedelta
                now = datetime.now()
                items = []
                for p in upcoming[:3]:
                    p_dt = parse_dt_safe(p.get('datetime', ''))
                    if p_dt != datetime.max:
                        if p_dt.date() == now.date():
                            t_prefix = f"сегодня в {p_dt.strftime('%H:%M')}"
                        elif p_dt.date() == (now + timedelta(days=1)).date():
                            t_prefix = f"завтра в {p_dt.strftime('%H:%M')}"
                        else:
                            t_prefix = f"{p_dt.strftime('%d.%m')} в {p_dt.strftime('%H:%M')}"
                    else:
                        t_prefix = p.get('datetime', '')
                    items.append(f"{t_prefix} — {p['title']}")
                summary = "; ".join(items)
                return True, f"Открываю список планов, {user_title}. Ближайшие события: {summary}."
            else:
                return True, f"Открываю окно планов, {user_title}. На ближайшее время запланированных событий нет."

        # 5. Multimodal Screen Analysis (F7.2)
        if re.search(r'\b(что тут написано|что на экране|проанализируй\w*|посмотри на экран|на экране|снимок экрана|скриншот|скрин)\b', command_text, re.IGNORECASE):
            speaker.speak(f"Минуту, {user_title}, изучаю происходящее на экране...", block=False, is_interim=True)
            return True, AIAgent.analyze_screen(command_text)

        # 6. Internet Search (F2.3)
        search_match = re.search(r'\b(?:найди в интернете|поиск в гугл\w*|найди|загугли|поищи|поиск)\s+(.+)', command_text, re.IGNORECASE)
        if search_match:
            query = search_match.group(1).strip()
            speaker.speak(f"Секунду, {user_title}, ищу информацию по запросу '{query}'...", block=False, is_interim=True)
            from modules.web_search import WebSearch
            result = WebSearch.search_and_summarize(query, open_browser=True)
            return True, result

        # 7. Time and date (F4.1)
        if re.search(r'\b(врем\w*|который час|сколько времени|какое число|какой день|дат\w*|числ\w*)\b', command_text, re.IGNORECASE):
            return True, InfoServices.get_time_and_date()

        # 8. Weather (F4.2)
        weather_match = re.search(r'\bпогод\w*(?:\s+в\s+([а-яa-z\-]+))?', command_text, re.IGNORECASE)
        if weather_match or any(w in command_text for w in ["какая погода", "прогноз", "температур"]):
            city = weather_match.group(1) if weather_match and weather_match.group(1) else None
            speaker.speak(f"Секунду, {user_title}, запрашиваю прогноз погоды...", block=False, is_interim=True)
            return True, InfoServices.get_weather(city)

        # 9. Currency (F4.3)
        if re.search(r'\b(курс\w*|валют\w*|доллар\w*|евро|юан\w*|рубл\w*|тенге|лир\w*|дирхам\w*|фунт\w*|иен\w*|франк\w*|бат\w*|драм\w*|лари|сом\w*|сум\w*)\b', command_text, re.IGNORECASE):
            speaker.speak(f"Секунду, {user_title}, уточняю актуальный курс валют...", block=False, is_interim=True)
            try:
                rates_msg = InfoServices.get_exchange_rates(command_text)
            except TypeError:
                rates_msg = InfoServices.get_exchange_rates()
            return True, rates_msg

        # 10. News (F4.4)
        if re.search(r'\b(новост\w*|новостную ленту|что в мире|что происходит|сводк\w*)\b', command_text, re.IGNORECASE):
            speaker.speak(f"Секунду, {user_title}, загружаю свежую ленту новостей...", block=False, is_interim=True)
            return True, InfoServices.get_news(2)

        # 11. Multimedia control (F5.1 - F5.4)
        if re.search(r'\b(следующ\w* трек|следующ\w* песн\w*|вперед трек)\b', command_text, re.IGNORECASE):
            SystemCommands.media_next()
            return True, f"Следующий трек, {user_title}."

        if re.search(r'\b(предыдущ\w* трек|предыдущ\w* песн\w*|назад трек)\b', command_text, re.IGNORECASE):
            SystemCommands.media_prev()
            return True, f"Предыдущий трек, {user_title}."

        # 11. Media control & Volume
        if re.search(r'\b(пауз\w*|останови музыку|стоп музыка)\b', command_text, re.IGNORECASE):
            SystemCommands.media_play_pause()
            return True, f"Музыка приостановлена, {user_title}."

        if re.search(r'\b(музык\w*|включи музыку|продолжи воспроизведение)\b', command_text, re.IGNORECASE):
            SystemCommands.media_play_pause()
            return True, f"Управляю воспроизведением музыки, {user_title}."

        # Mute / Unmute
        if re.search(r'\b(выключи(?:\s+весь)?\s+звук|отключи(?:\s+весь)?\s+звук|заглуши\s+звук|без\s+звука|включи\s+звук|верни\s+звук|разглуши\s+звук|выключи\s+громкость)\b', command_text, re.IGNORECASE):
            logger.info("Volume mute toggle command executed: '%s'", command_text)
            SystemCommands.volume_mute()
            return True, f"Переключаю режим звука, {user_title}."

        # Volume Up
        if re.search(r'\b(сделай\s+громче|погромче|громче|прибав\w*(?:\s+громкость|\s+звук)?|увелич\w*(?:\s+громкость|\s+звук)|добавь(?:\s+громкость|\s+звук))\b', command_text, re.IGNORECASE):
            logger.info("Volume up command executed: '%s'", command_text)
            for _ in range(5):
                SystemCommands.volume_up()
            return True, f"Громкость увеличена, {user_title}."

        # Volume Down (strict matching; protects against quiet noise / "тишина" / "тихо")
        if re.search(r'\b(сделай\s+тише|потише|тише|убав\w*(?:\s+громкость|\s+звук)?|уменьш\w*(?:\s+громкость|\s+звук)|сбав\w*(?:\s+громкость|\s+звук))\b', command_text, re.IGNORECASE):
            if re.search(r'\b(тишина|тишину|тишины|тихо)\b', command_text, re.IGNORECASE) and not re.search(r'\b(сделай|потише|убав|уменьш|сбав)\b', command_text, re.IGNORECASE):
                pass
            else:
                logger.info("Volume down command executed: '%s'", command_text)
                for _ in range(5):
                    SystemCommands.volume_down()
                return True, f"Громкость уменьшена, {user_title}."

        # 12. Plans & Reminders creation (F3.1)
        plan_create_pattern = re.search(
            r'\b(?:запомни|напомни|запиши|добавь|создай|запланируй|поставь)\b.*?'
            r'\b(?:план\w*|событи\w*|встреч\w*|напоминани\w*|задач\w*|календар\w*|расписани\w*)\b|'
            r'\b(?:запомни|напомни|запиши|запланируй)\b',
            command_text,
            re.IGNORECASE
        )
        if plan_create_pattern:
            parsed = scheduler.parse_natural_datetime(command_text)
            if parsed:
                target_dt, title = parsed
                scheduler.add_plan(title, target_dt)
                self._pending_plan = None
                date_part = target_dt.strftime("%d.%m")
                time_part = target_dt.strftime("%H:%M")
                time_str = f"{date_part} в {time_part}"
                return True, f"Запланировано, {user_title}: событие '{title}' на {time_str}."
            else:
                # Save pending context for multi-turn follow-up (e.g. user follows up with "через пять минут")
                raw_title = re.sub(
                    r'^(?:запомни|напомни|запиши|добавь|создай|запланируй|поставь)\s*(?:в\s+(?:планы|календарь|расписание))?\s*(?:мне)?\s*(?:событие|встречу|напоминание|задачу|план)?[:\s]*',
                    '', command_text, flags=re.IGNORECASE
                ).strip()
                self._pending_plan = {
                    "title": raw_title or "Событие",
                    "expires_at": time.time() + 60.0
                }
                return True, f"{user_title.capitalize()}, укажите, пожалуйста, время напоминания, например: завтра в 15:00 или через 30 минут."

        # 13. Application launch (F2.1)
        open_app_match = re.search(r'\b(?:открой|запусти|включи)\s+(?:программу|приложение)?\s*([а-яa-z0-9\s._\-]+)', command_text, re.IGNORECASE)
        if open_app_match:
            target_raw = open_app_match.group(1).strip()
            # Check if it is a known site first
            default_sites = config.get("default_sites", {})
            if target_raw in default_sites or any(s in target_raw for s in ["ютуб", "гугл", "яндекс", "вк", "сайт", ".com", ".ru"]):
                if SystemCommands.open_website(target_raw):
                    return True, f"Открываю {target_raw}, {user_title}."

            # Otherwise launch application
            if SystemCommands.open_app(target_raw):
                return True, f"Запускаю {target_raw}, {user_title}."

        # 14. Direct site open (F2.2)
        site_match = re.search(r'\b(?:сайт|перейди на|открой сайт)\s+([а-яa-z0-9.\-_/:]+)', command_text, re.IGNORECASE)
        if site_match:
            target_site = site_match.group(1).strip()
            SystemCommands.open_website(target_site)
            return True, f"Открываю {target_site}, {user_title}."

        # 15. Arbitrary AI Questions & Conversational Queries (F7.1)
        ai_question_pattern = re.search(
            r'\b(объясни\w*|что такое|расскажи\w*|кто так\w*|почему|как устроен\w*|'
            r'что ты знаешь|что зна\w*|подскажи\w*|посоветуй\w*|в чем разниц\w*|'
            r'как\b|что\b|какой\b|какая\b|какие\b|где\b|когда\b|зачем\b|можно ли\b|сколько\b)\b',
            command_text,
            re.IGNORECASE
        )
        words_count = len(command_text.split())
        is_conversational = words_count >= 3 and not command_text.startswith(
            ('открой', 'запусти', 'включи', 'создай', 'поставь', 'удали', 'закрой', 'добавь', 'запланируй', 'напомни', 'запомни', 'запиши')
        )

        if ai_question_pattern or is_conversational:
            provider, api_key, _, _ = AIAgent.get_ai_config()
            if api_key and api_key != "ваш_ключ_здесь":
                speaker.speak(f"Секунду, {user_title}, обращаюсь к нейросети...", block=False, is_interim=True)
                return True, AIAgent.ask_ai(command_text)
            elif ai_question_pattern:
                return True, AIAgent.ask_ai(command_text)

        # Default fallback
        return True, self.personality.get_unknown()



# Global dispatcher instance
dispatcher = CommandDispatcher()
