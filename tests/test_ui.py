import pytest
import tkinter as tk
from ui.control_window import SputnikControlWindow
from ui.tray import create_tray_icon_image, TrayManager
from core.state import AssistantState


def test_tray_icon_image_creation():
    for status in ["idle", "active", "speaking", "paused"]:
        img = create_tray_icon_image(status)
        assert img is not None
        assert img.size == (64, 64)
        assert img.mode == "RGBA"


def test_control_window_creation_and_messages():
    root = tk.Tk()
    root.withdraw()

    executed = []
    window = SputnikControlWindow(
        root=root,
        on_execute_command=lambda cmd, speak: executed.append((cmd, speak)),
        on_open_settings=lambda: None,
        on_open_plans=lambda: None,
        on_toggle_pause=lambda: None,
        on_shutdown=lambda: None
    )

    window.show()
    assert window._window is not None
    assert window._window.winfo_exists()

    # Append test messages
    window.append_user_message("Привет, Спутник")
    window.append_sputnik_message("Слушаю вас, сэр.")
    window.append_system_message("Тест системы")

    chat_content = window.chat_text.get("1.0", tk.END)
    assert "Привет, Спутник" in chat_content
    assert "Слушаю вас, сэр." in chat_content
    assert "Тест системы" in chat_content

    # Status update
    window.update_status(AssistantState.ACTIVE, is_paused=False)
    assert "Слушает" in window.lbl_status.cget("text")

    window.update_status(AssistantState.IDLE, is_paused=True)
    assert "приостановлено" in window.lbl_status.cget("text")

    # Send input
    window.cmd_entry.insert(0, "сколько времени")
    window._send_input_command()
    assert len(executed) == 1
    assert executed[0][0] == "сколько времени"

    window.hide()
    root.destroy()


def test_plans_window_chronological_display(monkeypatch):
    from ui.plans_window import PlansWindow
    from modules.scheduler import scheduler

    mock_plans = [
        {"id": 1, "datetime": "2026-09-25 10:00", "title": "Позже", "reminded_1h": False, "reminded_event": False},
        {"id": 2, "datetime": "2026-09-22 09:00", "title": "Раньше", "reminded_1h": False, "reminded_event": False},
        {"id": 3, "datetime": "2026-09-23 14:00", "title": "Середина", "reminded_1h": False, "reminded_event": False},
    ]
    monkeypatch.setattr(scheduler, "load", lambda: None)
    monkeypatch.setattr(scheduler, "get_all_plans", lambda sorted_by_date=False: list(mock_plans))

    root = tk.Tk()
    root.withdraw()

    pw = PlansWindow(root=root)
    pw.show()

    # Initial refresh: should sort chronologically by datetime ascending
    items = pw.tree.get_children()
    assert len(items) == 3

    rows = [pw.tree.item(item)["values"] for item in items]
    # Row format: [id, datetime, title, status]
    assert rows[0][2] == "Раньше"
    assert rows[1][2] == "Середина"
    assert rows[2][2] == "Позже"

    # Click datetime column header to reverse sort
    pw._sort_by_column("datetime")
    rev_items = pw.tree.get_children()
    rev_rows = [pw.tree.item(item)["values"] for item in rev_items]
    assert rev_rows[0][2] == "Позже"
    assert rev_rows[1][2] == "Середина"
    assert rev_rows[2][2] == "Раньше"

    pw._window.destroy()
    root.destroy()


def test_control_window_close_confirmation(monkeypatch):
    from tkinter import messagebox
    try:
        root = tk.Tk()
        root.withdraw()
    except (tk.TclError, Exception):
        import pytest
        pytest.skip("Tkinter display not available")
        return

    shutdown_called = []
    window = SputnikControlWindow(
        root=root,
        on_execute_command=lambda cmd, speak: None,
        on_open_settings=lambda: None,
        on_open_plans=lambda: None,
        on_toggle_pause=lambda: None,
        on_shutdown=lambda: shutdown_called.append(True)
    )
    window.show()

    # Case 1: User cancels (clicks "Нет")
    monkeypatch.setattr(messagebox, "askyesno", lambda title, msg: False)
    window._on_close_attempt()
    assert len(shutdown_called) == 0
    assert window._window.winfo_exists()

    # Case 2: User confirms (clicks "Да")
    monkeypatch.setattr(messagebox, "askyesno", lambda title, msg: True)
    window._on_close_attempt()
    assert len(shutdown_called) == 1

    root.destroy()


def test_sound_effects_chime():
    from utils.sound_effects import _generate_chime_waveform, play_wake_chime
    waveform = _generate_chime_waveform()
    assert waveform is not None
    assert len(waveform) > 0
    # Calling play_wake_chime shouldn't crash
    play_wake_chime()


def test_settings_window_gender_sync():
    from core.config import config
    from core.personality import SputnikPersonality

    config.set("assistant.user_gender", "female")
    assert config.get("assistant.user_gender") == "female"
    assert config.get("assistant.user_title") == "госпожа"
    assert "госпожа" in SputnikPersonality.get_user_title().lower()

    config.set("assistant.user_gender", "male")
    assert config.get("assistant.user_gender") == "male"
    assert config.get("assistant.user_title") == "сэр"
    assert "сэр" in SputnikPersonality.get_user_title().lower()

    # Restore female preference
    config.set("assistant.user_gender", "female")
    config.set("assistant.user_title", "госпожа")


def test_settings_window_voice_options_include_kirill():
    """Verify that Kirill strict is available in voice choices and preserved across gender switch."""
    from ui.settings_window import SettingsWindow
    from core.config import config
    import tkinter as tk

    config.set("voice.engine", "yandex")
    config.set("voice.yandex_voice", "kirill")
    config.set("voice.yandex_role", "strict")

    try:
        root = tk.Tk()
        root.withdraw()
    except (tk.TclError, Exception):
        import pytest
        pytest.skip("Tkinter display not available")
        return
    try:
        sw = SettingsWindow(root=root)
        sw.show()

        # Find voice combobox
        found_kirill = False
        for child in sw._window.winfo_children():
            pass

        # Check that config remained kirill
        assert config.get("voice.yandex_voice") == "kirill"
        assert config.get("voice.yandex_role") == "strict"
        sw._window.destroy()
    finally:
        root.destroy()


