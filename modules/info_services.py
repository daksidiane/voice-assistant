import os
import re
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional
import requests

from core.config import config

logger = logging.getLogger(__name__)

MONTHS_RU = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

DAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье"
]


class InfoServices:
    """Provides time/date, weather, exchange rates and news."""

    @classmethod
    def get_time_and_date(cls) -> str:
        """Return humanized current time and date in Russian spelled out as words."""
        now = datetime.now()
        day_str = DAYS_RU[now.weekday()]
        month_str = MONTHS_RU[now.month]
        
        hours = now.hour
        minutes = now.minute

        HOURS_RU = {
            0: "ноль часов", 1: "один час", 2: "два часа", 3: "три часа", 4: "четыре часа",
            5: "пять часов", 6: "шесть часов", 7: "семь часов", 8: "восемь часов", 9: "девять часов",
            10: "десять часов", 11: "одиннадцать часов", 12: "двенадцать часов", 13: "тринадцать часов",
            14: "четырнадцать часов", 15: "пятнадцать часов", 16: "шестнадцать часов", 17: "семнадцать часов",
            18: "восемнадцать часов", 19: "девятнадцать часов", 20: "двадцать часов", 21: "двадцать один час",
            22: "двадцать два часа", 23: "двадцать три часа"
        }

        UNITS_FEM = ["", "одна минута", "две минуты", "три минуты", "четыре минуты", "пять минут",
                     "шесть минут", "семь минут", "восемь минут", "девять минут"]
        TEENS_FEM = {
            10: "десять минут", 11: "одиннадцать минут", 12: "двенадцать минут", 13: "тринадцать минут",
            14: "четырнадцать минут", 15: "пятнадцать минут", 16: "шестнадцать минут",
            17: "семнадцать минут", 18: "восемнадцать минут", 19: "девятнадцать минут"
        }
        TENS_WORDS = {2: "двадцать", 3: "тридцать", 4: "сорок", 5: "пятьдесят"}

        h_str = HOURS_RU.get(hours, f"{hours} часов")
        if minutes == 0:
            time_phrase = f"{h_str} ровно"
        elif 10 <= minutes <= 19:
            time_phrase = f"{h_str} {TEENS_FEM[minutes]}"
        elif minutes < 10:
            time_phrase = f"{h_str} {UNITS_FEM[minutes]}"
        else:
            tens = minutes // 10
            units = minutes % 10
            if units == 0:
                time_phrase = f"{h_str} {TENS_WORDS[tens]} минут"
            else:
                time_phrase = f"{h_str} {TENS_WORDS[tens]} {UNITS_FEM[units]}"

        time_phrase = time_phrase.lower()
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()
        return f"Сейчас {time_phrase}, {day_str}, {now.day} {month_str}, {title}."

    @classmethod
    def get_weather(cls, city: Optional[str] = None) -> str:
        """Fetch weather via OpenWeatherMap or fallback to open-meteo."""
        if not city:
            city = config.get("info.weather_default_city", "Москва")
        city = city.strip()
            
        api_key = config.get_api_key("OPENWEATHER_API_KEY")
        if api_key and api_key != "ваш_ключ_здесь":
            try:
                # Use parameterized requests to prevent URL injection and prevent key leakage in exception logs
                resp = requests.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": city, "appid": api_key, "units": "metric", "lang": "ru"},
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    temp = round(data["main"]["temp"])
                    desc = data["weather"][0]["description"]
                    humidity = data["main"]["humidity"]
                    wind = int(round(data["wind"]["speed"]))
                    wind_str = cls._format_wind(wind)
                    return f"В городе {city} сейчас {desc}, температура {temp} градусов цельсия, влажность {humidity} процентов, ветер {wind_str}, сэр."
            except Exception:
                # Do not log exception object directly to avoid leaking API key contained in query parameters
                logger.warning(f"OpenWeatherMap request failed for city '{city}'")

        # Fallback to Open-Meteo geocoding + weather (no key required!)
        try:
            geo_resp = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "ru"},
                timeout=5
            ).json()
            if "results" in geo_resp and len(geo_resp["results"]) > 0:
                loc = geo_resp["results"][0]
                lat, lon = loc["latitude"], loc["longitude"]
                city_name = loc.get("name", city)

                m_resp = requests.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
                    },
                    timeout=5
                ).json()
                current = m_resp.get("current", {})
                temp = round(current.get("temperature_2m", 0))
                humidity = current.get("relative_humidity_2m", 0)
                wind = int(round(current.get("wind_speed_10m", 0) / 3.6)) # km/h to m/s
                wind_str = cls._format_wind(wind)
                
                # Weather code mapping
                wcode = current.get("weather_code", 0)
                desc = "ясно"
                if wcode in [1, 2, 3]:
                    desc = "переменная облачность"
                elif wcode in [45, 48]:
                    desc = "туманно"
                elif wcode in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
                    desc = "дождь"
                elif wcode in [71, 73, 75, 85, 86]:
                    desc = "снег"
                elif wcode >= 95:
                    desc = "гроза"

                return f"В городе {city_name} сейчас {desc}, температура {temp} градусов цельсия, влажность {humidity} процентов, скорость ветра {wind_str}, сэр."
        except Exception as e:
            logger.error(f"Weather fallback failed: {e}")

        return f"К сожалению, не удалось получить сводку погоды для города {city}, сэр."

    @staticmethod
    def _format_wind(speed: int) -> str:
        """Return grammatically correct Russian phrasing for wind speed."""
        if 11 <= (speed % 100) <= 19:
            return f"{speed} метров в секунду"
        rem = speed % 10
        if rem == 1:
            return f"{speed} метр в секунду"
        elif rem in (2, 3, 4):
            return f"{speed} метра в секунду"
        return f"{speed} метров в секунду"

    CURRENCY_MAP = {
        "USD": ["доллар", "бакс", "usd"],
        "EUR": ["евро", "eur"],
        "CNY": ["юан", "cny", "китайск"],
        "KZT": ["тенге", "казахстан", "kzt"],
        "TRY": ["лир", "турецк", "try"],
        "AED": ["дирхам", "оаэ", "эмират", "aed"],
        "BYN": ["белорус", "byn"],
        "GEL": ["лари", "грузи", "gel"],
        "AMD": ["драм", "армян", "amd"],
        "GBP": ["фунт", "стерлинг", "английск", "gbp"],
        "JPY": ["иен", "японск", "jpy"],
        "CHF": ["франк", "швейцарск", "chf"],
        "THB": ["бат", "тайск", "thb"],
        "KGS": ["сом", "киргиз", "кыргыз", "kgs"],
        "UZS": ["сум", "узбек", "uzs"],
        "INR": ["рупи", "индийск", "inr"],
        "PLN": ["злоты", "польск", "pln"],
        "CZK": ["крон", "чешск", "czk"],
        "BRL": ["реал", "бразиль", "brl"],
        "EGP": ["египет", "egp"],
        "AZN": ["манат", "азербайджан", "azn"],
        "RSD": ["динар", "сербск", "rsd"],
        "KRW": ["вон", "корейск", "krw"],
        "ILS": ["шекел", "израил", "ils"],
    }

    CURRENCY_INFO_RU = {
        "USD": ("доллар США", "доллара", "долларов"),
        "EUR": ("евро", "евро", "евро"),
        "CNY": ("китайский юань", "юаня", "китайских юаней"),
        "KZT": ("казахстанский тенге", "тенге", "казахстанских тенге"),
        "TRY": ("турецкая лира", "лиры", "турецких лир"),
        "AED": ("дирхам ОАЭ", "дирхама", "дирхамов ОАЭ"),
        "BYN": ("белорусский рубль", "белорусского рубля", "белорусских рублей"),
        "GEL": ("грузинский лари", "лари", "лари"),
        "AMD": ("армянский драм", "драма", "армянских драмов"),
        "GBP": ("британский фунт", "фунта", "британских фунтов"),
        "JPY": ("японская иена", "иены", "японских иен"),
        "CHF": ("швейцарский франк", "франка", "швейцарских франков"),
        "THB": ("тайский бат", "бата", "тайских батов"),
        "KGS": ("киргизский сом", "сома", "киргизских сомов"),
        "UZS": ("узбекский сум", "сума", "узбекских сумов"),
        "INR": ("индийская рупия", "рупии", "индийских рупий"),
        "PLN": ("польский злотый", "злотого", "польских злотых"),
        "CZK": ("чешская крона", "кроны", "чешских крон"),
        "BRL": ("бразильский реал", "реала", "бразильских реалов"),
        "EGP": ("египетский фунт", "египетского фунта", "египетских фунтов"),
        "AZN": ("азербайджанский манат", "маната", "азербайджанских манатов"),
        "RSD": ("сербский динар", "динара", "сербских динаров"),
        "KRW": ("южнокорейская вона", "воны", "южнокорейских вон"),
        "ILS": ("израильский шекель", "шекеля", "израильских шекелей"),
    }

    NOMINALS = {
        "KZT": 100, "AMD": 100, "JPY": 100, "KGS": 100,
        "UZS": 10000, "INR": 100, "KRW": 1000, "THB": 10
    }

    @classmethod
    def get_exchange_rates(cls, query: Optional[str] = None) -> str:
        """Fetch foreign currency rates against Russian Ruble supporting all major world currencies."""
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()

        # 1. Detect if a specific currency was requested
        target_code = None
        if query:
            q_lower = query.lower()
            for code, keywords in cls.CURRENCY_MAP.items():
                if any(kw in q_lower for kw in keywords):
                    target_code = code
                    break

        # 2. Fetch exchange rates (open.er-api.com primary with CBR fallback)
        rates_per_rub: Dict[str, float] = {}
        try:
            resp = requests.get("https://open.er-api.com/v6/latest/RUB", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                raw_rates = data.get("rates", {})
                for c_code, r_val in raw_rates.items():
                    if r_val and r_val > 0:
                        rates_per_rub[c_code] = 1.0 / r_val
        except Exception as e:
            logger.debug(f"open.er-api failed: {e}, trying CBR fallback")

        if not rates_per_rub:
            try:
                resp = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=5)
                if resp.status_code == 200:
                    valute = resp.json().get("Valute", {})
                    for c_code, v_obj in valute.items():
                        nominal = v_obj.get("Nominal", 1)
                        val = v_obj.get("Value", 0)
                        if nominal and val:
                            rates_per_rub[c_code] = val / nominal
            except Exception as e:
                logger.error(f"CBR fallback failed: {e}")

        if not rates_per_rub:
            return f"К сожалению, не удалось получить актуальные курсы валют, {title}."

        def _format_currency(code: str) -> Optional[str]:
            if code not in rates_per_rub:
                return None
            rate_1 = rates_per_rub[code]
            nominal = cls.NOMINALS.get(code, 1)
            val = round(rate_1 * nominal, 2)
            nm = cls.CURRENCY_INFO_RU.get(code, (code, code, code))
            prefix = f"1 {nm[0]}" if nominal == 1 else f"{nominal} {nm[2]}"
            return f"{prefix}: {val} рублей"

        # 3. If specific currency requested
        if target_code and target_code in rates_per_rub:
            formatted = _format_currency(target_code)
            return f"Курс валюты {formatted}, {title}."

        # 4. Otherwise report popular basket
        default_basket = config.get("info.exchange_currencies", ["USD", "EUR", "CNY", "AED", "KZT", "TRY"])
        lines = []
        for c in default_basket:
            f_str = _format_currency(c)
            if f_str:
                lines.append(f_str)

        if lines:
            return f"Актуальный курс валют: {', '.join(lines)}, {title}."
        return f"К сожалению, не удалось сформировать курсы валют, {title}."

    @classmethod
    def get_news(cls, max_items: int = 3) -> str:
        """Fetch latest news headlines from RSS with fallbacks."""
        sources = [
            config.get("info.news_rss_url", "https://ria.ru/export/rss2/archive/index.xml"),
            "https://feeds.bbci.co.uk/russian/rss.xml",
            "https://lenta.ru/rss/news"
        ]

        for rss_url in sources:
            if not (rss_url.startswith("http://") or rss_url.startswith("https://")):
                continue
            try:
                resp = requests.get(rss_url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    content = resp.content
                    # Protection against XML entity expansion / Billion Laughs attacks
                    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
                        logger.warning(f"Skipping RSS feed from {rss_url}: DTD/ENTITY declarations detected")
                        continue
                    root = ET.fromstring(content)
                    items = root.findall(".//item")
                    headlines = []
                    for item in items[:max_items]:
                        title_elem = item.find("title")
                        if title_elem is not None and title_elem.text:
                            title = re.sub(r'<[^>]+>', '', title_elem.text).strip()
                            headlines.append(title)
                    if headlines:
                        joined = ". Вторая новость: ".join(headlines)
                        return f"Главные новости на данный момент, сэр. Первая новость: {joined}."
            except Exception as e:
                logger.debug(f"News RSS {rss_url} failed: {e}")

        return "К сожалению, не удалось загрузить новостную ленту, сэр."
