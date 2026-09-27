import os
import sys
import shutil
import re
import subprocess
import webbrowser
import urllib.parse
import logging
from typing import Optional

from core.config import config

logger = logging.getLogger(__name__)

# Windows Virtual-Key codes for multimedia
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


class SystemCommands:
    """Handles OS-level actions: running apps, opening websites, search, media control."""

    # Dangerous script and executable extensions strictly prohibited from execution
    FORBIDDEN_EXTENSIONS = {
        ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
        ".hta", ".scr", ".pif", ".reg", ".ps1", ".psm1", ".psd1", ".com",
        ".cpl", ".msc", ".jar", ".sys", ".inf", ".dll", ".ocx"
    }

    # Shell command interpreters and dangerous system tools blocked from execution
    FORBIDDEN_COMMANDS = {
        "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "bash", "bash.exe", "sh", "sh.exe", "wscript", "wscript.exe",
        "cscript", "cscript.exe", "mshta", "mshta.exe", "rundll32", "rundll32.exe",
        "regsvr32", "regsvr32.exe", "certutil", "certutil.exe", "vssadmin", "vssadmin.exe",
        "format", "format.com", "del", "erase", "rmdir", "rd", "net", "net.exe",
        "netsh", "netsh.exe", "sc", "sc.exe", "reg", "reg.exe", "bitsadmin", "bitsadmin.exe",
        "schtasks", "schtasks.exe", "at", "at.exe", "curl", "curl.exe", "wget", "wget.exe",
        "taskkill", "taskkill.exe"
    }

    SAFE_APP_MAP = {
        "блокнот": "notepad.exe",
        "калькулятор": "calc.exe",
        "проводник": "explorer.exe",
        "диспетчер задач": "taskmgr.exe",
        "диспетчер": "taskmgr.exe",
        "paint": "mspaint.exe",
        "паинт": "mspaint.exe",
    }

    @classmethod
    def is_safe_app_target(cls, target: str) -> bool:
        """Validate whether an application target is safe to configure or execute."""
        target_clean = target.strip().lower()
        if not target_clean or len(target_clean) > 260:
            return False
        # Block dangerous metacharacters and control characters
        if re.search(r'[&|;><`$\n\r^"%\0]', target_clean):
            return False
        # Block forbidden extensions
        ext = os.path.splitext(target_clean)[1]
        if ext in cls.FORBIDDEN_EXTENSIONS:
            return False
        base_cmd = os.path.basename(target_clean)
        if base_cmd in cls.FORBIDDEN_COMMANDS or any(f in base_cmd for f in cls.FORBIDDEN_COMMANDS):
            return False
        return True

    @classmethod
    def is_safe_url(cls, url: str) -> bool:
        """Validate that a URL uses safe protocols (http/https only) and has valid structure."""
        url_clean = url.strip()
        if not url_clean or len(url_clean) > 2000 or re.search(r'[\r\n\0]', url_clean):
            return False
        parsed = urllib.parse.urlparse(url_clean)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        return True

    @classmethod
    def open_app(cls, app_name: str) -> bool:
        """Safely launch an allowed application without invoking a shell."""
        app_name_clean = app_name.strip().lower()
        if not app_name_clean:
            return False

        # Reject inputs containing dangerous shell metacharacters, environment variables, or null bytes
        if re.search(r'[&|;><`$\n\r^"%\0]', app_name_clean):
            logger.warning(f"Rejected unsafe application name containing metacharacters: {app_name}")
            return False

        # Reject forbidden script and executable extensions immediately
        ext = os.path.splitext(app_name_clean)[1]
        if ext in cls.FORBIDDEN_EXTENSIONS:
            logger.warning(f"Rejected execution of forbidden file extension '{ext}': {app_name}")
            return False

        # Handle browser request safely without shell
        if app_name_clean in ("браузер", "browser", "start msedge", "msedge"):
            try:
                webbrowser.open("https://www.google.com")
                return True
            except Exception as e:
                logger.error(f"Failed to open browser: {e}")
                return False

        default_apps = config.get("default_apps", {})

        # Direct dictionary match
        target = default_apps.get(app_name_clean)
        if not target:
            target = cls.SAFE_APP_MAP.get(app_name_clean)

        # Substring match if exact match not found
        if not target:
            for k, v in default_apps.items():
                if k in app_name_clean:
                    target = v
                    break
            if not target:
                for k, v in cls.SAFE_APP_MAP.items():
                    if k in app_name_clean:
                        target = v
                        break

        if not target:
            target = app_name_clean

        # Handle 'start msedge' in config
        if target.startswith("start "):
            target = target[6:].strip()
            if target in ("msedge", "chrome", "firefox", "browser"):
                webbrowser.open("https://www.google.com")
                return True

        # Check target against forbidden extensions
        target_ext = os.path.splitext(target)[1].lower()
        if target_ext in cls.FORBIDDEN_EXTENSIONS:
            logger.warning(f"Execution of forbidden file extension blocked: {target}")
            return False

        # Check against forbidden commands list
        base_cmd = os.path.basename(target).lower()
        if base_cmd in cls.FORBIDDEN_COMMANDS or any(f in base_cmd for f in cls.FORBIDDEN_COMMANDS):
            logger.warning(f"Execution of forbidden executable blocked: {target}")
            return False

        try:
            logger.info(f"Executing application command safely: {target}")
            # Explicit full path to local executable (strictly .exe only)
            if os.path.isabs(target) and os.path.isfile(target):
                if not target.lower().endswith(".exe"):
                    logger.warning(f"Refusing to execute non-executable file: {target}")
                    return False
                os.startfile(target)
                return True

            # Relative or known executable (e.g. notepad.exe, calc.exe, explorer.exe)
            resolved = shutil.which(target)
            if resolved:
                resolved_base = os.path.basename(resolved).lower()
                resolved_ext = os.path.splitext(resolved)[1].lower()
                if resolved_base in cls.FORBIDDEN_COMMANDS or resolved_ext in cls.FORBIDDEN_EXTENSIONS:
                    logger.warning(f"Resolved path to forbidden binary blocked: {resolved}")
                    return False
                if not resolved.lower().endswith(".exe"):
                    logger.warning(f"Resolved path is not an executable: {resolved}")
                    return False
                os.startfile(resolved)
                return True

            # If registered standard Windows application (notepad.exe etc.)
            if target.endswith(".exe") and re.match(r'^[a-zA-Z0-9_\-.]+\.exe$', target):
                os.startfile(target)
                return True

            logger.warning(f"Refusing to execute unverified application: '{target}'")
            return False
        except Exception as e:
            logger.error(f"Failed to open application '{target}': {e}")
            return False

    @classmethod
    def open_website(cls, site_name_or_url: str) -> bool:
        """Open website in default browser safely."""
        cleaned = re.sub(r'[\r\n\0]', '', site_name_or_url).strip()
        if not cleaned:
            return False

        # If an explicit scheme is provided, validate it immediately
        parsed_input = urllib.parse.urlparse(cleaned)
        if parsed_input.scheme:
            if parsed_input.scheme.lower() not in ("http", "https") or not parsed_input.netloc:
                logger.warning(f"Blocked dangerous or unsupported URL scheme '{parsed_input.scheme}': {cleaned}")
                return False
            url = cleaned
        else:
            default_sites = config.get("default_sites", {})
            url = default_sites.get(cleaned.lower())
            if not url:
                for k, v in default_sites.items():
                    if k in cleaned.lower():
                        url = v
                        break

            if not url:
                if "." in cleaned and " " not in cleaned and "/" not in cleaned and not cleaned.startswith("\\"):
                    url = f"https://{cleaned}"
                else:
                    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(cleaned)}"

        # Final verification of URL scheme and host
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            logger.warning(f"Blocked dangerous URL '{url}'")
            return False

        try:
            logger.info(f"Opening URL: {url}")
            webbrowser.open(url)
            return True
        except Exception as e:
            logger.error(f"Failed to open website {url}: {e}")
            return False

    @classmethod
    def search_internet(cls, query: str) -> bool:
        """Search query in Google."""
        clean_query = query.strip()
        if not clean_query:
            return False
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(clean_query)}"
        try:
            logger.info(f"Searching internet for query")
            webbrowser.open(url)
            return True
        except Exception as e:
            logger.error(f"Failed to search internet for query: {e}")
            return False

    @classmethod
    def send_media_key(cls, vk_code: int) -> bool:
        """Send virtual media key event to Windows."""
        try:
            import win32api
            win32api.keybd_event(vk_code, 0, 0, 0)
            win32api.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            logger.error(f"Failed to send media key {vk_code}: {e}")
            return False

    @classmethod
    def media_play_pause(cls) -> bool:
        return cls.send_media_key(VK_MEDIA_PLAY_PAUSE)

    @classmethod
    def media_next(cls) -> bool:
        return cls.send_media_key(VK_MEDIA_NEXT_TRACK)

    @classmethod
    def media_prev(cls) -> bool:
        return cls.send_media_key(VK_MEDIA_PREV_TRACK)

    @classmethod
    def media_stop(cls) -> bool:
        return cls.send_media_key(VK_MEDIA_STOP)

    @classmethod
    def volume_up(cls) -> bool:
        return cls.send_media_key(VK_VOLUME_UP)

    @classmethod
    def volume_down(cls) -> bool:
        return cls.send_media_key(VK_VOLUME_DOWN)

    @classmethod
    def volume_mute(cls) -> bool:
        return cls.send_media_key(VK_VOLUME_MUTE)
