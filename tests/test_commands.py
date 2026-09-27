import pytest
from commands.dispatcher import dispatcher
from core.personality import SputnikPersonality


def test_clean_wake_word():
    assert dispatcher.clean_wake_word("спутник сколько времени") == "сколько времени"
    assert dispatcher.clean_wake_word("спутник, открой блокнот") == "открой блокнот"
    assert dispatcher.clean_wake_word("ало, как дела") == "как дела"
    assert dispatcher.clean_wake_word("привет") == ""


def test_time_command():
    should_cont, resp = dispatcher.dispatch("спутник сколько времени")
    assert should_cont is True
    assert "Сейчас" in resp
    assert any(w in resp.lower() for w in ["сэр", "госпожа"])


def test_exit_command():
    should_cont, resp = dispatcher.dispatch("спутник выход")
    assert should_cont is False
    assert any(w in resp for w in ["сэр", "госпожа", "Всегда", "До свидания", "Отключаюсь"])


def test_search_command():
    should_cont, resp = dispatcher.dispatch("спутник найди в интернете новости науки")
    assert should_cont is True
    assert "Ищу в интернете" in resp
    assert "новости науки" in resp


def test_clean_wake_word_extended():
    assert dispatcher.clean_wake_word("спутник погода") == "погода"
    assert dispatcher.clean_wake_word("дарвис который час") == "который час"
    assert dispatcher.clean_wake_word("ярвис новости") == "новости"


def test_command_normalization():
    # Misrecognitions by Vosk
    assert dispatcher.normalize_command_text("ко времени") == "сколько времени"
    assert dispatcher.normalize_command_text("ко время") == "сколько времени"
    assert dispatcher.normalize_command_text("с погоды") == "погода"
    assert dispatcher.normalize_command_text("прогноз погоды") == "погода"
    assert dispatcher.normalize_command_text("доллара") == "курс доллара"
    assert dispatcher.normalize_command_text("свежие новости") == "новости"
    assert dispatcher.normalize_command_text("открой ютуп") == "открой ютуб"


def test_dispatch_misrecognized_time():
    should_cont, resp = dispatcher.dispatch("спутник ко времени")
    assert should_cont is True
    assert "Сейчас" in resp
    assert any(w in resp.lower() for w in ["сэр", "госпожа"])


def test_dispatch_misrecognized_weather(monkeypatch):
    spoken = []
    from tts.speaker import speaker
    monkeypatch.setattr(speaker, "speak", lambda text, **kwargs: spoken.append(text))
    monkeypatch.setattr("modules.info_services.InfoServices.get_weather", lambda city: "В городе Москва ясно, сэр.")

    should_cont, resp = dispatcher.dispatch("спутник с погоды")
    assert should_cont is True
    assert "Москва" in resp
    # Check that intermediate waiting phrase was spoken
    assert any("Секунду" in s or "запрашиваю" in s for s in spoken)


def test_dispatch_currency_with_wait_speech(monkeypatch):
    spoken = []
    from tts.speaker import speaker
    monkeypatch.setattr(speaker, "speak", lambda text, **kwargs: spoken.append(text))
    monkeypatch.setattr("modules.info_services.InfoServices.get_exchange_rates", lambda: "Актуальный курс валют: 85 рублей, сэр.")

    should_cont, resp = dispatcher.dispatch("спутник доллара")
    assert should_cont is True
    assert "85 рублей" in resp
    assert any("уточняю" in s or "курс" in s for s in spoken)


def test_personality_address():
    from core.config import config
    config.set("assistant.user_gender", "male")
    greeting = SputnikPersonality.get_wake_greeting()
    assert "сэр" in greeting.lower()
    error_msg = SputnikPersonality.get_error()
    assert "сэр" in error_msg.lower()


def test_personality_female_address():
    from core.config import config
    config.set("assistant.user_gender", "female")
    greeting = SputnikPersonality.get_wake_greeting()
    assert "госпожа" in greeting.lower()

    startup = SputnikPersonality.get_startup_greeting()
    assert "госпожа" in startup.lower()

    # Test command response formatting
    should_cont, resp = dispatcher.dispatch("спутник сколько времени")
    assert should_cont is True
    assert "госпожа" in resp.lower()
    assert "сэр" not in resp.lower()

    # Reset back to male
    config.set("assistant.user_gender", "male")


def test_open_plans_phrase_recognition():
    clean = dispatcher.clean_wake_word("спутник открой список планов")
    assert clean == "открой список планов"

    # Verify dispatcher recognizes the full phrase as plans window
    should_cont, resp = dispatcher.dispatch(clean)
    assert should_cont is True
    assert "список планов" in resp.lower() or "планов" in resp.lower()


def test_voice_gender_switch_commands():
    from core.config import config
    # Test setting female by voice
    should_cont, resp = dispatcher.dispatch("спутник я женщина")
    assert should_cont is True
    assert "госпожа" in resp.lower()
    assert config.get("assistant.user_gender") == "female"
    assert config.get("assistant.user_title") == "госпожа"

    # Test setting male by voice
    should_cont, resp = dispatcher.dispatch("спутник я мужчина")
    assert should_cont is True
    assert "сэр" in resp.lower()
    assert config.get("assistant.user_gender") == "male"
    assert config.get("assistant.user_title") == "сэр"

    # Restore female preference
    config.set("assistant.user_gender", "female")
    config.set("assistant.user_title", "госпожа")


def test_volume_controls(monkeypatch):
    from commands.system_commands import SystemCommands
    events = []
    monkeypatch.setattr(SystemCommands, "volume_up", lambda: events.append("up"))
    monkeypatch.setattr(SystemCommands, "volume_down", lambda: events.append("down"))
    monkeypatch.setattr(SystemCommands, "volume_mute", lambda: events.append("mute"))

    # Volume up
    events.clear()
    cont, resp = dispatcher.dispatch("спутник сделай громче")
    assert cont is True
    assert "увеличена" in resp
    assert len(events) == 5 and all(e == "up" for e in events)

    # Volume down
    events.clear()
    cont, resp = dispatcher.dispatch("спутник сделай тише")
    assert cont is True
    assert "уменьшена" in resp
    assert len(events) == 5 and all(e == "down" for e in events)

    # Volume mute
    events.clear()
    cont, resp = dispatcher.dispatch("спутник выключи звук")
    assert cont is True
    assert "Переключаю режим звука" in resp
    assert events == ["mute"]


def test_silence_does_not_trigger_volume_down(monkeypatch):
    from commands.system_commands import SystemCommands
    events = []
    monkeypatch.setattr(SystemCommands, "volume_down", lambda: events.append("down"))

    # Hallucinated ambient phrases must NOT trigger volume down
    for phrase in ["тихо", "тишина", "в тишине", "тишину"]:
        events.clear()
        dispatcher.dispatch(f"спутник {phrase}")
        assert events == [], f"Phrase '{phrase}' falsely triggered volume down!"


def test_dispatch_add_event_natural():
    from commands.dispatcher import CommandDispatcher
    d = CommandDispatcher()
    should_cont, resp = d.dispatch("спутник добавь событие девятнадцать ноль ноль тренировка")
    assert should_cont is True
    assert "Запланировано" in resp
    assert "тренировка" in resp
    assert "19:00" in resp


def test_dispatch_pending_reminder_dialog():
    from commands.dispatcher import CommandDispatcher
    d = CommandDispatcher()

    # Step 1: User asks to remind without time
    should_cont1, resp1 = d.dispatch("напомни обед")
    assert should_cont1 is True
    assert "укажите, пожалуйста, время напоминания" in resp1.lower()
    assert d._pending_plan is not None
    assert d._pending_plan["title"] == "обед"

    # Step 2: User responds with time
    should_cont2, resp2 = d.dispatch("через пять минут")
    assert should_cont2 is True
    assert "Запланировано" in resp2
    assert "обед" in resp2
    assert d._pending_plan is None




