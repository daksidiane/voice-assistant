import pytest
from pynput import keyboard
from hotkey import EmergencyHotkeyListener


def test_hotkey_left_shift_plus_enter_does_not_trigger(monkeypatch):
    """Left Shift + Enter (used for newlines / running cells) must NEVER trigger emergency shutdown."""
    triggered = []
    listener = EmergencyHotkeyListener(on_emergency_exit=lambda: triggered.append(True))

    # User presses Left Shift
    listener._on_press(keyboard.Key.shift)
    # User presses Enter
    listener._on_press(keyboard.Key.enter)

    assert len(triggered) == 0, "Left Shift + Enter must NOT trigger emergency exit!"


def test_hotkey_enter_alone_does_not_trigger():
    """Regular Enter key alone must NEVER trigger emergency shutdown."""
    triggered = []
    listener = EmergencyHotkeyListener(on_emergency_exit=lambda: triggered.append(True))

    listener._on_press(keyboard.Key.enter)
    assert len(triggered) == 0


def test_hotkey_right_shift_plus_enter_triggers(monkeypatch):
    """Right Shift + Enter MUST trigger emergency shutdown."""
    triggered = []
    listener = EmergencyHotkeyListener(on_emergency_exit=lambda: triggered.append(True))

    # Mock hardware check to return True for RSHIFT and RETURN
    import hotkey
    monkeypatch.setattr(hotkey, "_is_physically_down", lambda vk: vk in (161, 13))

    listener._on_press(keyboard.Key.shift_r)
    listener._on_press(keyboard.Key.enter)

    assert len(triggered) == 1, "Right Shift + Enter must trigger emergency shutdown!"


def test_hotkey_release_clears_keys():
    """Key release removes keys from internal state."""
    listener = EmergencyHotkeyListener(on_emergency_exit=lambda: None)

    listener._on_press(keyboard.Key.shift_r)
    assert keyboard.Key.shift_r in listener._pressed_keys

    listener._on_release(keyboard.Key.shift_r)
    assert keyboard.Key.shift_r not in listener._pressed_keys
