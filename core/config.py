import os
import re
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"
ENV_PATH = BASE_DIR / ".env"
CUSTOM_COMMANDS_PATH = BASE_DIR / "custom_commands.json"
PLANS_PATH = BASE_DIR / "plans.json"
TTS_CACHE_DIR = BASE_DIR / ".tts_cache"


PROTECTED_ENV_KEYS = {
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "PYTHONPATH", "PYTHONHOME", "OS", "ALLUSERSPROFILE", "APPDATA",
    "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "HOMEDRIVE", "HOMEPATH", "USERPROFILE",
    "SYSTEMDRIVE", "PSMODULEPATH"
}


def load_env_file(path: Path) -> Dict[str, str]:
    """Load simple key=value pairs from .env safely without extra dependencies."""
    env_vars = {}
    if not path.exists():
        return env_vars
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"").replace("\0", "")
                    # Whitelist valid env variable names and protect critical system variables
                    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
                        if key.upper() in PROTECTED_ENV_KEYS:
                            logger.warning(f"Ignored prohibited attempt to override protected environment variable: {key}")
                            continue
                        env_vars[key] = val
                        os.environ[key] = val
    except Exception as e:
        logger.warning(f"Failed to parse .env file: {e}")
    return env_vars


class Config:
    """Application configuration manager."""

    def __init__(self):
        self.base_dir = BASE_DIR
        self.config_path = CONFIG_PATH
        self.custom_commands_path = CUSTOM_COMMANDS_PATH
        self.plans_path = PLANS_PATH
        self.env = load_env_file(ENV_PATH)
        self.data: Dict[str, Any] = self._load_default_config()
        self.load()

    def _load_default_config(self) -> Dict[str, Any]:
        return {
            "assistant": {
                "name": "Спутник",
                "wake_words": ["спутник", "спутник", "ало", "алло", "привет"],
                "user_title": "сэр",
                "user_gender": "male",
                "commands_timeout_sec": 6,
                "work_break_hours": 3.0,
                "greeting_on_start": True
            },
            "voice": {
                "engine": "piper",
                "gender": "male",
                "piper_voice": "ru_RU-ruslan-medium",
                "edge_voice": "ru-RU-DmitryNeural",
                "sapi_voice": "Microsoft Pavel",
                "sapi_voice_index": 2,
                "rate": "+0%",
                "volume": "+0%"
            },
            "stt": {
                "model_path": "model/vosk-model-small-ru-0.22",
                "sample_rate": 16000
            },
            "info": {
                "weather_default_city": "Москва",
                "news_rss_url": "https://ria.ru/export/rss2/archive/index.xml",
                "exchange_currencies": ["USD", "EUR", "CNY"]
            },
            "ai": {
                "enabled": True,
                "provider": "google",
                "base_url": "https://api.openai.com/v1",
                "model": "gemini-3-flash-preview"
            },
            "default_apps": {
                "блокнот": "notepad.exe",
                "калькулятор": "calc.exe",
                "проводник": "explorer.exe",
                "диспетчер задач": "taskmgr.exe",
                "браузер": "start msedge"
            },
            "default_sites": {
                "ютуб": "https://youtube.com",
                "ютубе": "https://youtube.com",
                "гугл": "https://google.com",
                "яндекс": "https://ya.ru",
                "вк": "https://vk.com",
                "вконтакте": "https://vk.com",
                "почту": "https://mail.ru",
                "новости": "https://ria.ru"
            }
        }

    def load(self) -> None:
        """Load configuration from config.json."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    self._deep_update(self.data, file_data)
            except Exception as e:
                logger.error(f"Error reading config.json: {e}")

    def save(self) -> None:
        """Save current configuration to config.json."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving config.json: {e}")

    def _deep_update(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, val in source.items():
            if isinstance(val, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], val)
            else:
                target[key] = val

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get nested value by dot notation e.g. 'assistant.name'."""
        keys = key_path.split(".")
        val = self.data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any, auto_save: bool = True) -> None:
        """Set nested value by dot notation."""
        keys = key_path.split(".")
        val = self.data
        for k in keys[:-1]:
            if k not in val or not isinstance(val[k], dict):
                val[k] = {}
            val = val[k]
        val[keys[-1]] = value

        # Keep user_gender and user_title strictly synchronized
        if key_path == "assistant.user_gender":
            if str(value).lower() == "female":
                self.data.setdefault("assistant", {})["user_title"] = "госпожа"
            elif str(value).lower() == "male":
                self.data.setdefault("assistant", {})["user_title"] = "сэр"
        elif key_path == "assistant.user_title":
            if str(value).lower() == "госпожа":
                self.data.setdefault("assistant", {})["user_gender"] = "female"
            elif str(value).lower() == "сэр":
                self.data.setdefault("assistant", {})["user_gender"] = "male"

        if auto_save:
            self.save()

    def get_api_key(self, name: str) -> str:
        """Get API key from environment variable or .env file, prioritizing non-placeholder values."""
        cfg_val = self.env.get(name, "")
        env_val = os.environ.get(name, "")
        if cfg_val and cfg_val != "ваш_ключ_здесь":
            return cfg_val
        if env_val and env_val != "ваш_ключ_здесь":
            return env_val
        return cfg_val or env_val or ""


# Global configuration instance
config = Config()
