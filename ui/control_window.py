import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import logging
from typing import Callable, Optional, List
from datetime import datetime

from core.state import AssistantState

logger = logging.getLogger(__name__)


class SputnikControlWindow:
    """
    Unified Graphical Control Center and Chat Interface for SPUTNIK.
    Supports text input, conversation history, status monitoring, and quick action buttons.
    """

    def __init__(
        self,
        root: tk.Tk,
        on_execute_command: Callable[[str, bool], None],
        on_open_settings: Callable[[], None],
        on_open_plans: Callable[[], None],
        on_toggle_pause: Callable[[], None],
        on_shutdown: Callable[[], None]
    ):
        self._root = root
        self._on_execute_command = on_execute_command
        self._on_open_settings = on_open_settings
        self._on_open_plans = on_open_plans
        self._on_toggle_pause = on_toggle_pause
        self._on_shutdown = on_shutdown

        self._window: Optional[tk.Toplevel] = None
        self._history: List[str] = []
        self._history_idx = -1
        self._is_paused = False
        self._current_state = AssistantState.IDLE

    def show(self):
        """Open or restore the control window."""
        if self._window is not None and self._window.winfo_exists():
            self._window.deiconify()
            self._window.lift()
            self._window.focus_force()
            return

        self._window = tk.Toplevel(self._root)
        self._window.title("Спутник — Панель управления")
        self._window.geometry("780x580")
        self._window.minsize(680, 480)

        # Style configuration
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Intercept close window to prompt confirmation before quitting
        self._window.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

        self._build_ui()
        self.update_status(self._current_state, self._is_paused)

    def _on_close_attempt(self):
        """Prompt confirmation popup when user attempts to close the SPUTNIK interface."""
        if messagebox.askyesno("Подтверждение", "Вы точно хотите закрыть окно Спутника?"):
            logger.info("User confirmed closing SPUTNIK interface. Shutting down...")
            if self._window and self._window.winfo_exists():
                self._window.destroy()
            self._on_shutdown()
        else:
            logger.info("User cancelled closing SPUTNIK interface.")

    def hide(self):
        """Hide window to system tray."""
        if self._window and self._window.winfo_exists():
            self._window.withdraw()
            logger.info("Control window minimized to system tray.")

    def _build_ui(self):
        """Construct modern dashboard UI."""
        main_container = ttk.Frame(self._window, padding=8)
        main_container.pack(fill="both", expand=True)

        # 1. Top Header & Toolbar
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill="x", pady=(0, 6))

        # Title and Status
        title_box = ttk.Frame(header_frame)
        title_box.pack(side="left", fill="x", expand=True)

        self.lbl_title = ttk.Label(
            title_box,
            text="⚡ СПУТНИК : ГОЛОСОВОЙ АССИСТЕНТ",
            font=("Segoe UI", 12, "bold"),
            foreground="#0284c7"
        )
        self.lbl_title.pack(anchor="w")

        self.lbl_status = ttk.Label(
            title_box,
            text="🟢 Ожидает активации («Спутник»)",
            font=("Segoe UI", 9)
        )
        self.lbl_status.pack(anchor="w")

        # Toolbar buttons
        btn_box = ttk.Frame(header_frame)
        btn_box.pack(side="right")

        self.btn_pause = ttk.Button(btn_box, text="⏸ Пауза", command=self._toggle_pause_action)
        self.btn_pause.pack(side="left", padx=2)

        ttk.Button(btn_box, text="⚙ Настройки", command=self._on_open_settings).pack(side="left", padx=2)
        ttk.Button(btn_box, text="📅 Планы", command=self._on_open_plans).pack(side="left", padx=2)
        ttk.Button(btn_box, text="🧹 Очистить", command=self.clear_chat).pack(side="left", padx=2)
        ttk.Button(btn_box, text="❌ Выход", command=self._on_close_attempt).pack(side="left", padx=2)

        # 2. Chat Conversation View
        chat_frame = ttk.LabelFrame(main_container, text=" Диалог и журнал команд ", padding=4)
        chat_frame.pack(fill="both", expand=True, pady=4)

        self.chat_text = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#00e5ff",
            relief="flat",
            padx=8,
            pady=8
        )
        self.chat_text.pack(fill="both", expand=True)

        # Text color tags
        self.chat_text.tag_config("time", foreground="#64748b")
        self.chat_text.tag_config("user_tag", foreground="#38bdf8", font=("Consolas", 10, "bold"))
        self.chat_text.tag_config("user_msg", foreground="#e2e8f0")
        self.chat_text.tag_config("sputnik_tag", foreground="#34d399", font=("Consolas", 10, "bold"))
        self.chat_text.tag_config("sputnik_msg", foreground="#a7f3d0")
        self.chat_text.tag_config("system_tag", foreground="#fbbf24", font=("Consolas", 9, "italic"))
        self.chat_text.tag_config("wait_msg", foreground="#cbd5e1", font=("Consolas", 9, "italic"))

        self.append_system_message("Система инициализирована. Вы можете вводить команды текстом или использовать голос.")

        # 3. Quick Action Buttons Bar
        quick_frame = ttk.Frame(main_container)
        quick_frame.pack(fill="x", pady=4)

        quick_buttons = [
            ("🕒 Время", "сколько времени"),
            ("⛅ Погода", "какая погода"),
            ("💵 Курс валют", "курс доллара"),
            ("📰 Новости", "свежие новости"),
            ("🖥️ Что на экране", "что на экране"),
            ("📅 Список планов", "покажи планы"),
        ]

        for label, cmd in quick_buttons:
            b = ttk.Button(quick_frame, text=label, command=lambda c=cmd: self._send_quick_command(c))
            b.pack(side="left", padx=3, fill="x", expand=True)

        # 4. Input Area
        input_container = ttk.Frame(main_container)
        input_container.pack(fill="x", pady=(4, 2))

        self.cmd_entry = ttk.Entry(input_container, font=("Segoe UI", 10))
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cmd_entry.bind("<Return>", lambda e: self._send_input_command())
        self.cmd_entry.bind("<Up>", self._history_prev)
        self.cmd_entry.bind("<Down>", self._history_next)

        btn_send = ttk.Button(input_container, text="Отправить ↵", command=self._send_input_command)
        btn_send.pack(side="left")

        # 5. Bottom Status / Options Bar
        bottom_frame = ttk.Frame(main_container)
        bottom_frame.pack(fill="x", pady=(2, 0))

        self.var_speak = tk.BooleanVar(value=True)
        cb_speak = ttk.Checkbutton(bottom_frame, text="Озвучивать ответ голосом", variable=self.var_speak)
        cb_speak.pack(side="left")

        lbl_hint = ttk.Label(
            bottom_frame,
            text="💡 Клик по [X] сворачивает в трей | Экстренная остановка: Right Shift + Enter",
            font=("Segoe UI", 8),
            foreground="#64748b"
        )
        lbl_hint.pack(side="right")

    def _toggle_pause_action(self):
        """Toggle audio listening."""
        self._on_toggle_pause()

    def _send_quick_command(self, cmd_text: str):
        """Send command from quick button."""
        self.cmd_entry.delete(0, tk.END)
        self.cmd_entry.insert(0, cmd_text)
        self._send_input_command()

    def _send_input_command(self):
        """Dispatch command entered in text box."""
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return

        # Add to history
        self._history.append(cmd)
        self._history_idx = len(self._history)
        self.cmd_entry.delete(0, tk.END)

        speak = self.var_speak.get()
        self.append_user_message(cmd)
        self._on_execute_command(cmd, speak)

    def _history_prev(self, event):
        """Navigate backward in command history."""
        if self._history and self._history_idx > 0:
            self._history_idx -= 1
            self.cmd_entry.delete(0, tk.END)
            self.cmd_entry.insert(0, self._history[self._history_idx])
        return "break"

    def _history_next(self, event):
        """Navigate forward in command history."""
        if self._history and self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self.cmd_entry.delete(0, tk.END)
            self.cmd_entry.insert(0, self._history[self._history_idx])
        elif self._history_idx >= len(self._history) - 1:
            self._history_idx = len(self._history)
            self.cmd_entry.delete(0, tk.END)
        return "break"

    def append_user_message(self, text: str):
        """Append user message to chat log."""
        if not self._window or not self._window.winfo_exists():
            return
        now_str = datetime.now().strftime("%H:%M:%S")
        self.chat_text.insert(tk.END, f"[{now_str}] ", "time")
        self.chat_text.insert(tk.END, "Вы: ", "user_tag")
        self.chat_text.insert(tk.END, f"{text}\n", "user_msg")
        self.chat_text.see(tk.END)

    def append_sputnik_message(self, text: str):
        """Append assistant response to chat log."""
        if not self._window or not self._window.winfo_exists():
            return
        now_str = datetime.now().strftime("%H:%M:%S")
        self.chat_text.insert(tk.END, f"[{now_str}] ", "time")
        self.chat_text.insert(tk.END, "Спутник: ", "sputnik_tag")
        self.chat_text.insert(tk.END, f"{text}\n\n", "sputnik_msg")
        self.chat_text.see(tk.END)

    def append_system_message(self, text: str):
        """Append informational system message."""
        if not self._window or not self._window.winfo_exists():
            return
        now_str = datetime.now().strftime("%H:%M:%S")
        self.chat_text.insert(tk.END, f"[{now_str}] [Система] {text}\n", "system_tag")
        self.chat_text.see(tk.END)

    def clear_chat(self):
        """Clear chat history."""
        if self._window and self._window.winfo_exists():
            self.chat_text.delete("1.0", tk.END)
            self.append_system_message("Журнал диалога очищен.")

    def update_status(self, state: AssistantState, is_paused: bool):
        """Update status label and pause button."""
        self._current_state = state
        self._is_paused = is_paused

        if not self._window or not self._window.winfo_exists():
            return

        if is_paused:
            self.lbl_status.config(
                text="🔴 Прослушивание микрофона приостановлено",
                foreground="#ef4444"
            )
            self.btn_pause.config(text="▶ Возобновить")
        elif state == AssistantState.IDLE:
            self.lbl_status.config(
                text="🟢 Ожидает активации («Спутник» или текстовая команда)",
                foreground="#10b981"
            )
            self.btn_pause.config(text="⏸ Пауза")
        elif state == AssistantState.ACTIVE:
            self.lbl_status.config(
                text="🔵 Слушает команду пользователя...",
                foreground="#3b82f6"
            )
            self.btn_pause.config(text="⏸ Пауза")
        elif state in (AssistantState.PROCESSING, AssistantState.SPEAKING):
            self.lbl_status.config(
                text="🟡 Выполняет команду / Озвучивает ответ...",
                foreground="#f59e0b"
            )
            self.btn_pause.config(text="⏸ Пауза")
