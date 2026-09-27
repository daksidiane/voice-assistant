import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import logging
from typing import Optional

from modules.scheduler import scheduler, parse_dt_safe

logger = logging.getLogger(__name__)


class PlansWindow:
    """GUI window displaying scheduled plans and reminders (F3.3)."""

    def __init__(self, root: Optional[tk.Tk] = None):
        self._root = root
        self._window: Optional[tk.Toplevel] = None
        self._sort_col = "datetime"
        self._sort_reverse = False

    def show(self):
        """Open or focus the plans window."""
        self._sort_col = "datetime"
        self._sort_reverse = False
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            self._refresh_plans()
            return

        self._window = tk.Toplevel(self._root) if self._root else tk.Tk()
        self._window.title("Спутник — Список планов и напоминаний")
        self._window.geometry("720x480")
        self._window.minsize(620, 400)

        # Style
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        main_frame = ttk.Frame(self._window, padding=12)
        main_frame.pack(fill="both", expand=True)

        header = ttk.Label(
            main_frame,
            text="📅 Запланированные события и автоматические напоминания:",
            font=("Segoe UI", 11, "bold")
        )
        header.pack(anchor="w", pady=(0, 2))

        self.hint_label = ttk.Label(
            main_frame,
            text="📌 Порядок событий: сначала ближайшие (сегодня 18:00, затем 19:00, затем завтра).",
            font=("Segoe UI", 9),
            foreground="#2563eb"
        )
        self.hint_label.pack(anchor="w", pady=(0, 8))

        # Table
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill="both", expand=True)

        columns = ("id", "datetime", "title", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)

        self.tree.column("id", width=40, anchor="center")
        self.tree.column("datetime", width=180, anchor="center")
        self.tree.column("title", width=310)
        self.tree.column("status", width=140, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._refresh_plans()

        # Add form
        form = ttk.LabelFrame(main_frame, text=" Быстрое добавление события ", padding=8)
        form.pack(fill="x", pady=10)

        row1 = ttk.Frame(form)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Событие:", width=10).pack(side="left")
        self.entry_title = ttk.Entry(row1)
        self.entry_title.pack(side="left", fill="x", expand=True, padx=5)

        ttk.Label(row1, text="ДД-ММ-ГГГГ ЧЧ:ММ:", width=18).pack(side="left", padx=(10, 0))
        self.entry_dt = ttk.Entry(row1, width=18)
        self.entry_dt.insert(0, datetime.now().strftime("%d-%m-%Y %H:%M"))
        self.entry_dt.pack(side="left", padx=5)

        btn_bar = ttk.Frame(form)
        btn_bar.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_bar, text="➕ Добавить событие", command=self._add_plan).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="🗑 Удалить выбранное", command=self._delete_plan).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="🔄 Сбросить порядок (сначала 18:00 ➔ 19:00)", command=self._reset_to_chronological).pack(side="left", padx=4)

        # Bottom
        footer = ttk.Frame(main_frame)
        footer.pack(fill="x", pady=(4, 0))
        ttk.Button(footer, text="Закрыть", command=self._window.destroy).pack(side="right")

    def _reset_to_chronological(self):
        """Reset table to default chronological order (earliest first)."""
        self._sort_col = "datetime"
        self._sort_reverse = False
        self._refresh_plans()

    def _sort_by_column(self, col: str):
        """Toggle sort direction for clicked column and refresh."""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._refresh_plans()

    def _refresh_plans(self):
        """Refresh table contents sorted chronologically by default or by selected column."""
        for row in self.tree.get_children():
            self.tree.delete(row)

        if hasattr(self, "hint_label") and self.hint_label:
            if self._sort_col == "datetime" and self._sort_reverse:
                self.hint_label.config(
                    text="⚠️ Включен ОБРАТНЫЙ порядок (поздние сначала: 19:00 выше, 18:00 ниже). Нажмите кнопку ниже для возврата!",
                    foreground="#dc2626"
                )
            else:
                self.hint_label.config(
                    text="📌 Порядок событий: сначала ближайшие (сегодня 18:00, затем 19:00, затем завтра).",
                    foreground="#2563eb"
                )

        # Update headings with sort indicators
        col_names = {
            "id": "#",
            "datetime": "Дата и время",
            "title": "Событие / Задача",
            "status": "Статус напоминания"
        }
        for c, name in col_names.items():
            if c == self._sort_col:
                if c == "datetime":
                    order_label = " ▲ (сначала ближайшие)" if not self._sort_reverse else " ▼ (поздние сначала)"
                    header_text = f"{name}{order_label}"
                else:
                    arrow = " ▲" if not self._sort_reverse else " ▼"
                    header_text = f"{name}{arrow}"
            else:
                header_text = name
            self.tree.heading(c, text=header_text, command=lambda _c=c: self._sort_by_column(_c))

        scheduler.load()
        plans = scheduler.get_all_plans(sorted_by_date=False)

        # Apply column sorting (default: datetime ascending)
        if self._sort_col == "datetime":
            plans.sort(key=lambda p: parse_dt_safe(p.get("datetime", "")), reverse=self._sort_reverse)
        elif self._sort_col == "id":
            plans.sort(key=lambda p: p.get("id", 0), reverse=self._sort_reverse)
        elif self._sort_col == "title":
            plans.sort(key=lambda p: str(p.get("title", "")).lower(), reverse=self._sort_reverse)
        elif self._sort_col == "status":
            plans.sort(key=lambda p: (p.get("reminded_event", False), p.get("reminded_1h", False)), reverse=self._sort_reverse)
        else:
            plans.sort(key=lambda p: parse_dt_safe(p.get("datetime", "")), reverse=self._sort_reverse)

        for p in plans:
            status = "Ожидает"
            if p.get("reminded_event", False):
                status = "Выполнено"
            elif p.get("reminded_1h", False):
                status = "Предупрежден (1 ч)"
            raw_dt = p.get("datetime", "")
            dt_obj = parse_dt_safe(raw_dt)
            display_dt = dt_obj.strftime("%d-%m-%Y %H:%M") if dt_obj != datetime.max else raw_dt
            self.tree.insert("", "end", values=(
                p.get("id"),
                display_dt,
                p.get("title"),
                status
            ))

    def _add_plan(self):
        title = self.entry_title.get().strip()
        dt_str = self.entry_dt.get().strip()
        if not title:
            messagebox.showwarning("Внимание", "Пожалуйста, введите название события.")
            return
        dt = parse_dt_safe(dt_str)
        if dt == datetime.max:
            messagebox.showerror("Ошибка", "Неверный формат даты и времени. Используйте: ДД-ММ-ГГГГ ЧЧ:ММ\nПример: 22-09-2026 18:30")
            return

        scheduler.add_plan(title, dt)
        self.entry_title.delete(0, tk.END)
        self._sort_col = "datetime"
        self._sort_reverse = False
        self._refresh_plans()
        messagebox.showinfo("Успешно", f"Событие '{title}' добавлено в расписание!")

    def _delete_plan(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите событие из таблицы для удаления.")
            return
        item = self.tree.item(selected[0])
        plan_id = item["values"][0]
        title = item["values"][2]
        if messagebox.askyesno("Подтверждение", f"Удалить событие #{plan_id} '{title}'?"):
            scheduler.delete_plan(int(plan_id))
            self._refresh_plans()
