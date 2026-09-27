import random
import re
from datetime import datetime
from typing import List

from core.config import config


class SputnikPersonality:
    """Manages conversational style, politeness and speech variations of SPUTNIK."""

    WAKE_RESPONSES = [
        "Слушаю вас, сэр.",
        "Да, сэр?",
        "Всегда к вашим услугам, сэр.",
        "Чем могу помочь, сэр?",
        "На связи, сэр.",
        "Готов к выполнению указаний, сэр."
    ]

    SUCCESS_RESPONSES = [
        "Сделано, сэр.",
        "Задание выполнено, сэр.",
        "Всё готово, сэр.",
        "Приказ выполнен, сэр."
    ]

    ERROR_RESPONSES = [
        "К сожалению, не удалось выполнить команду, сэр.",
        "Произошла ошибка при выполнении операции, сэр.",
        "Действие не удалось завершить, сэр.",
        "Возникли непредвиденные трудности, сэр."
    ]

    UNKNOWN_RESPONSES = [
        "Не совсем понял команду, сэр. Повторите, пожалуйста.",
        "Не удалось распознать ваше указание, сэр.",
        "Прошу прощения, сэр, повторите ещё раз.",
        "Команда не распознана, сэр."
    ]

    EXIT_RESPONSES = [
        "Завершаю работу, сэр. Всегда к вашим услугам.",
        "До свидания, сэр. Буду на связи.",
        "Отключаюсь, сэр. Хорошего вам дня.",
        "Система переходит в автономный режим. До встречи, сэр."
    ]

    BREAK_REMINDER_RESPONSES = [
        "Сэр, вы непрерывно работаете уже более трёх часов. Настоятельно рекомендую сделать небольшую паузу и размяться.",
        "Прошу прощения, сэр, но продолжительность непрерывной работы превысила три часа. Рекомендую отвлечься от экрана и выпить воды.",
        "Сэр, ваше здоровье в приоритете. Сделайте перерыв на 10-15 минут, это повысит вашу продуктивность."
    ]

    @classmethod
    def get_user_title(cls, capitalize: bool = False) -> str:
        """Get polite address title according to user gender ('сэр' or 'госпожа')."""
        gender = str(config.get("assistant.user_gender", "male")).lower()
        if gender == "female":
            title = "госпожа"
        elif gender == "male":
            title = "сэр"
        else:
            title_cfg = str(config.get("assistant.user_title", "сэр")).lower()
            title = "госпожа" if title_cfg == "госпожа" else "сэр"
        return title.capitalize() if capitalize else title

    @classmethod
    def apply_title(cls, text: str) -> str:
        """
        Dynamically format address title in any string according to configured user gender.
        If female: 'сэр' -> 'госпожа', 'Сэр' -> 'Госпожа'.
        If male: 'госпожа' -> 'сэр', 'Госпожа' -> 'Сэр'.
        """
        if not text:
            return ""

        gender = str(config.get("assistant.user_gender", "male")).lower()
        if gender == "female":
            text = re.sub(r'\bСэр\b', "Госпожа", text)
            text = re.sub(r'\bсэр\b', "госпожа", text)
        elif gender == "male":
            text = re.sub(r'\bГоспожа\b', "Сэр", text)
            text = re.sub(r'\bгоспожа\b', "сэр", text)
        else:
            title_cfg = str(config.get("assistant.user_title", "сэр")).lower()
            if title_cfg == "госпожа":
                text = re.sub(r'\bСэр\b', "Госпожа", text)
                text = re.sub(r'\bсэр\b', "госпожа", text)
            else:
                text = re.sub(r'\bГоспожа\b', "Сэр", text)
                text = re.sub(r'\bгоспожа\b', "сэр", text)

        return text

    @classmethod
    def get_wake_greeting(cls) -> str:
        return cls.apply_title(random.choice(cls.WAKE_RESPONSES))

    @classmethod
    def get_success(cls) -> str:
        return cls.apply_title(random.choice(cls.SUCCESS_RESPONSES))

    @classmethod
    def get_error(cls, detail: str = "") -> str:
        base = random.choice(cls.ERROR_RESPONSES)
        if detail:
            res = f"{base} {detail}"
        else:
            res = base
        return cls.apply_title(res)

    @classmethod
    def get_unknown(cls) -> str:
        return cls.apply_title(random.choice(cls.UNKNOWN_RESPONSES))

    @classmethod
    def get_exit(cls) -> str:
        return cls.apply_title(random.choice(cls.EXIT_RESPONSES))

    @classmethod
    def get_break_reminder(cls) -> str:
        return cls.apply_title(random.choice(cls.BREAK_REMINDER_RESPONSES))

    @classmethod
    def get_startup_greeting(cls) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            time_greeting = "Доброе утро, сэр."
        elif 12 <= hour < 18:
            time_greeting = "Добрый день, сэр."
        elif 18 <= hour < 23:
            time_greeting = "Добрый вечер, сэр."
        else:
            time_greeting = "Доброй ночи, сэр."
        res = f"{time_greeting} Все системы Спутник активны и готовы к работе."
        return cls.apply_title(res)

