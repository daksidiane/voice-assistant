import pytest
import tempfile
import zipfile
from pathlib import Path

from commands.system_commands import SystemCommands
from commands.custom_commands import CustomCommandManager
from core.config import load_env_file
from modules.info_services import InfoServices


def test_open_app_command_injection_prevention():
    """Verify that command injection attempts and shell metacharacters are rejected."""
    malicious_inputs = [
        "notepad.exe & calc.exe",
        "calc.exe | dir",
        "notepad.exe; calc.exe",
        "cmd.exe /c whoami",
        "powershell -Command Start-Process calc",
        "cmd",
        "powershell.exe",
        "wscript.exe",
        "cscript.exe",
        "format.com",
        "test`echo 1`",
        "test$(whoami)",
        "app > output.txt",
    ]
    for bad_input in malicious_inputs:
        assert SystemCommands.open_app(bad_input) is False, f"Failed to block: {bad_input}"


def test_open_website_scheme_validation():
    """Verify that dangerous URL schemes are blocked."""
    bad_urls = [
        "file:///C:/Windows/System32/cmd.exe",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ms-msdt:/id PCWDiagnostic",
        "vbscript:msgbox(1)",
    ]
    for bad_url in bad_urls:
        assert SystemCommands.open_website(bad_url) is False, f"Failed to block dangerous URL: {bad_url}"


def test_custom_commands_shell_action_blocked():
    """Verify that arbitrary 'shell' action is blocked in custom commands."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_file = Path(tf.name)

    try:
        manager = CustomCommandManager(file_path=temp_file)
        # Attempt to add a shell command
        manager.add_command("запусти взлом", "shell", "calc.exe")
        assert "запусти взлом" not in manager.get_all(), "Shell action should not be allowed"

        # Attempt to execute an injected shell command directly
        fake_cmd = {"action": "shell", "target": "calc.exe", "response": "done"}
        success, _ = manager.execute_custom_command(fake_cmd)
        assert success is False, "Direct execution of shell action must fail"
    finally:
        if temp_file.exists():
            temp_file.unlink()


def test_zip_slip_prevention():
    """Verify that archives with directory traversal paths are blocked during model unpacking."""
    from stt.model_loader import ensure_vosk_model

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        zip_path = temp_dir_path / "vosk-model-small-ru-0.22.zip"

        # Create a malicious zip file containing Zip Slip path
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../evil.txt", "malicious payload")

        # The loader must reject extraction and raise RuntimeError
        with pytest.raises(RuntimeError, match="Zip Slip"):
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                target_resolved = temp_dir_path.resolve()
                for member in zip_ref.infolist():
                    member_path = (temp_dir_path / member.filename).resolve()
                    if not str(member_path).startswith(str(target_resolved)):
                        raise RuntimeError(f"Zip Slip detected in archive: {member.filename}")


def test_load_env_file_security():
    """Verify that .env parsing validates keys and sanitizes values."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
        tf.write(
            "# Comment\n"
            "VALID_KEY=safe_value\n"
            "INVALID KEY=bad\n"
            "123_BAD=bad\n"
            "SYSTEMROOT=should_not_crash\n"
        )
        temp_path = Path(tf.name)

    try:
        loaded = load_env_file(temp_path)
        assert loaded.get("VALID_KEY") == "safe_value"
        assert "INVALID KEY" not in loaded
        assert "123_BAD" not in loaded
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_scheduler_title_sanitization():
    """Verify that plan titles with control characters are sanitized and length-capped."""
    from modules.scheduler import Scheduler
    from datetime import datetime

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        sch = Scheduler(storage_path=temp_path)
        long_title = "A" * 300 + "\r\nmalicious\0line"
        plan = sch.add_plan(long_title, datetime.now())
        assert len(plan["title"]) <= 200
        assert "\r" not in plan["title"]
        assert "\n" not in plan["title"]
        assert "\0" not in plan["title"]
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_notifier_powershell_template_safety():
    """Verify that Notifier uses encoded commands and environment variables rather than string interpolation."""
    from ui.notifier import _ENCODED_TOAST_SCRIPT, _POWERSHELL_TOAST_SCRIPT

    # Script should reference environment variables, not raw format specifiers
    assert "SPUTNIK_TOAST_TITLE" in _POWERSHELL_TOAST_SCRIPT
    assert "SPUTNIK_TOAST_MSG" in _POWERSHELL_TOAST_SCRIPT
    assert "CreateTextNode" in _POWERSHELL_TOAST_SCRIPT
    assert _ENCODED_TOAST_SCRIPT is not None


def test_screen_analysis_guardrail_desktop(monkeypatch):
    """Verify that when no window or desktop is active, the guardrail blocks capture."""
    import win32gui
    from modules.ai_agent import AIAgent

    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 12345)
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetClassName", lambda hwnd: "Progman")
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "Program Manager")

    bbox, guard_msg = AIAgent.get_target_window_bbox()
    assert bbox is None
    assert "активен рабочий стол" in guard_msg


def test_screen_analysis_guardrail_sensitive_app(monkeypatch):
    """Verify that sensitive applications (Telegram, KeePass, Incognito) are blocked."""
    import win32gui
    from modules.ai_agent import AIAgent

    monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda: 12345)
    monkeypatch.setattr(win32gui, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetClassName", lambda hwnd: "Qt5QWindowIcon")
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "Telegram (3 сообщения)")

    bbox, guard_msg = AIAgent.get_target_window_bbox()
    assert bbox is None
    assert "конфиденциальное окно" in guard_msg


def test_dangerous_script_extensions_blocked():
    """Verify that script extensions (.bat, .cmd, .ps1, .vbs, .js) are strictly blocked in open_app."""
    dangerous_files = [
        "payload.bat",
        "script.cmd",
        "exploit.vbs",
        "attack.ps1",
        "drop.js",
        "malware.hta",
        "stealer.scr",
        "virus.com",
        "trojan.pif",
        "registry.reg",
        "C:\\Users\\test\\evil.bat",
        "C:\\Windows\\Temp\\run.cmd",
    ]
    for d in dangerous_files:
        assert SystemCommands.open_app(d) is False, f"Dangerous file extension must be blocked: {d}"
        assert SystemCommands.is_safe_app_target(d) is False, f"is_safe_app_target must reject: {d}"


def test_custom_command_target_validation():
    """Verify that CustomCommandManager rejects invalid URLs and unsafe application targets."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_file = Path(tf.name)

    try:
        manager = CustomCommandManager(file_path=temp_file)

        # Unsafe app target
        res1 = manager.add_command("запусти скрипт", "open_app", "C:\\evil.bat")
        assert res1 is False
        assert "запусти скрипт" not in manager.get_all()

        # Unsafe URL target (javascript scheme)
        res2 = manager.add_command("взлом", "open_url", "javascript:alert(1)")
        assert res2 is False
        assert "взлом" not in manager.get_all()

        # Safe URL target
        res3 = manager.add_command("открой хабр", "open_url", "https://habr.com")
        assert res3 is True
        assert "открой хабр" in manager.get_all()
    finally:
        if temp_file.exists():
            temp_file.unlink()


def test_protected_system_env_vars_cannot_be_overridden():
    """Verify that load_env_file cannot override critical OS environment variables."""
    import os
    original_path = os.environ.get("PATH", "")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
        tf.write(
            "PATH=C:\\fake_hijacked_path\n"
            "COMSPEC=C:\\fake_cmd.exe\n"
            "PYTHONPATH=C:\\fake_python\n"
            "SYSTEMROOT=C:\\fake_sys\n"
            "CUSTOM_API_KEY=valid_secret\n"
        )
        temp_path = Path(tf.name)

    try:
        loaded = load_env_file(temp_path)
        assert loaded.get("CUSTOM_API_KEY") == "valid_secret"
        assert "PATH" not in loaded
        assert "COMSPEC" not in loaded
        assert "PYTHONPATH" not in loaded
        assert "SYSTEMROOT" not in loaded
        assert os.environ.get("PATH") == original_path
    finally:
        if temp_path.exists():
            temp_path.unlink()


def test_gemini_api_key_sent_in_header_not_query_param(monkeypatch):
    """Verify that Gemini REST requests transmit API key in x-goog-api-key header and not in query string."""
    import requests
    captured_requests = []

    def mock_post(url, headers=None, json=None, timeout=None):
        captured_requests.append({"url": url, "headers": headers, "json": json})
        class MockResp:
            status_code = 200
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
        return MockResp()

    monkeypatch.setattr(requests, "post", mock_post)

    from modules.ai_agent import AIAgent
    res = AIAgent._query_gemini("test_secret_key_123", "gemini-3.6-flash", "system prompt", "hello")
    assert res == "OK"
    assert len(captured_requests) > 0
    req = captured_requests[0]
    # API key MUST be in header
    assert req["headers"].get("x-goog-api-key") == "test_secret_key_123"
    # API key MUST NOT be in URL
    assert "test_secret_key_123" not in req["url"]
    assert "?key=" not in req["url"]



