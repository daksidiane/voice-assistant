import re
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox
import logging
from typing import Optional

from core.config import config
from commands.custom_commands import custom_command_manager

logger = logging.getLogger(__name__)


class SettingsWindow:
    """GUI window for configuration and custom command management (F3.2, F8.3)."""

    def __init__(self, root: Optional[tk.Tk] = None):
        self._root = root
        self._window: Optional[tk.Toplevel] = None

    def show(self):
        """Open or bring settings window to focus."""
        if self._window is not None and self._window.winfo_exists():
            self._window.lift()
            self._window.focus_force()
            return

        self._window = tk.Toplevel(self._root) if self._root else tk.Tk()
        self._window.title("Спутник — Настройки системы")
        self._window.geometry("780x620")
        self._window.minsize(680, 520)

        # Style
        style = ttk.Style(self._window)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        notebook = ttk.Notebook(self._window)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Tabs
        tab_commands = ttk.Frame(notebook, padding=10)
        tab_voice = ttk.Frame(notebook, padding=10)
        tab_api = ttk.Frame(notebook, padding=10)

        notebook.add(tab_commands, text="  Пользовательские команды  ")
        notebook.add(tab_voice, text="  Голос и обращение  ")
        notebook.add(tab_api, text="  API и Нейросети (ИИ)  ")

        self._build_commands_tab(tab_commands)
        self._build_voice_tab(tab_voice)
        self._build_api_tab(tab_api)

        # Footer
        footer = ttk.Frame(self._window, padding=10)
        footer.pack(fill="x")
        ttk.Button(footer, text="Закрыть", command=self._window.destroy).pack(side="right", padx=5)

    def _build_commands_tab(self, parent: ttk.Frame):
        """Custom commands CRUD table and form."""
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill="both", expand=True)

        columns = ("phrase", "action", "target", "response")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        self.tree.heading("phrase", text="Голосовая фраза")
        self.tree.heading("action", text="Действие")
        self.tree.heading("target", text="Цель (URL/Путь/Параметр)")
        self.tree.heading("response", text="Ответ ассистента")

        self.tree.column("phrase", width=160)
        self.tree.column("action", width=120)
        self.tree.column("target", width=220)
        self.tree.column("response", width=180)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._refresh_commands_table()

        # Add / Edit form
        form = ttk.LabelFrame(parent, text=" Добавить / Изменить команду ", padding=10)
        form.pack(fill="x", pady=10)

        r1 = ttk.Frame(form)
        r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="Фраза:", width=12).pack(side="left")
        self.entry_phrase = ttk.Entry(r1)
        self.entry_phrase.pack(side="left", fill="x", expand=True, padx=5)

        ttk.Label(r1, text="Действие:", width=10).pack(side="left", padx=(10, 0))
        self.combo_action = ttk.Combobox(
            r1,
            values=[
                "open_url",
                "open_app",
                "say",
                "media_play_pause",
                "media_next",
                "media_prev",
                "media_stop",
                "volume_up",
                "volume_down",
            ],
            state="readonly",
            width=15,
        )
        self.combo_action.set("open_url")
        self.combo_action.pack(side="left", padx=5)

        r2 = ttk.Frame(form)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Цель:", width=12).pack(side="left")
        self.entry_target = ttk.Entry(r2)
        self.entry_target.pack(side="left", fill="x", expand=True, padx=5)

        r3 = ttk.Frame(form)
        r3.pack(fill="x", pady=2)
        ttk.Label(r3, text="Ответ TTS:", width=12).pack(side="left")
        self.entry_response = ttk.Entry(r3)
        self.entry_response.pack(side="left", fill="x", expand=True, padx=5)

        btn_row = ttk.Frame(form)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="💾 Сохранить команду", command=self._save_command).pack(side="left", padx=5)
        ttk.Button(btn_row, text="🗑 Удалить выбранную", command=self._delete_command).pack(side="left", padx=5)

    def _refresh_commands_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for phrase, c in custom_command_manager.commands.items():
            self.tree.insert("", "end", values=(phrase, c.get("action", ""), c.get("target", ""), c.get("response", "")))

    def _save_command(self):
        phrase = self.entry_phrase.get().strip().lower()
        action = self.combo_action.get().strip()
        target = self.entry_target.get().strip()
        response = self.entry_response.get().strip()

        if not phrase:
            messagebox.showerror("Ошибка", "Укажите голосовую фразу!")
            return

        if not custom_command_manager.add_command(phrase, action, target, response):
            messagebox.showerror("Ошибка валидации", "Недопустимый URL или имя программы.")
            return

        self._refresh_commands_table()
        self.entry_phrase.delete(0, tk.END)
        self.entry_target.delete(0, tk.END)
        self.entry_response.delete(0, tk.END)
        messagebox.showinfo("Успешно", f"Команда '{phrase}' сохранена!")

    def _delete_command(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите команду из таблицы для удаления.")
            return
        item = self.tree.item(selected[0])
        phrase = item["values"][0]
        if messagebox.askyesno("Подтверждение", f"Удалить команду '{phrase}'?"):
            custom_command_manager.remove_command(phrase)
            self._refresh_commands_table()

    def _build_voice_tab(self, parent: ttk.Frame):
        """Voice and User Title settings tab."""
        # 1. Section: Owner Gender & Address Title
        f_user = ttk.LabelFrame(parent, text=" 👤 Профиль владельца и форма обращения ", padding=12)
        f_user.pack(fill="x", pady=(0, 10))

        row_u = ttk.Frame(f_user)
        row_u.pack(fill="x", pady=4)
        ttk.Label(row_u, text="Пол владельца:", width=20, font=("Segoe UI", 9, "bold")).pack(side="left")

        current_gender = config.get("assistant.user_gender", "male").lower()
        gender_options = [
            ("Мужской (Обращение: «Сэр»)", "male"),
            ("Женский (Обращение: «Госпожа»)", "female")
        ]

        combo_gender = ttk.Combobox(
            row_u,
            values=[opt[0] for opt in gender_options],
            state="readonly",
            width=35
        )
        if current_gender == "female":
            combo_gender.set(gender_options[1][0])
        else:
            combo_gender.set(gender_options[0][0])
        combo_gender.pack(side="left", padx=5)

        ttk.Label(
            f_user,
            text="💡 Если выбран женский пол, Спутник обращается исключительно «Госпожа» во всех ответах.",
            font=("Segoe UI", 8),
            foreground="#64748b"
        ).pack(anchor="w", pady=(4, 0))

        # 2. Section: Voice Engine & Voice Selection
        f_voice = ttk.LabelFrame(parent, text=" 🔊 Голос и синтез речи (TTS) ", padding=12)
        f_voice.pack(fill="x", pady=5)

        row_v1 = ttk.Frame(f_voice)
        row_v1.pack(fill="x", pady=6)
        ttk.Label(row_v1, text="Голос ассистента:", width=20, font=("Segoe UI", 9, "bold")).pack(side="left")

        current_v_gender = config.get("voice.gender", "male").lower()
        current_engine = config.get("voice.engine", "yandex").lower()
        current_y_voice = config.get("voice.yandex_voice", "kirill").lower()
        current_edge_voice = config.get("voice.edge_voice", "ru-RU-DmitryNeural")
        current_sapi_voice = config.get("voice.sapi_voice", "Microsoft Pavel")

        voice_options = [
            ("Мужской голос (Кирилл строгий, Yandex SpeechKit)", "male", "yandex", "kirill", "strict"),
            ("Мужской голос (Ермил радостный, Yandex SpeechKit)", "male", "yandex", "ermil", "good"),
            ("Мужской голос (Руслан, Piper TTS Оффлайн Нейросеть)", "male", "piper", "ru_RU-ruslan-medium", ""),
            ("Мужской голос (Павел, Windows Local / Оффлайн)", "male", "sapi", "Microsoft Pavel", ""),
            ("Мужской голос (Дмитрий, Edge-TTS Онлайн)", "male", "edge_tts", "ru-RU-DmitryNeural", ""),
            ("Женский голос (Ирина, Windows Local / Оффлайн)", "female", "sapi", "Microsoft Irina", ""),
            ("Женский голос (Светлана, Edge-TTS Онлайн)", "female", "edge_tts", "ru-RU-SvetlanaNeural", "")
        ]

        combo_voice_choice = ttk.Combobox(
            row_v1,
            values=[opt[0] for opt in voice_options],
            state="readonly",
            width=50
        )

        selected_voice_label = voice_options[0][0]
        for opt in voice_options:
            label, v_gender, eng, v_name, v_role = opt
            if eng == current_engine:
                if eng == "yandex":
                    if v_name == current_y_voice:
                        selected_voice_label = label
                        break
                elif eng == "piper":
                    selected_voice_label = label
                    break
                elif eng == "sapi":
                    if v_gender == current_v_gender or v_name == current_sapi_voice:
                        selected_voice_label = label
                        break
                elif eng == "edge_tts":
                    if v_gender == current_v_gender or v_name == current_edge_voice:
                        selected_voice_label = label
                        break
        combo_voice_choice.set(selected_voice_label)
        combo_voice_choice.pack(side="left", padx=5)

        row_v2 = ttk.Frame(f_voice)
        row_v2.pack(fill="x", pady=6)
        ttk.Label(row_v2, text="Движок синтеза:", width=20).pack(side="left")
        combo_engine = ttk.Combobox(row_v2, values=["yandex", "piper", "sapi", "edge_tts"], state="readonly", width=25)
        combo_engine.set(config.get("voice.engine", "yandex"))
        combo_engine.pack(side="left", padx=5)

        def _on_gender_changed(e=None):
            sel_g_idx = combo_gender.current()
            if sel_g_idx >= 0:
                chosen_u_gender = gender_options[sel_g_idx][1]
                title = "госпожа" if chosen_u_gender == "female" else "сэр"
                config.set("assistant.user_gender", chosen_u_gender)
                config.set("assistant.user_title", title)
                logger.info(f"Updated owner profile: gender={chosen_u_gender}, title={title}")

        def _on_voice_changed(e=None):
            sel_v_idx = combo_voice_choice.current()
            if sel_v_idx >= 0:
                opt_label, chosen_v_gender, chosen_engine, chosen_voice_name, chosen_role = voice_options[sel_v_idx]
                config.set("voice.engine", chosen_engine)
                combo_engine.set(chosen_engine)
                if chosen_engine == "yandex":
                    config.set("voice.yandex_voice", chosen_voice_name)
                    if chosen_role:
                        config.set("voice.yandex_role", chosen_role)
                        config.set("voice.yandex_emotion", chosen_role)
                    config.set("voice.yandex_speed", "1.0")
                elif chosen_engine == "piper":
                    config.set("voice.piper_voice", chosen_voice_name)
                elif chosen_engine == "sapi":
                    config.set("voice.sapi_voice", chosen_voice_name)
                else:
                    config.set("voice.edge_voice", chosen_voice_name)
                config.set("voice.gender", chosen_v_gender)
                logger.info(f"Saved voice: {opt_label}, engine={chosen_engine}")

        def _on_engine_changed(e=None):
            eng = combo_engine.get()
            config.set("voice.engine", eng)
            for opt in voice_options:
                if opt[2] == eng:
                    combo_voice_choice.set(opt[0])
                    _on_voice_changed()
                    break

        def _save_all(silent: bool = False):
            _on_gender_changed()
            _on_voice_changed()
            title = config.get("assistant.user_title", "госпожа")
            sel_v_idx = combo_voice_choice.current()
            chosen_label = voice_options[sel_v_idx][0] if sel_v_idx >= 0 else config.get("voice.engine")
            if not silent:
                messagebox.showinfo("Успешно", f"Настройки сохранены!\nОбращение: {title.capitalize()}\nГолос: {chosen_label}")

        # Bind event listeners
        combo_gender.bind("<<ComboboxSelected>>", lambda e: _on_gender_changed())
        combo_voice_choice.bind("<<ComboboxSelected>>", lambda e: _on_voice_changed())
        combo_engine.bind("<<ComboboxSelected>>", lambda e: _on_engine_changed())

        def _test_speech():
            from tts.speaker import speaker
            _save_all(silent=True)
            title = config.get("assistant.user_title", "госпожа")
            preview_text = f"Слушаю вас, {title}. Все системы работают в штатном режиме."
            speaker.speak(preview_text)

        btn_row = ttk.Frame(f_voice)
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="💾 Сохранить настройки", command=lambda: _save_all(silent=False)).pack(side="left", padx=5)
        ttk.Button(btn_row, text="🔊 Прослушать пример", command=_test_speech).pack(side="left", padx=5)

    def _build_api_tab(self, parent: ttk.Frame):
        """API keys, Search and AI configuration."""
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 1. Section: AI Provider & LLM
        f_ai = ttk.LabelFrame(scrollable_frame, text=" 🧠 Нейросеть (LLM) и Визуальный анализ экрана ", padding=12)
        f_ai.pack(fill="x", pady=6)

        # Provider
        r_prov = ttk.Frame(f_ai)
        r_prov.pack(fill="x", pady=4)
        ttk.Label(r_prov, text="Провайдер ИИ:", width=22, font=("Segoe UI", 9, "bold")).pack(side="left")
        current_prov = str(config.get("ai.provider", "google")).lower()
        combo_prov = ttk.Combobox(r_prov, values=["Google AI (Gemini)", "OpenAI / Совместимый API"], state="readonly", width=28)
        combo_prov.set("Google AI (Gemini)" if current_prov == "google" else "OpenAI / Совместимый API")
        combo_prov.pack(side="left", padx=5)

        # Google AI Key
        r_gkey = ttk.Frame(f_ai)
        r_gkey.pack(fill="x", pady=4)
        ttk.Label(r_gkey, text="Google AI API Key:", width=22).pack(side="left")
        e_gkey = ttk.Entry(r_gkey, width=38, show="*")
        e_gkey.insert(0, config.get_api_key("GEMINI_API_KEY") or config.get_api_key("GOOGLE_API_KEY"))
        e_gkey.pack(side="left", padx=5)
        ttk.Label(r_gkey, text="(бесплатно на aistudio.google.com)", foreground="#64748b", font=("Segoe UI", 8)).pack(side="left")

        # OpenAI Key
        r_oai = ttk.Frame(f_ai)
        r_oai.pack(fill="x", pady=4)
        ttk.Label(r_oai, text="OpenAI API Key:", width=22).pack(side="left")
        e_oai = ttk.Entry(r_oai, width=38, show="*")
        e_oai.insert(0, config.get_api_key("OPENAI_API_KEY"))
        e_oai.pack(side="left", padx=5)

        # AI Model
        r_model = ttk.Frame(f_ai)
        r_model.pack(fill="x", pady=4)
        ttk.Label(r_model, text="Модель ИИ:", width=22).pack(side="left")
        e_model = ttk.Combobox(
            r_model,
            values=[
                "gemini-flash-lite-latest",
                "gemini-3.1-flash-lite",
                "gemini-flash-latest",
                "gemini-3.6-flash",
                "gpt-4o-mini"
            ],
            width=36
        )
        cur_model = config.get("ai.model", "gemini-flash-lite-latest")
        if "preview" in cur_model or "1.5" in cur_model:
            cur_model = "gemini-flash-lite-latest"
        e_model.set(cur_model)
        e_model.pack(side="left", padx=5)

        # AI Base URL (OpenAI / Ollama)
        r_url = ttk.Frame(f_ai)
        r_url.pack(fill="x", pady=4)
        ttk.Label(r_url, text="AI Base URL:", width=22).pack(side="left")
        e_url = ttk.Entry(r_url, width=38)
        e_url.insert(0, config.get("ai.base_url", "https://api.openai.com/v1"))
        e_url.pack(side="left", padx=5)

        # 2. Section: Internet Search
        f_search = ttk.LabelFrame(scrollable_frame, text=" 🌐 Поиск в интернете ", padding=12)
        f_search.pack(fill="x", pady=6)

        r_serper = ttk.Frame(f_search)
        r_serper.pack(fill="x", pady=4)
        ttk.Label(r_serper, text="Serper API Key:", width=22).pack(side="left")
        e_serper = ttk.Entry(r_serper, width=38, show="*")
        e_serper.insert(0, config.get_api_key("SERPER_API_KEY"))
        e_serper.pack(side="left", padx=5)
        ttk.Label(r_serper, text="(бесплатно 2500 запросов на serper.dev)", foreground="#64748b", font=("Segoe UI", 8)).pack(side="left")

        ttk.Label(
            f_search,
            text="При отсутствии ключа Serper работает бесплатный поиск энциклопедических фактов через Википедию.",
            foreground="#64748b",
            font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(2, 0))

        # 3. Section: Weather & Info
        f_info = ttk.LabelFrame(scrollable_frame, text=" ⛅ Погода и справочные сервисы ", padding=12)
        f_info.pack(fill="x", pady=6)

        # Weather city
        r_city = ttk.Frame(f_info)
        r_city.pack(fill="x", pady=4)
        ttk.Label(r_city, text="Город по умолчанию:", width=22).pack(side="left")
        e_city = ttk.Entry(r_city, width=25)
        e_city.insert(0, config.get("info.weather_default_city", "Москва"))
        e_city.pack(side="left", padx=5)

        # OpenWeatherMap Key
        r_wkey = ttk.Frame(f_info)
        r_wkey.pack(fill="x", pady=4)
        ttk.Label(r_wkey, text="OpenWeather API Key:", width=22).pack(side="left")
        e_wkey = ttk.Entry(r_wkey, width=38, show="*")
        e_wkey.insert(0, config.get_api_key("OPENWEATHER_API_KEY"))
        e_wkey.pack(side="left", padx=5)
        ttk.Label(r_wkey, text="(опционально, есть Open-Meteo)", foreground="#64748b", font=("Segoe UI", 8)).pack(side="left")

        # Yandex SpeechKit Key
        r_ykey = ttk.Frame(f_info)
        r_ykey.pack(fill="x", pady=4)
        ttk.Label(r_ykey, text="Yandex SpeechKit Key:", width=22).pack(side="left")
        e_ykey = ttk.Entry(r_ykey, width=38, show="*")
        e_ykey.insert(0, config.get_api_key("YANDEX_API_KEY"))
        e_ykey.pack(side="left", padx=5)
        ttk.Label(r_ykey, text="(для голоса Кирилл / Yandex TTS)", foreground="#64748b", font=("Segoe UI", 8)).pack(side="left")

        def _save_api():
            import os
            from core.config import ENV_PATH

            def _sanitize(val: str) -> str:
                return re.sub(r'[\r\n\0]', '', val).strip()

            city = _sanitize(e_city.get())
            wkey = _sanitize(e_wkey.get())
            gkey = _sanitize(e_gkey.get())
            serper_key = _sanitize(e_serper.get())
            oai_key = _sanitize(e_oai.get())
            ykey = _sanitize(e_ykey.get())
            url_val = _sanitize(e_url.get())
            model_val = _sanitize(e_model.get())
            prov_val = "google" if "Google" in combo_prov.get() else "openai"

            if url_val:
                parsed = urllib.parse.urlparse(url_val)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    messagebox.showerror("Ошибка", "AI Base URL должен начинаться с http:// или https:// и содержать домен.")
                    return

            config.set("info.weather_default_city", city)
            config.set("ai.provider", prov_val)
            config.set("ai.model", model_val or ("gemini-3-flash-preview" if prov_val == "google" else "gpt-4o-mini"))
            config.set("ai.base_url", url_val)

            # Update existing environment variables in memory
            updated_keys = {
                "AI_PROVIDER": prov_val,
                "AI_MODEL": model_val,
                "GEMINI_API_KEY": gkey,
                "SERPER_API_KEY": serper_key,
                "OPENAI_API_KEY": oai_key,
                "AI_BASE_URL": url_val,
                "OPENWEATHER_API_KEY": wkey,
                "YANDEX_API_KEY": ykey,
            }

            for k, v in updated_keys.items():
                os.environ[k] = v
                config.env[k] = v

            # Safely preserve any other existing environment variables in .env
            existing_env = {}
            if ENV_PATH.exists():
                try:
                    with open(ENV_PATH, "r", encoding="utf-8") as ef:
                        for line in ef:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                ek, ev = line.split("=", 1)
                                existing_env[ek.strip()] = ev.strip().strip("'\"")
                except Exception as e:
                    logger.warning(f"Could not read existing .env for merging: {e}")

            existing_env.update(updated_keys)

            # Save keys to .env safely
            lines = ["# Настройки API-ключей для голосового помощника Спутник\n"]
            for k, v in existing_env.items():
                lines.append(f"{k}={v}\n")

            try:
                with open(ENV_PATH, "w", encoding="utf-8") as env_f:
                    env_f.writelines(lines)
                messagebox.showinfo("Успешно", "Настройки API и внешних сервисов сохранены!")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось записать .env: {e}")

        btn_row = ttk.Frame(scrollable_frame)
        btn_row.pack(fill="x", pady=(10, 15))
        ttk.Button(btn_row, text="💾 Сохранить все настройки API", command=_save_api).pack(side="left", padx=5)
