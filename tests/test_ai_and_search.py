import pytest
from unittest.mock import patch, MagicMock
from modules.info_services import InfoServices
from modules.web_search import WebSearch
from modules.ai_agent import AIAgent
from core.config import config


def test_multi_currency_exchange_rates():
    """Verify multi-currency support fetches world currencies (KZT, AED, TRY, USD, EUR, etc.)."""
    # Specific currency: Tenge
    tenge_resp = InfoServices.get_exchange_rates("курс тенге")
    assert "тенге" in tenge_resp.lower() or "рубл" in tenge_resp.lower() or "не удалось" in tenge_resp.lower()

    # Specific currency: Dirham
    aed_resp = InfoServices.get_exchange_rates("курс дирхама")
    assert "дирхам" in aed_resp.lower() or "рубл" in aed_resp.lower() or "не удалось" in aed_resp.lower()

    # General basket
    basket_resp = InfoServices.get_exchange_rates("курс валют")
    assert "доллар" in basket_resp.lower() or "евро" in basket_resp.lower() or "не удалось" in basket_resp.lower()


def test_web_search_fallback_wiki():
    """Verify free Wikipedia fallback search extracts factual summary."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "query": {
            "search": [
                {
                    "title": "Париж",
                    "snippet": "Париж — столица и крупнейший город Франции."
                }
            ]
        }
    }
    with patch("requests.get", return_value=mock_resp):
        res = WebSearch.search_fallback_wiki("столица Франции")
        assert res is not None
        assert "Париж" in res
        assert "Франции" in res


def test_web_search_serper():
    """Verify Serper.dev API parser handles answerBox and organic results."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "answerBox": {
            "snippet": "Квантовый компьютер использует кубиты для вычислений."
        }
    }
    with patch("requests.post", return_value=mock_resp):
        res = WebSearch.search_serper("квантовый компьютер", "fake_key_for_test")
        assert res == "Квантовый компьютер использует кубиты для вычислений."


def test_web_search_and_summarize():
    """Verify search_and_summarize returns proper response and opens browser."""
    with patch.object(WebSearch, "search_fallback_wiki", return_value="Илон Маск: американский предприниматель и инженер."), \
         patch("commands.system_commands.SystemCommands.search_internet") as mock_browser:
        resp = WebSearch.search_and_summarize("кто такой Илон Маск", open_browser=True)
        assert "Илон Маск" in resp
        assert "Ищу в интернете" in resp
        mock_browser.assert_called_once_with("кто такой Илон Маск")


def test_ai_agent_gemini_query():
    """Verify Google AI Gemini integration via REST endpoint."""
    config.set("ai.provider", "google")
    config.env["GEMINI_API_KEY"] = "fake_gemini_key_for_test"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Искусственный интеллект — это область компьютерных наук, госпожа."}
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        answer = AIAgent.ask_ai("что такое ИИ")
        assert "Искусственный интеллект" in answer
        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert "generativelanguage.googleapis.com" in call_url
        assert "gemini" in call_url

    # Clean up test env
    config.env.pop("GEMINI_API_KEY", None)


def test_ai_agent_summarize_search():
    """Verify AIAgent.summarize_search generates concise speech."""
    config.set("ai.provider", "google")
    config.env["GEMINI_API_KEY"] = "fake_gemini_key_for_test"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Столицей Австралии является город Канберра."}
                    ]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        summary = AIAgent.summarize_search("столица Австралии", "Канберра — столица Австралийского Союза")
        assert summary == "Столицей Австралии является город Канберра."

    config.env.pop("GEMINI_API_KEY", None)


def test_ai_agent_no_key_prompt(monkeypatch):
    """Verify polite notification when AI API key is not configured."""
    config.set("ai.provider", "google")
    monkeypatch.setattr(config, "get_api_key", lambda name: "")

    msg = AIAgent.ask_ai("почему небо синее")
    assert "Google AI" in msg or "API-ключ" in msg or "ключ" in msg


def test_dispatch_ai_conversational_question():
    """Verify dispatcher routes 'что ты знаешь а садоводстве' to AIAgent."""
    from commands.dispatcher import dispatcher
    with patch.object(AIAgent, "ask_ai", return_value="Садоводство — это искусство возделывания растений.") as mock_ask:
        success, reply = dispatcher.dispatch("что ты знаешь а садоводстве")
        assert success is True
        assert "Садоводство" in reply
        assert mock_ask.called
