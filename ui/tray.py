import logging
import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray

from core.event_bus import event_bus
from core.state import AssistantState
from ui.notifier import Notifier

logger = logging.getLogger(__name__)


def create_tray_icon_image(status: str) -> Image.Image:
    """Generate a crisp, high-contrast SPUTNIK Arc-Reactor icon for Windows system tray."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Color palette per status
    palettes = {
        "idle": ("#06101E", "#00E5FF", "#38BDF8", "#E0F2FE"),       # High-tech Cyan/Neon
        "active": ("#08152E", "#3B82F6", "#60A5FA", "#EFF6FF"),     # Blue (listening)
        "speaking": ("#1C1005", "#F59E0B", "#FCD34D", "#FEF3C7"),   # Amber (speaking/processing)
        "paused": ("#1C0709", "#EF4444", "#F87171", "#FEE2E2"),     # Red (muted)
    }
    bg, ring, core, accent = palettes.get(status, palettes["idle"])

    # Outer dark circular disc with vivid outline
    draw.ellipse((2, 2, size - 3, size - 3), fill=bg, outline=ring, width=3)

    # Concentric Arc-Reactor ring
    draw.ellipse((12, 12, size - 13, size - 13), outline=ring, width=2)

    # Reactor notches / cross-bars
    draw.line((31, 3, 31, 12), fill=accent, width=2)
    draw.line((31, size - 13, 31, size - 4), fill=accent, width=2)
    draw.line((3, 31, 12, 31), fill=accent, width=2)
    draw.line((size - 13, 31, size - 4, 31), fill=accent, width=2)

    # Inner glowing core
    draw.ellipse((21, 21, size - 22, size - 22), fill=core, outline=accent, width=1)

    # Center power dot
    draw.ellipse((28, 28, size - 29, size - 29), fill="#FFFFFF")

    return image


class TrayManager:
    """Controls the Windows system tray icon and context menu (F3.1)."""

    def __init__(
        self,
        on_open_settings: Callable[[], None],
        on_open_plans: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_exit: Callable[[], None],
        on_open_control: Optional[Callable[[], None]] = None
    ):
        self.on_open_settings = on_open_settings
        self.on_open_plans = on_open_plans
        self.on_toggle_pause = on_toggle_pause
        self.on_exit = on_exit
        self.on_open_control = on_open_control

        self._icon: Optional[pystray.Icon] = None
        self._current_state = AssistantState.IDLE
        self._is_paused = False

        self._icons = {
            "idle": create_tray_icon_image("idle"),
            "active": create_tray_icon_image("active"),
            "paused": create_tray_icon_image("paused"),
            "speaking": create_tray_icon_image("speaking")
        }

    def _handle_open_control(self):
        if self.on_open_control:
            self.on_open_control()

    def _get_menu(self):
        status_text = "🟢 Ожидает («Спутник»)"
        if self._is_paused:
            status_text = "🔴 Прослушивание приостановлено"
        elif self._current_state == AssistantState.ACTIVE:
            status_text = "🔵 Слушает команду..."
        elif self._current_state in (AssistantState.PROCESSING, AssistantState.SPEAKING):
            status_text = "🟡 Обработка / Речь..."

        pause_label = "▶ Возобновить прослушивание" if self._is_paused else "⏸ Приостановить прослушивание"

        menu_items = [
            pystray.MenuItem("💬 Панель управления", lambda icon, item: self._handle_open_control(), default=True),
            pystray.MenuItem(status_text, lambda icon, item: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙ Настройки...", lambda icon, item: self.on_open_settings()),
            pystray.MenuItem("📅 Планы и напоминания...", lambda icon, item: self.on_open_plans()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(pause_label, lambda icon, item: self.toggle_pause()),
            pystray.MenuItem("❌ Выйти", lambda icon, item: self.on_exit())
        ]

        return pystray.Menu(*menu_items)

    def run(self):
        """Run the tray icon loop (blocking in its own thread)."""
        self._icon = pystray.Icon(
            "SPUTNIK",
            icon=self._icons["idle"],
            title="Спутник — Голосовой помощник (Активен)",
            menu=self._get_menu()
        )
        Notifier.set_tray_icon(self._icon)
        self._icon.run()

    def update_state(self, state: AssistantState):
        """Update tray icon and title according to current state safely without recreating Win32 HMENU."""
        self._current_state = state
        if not self._icon:
            return

        try:
            if self._is_paused:
                self._icon.icon = self._icons["paused"]
                self._icon.title = "Спутник — На паузе"
            elif state == AssistantState.IDLE:
                self._icon.icon = self._icons["idle"]
                self._icon.title = "Спутник — Голосовой помощник (Активен)"
            elif state == AssistantState.ACTIVE:
                self._icon.icon = self._icons["active"]
                self._icon.title = "Спутник — Слушает команду..."
            elif state in (AssistantState.PROCESSING, AssistantState.SPEAKING):
                self._icon.icon = self._icons["speaking"]
                self._icon.title = "Спутник — Обработка / Говорит"
        except Exception as e:
            logger.debug(f"Tray update_state suppressed error: {e}")

    def toggle_pause(self):
        """Toggle paused state."""
        self._is_paused = not self._is_paused
        self.on_toggle_pause()
        self.update_state(self._current_state)
        if self._icon:
            try:
                self._icon.menu = self._get_menu()
            except Exception:
                pass

    def stop(self):
        """Stop tray icon."""
        if self._icon:
            self._icon.stop()
