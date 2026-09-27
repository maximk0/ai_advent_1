import json
import os
import time
import urllib.request
import urllib.error

class SimpleAgent:
    MODEL_DEFAULT = "openrouter/free"
    WINDOW_SIZE = 6
    FAST_MODEL = "cohere/north-mini-code:free"

    # День 15: Определение разрешенных переходов конечного автомата
    TSM_ALLOWED_TRANSITIONS = {
        "none": ["planning"],
        "planning": ["execution", "none"],
        "execution": ["validation", "planning"],
        "validation": ["done", "execution", "planning"],
        "done": ["planning", "none"]
    }

    # Путь к файлу состояния относительно файла скрипта
    STATE_FILE = os.path.join(os.path.dirname(__file__), "history_day15.json")

    def __init__(self):
        self.history = []
        self.system_prompt = "Ты — полезный AI-ассистент."
        self.model = self.MODEL_DEFAULT
        self.temperature = 0.7
        self.top_p = 1.0
        self.top_k = 0
        self.context_compression = True
        self.planning_mode_enabled = True

        # Трехуровневая система памяти
        self.wm = {}   # Working Memory: текущая задача, активный контекст
        self.ltm = {}  # Long-Term Memory: глобальные факты, предпочтения

        # День 12: Система персонализации и профилей пользователей
        self.current_profile = "Android Developer"
        self.profiles = {
            "Android Developer": {
                "role": "Старший Android-разработчик (Kotlin, Compose, Koin)",
                "style": "Технический, лаконичный, без лишней 'воды', строго по делу.",
                "format": "Только чистый Kotlin-код с лаконичными комментариями к неочевидным архитектурным моментам.",
                "constraints": "Писать код строго с использованием Jetpack Compose, Type Hints, чистой архитектуры. Никакого Java-кода."
            },
            "Data Scientist": {
                "role": "Эксперт по анализу данных и машинному обучению (Python, Pandas, ML)",
                "style": "Академический, подробный, с разбором математической сути формул.",
                "format": "Python-код (скрипты или jupyter-блоки) с развернутыми комментариями к каждой математической операции.",
                "constraints": "Использовать только современные библиотеки (pandas, numpy, scikit-learn). Подробно расписывать логику обучения."
            },
            "Technical Writer": {
                "role": "Профессиональный технический писатель и UX-копирайтер",
                "style": "Литературный, понятный, структурированный, ориентированный на широкую аудиторию.",
                "format": "Красиво размеченный Markdown (списки, таблицы, цитаты, blocks внимания). Код приводить только в виде коротких примеров.",
                "constraints": "Запрещено отвечать сплошным неразмеченным текстом. Использовать только русский язык, избегать сложного сленга без пояснений."
            }
        }

        # День 13: Конечный автомат задачи (Task State Machine)
        self.tsm_stage = "none"
        self.tsm_step = "Нет активной задачи"
        self.tsm_action = "Ожидание постановки задачи пользователем"

        # День 14: Жесткие инварианты и архитектурные ограничения проекта
        self.invariants = {
            "Архитектура": "Strict MVI (Model-View-Intent) с однонаправленным потоком данных (UDF). Любые сайд-эффекты оборачивать в News/Effects.",
            "Стек проекта": "Только чистый Kotlin, Jetpack Compose для UI и Koin для Dependency Injection. Использование Java или устаревших XML Layouts КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО.",
            "Безопасность": "Запрещено логировать, сохранять в plain-text или передавать на сторонние сервера пароли, токены и приватные ключи пользователей.",
            "Бизнес-правило": "Все финансовые транзакции и операции с балансом пользователя должны проходить обязательную двойную верификацию локально перед отправкой в сеть."
        }

        self.summary_context = ""
        self.saved_tokens = 0
        self.stats = {"total_tokens": 0, "last_prompt_tokens": 0, "cost": 0}
        self._load_state()

    def _save_state(self):
        state = {
            "history": self.history,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
            "current_profile": self.current_profile,
            "profiles": self.profiles,
            "tsm": {
                "stage": self.tsm_stage,
                "step": self.tsm_step,
                "action": self.tsm_action
            },
            "invariants": self.invariants,
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
                "planning_mode_enabled": self.planning_mode_enabled,
            },
            "stats": self.get_token_stats()
        }
        try:
            with open(self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            print(f"[{time.strftime('%H:%M:%S')}] State saved to {self.STATE_FILE} ({len(self.history)} msgs)")
        except Exception as e:
            print(f"Error saving state: {e}")

    def _load_state(self):
        if not os.path.exists(self.STATE_FILE):
            print(f"[{time.strftime('%H:%M:%S')}] No state file found at {self.STATE_FILE}")
            return
        try:
            with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                self.summary_context = state.get("summary_context", "")
                self.saved_tokens = state.get("saved_tokens", 0)
                self.wm = state.get("wm", {})
                self.ltm = state.get("ltm", {})
                self.history = state.get("history", [])

                if "current_profile" in state:
                    self.current_profile = state["current_profile"]
                if "profiles" in state:
                    self.profiles = state["profiles"]

                if "tsm" in state:
                    tsm = state["tsm"]
                    self.tsm_stage = tsm.get("stage", "none")
                    self.tsm_step = tsm.get("step", "Нет активной задачи")
                    self.tsm_action = tsm.get("action", "Ожидание постановки задачи")

                if "invariants" in state:
                    self.invariants = state["invariants"]

                config = state.get("config", {})
                self.system_prompt = config.get("system_prompt", self.system_prompt)
                self.model = config.get("model", self.model)
                self.temperature = config.get("temperature", self.temperature)
                self.top_p = config.get("top_p", self.top_p)
                self.top_k = config.get("top_k", self.top_k)
                self.context_compression = config.get("context_compression", True)
                self.planning_mode_enabled = config.get("planning_mode_enabled", True)
            print(f"[{time.strftime('%H:%M:%S')}] State loaded from {self.STATE_FILE} ({len(self.history)} msgs)")
        except Exception as e:
            print(f"Error loading state: {e}")

    def set_config(self, config: dict):
        self.system_prompt = config.get("system_prompt", self.system_prompt)
        self.model = config.get("model", self.model)
        self.temperature = float(config.get("temperature", self.temperature))
        self.top_p = float(config.get("top_p", self.top_p))
        self.top_k = int(config.get("top_k", self.top_k))
        self.context_compression = config.get("context_compression", self.context_compression)
        if "planning_mode_enabled" in config:
            self.planning_mode_enabled = bool(config["planning_mode_enabled"])
        self._save_state()

    def clear_history(self, clear_all: bool = False):
        self.history = []
        if clear_all:
            self.wm = {}
            self.ltm = {}
            self.tsm_stage = "none"
            self.tsm_step = "Нет активной задачи"
            self.tsm_action = "Ожидание постановки задачи пользователем"
            self.invariants = {
                "Архитектура": "Strict MVI (Model-View-Intent) с однонаправленным потоком данных (UDF). Любые сайд-эффекты оборачивать в News/Effects.",
                "Стек проекта": "Только чистый Kotlin, Jetpack Compose для UI и Koin для Dependency Injection. Использование Java или устаревших XML Layouts КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО.",
                "Безопасность": "Запрещено логировать, сохранять в plain-text или передавать на сторонние сервера пароли, токены и приватные ключи пользователей.",
                "Бизнес-правило": "Все финансовые транзакции и операции с балансом пользователя должны проходить обязательную двойную верификацию локально перед отправкой в сеть."
            }
            self.summary_context = ""
            self.saved_tokens = 0
        self._save_state()

    def pin_to_ltm(self, key: str, value: str):
        if key.strip():
            self.ltm[key.strip()] = value.strip()
            self._save_state()

    def update_wm_manually(self, wm_dict: dict):
        self.wm = wm_dict
        self._save_state()

    def update_ltm_manually(self, ltm_dict: dict):
        self.ltm = ltm_dict
        self._save_state()

    def update_tsm_manually(self, stage: str, step: str, action: str):
        self.tsm_stage = stage
        self.tsm_step = step
        self.tsm_action = action
        self._save_state()

    def pin_invariant(self, key: str, value: str):
        if key.strip():
            self.invariants[key.strip()] = value.strip()
            self._save_state()

    def delete_invariant(self, key: str):
        if key in self.invariants:
            del self.invariants[key]
            self._save_state()

    def switch_profile(self, profile_name: str):
        if profile_name in self.profiles:
            self.current_profile = profile_name
            self._save_state()

    def save_profile_data(self, profile_name: str, data: dict):
        if profile_name.strip():
            self.profiles[profile_name.strip()] = {
                "role": data.get("role", "").strip(),
                "style": data.get("style", "").strip(),
                "format": data.get("format", "").strip(),
                "constraints": data.get("constraints", "").strip()
            }
            self.current_profile = profile_name.strip()
            self._save_state()

    def is_transition_allowed(self, new_stage: str) -> bool:
        if new_stage == self.tsm_stage: return True
        allowed = self.TSM_ALLOWED_TRANSITIONS.get(self.tsm_stage, [])
        return new_stage in allowed

    def _route_memory(self, user_msg: str, assistant_msg: str):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key: return

        prompt = (
            "Ты — менеджер многоуровневой памяти и контроллер конечного автомата задач (TSM) ИИ-агента.\n"
            "Твоя задача — проанализировать последний обмен сообщениями и обновить три структуры данных:\n"
            "1. Long-Term Memory (LTM): глобальные, постоянные факты.\n"
            "2. Working Memory (WM): блок активных данных текущей задачи.\n"
            "3. Task State Machine (TSM): текущее состояние конечного автомата.\n"
            "   ДОСТУПНЫЕ ЭТАПЫ (stage):\n"
            "   - \"none\": задача еще не поставлена.\n"
            "   - \"planning\": обсуждение архитектуры и составление плана.\n"
            "   - \"execution\": написание кода, непосредственное решение.\n"
            "   - \"validation\": тестирование и верификация решения.\n"
            "   - \"done\": задача завершена.\n\n"
            "   СТРОГИЕ ПРАВИЛА ПЕРЕХОДОВ:\n"
            f"   Текущий этап: {self.tsm_stage}\n"
            f"   Разрешенные следующие этапы: {', '.join(self.TSM_ALLOWED_TRANSITIONS.get(self.tsm_stage, []))}\n"
            "   Ты НЕ ИМЕЕШЬ ПРАВА перепрыгивать этапы. Например, нельзя перейти в 'execution', если сейчас 'none' или 'planning' еще не завершен.\n\n"
            f"Текущая LTM: {json.dumps(self.ltm, ensure_ascii=False)}\n"
            f"Текущая WM: {json.dumps(self.wm, ensure_ascii=False)}\n"
            f"Текущее состояние TSM: stage=\"{self.tsm_stage}\", step=\"{self.tsm_step}\", action=\"{self.tsm_action}\"\n\n"
            "Последний диалог:\n"
            f"User: {user_msg}\n"
            f"Assistant: {assistant_msg}\n\n"
            "Верни ТОЛЬКО валидный JSON-объект со следующей структурой:\n"
            "{\n"
            "  \"ltm\": { ... },\n"
            "  \"wm\": { ... },\n"
            "  \"tsm\": {\n"
            "     \"stage\": \"... строго из списка разрешенных или текущий ...\",\n"
            "     \"step\": \"... описание текущего шага ...\",\n"
            "     \"action\": \"... ожидаемое следующее действие ...\"\n"
            "  }\n"
            "}\n"
        )

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.FAST_MODEL,
            "messages": [
                {"role": "system", "content": "Ты — эксперт по структурированию памяти и состояний. Отвечаешь строго валидным JSON без markdown."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Controlled TSM Router"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as res:
                raw_res = res.read().decode("utf-8")
                resp_data = json.loads(raw_res)

                if "choices" in resp_data:
                    content = resp_data["choices"][0]["message"]["content"].strip()
                    start_idx = content.find('{')
                    end_idx = content.rfind('}')
                    if start_idx != -1 and end_idx != -1:
                        content = content[start_idx:end_idx+1]

                    memory_data = json.loads(content)
                    if "ltm" in memory_data: self.ltm = memory_data["ltm"]
                    if "wm" in memory_data: self.wm = memory_data["wm"]
                    if "tsm" in memory_data:
                        tsm_res = memory_data["tsm"]
                        new_stage = tsm_res.get("stage", self.tsm_stage)
                        # Валидация перехода на стороне бэкенда
                        if self.is_transition_allowed(new_stage):
                            self.tsm_stage = new_stage
                            self.tsm_step = tsm_res.get("step", self.tsm_step)
                            self.tsm_action = tsm_res.get("action", self.tsm_action)
                        else:
                            print(f"[WARN] TSM transition rejected: {self.tsm_stage} -> {new_stage}")
                    print(f"[{time.strftime('%H:%M:%S')}] TSM & Memory routed successfully.")
        except Exception as e:
            print(f"Error in _route_memory: {e}")

    def chat(self, user_message: str) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {"error": "Нет OPENROUTER_API_KEY в .env"}

        # 1. Сохраняем сообщение пользователя в историю
        self.history.append({"role": "user", "content": user_message})
        self._save_state()

        # 2. Формируем строку жестких инвариантов проекта
        inv_str = "НЕТ"
        if self.invariants:
            inv_str = "\n".join([f"🔴 [ЗАКОН] {k}: {v}" for k, v in self.invariants.items()])

        # 3. Извлекаем активный профиль персонализации
        profile = self.profiles.get(self.current_profile, {})
        profile_context = (
            f"=== АКТИВНЫЙ ПРОФИЛЬ ПЕРСОНАЛИЗАЦИИ: {self.current_profile} ===\n"
            f"Твоя роль: {profile.get('role', 'Полезный ассистент')}\n"
            f"Стиль общения: {profile.get('style', 'Обычный')}\n"
            f"Формат ответов: {profile.get('format', 'Свободный')}\n"
            f"Жесткие ограничения профиля: {profile.get('constraints', 'Нет')}\n"
            "===============================================================\n"
        )

        # 4. Правила ЖИЗНЕННОГО ЦИКЛА ЗАДАЧИ (TSM)
        if self.planning_mode_enabled:
            tsm_rules = (
                "=== СТРОГИЕ ПРАВИЛА ЖИЗНЕННОГО ЦИКЛА ЗАДАЧИ ===\n"
                f"ТЕКУЩИЙ ЭТАП: {self.tsm_stage.upper()}\n"
                "1. Твой рабочий процесс СТРОГО ПОСЛЕДОВАТЕЛЕН: PLANNING -> EXECUTION -> VALIDATION -> DONE.\n"
                "2. Ты НЕ ИМЕЕШЬ ПРАВА выполнять действия из будущих этапов. \n"
                "   - Если этап PLANNING еще не завершен, ТЫ ЗАПРЕЩАЕШЬ СЕБЕ писать реализацию (код).\n"
                "   - Если этап EXECUTION еще не завершен, ТЫ ЗАПРЕЩАЕШЬ СЕБЕ переходить к финальной валидации.\n"
                "3. Если пользователь требует немедленного кода, а ты еще в PLANNING — ты ОБЯЗАН вежливо ОТКАЗАТЬ, объяснив, что сначала нужно утвердить план архитектуры.\n"
                "4. Твой ответ должен СТРОГО соответствовать текущему этапу.\n"
                "===============================================\n"
            )
        else:
            tsm_rules = (
                "=== РЕЖИМ ПЛАНИРОВАНИЯ ОТКЛЮЧЕН ===\n"
                "Режим строгого контроля этапов (TSM) отключен пользователем. "
                "Ты можешь сразу генерировать код и решать задачи без обязательной последовательности этапов планирования.\n"
                "===============================================\n"
            )

        # 5. Собираем супер-приоритетный системный промпт
        sys_prompt_full = (
            f"{self.system_prompt}\n\n"
            f"🛑🛑🛑 КРИТИЧЕСКИЕ СИСТЕМНЫЕ ИНВАРИАНТЫ 🛑🛑🛑\n"
            f"{inv_str}\n"
            "⚠️ Если запрос нарушает закон — пиши '❌ ОТКАЗ ВЫПОЛНЕНИЯ: Нарушение инварианта'.\n"
            "🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑🛑\n\n"
            f"{tsm_rules}\n\n"
            f"{profile_context}\n\n"
            "ИНСТРУКЦИЯ ПО ИСТОЧНИКАМ ЗНАНИЙ:\n"
            "🧠 - LTM, 🛠 - WM."
        )

        messages = [{"role": "system", "content": sys_prompt_full}]

        if self.ltm:
            ltm_str = "\n".join([f"- {k}: {v}" for k, v in self.ltm.items()])
            messages.append({"role": "system", "content": f"=== LONG-TERM MEMORY (LTM) ===\n{ltm_str}"})

        if self.wm:
            wm_str = "\n".join([f"- {k}: {v}" for k, v in self.wm.items()])
            messages.append({"role": "system", "content": f"=== WORKING MEMORY (WM) ===\n{wm_str}"})

        # Short-Term Memory (STM)
        stm_history = self.history[:-1][-self.WINDOW_SIZE:]
        messages += stm_history
        messages.append({"role": "user", "content": user_message})

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": 2000,
            "plugins": [{"id": "context-compression", "enabled": self.context_compression}]
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Day 15 Controlled TSM Agent"
        }

        start_time = time.time()
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as res:
                raw_response = res.read().decode("utf-8")
                elapsed = time.time() - start_time
                resp_data = json.loads(raw_response)

                if "choices" in resp_data and len(resp_data["choices"]) > 0:
                    answer = resp_data["choices"][0]["message"]["content"]
                    model_used = resp_data.get("model", self.model)
                    exec_time = round(elapsed, 2)
                    usage = resp_data.get("usage", {})

                    self.history.append({
                        "role": "assistant",
                        "content": answer,
                        "model": model_used,
                        "time": exec_time,
                        "usage": usage
                    })

                    self._route_memory(user_message, answer)
                    self._save_state()

                    return {
                        "role": "assistant",
                        "content": answer,
                        "model": model_used,
                        "time": exec_time,
                        "usage": usage,
                        "stats": self.get_token_stats()
                    }
                return {"error": f"API Error: {json.dumps(resp_data)}"}
        except urllib.error.HTTPError as e:
            try: return {"error": f"OpenRouter Error {e.code}: {json.loads(e.read().decode('utf-8')).get('error', {}).get('message')}"}
            except: return {"error": f"HTTP Error {e.code}: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}

    def get_token_stats(self) -> dict:
        total = 0
        last_prompt = 0
        for msg in self.history:
            if msg.get("role") == "assistant" and "usage" in msg:
                total += msg["usage"].get("total_tokens", 0)
                last_prompt = msg["usage"].get("prompt_tokens", 0)
        cost = (total / 1000000) * 0.15
        return {
            "total_tokens": total,
            "last_prompt_tokens": last_prompt,
            "cost": round(cost, 6),
            "history_len": len(self.history),
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
            "current_profile": self.current_profile,
            "tsm_stage": self.tsm_stage,
            "tsm_step": self.tsm_step,
            "tsm_action": self.tsm_action,
            "invariants": self.invariants
        }

    def get_state(self) -> dict:
        return {
            "history": self.history,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
            "current_profile": self.current_profile,
            "profiles_list": list(self.profiles.keys()),
            "current_profile_data": self.profiles.get(self.current_profile, {}),
            "tsm": {
                "stage": self.tsm_stage,
                "step": self.tsm_step,
                "action": self.tsm_action,
                "allowed_next": self.TSM_ALLOWED_TRANSITIONS.get(self.tsm_stage, [])
            },
            "invariants": self.invariants,
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
            },
            "stats": self.get_token_stats()
        }
