import json
import os
import time
import urllib.request
import urllib.error

class SimpleAgent:
    MODEL_DEFAULT = "openrouter/free"
    WINDOW_SIZE = 6
    FAST_MODEL = "cohere/north-mini-code:free"

    # Путь к файлу состояния относительно файла скрипта
    STATE_FILE = os.path.join(os.path.dirname(__file__), "history_day11.json")

    def __init__(self):
        self.history = []
        self.system_prompt = "Ты — полезный AI-ассистент."
        self.model = self.MODEL_DEFAULT
        self.temperature = 0.7
        self.top_p = 1.0
        self.top_k = 0
        self.context_compression = True

        # Трехуровневая система памяти
        self.wm = {}   # Working Memory: текущая задача, активный контекст
        self.ltm = {}  # Long-Term Memory: глобальные факты, профиль, предпочтения

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

                config = state.get("config", {})
                self.system_prompt = config.get("system_prompt", self.system_prompt)
                self.model = config.get("model", self.model)
                self.temperature = config.get("temperature", self.temperature)
                self.top_p = config.get("top_p", self.top_p)
                self.top_k = config.get("top_k", self.top_k)
                self.context_compression = config.get("context_compression", True)
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
        self._save_state()

    def clear_history(self, clear_all: bool = False):
        self.history = []
        if clear_all:
            self.wm = {}
            self.ltm = {}
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

    def _route_memory(self, user_msg: str, assistant_msg: str):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key: return

        prompt = (
            "Ты — менеджер многоуровневой памяти ИИ-агента.\n"
            "Твоя задача — проанализировать последний обмен сообщениями между User и Assistant и обновить два слоя памяти:\n"
            "1. Long-Term Memory (LTM): глобальные, постоянные факты о пользователе (имя, общие предпочтения, стек, принятые важные архитектурные решения, 'законы' проекта).\n"
            "2. Working Memory (WM): блок активных данных текущей задачи (какой баг сейчас чиним, над какой конкретной проблемой работаем, список файлов, текущие вводные). "
            "WM должна обновляться динамически! Если пользователь сменил задачу, уточнил или опроверг старые данные, обязательно сотри неактуальные или ошибочные ключи из WM, чтобы они не мешали.\n\n"
            f"Текущая LTM: {json.dumps(self.ltm, ensure_ascii=False)}\n"
            f"Текущая WM: {json.dumps(self.wm, ensure_ascii=False)}\n\n"
            "Последний диалог:\n"
            f"User: {user_msg}\n"
            f"Assistant: {assistant_msg}\n\n"
            "Верни ТОЛЬКО валидный JSON-объект со следующей структурой:\n"
            "{\n"
            "  \"ltm\": { ... обновленный плоский словарь ... },\n"
            "  \"wm\": { ... обновленный плоский словарь ... }\n"
            "}\n"
            "Никакого другого текста, разметки markdown или пояснений."
        )

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.FAST_MODEL,
            "messages": [
                {"role": "system", "content": "Ты — эксперт по структурированию памяти агентов. Отвечаешь только чистым JSON без markdown."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Memory Router"
        }

        print(f"\n=== [DEBUG] ROUTE MEMORY REQUEST ===")
        print(f"URL: {url}")
        print(f"Model: {body['model']}")
        print(f"Body: {json.dumps(body, ensure_ascii=False, indent=2)}")
        print("=====================================\n")

        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as res:
                raw_res = res.read().decode("utf-8")
                resp_data = json.loads(raw_res)

                print(f"=== [DEBUG] ROUTE MEMORY RESPONSE ===")
                print(json.dumps(resp_data, ensure_ascii=False, indent=2))
                print("======================================\n")

                if "choices" in resp_data:
                    content = resp_data["choices"][0]["message"]["content"].strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]

                    memory_data = json.loads(content.strip())
                    if "ltm" in memory_data and isinstance(memory_data["ltm"], dict):
                        self.ltm = memory_data["ltm"]
                    if "wm" in memory_data and isinstance(memory_data["wm"], dict):
                        self.wm = memory_data["wm"]
                    print(f"[{time.strftime('%H:%M:%S')}] Memory routed successfully. LTM keys: {list(self.ltm.keys())}, WM keys: {list(self.wm.keys())}")
        except urllib.error.HTTPError as e:
            print(f"=== [DEBUG] ROUTE MEMORY HTTP ERROR ===")
            print(f"Code: {e.code}")
            try:
                err_body = e.read().decode("utf-8")
                print(f"Response body: {err_body}")
            except Exception as read_err:
                print(f"Could not read error body: {read_err}")
            print("========================================\n")
        except Exception as e:
            print(f"=== [DEBUG] ROUTE MEMORY GENERAL ERROR ===")
            print(f"Error: {str(e)}")
            print("==========================================\n")
        except Exception as e:
            print(f"Memory routing error: {e}")

    def chat(self, user_message: str) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {"error": "Нет OPENROUTER_API_KEY в .env"}

        # 1. Сохраняем сообщение пользователя в историю
        self.history.append({"role": "user", "content": user_message})
        self._save_state()

        # 2. Формируем системный промпт с правилами использования иконок памяти
        sys_prompt_full = (
            f"{self.system_prompt}\n\n"
            "ИНСТРУКЦИЯ ПО ИСТОЧНИКАМ ЗНАНИЙ:\n"
            "В твоем распоряжении находятся блоки Long-Term Memory (LTM) и Working Memory (WM).\n"
            "Если при ответе пользователю ты опираешься на информацию или предпочтения из Long-Term Memory (LTM), ОБЯЗАТЕЛЬНО добавь в текст ответа иконку 🧠.\n"
            "If при ответе ты используешь активный контекст текущей задачи из Working Memory (WM), ОБЯЗАТЕЛЬНО добавь в текст ответа иконку 🛠.\n"
            "Иконки можно органично вплетать в текст или ставить в конце ответа."
        )

        messages = [{"role": "system", "content": sys_prompt_full}]

        # Добавляем Long-Term Memory (LTM) как контекст
        if self.ltm:
            ltm_str = "\n".join([f"- {k}: {v}" for k, v in self.ltm.items()])
            messages.append({"role": "system", "content": f"=== LONG-TERM MEMORY (LTM) ===\n{ltm_str}"})

        # Добавляем Working Memory (WM) как контекст
        if self.wm:
            wm_str = "\n".join([f"- {k}: {v}" for k, v in self.wm.items()])
            messages.append({"role": "system", "content": f"=== WORKING MEMORY (WM) ===\n{wm_str}"})

        # Short-Term Memory (STM): Скользящее окно из последних WINDOW_SIZE реплик истории
        # Исключаем последнее сообщение пользователя, так как оно добавится следом
        stm_history = self.history[:-1][-self.WINDOW_SIZE:]
        messages += stm_history

        # Добавляем само последнее сообщение пользователя
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
        if self.top_k > 0:
            body["top_k"] = self.top_k

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Day 11 Multi-Layer Memory Agent"
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

                    # Выполняем динамическую маршрутизацию памяти после ответа
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
            try:
                err_body = e.read().decode("utf-8")
                err_json = json.loads(err_body)
                return {"error": f"OpenRouter Error {e.code}: {err_json.get('error', {}).get('message', err_body)}"}
            except:
                return {"error": f"HTTP Error {e.code}: {str(e)}"}
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
            "ltm": self.ltm
        }

    def get_state(self) -> dict:
        return {
            "history": self.history,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "wm": self.wm,
            "ltm": self.ltm,
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
