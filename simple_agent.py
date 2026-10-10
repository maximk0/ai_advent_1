import json
import os
import time
import urllib.request
import urllib.error


def _openrouter_request_with_retry(request, timeout=120, max_retries=2):
    """Retry transient OpenRouter rate limits without duplicating chat history."""
    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt >= max_retries:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                delay = min(8.0, max(1.0, float(retry_after))) if retry_after else 1.5 * (attempt + 1)
            except (TypeError, ValueError):
                delay = 1.5 * (attempt + 1)
            error.read()
            error.close()
            print(f"[OpenRouter] Rate limited; retrying in {delay:.1f}s ({attempt + 1}/{max_retries}).")
            time.sleep(delay)


def _quote_from_chunk(chunk: dict, max_chars: int = 360) -> str:
    """Return a verbatim, compact excerpt from a retrieved chunk."""
    text = str(chunk.get("text", "")).strip()
    if len(text) <= max_chars:
        return text
    positions = [text.casefold().find(str(term).casefold()) for term in chunk.get("matched_terms", []) if term]
    positions = [position for position in positions if position >= 0]
    start = max(0, (min(positions) if positions else 0) - max_chars // 4)
    end = min(len(text), start + max_chars)
    if end < len(text):
        boundary = text.rfind(" ", start, end)
        if boundary > start + max_chars // 2:
            end = boundary
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def format_rag_evidence(chunks: list[dict]) -> str:
    """Append source metadata and exact excerpts for chunks supplied to the model."""
    if not chunks:
        return ""
    lines = ["### Источники и цитаты"]
    seen = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "не указан")
        key = (chunk.get("source"), chunk.get("section"), chunk_id)
        if key in seen:
            continue
        seen.add(key)
        lines.extend([
            f"- **Источник:** `{chunk.get('source', 'неизвестный источник')}`; "
            f"**раздел:** {chunk.get('section') or 'не указан'}; **chunk_id:** `{chunk_id}`",
            f"  **Цитата:** «{_quote_from_chunk(chunk)}»",
        ])
    return "\n".join(lines)


def answer_without_rag_evidence(answer: str) -> str:
    """Remove the generated evidence appendix before scoring answer facts."""
    return str(answer or "").split("\n### Источники и цитаты", 1)[0].strip()

LEGACY_DEFAULT_INVARIANTS = {
    "Архитектура": "Strict MVI (Model-View-Intent) с однонаправленным потоком данных (UDF). Любые сайд-эффекты оборачивать в News/Effects.",
    "Стек проекта": "Только чистый Kotlin, Jetpack Compose для UI и Koin для Dependency Injection. Использование Java или устаревших XML Layouts КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО.",
    "Безопасность": "Запрещено логировать, сохранять в plain-text или передавать на сторонние сервера пароли, токены и приватные ключи пользователей.",
    "Бизнес-правило": "Все финансовые транзакции и операции с балансом пользователя должны проходить обязательную двойную верификацию локально перед отправкой в сеть."
}

class SimpleAgent:
    MODEL_DEFAULT = "openrouter/free"
    WINDOW_SIZE = 6
    FAST_MODEL = "openrouter/free"

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
        self.model_supported_parameters = ["temperature", "top_p", "top_k"]
        self.temperature = 0.7
        self.top_p = 1.0
        self.top_k = 0
        self.context_compression = True
        self.planning_mode_enabled = False
        self.rag_mode_enabled = True
        self.rag_settings_visible = False
        self.invariants_enabled = False
        self.rag_query_rewrite_enabled = True
        self.rag_top_k_before = 10
        self.rag_top_k_after = 3
        self.rag_similarity_threshold = 0.25

        # Трехуровневая система памяти
        self.wm = {}   # Working Memory: текущая задача, активный контекст
        self.ltm = {}  # Long-Term Memory: глобальные факты, предпочтения
        self.task_state = {"goal": "", "clarifications": [], "constraints": [], "terms": {}}

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
        self.invariants = {}

        self.summary_context = ""
        self.saved_tokens = 0
        self.stats = {"total_tokens": 0, "last_prompt_tokens": 0, "cost": 0}
        self._load_state()

    def _save_state(self):
        state = {
            "settings_version": 2,
            "history": self.history,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
            "task_state": self.task_state,
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
                "model_supported_parameters": self.model_supported_parameters,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
                "planning_mode_enabled": self.planning_mode_enabled,
                "rag_mode_enabled": self.rag_mode_enabled,
                "rag_settings_visible": self.rag_settings_visible,
                "invariants_enabled": self.invariants_enabled,
                "rag_query_rewrite_enabled": self.rag_query_rewrite_enabled,
                "rag_top_k_before": self.rag_top_k_before,
                "rag_top_k_after": self.rag_top_k_after,
                "rag_similarity_threshold": self.rag_similarity_threshold,
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
                migrate_settings_defaults = state.get("settings_version", 1) < 2
                self.summary_context = state.get("summary_context", "")
                self.saved_tokens = state.get("saved_tokens", 0)
                self.wm = state.get("wm", {})
                self.ltm = state.get("ltm", {})
                saved_task_state = state.get("task_state", {})
                if isinstance(saved_task_state, dict):
                    self.task_state = {
                        "goal": str(saved_task_state.get("goal", ""))[:500],
                        "clarifications": [str(v)[:300] for v in saved_task_state.get("clarifications", []) if isinstance(v, str)][-20:],
                        "constraints": [str(v)[:300] for v in saved_task_state.get("constraints", []) if isinstance(v, str)][-20:],
                        "terms": {str(k)[:100]: str(v)[:200] for k, v in saved_task_state.get("terms", {}).items() if isinstance(v, str)} if isinstance(saved_task_state.get("terms", {}), dict) else {},
                    }
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
                    loaded_invariants = state["invariants"]
                    # These four rules used to be auto-added on first launch.
                    # Migrate them out so only rules explicitly selected by the user remain.
                    self.invariants = {
                        key: value for key, value in loaded_invariants.items()
                        if LEGACY_DEFAULT_INVARIANTS.get(key) != value
                    }

                config = state.get("config", {})
                self.system_prompt = config.get("system_prompt", self.system_prompt)
                self.model = config.get("model", self.model)
                self.model_supported_parameters = config.get("model_supported_parameters", self.model_supported_parameters)
                self.temperature = config.get("temperature", self.temperature)
                self.top_p = config.get("top_p", self.top_p)
                self.top_k = config.get("top_k", self.top_k)
                self.context_compression = config.get("context_compression", True)
                self.planning_mode_enabled = config.get("planning_mode_enabled", False)
                self.rag_mode_enabled = config.get("rag_mode_enabled", True)
                self.rag_settings_visible = config.get("rag_settings_visible", False)
                self.invariants_enabled = config.get("invariants_enabled", False)
                self.rag_query_rewrite_enabled = config.get("rag_query_rewrite_enabled", True)
                self.rag_top_k_before = int(config.get("rag_top_k_before", 10))
                self.rag_top_k_after = int(config.get("rag_top_k_after", 3))
                self.rag_similarity_threshold = float(config.get("rag_similarity_threshold", 0.25))
                if migrate_settings_defaults:
                    # The old UI shipped with lifecycle planning checked by default.
                    # Treat that legacy default as the new opt-in default once.
                    self.planning_mode_enabled = False
            print(f"[{time.strftime('%H:%M:%S')}] State loaded from {self.STATE_FILE} ({len(self.history)} msgs)")
            if migrate_settings_defaults:
                self._save_state()
        except Exception as e:
            print(f"Error loading state: {e}")

    def set_config(self, config: dict):
        self.system_prompt = config.get("system_prompt", self.system_prompt)
        self.model = config.get("model", self.model)
        if "model_supported_parameters" in config:
            self.model_supported_parameters = config["model_supported_parameters"]
        self.temperature = float(config.get("temperature", self.temperature))
        self.top_p = float(config.get("top_p", self.top_p))
        self.top_k = int(config.get("top_k", self.top_k))
        self.context_compression = config.get("context_compression", self.context_compression)
        if "planning_mode_enabled" in config:
            self.planning_mode_enabled = bool(config["planning_mode_enabled"])
        if "rag_mode_enabled" in config:
            self.rag_mode_enabled = bool(config["rag_mode_enabled"])
        if "rag_settings_visible" in config:
            self.rag_settings_visible = bool(config["rag_settings_visible"])
        if "invariants_enabled" in config:
            self.invariants_enabled = bool(config["invariants_enabled"])
        if "rag_query_rewrite_enabled" in config:
            self.rag_query_rewrite_enabled = bool(config["rag_query_rewrite_enabled"])
        if "rag_top_k_before" in config:
            self.rag_top_k_before = max(1, min(int(config["rag_top_k_before"]), 50))
        if "rag_top_k_after" in config:
            self.rag_top_k_after = max(1, min(int(config["rag_top_k_after"]), self.rag_top_k_before))
        if "rag_similarity_threshold" in config:
            self.rag_similarity_threshold = max(0.0, min(float(config["rag_similarity_threshold"]), 1.0))
        self.rag_top_k_after = min(self.rag_top_k_after, self.rag_top_k_before)
        self._save_state()

    def clear_history(self, clear_all: bool = False):
        self.history = []
        if clear_all:
            self.wm = {}
            self.ltm = {}
            self.task_state = {"goal": "", "clarifications": [], "constraints": [], "terms": {}}
            self.tsm_stage = "none"
            self.tsm_step = "Нет активной задачи"
            self.tsm_action = "Ожидание постановки задачи пользователем"
            self.invariants = {}
            self.invariants_enabled = False
            self.summary_context = ""
            self.saved_tokens = 0
        self._save_state()

    def reset_task_state(self):
        self.task_state = {"goal": "", "clarifications": [], "constraints": [], "terms": {}}
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

    def clear_invariants(self):
        self.invariants = {}
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
            "Твоя задача — проанализировать последний обмен сообщениями и обновить четыре структуры данных:\n"
            "1. Long-Term Memory (LTM): глобальные, постоянные факты.\n"
            "2. Working Memory (WM): блок активных данных текущей задачи.\n"
            "3. Task State Machine (TSM): текущее состояние конечного автомата.\n"
            "4. Память задачи: цель разговора, уточнения пользователя, ограничения и устойчивые термины.\n"
            "Сохраняй только явно сообщённое или подтверждённое пользователем. Сохраняй старые уточнения; меняй цель лишь при явной смене задачи.\n"
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
            f"Текущее состояние задачи: {json.dumps(self.task_state, ensure_ascii=False)}\n"
            f"Текущее состояние TSM: stage=\"{self.tsm_stage}\", step=\"{self.tsm_step}\", action=\"{self.tsm_action}\"\n\n"
            "Последний диалог:\n"
            f"User: {user_msg}\n"
            f"Assistant: {assistant_msg}\n\n"
            "Верни ТОЛЬКО валидный JSON-объект со следующей структурой:\n"
            "{\n"
            "  \"ltm\": { ... },\n"
            "  \"wm\": { ... },\n"
            "  \"task_state\": {\"goal\": \"...\", \"clarifications\": [], \"constraints\": [], \"terms\": {}},\n"
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
                    incoming_task_state = memory_data.get("task_state")
                    if isinstance(incoming_task_state, dict):
                        current = self.task_state
                        incoming_goal = incoming_task_state.get("goal")
                        if isinstance(incoming_goal, str) and incoming_goal.strip():
                            current["goal"] = incoming_goal.strip()[:500]
                        for field in ("clarifications", "constraints"):
                            existing = current.get(field, []) if isinstance(current.get(field), list) else []
                            incoming = incoming_task_state.get(field, [])
                            if isinstance(incoming, list):
                                merged = list(dict.fromkeys(
                                    str(value).strip()[:300]
                                    for value in existing + incoming
                                    if str(value).strip()
                                ))
                                current[field] = merged[-20:]
                        existing_terms = current.get("terms", {}) if isinstance(current.get("terms"), dict) else {}
                        incoming_terms = incoming_task_state.get("terms", {})
                        if isinstance(incoming_terms, dict):
                            existing_terms.update({
                                str(key)[:100]: str(value).strip()[:200]
                                for key, value in incoming_terms.items()
                                if isinstance(value, str) and value.strip()
                            })
                        current["terms"] = existing_terms
                        self.task_state = current
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

    def chat(
        self,
        user_message: str,
        mcp_clients: list = None,
        *,
        history: list | None = None,
        persist_state: bool = True,
        rag_source_prefix: str | None = None,
        rag_chunks: list | None = None,
    ) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {"error": "Нет OPENROUTER_API_KEY в .env"}

        # Evaluation runs can supply a fresh, in-memory history and avoid
        # changing the user's saved chat or memory state.
        conversation_history = self.history if history is None else history
        conversation_history.append({"role": "user", "content": user_message})
        if persist_state:
            self._save_state()

        # 2. Добавляем правила только тогда, когда пользователь включил их
        # и выбрал хотя бы одно. Неактивный блок не должен подсказывать модели отказывать.
        invariant_instruction = ""
        if self.invariants_enabled and self.invariants:
            inv_str = "\n".join([f"🔴 [ЗАКОН] {k}: {v}" for k, v in self.invariants.items()])
            invariant_instruction = (
                "=== АКТИВНЫЕ ИНВАРИАНТЫ ПОЛЬЗОВАТЕЛЯ ===\n"
                f"{inv_str}\n"
                "Если запрос прямо нарушает одно из перечисленных правил, кратко объясни конфликт и откажи. "
                "Не отказывай по причинам, которых нет в этом списке.\n"
                "==========================================\n"
            )

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
        if mcp_clients:
            orchestration_instruction = (
                "=== ИНСТРУКЦИЯ ПО МНОГОСЕРВЕРНОЙ ОРКЕСТРАЦИИ MCP ===\n"
                "Вызывай только инструменты, переданные текущему запросу. Если нужного инструмента нет, не утверждай, что вызываешь его.\n"
                "====================================================\n"
            )
            rag_instruction = (
                "=== ИНСТРУКЦИЯ ПО RAG И ИНДЕКСАЦИИ ДОКУМЕНТОВ (День 21) ===\n"
                "Инструменты индексации доступны только если они перечислены среди инструментов текущего запроса.\n"
                "==========================================================\n"
            )
        else:
            orchestration_instruction = ""
            rag_instruction = ""

        sys_prompt_full = (
            f"{self.system_prompt}\n\n"
            f"{invariant_instruction}\n"
            f"{orchestration_instruction}\n\n"
            f"{rag_instruction}\n\n"
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

        if self.task_state.get("goal") or self.task_state.get("clarifications") or self.task_state.get("constraints") or self.task_state.get("terms"):
            messages.append({
                "role": "system",
                "content": (
                    "=== ПАМЯТЬ ТЕКУЩЕЙ ЗАДАЧИ ===\n"
                    f"{json.dumps(self.task_state, ensure_ascii=False)}\n"
                    "Это подтверждённый контекст разговора. Не проси повторять уже указанные сведения. "
                    "Учитывай цель, уточнения, ограничения и зафиксированные термины при ответе.\n"
                    "================================"
                ),
            })

        # RAG Context Retrieval (если режим RAG ВКЛЮЧЕН)
        rag_evidence_chunks = []
        if self.rag_mode_enabled:
            try:
                from document_indexer import DocumentIndexer
                if rag_chunks is not None:
                    matches = rag_chunks
                else:
                    task_terms = " ".join(str(value) for value in self.task_state.get("terms", {}).values())
                    retrieval_query = " ".join(filter(None, [
                        user_message,
                        self.task_state.get("goal", ""),
                        task_terms,
                    ]))
                    retrieval = DocumentIndexer().compare_retrieval(
                        retrieval_query,
                        source_prefix=rag_source_prefix,
                        top_k_before=self.rag_top_k_before,
                        top_k_after=self.rag_top_k_after,
                        similarity_threshold=self.rag_similarity_threshold,
                        query_rewrite_enabled=self.rag_query_rewrite_enabled,
                    )
                    matches = retrieval["filtered_results"]
                rag_evidence_chunks = list(matches[:self.rag_top_k_after])
                if matches:
                    snippets = []
                    for match in matches[:self.rag_top_k_after]:
                        relevance = (
                            f"similarity {match['similarity']:.0%}"
                            if "similarity" in match
                            else f"совпало терминов {match.get('search_score', 0)}"
                        )
                        snippets.append(
                            f"📄 Источник [{match.get('source')} — {match.get('section')}; "
                            f"chunk_id={match.get('chunk_id', 'не указан')}]; "
                            f"{relevance}:\n{match.get('text')}"
                        )
                    rag_context_str = (
                        "=== RAG CONTEXT (Релевантные чанки из базы знаний проекта) ===\n"
                        "Отвечай только фактами, подтверждёнными этими фрагментами; не используй внешние знания и не додумывай. "
                        "Для каждого важного факта укажи в тексте ссылку вида [chunk_id]. Если фрагменты не отвечают на вопрос, "
                        "скажи «Не знаю по найденным документам» и попроси уточнить запрос. Сразу дай законченный ответ, "
                        "не объявляй о будущем поиске и не проси ждать.\n\n"
                        + "\n\n".join(snippets)
                    )
                    messages.append({"role": "system", "content": rag_context_str})
                    print(f"[{time.strftime('%H:%M:%S')}] [RAG ON] Injected {len(matches[:3])} chunks into prompt.")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] [RAG ON] No chunks passed the relevance filter.")
            except Exception as e:
                print(f"[RAG Retrieval Error]: {e}")
                matches = []
        else:
            print(f"[{time.strftime('%H:%M:%S')}] [RAG OFF] Skipping retrieval context.")

        # При включённом RAG пустая выборка означает, что все результаты
        # отсутствуют или ниже порога. Не отправляем вопрос в модель без контекста.
        if self.rag_mode_enabled and not rag_evidence_chunks:
            answer = (
                "Не знаю по найденным документам: релевантных фрагментов выше порога "
                f"{self.rag_similarity_threshold:.2f} не найдено. Уточните вопрос или проверьте базу знаний."
            )
            no_source_evidence = "### Источники и цитаты\nПоиск выполнялся, но фрагментов выше заданного порога не найдено; подтвердить ответ цитатами нельзя."
            conversation_history.append({"role": "assistant", "content": answer, "rag_evidence": no_source_evidence, "model": self.model})
            if persist_state:
                self._save_state()
            return {
                "role": "assistant",
                "content": answer,
                "rag_evidence": no_source_evidence,
                "model": self.model,
                "time": 0,
                "usage": {},
                "stats": self.get_token_stats(),
            }

        # Short-Term Memory (STM)
        stm_history = conversation_history[:-1][-self.WINDOW_SIZE:]
        messages += stm_history
        messages.append({"role": "user", "content": user_message})

        # 6. Нативная конвертация инструментов MCP в формат OpenAI / OpenRouter tools
        openai_tools = []
        tool_map = {}

        if mcp_clients:
            for client in mcp_clients:
                if client:
                    try:
                        tools_list = client.refresh_tools()
                        for t in tools_list:
                            t_name = t.get("name")
                            if t_name:
                                tool_map[t_name] = client
                                openai_tools.append({
                                    "type": "function",
                                    "function": {
                                        "name": t_name,
                                        "description": t.get("description", ""),
                                        "parameters": t.get("inputSchema", {"type": "object", "properties": {}})
                                    }
                                })
                    except Exception as e:
                        print(f"[Native MCP] Error loading tools from client: {e}")

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2000,
            "plugins": [{"id": "context-compression", "enabled": self.context_compression}]
        }
        supported = self.model_supported_parameters
        if not supported or "temperature" in supported:
            body["temperature"] = self.temperature
        if not supported or "top_p" in supported:
            body["top_p"] = self.top_p
        if self.top_k > 0 and (not supported or "top_k" in supported):
            body["top_k"] = self.top_k

        if openai_tools:
            body["tools"] = openai_tools
            body["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Native MCP Agent"
        }

        start_time = time.time()
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with _openrouter_request_with_retry(req, timeout=120) as res:
                raw_response = res.read().decode("utf-8")
                elapsed = time.time() - start_time
                resp_data = json.loads(raw_response)

                if "choices" in resp_data and len(resp_data["choices"]) > 0:
                    choice_msg = resp_data["choices"][0]["message"]
                    model_used = resp_data.get("model", self.model)
                    exec_time = round(elapsed, 2)
                    usage = resp_data.get("usage", {})

                    # Нативный цикл Tool Calling Loop (до 5 итераций)
                    answer = ""
                    loop_count = 0
                    while loop_count < 5:
                        tool_calls = choice_msg.get("tool_calls")
                        if not tool_calls or not tool_map:
                            answer = choice_msg.get("content", "Нет ответа.")
                            break

                        print(f"[{time.strftime('%H:%M:%S')}] [Native MCP] Turn {loop_count+1}: LLM requested {len(tool_calls)} tool calls!")
                        messages.append(choice_msg)

                        for tc in tool_calls:
                            tc_id = tc.get("id", f"call_{int(time.time())}")
                            fn_obj = tc.get("function", {})
                            fn_name = fn_obj.get("name")
                            fn_args_raw = fn_obj.get("arguments", "{}")

                            try:
                                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
                            except Exception:
                                fn_args = {}

                            client = tool_map.get(fn_name)
                            if client:
                                tool_result = client.call_tool(fn_name, fn_args)
                            else:
                                tool_result = f"Error: MCP Server for tool '{fn_name}' not found."

                            print(f"[Native MCP] Executed {fn_name}({fn_args}) -> {tool_result[:100]}...")

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": tool_result
                            })

                        # Следующий запрос в LLM API с результатами инструментов
                        body["messages"] = messages

                        req_next = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                        with urllib.request.urlopen(req_next, timeout=120) as res_next:
                            resp_next = json.loads(res_next.read().decode("utf-8"))
                            if "choices" in resp_next and len(resp_next["choices"]) > 0:
                                choice_msg = resp_next["choices"][0]["message"]
                                loop_count += 1
                            else:
                                answer = "Инструменты MCP выполнены, но нет ответа от модели."
                                break
                    else:
                        answer = choice_msg.get("content", "Пайплайн оркестрации завершен.")

                    if self.rag_mode_enabled and rag_evidence_chunks:
                        rag_evidence = format_rag_evidence(rag_evidence_chunks)
                    elif not self.rag_mode_enabled:
                        rag_evidence = "### Источники и цитаты\nПоиск по документам отключён для этого ответа; источники не запрашивались."
                    else:
                        rag_evidence = ""

                    conversation_history.append({
                        "role": "assistant",
                        "content": answer,
                        "rag_evidence": rag_evidence,
                        "model": model_used,
                        "time": exec_time,
                        "usage": usage
                    })

                    if persist_state:
                        self._route_memory(user_message, answer)
                        self._save_state()

                    return {
                        "role": "assistant",
                        "content": answer,
                        "rag_evidence": rag_evidence,
                        "model": model_used,
                        "time": exec_time,
                        "usage": usage,
                        "stats": self.get_token_stats()
                    }
                return {"error": f"API Error: {json.dumps(resp_data)}"}
        except urllib.error.HTTPError as e:
            if conversation_history and conversation_history[-1].get("role") == "user" and conversation_history[-1].get("content") == user_message:
                conversation_history.pop()
                if persist_state:
                    self._save_state()
            try: return {"error": f"OpenRouter Error {e.code}: {json.loads(e.read().decode('utf-8')).get('error', {}).get('message')}"}
            except: return {"error": f"HTTP Error {e.code}: {str(e)}"}
        except Exception as e:
            if conversation_history and conversation_history[-1].get("role") == "user" and conversation_history[-1].get("content") == user_message:
                conversation_history.pop()
                if persist_state:
                    self._save_state()
            return {"error": str(e)}

    def get_token_stats(self) -> dict:
        total = 0
        last_prompt = 0
        estimated_cost = 0.0
        for msg in self.history:
            if msg.get("role") == "assistant" and "usage" in msg:
                usage = msg.get("usage") or {}
                total += usage.get("total_tokens", 0)
                last_prompt = usage.get("prompt_tokens", 0)
                if usage.get("cost") is not None:
                    try:
                        estimated_cost += float(usage["cost"])
                    except (TypeError, ValueError):
                        estimated_cost += (usage.get("total_tokens", 0) / 1000000) * 0.15
                else:
                    estimated_cost += (usage.get("total_tokens", 0) / 1000000) * 0.15
        return {
            "total_tokens": total,
            "last_prompt_tokens": last_prompt,
            "cost": round(estimated_cost, 6),
            "history_len": len(self.history),
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
            "task_state": self.task_state,
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
            "task_state": self.task_state,
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
                "model_supported_parameters": self.model_supported_parameters,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
                "planning_mode_enabled": self.planning_mode_enabled,
                "rag_mode_enabled": self.rag_mode_enabled,
                "rag_settings_visible": self.rag_settings_visible,
                "invariants_enabled": self.invariants_enabled,
                "rag_query_rewrite_enabled": self.rag_query_rewrite_enabled,
                "rag_top_k_before": self.rag_top_k_before,
                "rag_top_k_after": self.rag_top_k_after,
                "rag_similarity_threshold": self.rag_similarity_threshold,
            },
            "stats": self.get_token_stats()
        }
