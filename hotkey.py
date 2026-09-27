import os
import sys
import logging
import threading
from typing import Callable, Set
from pynput import keyboard

logger = logging.getLogger(__name__)


import win32api
import win32con


def _is_physically_down(vk: int) -> bool:
    """Check actual hardware state of a virtual key to avoid stale software event bugs."""
    try:
        return (win32api.GetAsyncKeyState(vk) & 0x8000) != 0
    except Exception:
        return False


class EmergencyHotkeyListener:
    """Listens for global Right Shift + Enter to trigger instant emergency shutdown (F2.4)."""

    def __init__(self, on_emergency_exit: Callable[[], None]):
        self.on_emergency_exit = on_emergency_exit
        self._listener: Optional[keyboard.Listener] = None
        self._pressed_keys: Set[Any] = set()
        self._lock = threading.Lock()

    def _on_press(self, key):
        try:
            with self._lock:
                self._pressed_keys.add(key)

                # Emergency exit strictly requires Right Shift + Enter
                # Must NOT trigger on Left Shift (which is used for newlines in chat / running cells)
                has_rshift = keyboard.Key.shift_r in self._pressed_keys
                has_enter = keyboard.Key.enter in self._pressed_keys
                has_lshift = (
                    keyboard.Key.shift in self._pressed_keys
                    or getattr(keyboard.Key, 'shift_l', None) in self._pressed_keys
                    or _is_physically_down(win32con.VK_LSHIFT)
                )

                if has_rshift and has_enter and not has_lshift:
                    # Double-check physical hardware state of Right Shift and Return
                    if _is_physically_down(win32con.VK_RSHIFT) and _is_physically_down(win32con.VK_RETURN):
                        logger.warning("EMERGENCY HOTKEY TRIGGERED (Right Shift + Enter)! Terminating SPUTNIK...")
                        print("\n[SPUTNIK] АВАРИЙНОЕ ЗАВЕРШЕНИЕ РАБОТЫ (Right Shift + Enter)!")
                        try:
                            self.on_emergency_exit()
                        except Exception:
                            pass
        except Exception:
            pass

    def _on_release(self, key):
        try:
            with self._lock:
                self._pressed_keys.discard(key)
        except Exception:
            pass

    def start(self):
        """Start listening for hotkey in background thread."""
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self._listener.daemon = True
            self._listener.start()
            logger.info("Emergency hotkey listener (Right Shift + Enter) started.")
        except Exception as e:
            logger.error(f"Failed to start hotkey listener: {e}")

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
