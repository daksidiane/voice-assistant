import tempfile
import json
from pathlib import Path
import pytest

from commands.custom_commands import CustomCommandManager


def test_custom_command_crud():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        manager = CustomCommandManager(file_path=temp_path)
        # Add command (F8.0, F8.2)
        manager.add_command(
            phrase="открой портал",
            action="open_url",
            target="https://example.com/portal",
            response="Открываю корпоративный портал, сэр."
        )

        assert "открой портал" in manager.get_all()

        # Match command
        matched = manager.match_command("пожалуйста открой портал сейчас")
        assert matched is not None
        phrase, cmd_def = matched
        assert phrase == "открой портал"
        assert cmd_def["target"] == "https://example.com/portal"

        # Delete command
        assert manager.remove_command("открой портал") is True
        assert "открой портал" not in manager.get_all()
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_voice_add_parsing():
    manager = CustomCommandManager()
    parsed = manager.parse_voice_add_command("запомни команду тест портал как https://portal.corp")
    assert parsed is not None
    phrase, action, target = parsed
    assert phrase == "тест портал"
    assert action == "open_url"
    assert target == "https://portal.corp"
