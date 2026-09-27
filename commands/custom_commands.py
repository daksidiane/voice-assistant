import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from core.config import CUSTOM_COMMANDS_PATH
from commands.system_commands import SystemCommands

logger = logging.getLogger(__name__)


class CustomCommandManager:
    """Manages custom user-defined commands (F8.0 - F8.3)."""

    def __init__(self, file_path: Optional[Path] = None):
        self.file_path = file_path or CUSTOM_COMMANDS_PATH
        self.commands: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        """Load custom commands from JSON file."""
        if self.file_path.exists() and self.file_path.stat().st_size > 0:
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.commands = json.load(f)
            except Exception as e:
                logger.error(f"Error loading {self.file_path}: {e}")
                self.commands = {}
        else:
            self.commands = {}

    def save(self) -> None:
        """Save custom commands to JSON file."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.commands, f, ensure_ascii=False, indent=2)
            logger.info(f"Custom commands saved to {self.file_path}")
        except Exception as e:
            logger.error(f"Error saving {self.file_path}: {e}")

    ALLOWED_ACTIONS = {
        "open_url",
        "open_app",
        "media_play_pause",
        "media_next",
        "media_prev",
        "media_stop",
        "volume_up",
        "volume_down",
        "say",
    }

    def add_command(self, phrase: str, action: str, target: str = "", response: str = "") -> bool:
        """Add or update a custom command with strict action and target validation."""
        phrase_clean = re.sub(r'[\r\n\0]', ' ', phrase).strip().lower()[:150]
        if not phrase_clean:
            return False

        action_clean = action.strip().lower()
        if action_clean not in self.ALLOWED_ACTIONS:
            logger.warning(f"Rejected unsupported or insecure custom command action: {action}")
            return False

        target_clean = re.sub(r'[\r\n\0]', '', target).strip()
        response_clean = re.sub(r'[\r\n\0]', ' ', response).strip()[:300]

        # Target validation based on action
        if action_clean == "open_url":
            if not target_clean:
                return False
            import urllib.parse
            parsed_raw = urllib.parse.urlparse(target_clean)
            if parsed_raw.scheme:
                if parsed_raw.scheme.lower() not in ("http", "https"):
                    logger.warning(f"Rejected dangerous scheme in custom command URL: {target_clean}")
                    return False
            else:
                target_clean = f"https://{target_clean}"
            if not SystemCommands.is_safe_url(target_clean):
                logger.warning(f"Rejected unsafe custom command URL target: {target_clean}")
                return False
        elif action_clean == "open_app":
            if not target_clean or not SystemCommands.is_safe_app_target(target_clean):
                logger.warning(f"Rejected unsafe custom command app target: {target_clean}")
                return False

        if not response_clean:
            response_clean = f"Выполняю команду {phrase_clean}, сэр."

        self.commands[phrase_clean] = {
            "action": action_clean,
            "target": target_clean,
            "response": response_clean
        }
        self.save()
        return True

    def remove_command(self, phrase: str) -> bool:
        """Remove a custom command."""
        phrase_clean = phrase.strip().lower()
        if phrase_clean in self.commands:
            del self.commands[phrase_clean]
            self.save()
            return True
        return False

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        return self.commands

    def match_command(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Find matching custom command in recognized speech."""
        text_clean = text.strip().lower()
        # 1. Exact match
        if text_clean in self.commands:
            return text_clean, self.commands[text_clean]

        # 2. Substring match
        for phrase, cmd_def in self.commands.items():
            if phrase in text_clean:
                return phrase, cmd_def

        return None

    def execute_custom_command(self, cmd_def: Dict[str, Any]) -> Tuple[bool, str]:
        """Execute a matched custom command dictionary safely without arbitrary shell execution."""
        action = cmd_def.get("action", "")
        target = cmd_def.get("target", "")
        response = cmd_def.get("response", "Команда выполнена, сэр.")

        success = True
        if action == "open_url":
            success = SystemCommands.open_website(target)
        elif action == "open_app":
            success = SystemCommands.open_app(target)
        elif action == "media_play_pause":
            success = SystemCommands.media_play_pause()
        elif action == "media_next":
            success = SystemCommands.media_next()
        elif action == "media_prev":
            success = SystemCommands.media_prev()
        elif action == "media_stop":
            success = SystemCommands.media_stop()
        elif action == "volume_up":
            success = SystemCommands.volume_up()
        elif action == "volume_down":
            success = SystemCommands.volume_down()
        elif action == "say":
            success = True
        else:
            logger.warning(f"Rejected unsupported custom command action: {action}")
            success = False

        if not success:
            return False, "Не удалось выполнить команду, сэр."
        return True, response

    def parse_voice_add_command(self, text: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse voice command to add a new command (F8.1).
        Format: "запомни команду [фраза] как [действие/сайт/программа]"
        Example: "запомни команду открыть портал как https://portal.ru"
        """
        pattern = r'(?:запомни|добавь)\s+команду\s+(.+?)\s+как\s+(.+)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(1).strip()
            target = match.group(2).strip()
            
            # Determine action type safely
            if target.startswith("http://") or target.startswith("https://") or ".ru" in target or ".com" in target:
                action = "open_url"
            else:
                action = "open_app"

            return phrase, action, target
        return None


# Global custom commands manager instance
custom_command_manager = CustomCommandManager()
