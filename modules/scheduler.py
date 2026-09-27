import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import re

from core.config import config, PLANS_PATH
from core.event_bus import event_bus

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "января": 1, "январь": 1,
    "февраля": 2, "февраль": 2,
    "марта": 3, "март": 3,
    "апреля": 4, "апрель": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июнь": 6,
    "июля": 7, "июль": 7,
    "августа": 8, "август": 8,
    "сентября": 9, "сентябрь": 9,
    "октября": 10, "октябрь": 10,
    "ноября": 11, "ноябрь": 11,
    "декабря": 12, "декабрь": 12
}


def parse_dt_safe(dt_str: str) -> datetime:
    """Safely parse datetime supporting DD-MM-YYYY, DD.MM.YYYY, and YYYY-MM-DD."""
    if not dt_str:
        return datetime.max
    for fmt in ("%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%d-%m-%y %H:%M", "%d.%m.%y %H:%M"):
        try:
            return datetime.strptime(str(dt_str).strip(), fmt)
        except Exception:
            continue
    return datetime.max


def normalize_russian_time_words(text: str) -> str:
    """Normalize Russian numeral words into digit format for time parsing."""
    t = text.lower().strip()

    # Pre-replace special idioms
    t = re.sub(r'\bчерез\s+полчаса\b', 'через 30 минут', t)
    t = re.sub(r'\bчерез\s+полтора\s+часа\b', 'через 90 минут', t)
    t = re.sub(r'\bчерез\s+(?:одну\s+)?минуту\b', 'через 1 минуту', t)
    t = re.sub(r'\bчерез\s+(?:один\s+)?час\b', 'через 1 час', t)

    # Word numerals lookup
    nums = {
        "ноль ноль": "00", "ноль": "0", "нуль": "0",
        "один": "1", "одна": "1", "одну": "1",
        "два": "2", "две": "2", "три": "3", "четыре": "4", "пять": "5",
        "шесть": "6", "семь": "7", "восемь": "8", "девять": "9", "десять": "10",
        "одиннадцать": "11", "двенадцать": "12", "тринадцать": "13", "четырнадцать": "14",
        "пятнадцать": "15", "шестнадцать": "16", "семнадцать": "17", "восемнадцать": "18",
        "девятнадцать": "19", "двадцать": "20", "тридцать": "30", "сорок": "40", "пятьдесят": "50"
    }

    # Handle compound tens like "двадцать один" -> "21", "девятнадцать сорок пять" -> "19 45"
    # 1. First convert "ноль ноль"
    t = re.sub(r'\bноль\s+ноль\b', '00', t)

    # 2. Time expressions like "девятнадцать ноль ноль" -> "19:00", "девятнадцать тридцать" -> "19:30"
    for word_h, val_h in [
        ("ноль", "00"), ("один", "01"), ("два", "02"), ("три", "03"), ("четыре", "04"),
        ("пять", "05"), ("шесть", "06"), ("семь", "07"), ("восемь", "08"), ("девять", "09"),
        ("десять", "10"), ("одиннадцать", "11"), ("двенадцать", "12"), ("тринадцать", "13"),
        ("четырнадцать", "14"), ("пятнадцать", "15"), ("шестнадцать", "16"), ("семнадцать", "17"),
        ("восемнадцать", "18"), ("девятнадцать", "19"), ("двадцать", "20"), ("двадцать один", "21"),
        ("двадцать два", "22"), ("двадцать три", "23")
    ]:
        for word_m, val_m in [
            ("00", "00"), ("ноль ноль", "00"), ("ноль пять", "05"), ("десять", "10"),
            ("пятнадцать", "15"), ("двадцать", "20"), ("двадцать пять", "25"),
            ("тридцать", "30"), ("тридцать пять", "35"), ("сорок", "40"),
            ("сорок пять", "45"), ("пятьдесят", "50"), ("пятьдесят пять", "55")
        ]:
            pattern = rf'\b{word_h}\s+{word_m}\b'
            t = re.sub(pattern, f"{val_h}:{val_m}", t)

    # 3. Phrases with "часа / часов / вечера / утра / дня"
    day_eve_conversions = [
        (r'\b(?:в\s+)?(час|один)\s+(?:дня|ночи)\b', 'в 13:00'),
        (r'\b(?:в\s+)?(два|две)\s+(?:часа\s+)?дня\b', 'в 14:00'),
        (r'\b(?:в\s+)?три\s+(?:часа\s+)?дня\b', 'в 15:00'),
        (r'\b(?:в\s+)?четыре\s+(?:часа\s+)?дня\b', 'в 16:00'),
        (r'\b(?:в\s+)?пять\s+(?:часов\s+)?вечера\b', 'в 17:00'),
        (r'\b(?:в\s+)?шесть\s+(?:часов\s+)?вечера\b', 'в 18:00'),
        (r'\b(?:в\s+)?семь\s+(?:часов\s+)?вечера\b', 'в 19:00'),
        (r'\b(?:в\s+)?восемь\s+(?:часов\s+)?вечера\b', 'в 20:00'),
        (r'\b(?:в\s+)?девять\s+(?:часов\s+)?вечера\b', 'в 21:00'),
        (r'\b(?:в\s+)?десять\s+(?:часов\s+)?вечера\b', 'в 22:00'),
        (r'\b(?:в\s+)?одиннадцать\s+(?:часов\s+)?вечера\b', 'в 23:00'),
    ]
    for pattern, repl in day_eve_conversions:
        t = re.sub(pattern, repl, t)

    # 4. Standalone numerals in phrases like "через пять минут" or "в семь часов"
    for w_ten, v_ten in [("двадцать", 20), ("тридцать", 30), ("сорок", 40), ("пятьдесят", 50)]:
        for w_unit, v_unit in [("один", 1), ("два", 2), ("две", 2), ("три", 3), ("четыре", 4),
                               ("пять", 5), ("шесть", 6), ("семь", 7), ("восемь", 8), ("девять", 9)]:
            t = re.sub(rf'\b{w_ten}\s+{w_unit}\b', str(v_ten + v_unit), t)

    # Replace individual numerals
    for w, num_val in sorted(nums.items(), key=lambda x: -len(x[0])):
        t = re.sub(rf'\b{w}\b', str(num_val), t)

    return t


class Scheduler:
    """Manages events, reminders, and auto-notifications for SPUTNIK."""

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or PLANS_PATH
        self.plans: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._checker_thread = threading.Thread(target=self._run_checker, daemon=True)
        self.load()
        self._checker_thread.start()

    def _sort_plans(self) -> None:
        """Sort in-memory plans chronologically by datetime."""
        self.plans.sort(key=lambda p: parse_dt_safe(p.get("datetime", "")))

    def load(self) -> None:
        """Load plans from JSON storage and sort chronologically."""
        with self._lock:
            if self.storage_path.exists():
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        self.plans = json.load(f)
                    self._sort_plans()
                except Exception as e:
                    logger.error(f"Failed to load plans from {self.storage_path}: {e}")
                    self.plans = []
            else:
                self.plans = []

    def save(self) -> None:
        """Save plans to JSON storage."""
        with self._lock:
            try:
                self._sort_plans()
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self.plans, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Failed to save plans: {e}")

    def add_plan(self, title: str, dt: datetime) -> Dict[str, Any]:
        """Add a planned event with target datetime in DD-MM-YYYY HH:MM format."""
        dt_str = dt.strftime("%d-%m-%Y %H:%M")
        # Sanitize and truncate title to prevent unbounded storage or control character injection
        clean_title = re.sub(r'[\r\n\0]', ' ', title).strip()[:200]
        if not clean_title:
            clean_title = "Событие"

        with self._lock:
            next_id = max([p.get("id", 0) for p in self.plans], default=0) + 1
            plan = {
                "id": next_id,
                "title": clean_title,
                "datetime": dt_str,
                "reminded_1h": False,
                "reminded_event": False
            }
            self.plans.append(plan)
            self._sort_plans()
        self.save()
        logger.info(f"Added new plan: #{next_id} '{clean_title}' at {dt_str}")
        return plan

    def delete_plan(self, plan_id: int) -> bool:
        """Delete a plan by ID."""
        with self._lock:
            initial_len = len(self.plans)
            self.plans = [p for p in self.plans if p.get("id") != plan_id]
            changed = len(self.plans) < initial_len
            if changed:
                self._sort_plans()
        if changed:
            self.save()
        return changed

    def get_all_plans(self, sorted_by_date: bool = True) -> List[Dict[str, Any]]:
        """Return all plans, optionally sorted chronologically by datetime."""
        with self._lock:
            plans_copy = [dict(p) for p in self.plans]

        if sorted_by_date:
            plans_copy.sort(key=lambda p: parse_dt_safe(p.get("datetime", "")))
        return plans_copy

    def get_upcoming_plans(self) -> List[Dict[str, Any]]:
        """Return all upcoming plans sorted chronologically by datetime."""
        now = datetime.now()
        upcoming = []
        with self._lock:
            for p in self.plans:
                try:
                    p_dt = parse_dt_safe(p.get("datetime", ""))
                    if p_dt == datetime.max:
                        continue
                    # Skip plans that already fired in the past
                    if p.get("reminded_event", False) and p_dt < now:
                        continue
                    if p_dt >= now - timedelta(minutes=1):
                        upcoming.append(dict(p))
                except Exception:
                    continue
        upcoming.sort(key=lambda x: parse_dt_safe(x.get("datetime", "")))
        return upcoming

    def parse_natural_datetime(self, text: str) -> Optional[Tuple[datetime, str]]:
        """
        Parse Russian voice command for date/time and event title.
        Returns (datetime, title) or None.
        Examples:
        - "запомни: встреча с клиентом завтра в 15:00"
        - "напомни сделать отчет через 30 минут"
        - "добавь событие девятнадцать ноль ноль тренировка"
        - "напомни обед через пять минут"
        """
        if not text or not text.strip():
            return None

        # 1. Convert word numerals to digits
        normalized = normalize_russian_time_words(text.strip())
        now = datetime.now()

        # 2. Clean introductory trigger words
        intro_regex = (
            r'^(?:добавь(?:\s+в\s+(?:планы|календарь|расписание))?|создай|запланируй|поставь|запомни|напомни|запиши)'
            r'\s*(?:мне)?\s*(?:новое|новую)?\s*(?:событие|встречу|напоминание|задачу|план)?[:\s]*'
        )
        clean_text = re.sub(intro_regex, '', normalized, flags=re.IGNORECASE).strip()

        # 3. Relative time: "через X минут/часов"
        rel_match = re.search(r'\bчерез\s+(\d+)\s*(минут[уы]?|мин|часа?|часов|ч)\b', clean_text, re.IGNORECASE)
        if rel_match:
            val = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if "мин" in unit:
                dt = now + timedelta(minutes=val)
            else:
                dt = now + timedelta(hours=val)
            title = re.sub(r'\bчерез\s+\d+\s*(минут[уы]?|мин|часа?|часов|ч)\b', '', clean_text, flags=re.IGNORECASE).strip()
            title = re.sub(r'\s+', ' ', title).strip(" :-,")
            return dt, title or "Напоминание"

        # 4. Absolute date offset: "завтра / послезавтра / сегодня"
        day_offset = 0
        if "послезавтра" in clean_text.lower():
            day_offset = 2
            clean_text = re.sub(r'\bпослезавтра\b', '', clean_text, flags=re.IGNORECASE)
        elif "завтра" in clean_text.lower():
            day_offset = 1
            clean_text = re.sub(r'\bзавтра\b', '', clean_text, flags=re.IGNORECASE)
        elif "сегодня" in clean_text.lower():
            day_offset = 0
            clean_text = re.sub(r'\bсегодня\b', '', clean_text, flags=re.IGNORECASE)

        # 5. Time match: "в 19:00", "в 19 00", or without "в" -> "19:00", "19 00"
        time_match = re.search(r'\b(?:в\s+)?(\d{1,2})[:\s.]+(\d{2})\b', clean_text, re.IGNORECASE)
        if not time_match:
            time_match = re.search(r'\bв\s+(\d{1,2})\s*(часа|часов)?\b', clean_text, re.IGNORECASE)

        if time_match:
            hour = int(time_match.group(1))
            minute = 0
            if time_match.lastindex >= 2 and time_match.group(2) and time_match.group(2).isdigit():
                minute = int(time_match.group(2))

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                target_date = (now + timedelta(days=day_offset)).date()
                dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                # If "сегодня" or no day specified and time already passed today, assume tomorrow
                if day_offset == 0 and dt < now:
                    dt += timedelta(days=1)

                # Remove matched time from text to extract title
                title = clean_text[:time_match.start()] + " " + clean_text[time_match.end():]
                title = re.sub(r'\b(часов|часа|минут|минуты|в|на)\b', ' ', title, flags=re.IGNORECASE)
                title = re.sub(r'\s+', ' ', title).strip(" :-,")
                return dt, title or "Событие"

        return None

    def _run_checker(self):
        """Background thread checking upcoming reminders every 20 seconds."""
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                modified = False

                with self._lock:
                    for plan in self.plans:
                        p_dt = parse_dt_safe(plan.get("datetime", ""))
                        if p_dt == datetime.max:
                            continue

                        diff = (p_dt - now).total_seconds()
                        user_title = config.get("assistant.user_title", "сэр")

                        # F3.3: 1 hour advance notification (triggers at 60 minutes / <= 3620 seconds)
                        if 2400 <= diff <= 3620 and not plan.get("reminded_1h", False):
                            plan["reminded_1h"] = True
                            modified = True
                            mins_left = int(round(diff / 60))
                            if mins_left == 60:
                                time_phrase = "через один час"
                            elif mins_left == 1:
                                time_phrase = "через одну минуту"
                            elif 2 <= mins_left % 10 <= 4 and not (11 <= mins_left % 100 <= 14):
                                time_phrase = f"через {mins_left} минуты"
                            else:
                                time_phrase = f"через {mins_left} минут"

                            msg = f"{user_title.capitalize()}, напоминаю: {time_phrase} запланировано событие: {plan['title']} в {p_dt.strftime('%H:%M')}."
                            event_bus.publish("reminder_alert", {"plan": plan, "text": msg, "is_1h": True})

                        # Event exact time notification: triggers strictly when event time arrives (diff <= 0, up to 120s past)
                        if -120 <= diff <= 0 and not plan.get("reminded_event", False):
                            plan["reminded_event"] = True
                            modified = True
                            msg = f"{user_title.capitalize()}, наступило время запланированного события: {plan['title']}."
                            event_bus.publish("reminder_alert", {"plan": plan, "text": msg, "is_1h": False})

                if modified:
                    self.save()

            except Exception as e:
                logger.error(f"Error in scheduler checker loop: {e}", exc_info=True)

            self._stop_event.wait(5)

    def stop(self):
        self._stop_event.set()


# Global scheduler instance
scheduler = Scheduler()
