import re
import logging
from typing import Optional, Dict, Any
import requests

from core.config import config
from commands.system_commands import SystemCommands

logger = logging.getLogger(__name__)


class WebSearch:
    """Provides real-time internet search via Serper API with free encyclopedic fallback."""

    SERPER_ENDPOINT = "https://google.serper.dev/search"
    WIKIPEDIA_ENDPOINT = "https://ru.wikipedia.org/w/api.php"

    @classmethod
    def search_serper(cls, query: str, api_key: str) -> Optional[str]:
        """Query Google Search via Serper.dev API (free 2500 requests)."""
        if not api_key or api_key == "ваш_ключ_здесь":
            return None

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "gl": "ru",
            "hl": "ru",
            "num": 4
        }
        try:
            resp = requests.post(cls.SERPER_ENDPOINT, headers=headers, json=payload, timeout=7)
            if resp.status_code == 200:
                data = resp.json()

                # 1. Direct answer box
                if "answerBox" in data:
                    ab = data["answerBox"]
                    if "answer" in ab and ab["answer"]:
                        return str(ab["answer"]).strip()
                    if "snippet" in ab and ab["snippet"]:
                        return str(ab["snippet"]).strip()

                # 2. Knowledge graph summary
                if "knowledgeGraph" in data:
                    kg = data["knowledgeGraph"]
                    desc = kg.get("description")
                    title = kg.get("title")
                    if desc:
                        return f"{title}: {desc}" if title else desc

                # 3. Top organic snippets
                organic = data.get("organic", [])
                snippets = []
                for item in organic[:2]:
                    s = item.get("snippet", "").strip()
                    if s:
                        snippets.append(s)
                if snippets:
                    return " ".join(snippets)
            else:
                logger.warning(f"Serper API error response: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Serper API query failed: {e}")
        return None

    @classmethod
    def search_fallback_wiki(cls, query: str) -> Optional[str]:
        """Free verified factual search via Wikipedia REST API (no API key required)."""
        clean_q = re.sub(r'^(?:найди|поищи|что такое|кто такой|где находится|расскажи про|загугли)\s+', '', query, flags=re.IGNORECASE).strip()
        if not clean_q:
            clean_q = query.strip()

        params = {
            "action": "query",
            "list": "search",
            "srsearch": clean_q,
            "format": "json",
            "utf8": 1,
            "srlimit": 2
        }
        headers = {"User-Agent": "SputnikAssistant/1.0"}
        try:
            resp = requests.get(cls.WIKIPEDIA_ENDPOINT, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                results = resp.json().get("query", {}).get("search", [])
                if results:
                    best = results[0]
                    title = best.get("title", "")
                    raw_snippet = best.get("snippet", "")
                    clean_snippet = re.sub(r'<[^>]+>', '', raw_snippet).strip()
                    # Clean up wiki formatting artifacts
                    clean_snippet = re.sub(r'\s+', ' ', clean_snippet)
                    if clean_snippet:
                        return f"{title}: {clean_snippet}"
        except Exception as e:
            logger.debug(f"Wikipedia search fallback failed: {e}")
        return None

    @classmethod
    def search_and_summarize(cls, query: str, open_browser: bool = True) -> str:
        """Search internet, synthesize concise speech response, and open search results in browser."""
        from core.personality import SputnikPersonality
        title = SputnikPersonality.get_user_title()

        clean_query = query.strip()
        if not clean_query:
            return f"Уточните, пожалуйста, поисковый запрос, {title}."

        # 1. Try Serper API if key is provided
        serper_key = config.get_api_key("SERPER_API_KEY")
        search_result = None
        if serper_key and serper_key != "ваш_ключ_здесь":
            search_result = cls.search_serper(clean_query, serper_key)

        # 2. Fallback to free encyclopedic search
        if not search_result:
            search_result = cls.search_fallback_wiki(clean_query)

        # 3. Always open Google search in browser for user convenience
        if open_browser:
            SystemCommands.search_internet(clean_query)

        # 4. If search found results, synthesize clean short spoken answer
        if search_result:
            # If LLM is enabled, generate crisp natural voice summary
            from modules.ai_agent import AIAgent
            summary = AIAgent.summarize_search(clean_query, search_result)
            if summary:
                return f"Ищу в интернете информацию по запросу '{clean_query}'. {summary} Открываю подробные результаты в браузере, {title}."
            else:
                # Direct sanitized snippet
                short_snippet = search_result[:160].rstrip()
                if len(search_result) > 160:
                    short_snippet += "..."
                return f"Ищу в интернете информацию по запросу '{clean_query}'. По данным поиска: {short_snippet}. Открываю страницу в браузере, {title}."

        return f"Ищу в интернете информацию по запросу '{clean_query}', {title}. Страница открыта в браузере."
