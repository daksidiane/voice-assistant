import os
import io
import base64
import urllib.parse
import logging
from typing import Optional, Tuple
import requests
from PIL import ImageGrab

from core.config import config

logger = logging.getLogger(__name__)


class AIAgent:
    """Handles external AI responses and screen context analysis (F7.1 - F7.2)."""

    DESKTOP_CLASSES = {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
    }

    SENSITIVE_KEYWORDS = [
        "telegram", "whatsapp", "signal", "viber", "discord",
        "keepass", "bitwarden", "1password", "lastpass", "authy", "authenticator",
        "инкогнито", "incognito", "inprivate", "password", "парол",
        "сбербанк", "тинькофф", "альфа-банк", "банк", "конфиденциальн",
        "online-banking", "клиент-банк", "t-bank", "т-банк"
    ]

    @classmethod
    def get_target_window_bbox(cls) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[str]]:
        """
        Identify active foreground window and return (bbox, error_or_guard_message).
        If Desktop or sensitive app is detected, returns (None, user_guard_message).
        """
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title(capitalize=True)
        try:
            import win32gui
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd or not win32gui.IsWindow(hwnd):
                return None, f"{title}, сейчас активен рабочий стол. Пожалуйста, разверните или выберите окно, которое хотите проанализировать."

            class_name = win32gui.GetClassName(hwnd)
            title_text = win32gui.GetWindowText(hwnd).strip()

            # Guardrail 1: If active window is Desktop or Taskbar
            if class_name in cls.DESKTOP_CLASSES or title_text.lower() in ("program manager", ""):
                return None, f"{title}, сейчас активен рабочий стол. Пожалуйста, разверните или выберите окно, которое хотите проанализировать."

            # Guardrail 2: Sensitive application protection
            title_lower = title_text.lower()
            for kw in cls.SENSITIVE_KEYWORDS:
                if kw in title_lower:
                    logger.warning(f"Screen analysis blocked: sensitive window detected ({title_text})")
                    return None, f"{title}, активно конфиденциальное окно. Анализ отменён в целях безопасности."

            # Get active window coordinates (works accurately across multiple monitors)
            rect = win32gui.GetWindowRect(hwnd)  # (left, top, right, bottom)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 50 or height <= 50:
                return None, f"{title}, целевое окно свёрнуто или слишком мало для анализа."

            return rect, None
        except Exception as e:
            logger.debug(f"Window detection fallback: {e}")
            return None, None

    @classmethod
    def get_ai_config(cls) -> Tuple[str, str, str, str]:
        """Return (provider, api_key, model, base_url)."""
        provider = str(config.get("ai.provider", "google")).lower()
        gemini_key = config.get_api_key("GEMINI_API_KEY") or config.get_api_key("GOOGLE_API_KEY")
        openai_key = config.get_api_key("OPENAI_API_KEY")

        if provider == "google" or (gemini_key and not openai_key):
            model = config.get("ai.model", "gemini-3.6-flash")
            if "gpt" in model:
                model = "gemini-3.6-flash"
            return "google", gemini_key, model, ""
        else:
            model = config.get("ai.model", "gpt-4o-mini")
            base_url = config.get("ai.base_url", "https://api.openai.com/v1")
            return "openai", openai_key, model, base_url

    @classmethod
    def _query_gemini(cls, api_key: str, model: str, system_prompt: str, user_text: str, b64_image: Optional[str] = None) -> Optional[str]:
        """Query Google AI Gemini via REST API with automatic model fallback."""
        # Candidates in priority order: official high-quota production models first
        model_candidates = [
            model,
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite"
        ]
        # Deduplicate preserving order
        unique_models = []
        for m in model_candidates:
            if m and m not in unique_models:
                unique_models.append(m)

        parts = [{"text": user_text}]
        if b64_image:
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64_image
                }
            })

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1000,
                "temperature": 0.7
            }
        }
        # Securely pass API key in HTTP header to prevent exposure in query strings and logs
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        req_timeout = 25 if b64_image else 12

        for target_model in unique_models:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=req_timeout)

                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        c_parts = candidates[0].get("content", {}).get("parts", [])
                        if c_parts:
                            full_text = "".join([p.get("text", "") for p in c_parts if "text" in p]).strip()
                            if full_text:
                                # Update config to working model if fallback succeeded
                                if target_model != model:
                                    config.set("ai.model", target_model)
                                return full_text
                elif resp.status_code in (429, 404, 503, 400):
                    logger.warning(f"Gemini model '{target_model}' returned status {resp.status_code}, trying fallback to next model...")
                    continue
                else:
                    logger.warning(f"Gemini API returned status {resp.status_code}")
                    break
            except Exception as e:
                logger.warning(f"Gemini query attempt with model '{target_model}' failed.")
                continue

        return None

    @classmethod
    def _query_openai(cls, api_key: str, base_url: str, model: str, system_prompt: str, user_text: str, b64_image: Optional[str] = None) -> Optional[str]:
        """Query OpenAI or compatible REST endpoint."""
        parsed_url = urllib.parse.urlparse(base_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            logger.warning(f"Invalid AI base URL: {base_url}")
            return None

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        if b64_image:
            user_content = [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                }
            ]
        else:
            user_content = user_text

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 200,
            "temperature": 0.7
        }

        resp = requests.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        else:
            logger.warning(f"OpenAI API returned status {resp.status_code}")
        return None

    @classmethod
    def ask_ai(cls, question: str) -> str:
        """Query LLM with arbitrary user question."""
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()

        provider, api_key, model, base_url = cls.get_ai_config()

        # If no key set, inform user politely
        if not api_key or api_key == "ваш_ключ_здесь":
            provider_name = "Google AI (Gemini)" if provider == "google" else "OpenAI"
            return f"{title.capitalize()}, для ответа на произвольные вопросы необходимо указать ключ {provider_name} в настройках или файле .env."

        system_prompt = (
            f"Вы — голосовой помощник Спутник. Отвечайте строго, лаконично, вежливо на русском языке. "
            f"Обращайтесь к пользователю '{title}' или на 'Вы'. Длина ответа — максимум 2-3 емких предложения для озвучивания голосом."
        )

        try:
            if provider == "google":
                answer = cls._query_gemini(api_key, model, system_prompt, question)
            else:
                answer = cls._query_openai(api_key, base_url, model, system_prompt, question)

            if answer:
                return answer
            else:
                from modules.web_search import WebSearch
                logger.info("LLM unavailable, falling back to web search...")
                search_res = WebSearch.search_and_summarize(question, open_browser=False)
                if search_res:
                    return search_res
                return f"К сожалению, нейросеть временно недоступна из-за лимита запросов, {title}."
        except Exception:
            logger.error("Error querying AI API.")
            return f"Не удалось связаться с сервером искусственного интеллекта, {title}."

    @classmethod
    def summarize_search(cls, query: str, search_context: str) -> Optional[str]:
        """Summarize search results context into 1-2 concise spoken sentences using LLM."""
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()

        provider, api_key, model, base_url = cls.get_ai_config()
        if not api_key or api_key == "ваш_ключ_здесь":
            return None

        system_prompt = (
            f"Вы — голосовой помощник Спутник. Вы отвечаете пользователю голосом. "
            f"Отвечайте исключительно на русском языке, лаконично и емко (1-2 коротких предложения), обращаясь '{title}'."
        )
        user_prompt = (
            f"Пользователь спросил: \"{query}\".\n"
            f"Информация из поисковой системы:\n\"{search_context}\"\n"
            f"Сформулируй краткий прямой ответ на вопрос на основе этих данных для озвучивания."
        )

        try:
            if provider == "google":
                return cls._query_gemini(api_key, model, system_prompt, user_prompt)
            else:
                return cls._query_openai(api_key, base_url, model, system_prompt, user_prompt)
        except Exception as e:
            logger.debug(f"AI search summarization failed: {e}")
            return None

    @classmethod
    def analyze_screen(cls, prompt: str = "Объясни, что сейчас отображено на экране") -> str:
        """Capture active window safely and ask multimodal LLM to describe/analyze it."""
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()

        provider, api_key, model, base_url = cls.get_ai_config()

        if not api_key or api_key == "ваш_ключ_здесь":
            provider_name = "Google AI (Gemini)" if provider == "google" else "OpenAI"
            return f"{title.capitalize()}, для визуального анализа экрана требуется указать ключ {provider_name} в настройках."

        # Guardrail check: active window instead of full desktop/empty screen
        bbox, guard_message = cls.get_target_window_bbox()
        if guard_message:
            return guard_message

        try:
            # Capture only the target active window (supports multi-monitor setups)
            if bbox:
                screenshot = ImageGrab.grab(bbox=bbox, all_screens=True)
            else:
                screenshot = ImageGrab.grab(all_screens=True)

            # Resize and optimize compression to save bandwidth and stay fast
            screenshot.thumbnail((1024, 600))
            buffer = io.BytesIO()
            screenshot.save(buffer, format="JPEG", quality=70)
            b64_img = base64.b64encode(buffer.getvalue()).decode("utf-8")

            system_prompt = (
                f"Вы — голосовой помощник Спутник. Пользователь попросил проанализировать его экран. "
                f"Дайте краткий, четкий и полезный ответ на русском языке (2-3 предложения), обращаясь к пользователю '{title}'."
            )

            if provider == "google":
                answer = cls._query_gemini(api_key, model, system_prompt, prompt, b64_image=b64_img)
            else:
                answer = cls._query_openai(api_key, base_url, model, system_prompt, prompt, b64_image=b64_img)

            if answer:
                return answer
            else:
                return f"Не удалось получить анализ изображения от нейросети, {title}."
        except Exception:
            logger.error("Error capturing or analyzing screen.")
            return f"Произошла ошибка при захвате или анализе экрана, {title}."
