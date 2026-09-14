import json
import os
import time
import urllib.request
import urllib.error

class SimpleAgent:
    MODEL_DEFAULT = "openrouter/free"
    WINDOW_SIZE = 8
    FAST_MODEL = "openai/gpt-4o-mini"

    STRATEGY_SLIDING = "sliding"
    STRATEGY_FACTS = "facts"
    STRATEGY_BRANCHING = "branching"

    # Путь к файлу состояния относительно файла скрипта
    STATE_FILE = os.path.join(os.path.dirname(__file__), "history_day10.json")

    def __init__(self):
        self.history = []
        self.system_prompt = "Ты — полезный AI-ассистент."
        self.model = self.MODEL_DEFAULT
        self.temperature = 0.7
        self.top_p = 1.0
        self.top_k = 0
        self.context_compression = True

        self.strategy = self.STRATEGY_SLIDING
        self.facts = {}
        self.branches = {"main": []}
        self.current_branch = "main"

        self.summary_context = ""
        self.saved_tokens = 0
        self.stats = {"total_tokens": 0, "last_prompt_tokens": 0, "cost": 0}
        self._load_state()

    def _save_state(self):
        state = {
            "history": self.history,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "strategy": self.strategy,
            "facts": self.facts,
            "branches": self.branches,
            "current_branch": self.current_branch,
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
                "strategy": self.strategy
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
                self.facts = state.get("facts", {})
                self.branches = state.get("branches", {"main": []})
                self.current_branch = state.get("current_branch", "main")

                config = state.get("config", {})
                self.strategy = config.get("strategy", state.get("strategy", self.STRATEGY_SLIDING))

                # Если мы в режиме веток, history должна ссылаться на текущую ветку
                if self.strategy == self.STRATEGY_BRANCHING:
                    self.history = self.branches.get(self.current_branch, [])
                else:
                    self.history = state.get("history", [])

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
        self.context_compression = bool(config.get("context_compression", self.context_compression))

        new_strategy = config.get("strategy")
        if new_strategy in [self.STRATEGY_SLIDING, self.STRATEGY_FACTS, self.STRATEGY_BRANCHING]:
            if self.strategy != new_strategy:
                if new_strategy == self.STRATEGY_BRANCHING:
                    self.branches = {"main": list(self.history)}
                    self.current_branch = "main"
                self.strategy = new_strategy

        self._save_state()

    def clear_history(self, clear_branches: bool = False):
        if clear_branches:
            self.branches = {"main": []}
            self.current_branch = "main"
            self.history = self.branches["main"]
            self.facts = {}
            self.summary_context = ""
            self.saved_tokens = 0
        elif self.strategy == self.STRATEGY_BRANCHING:
            self.branches[self.current_branch] = []
            self.history = self.branches[self.current_branch]
        else:
            self.history = []
            self.facts = {}
            self.summary_context = ""
            self.saved_tokens = 0
        self._save_state()

    def create_branch(self, name: str):
        if self.strategy != self.STRATEGY_BRANCHING: return
        self.branches[name] = list(self.history)
        self.current_branch = name
        self.history = self.branches[name]
        self._save_state()

    def switch_branch(self, name: str):
        if self.strategy != self.STRATEGY_BRANCHING: return
        if name in self.branches:
            self.current_branch = name
            self.history = self.branches[name]
            self._save_state()

    def delete_branch(self, name: str):
        if self.strategy != self.STRATEGY_BRANCHING: return
        if name == "main": return
        if name in self.branches:
            del self.branches[name]
            if self.current_branch == name:
                self.current_branch = "main"
                self.history = self.branches["main"]
            self._save_state()

    def _update_facts(self, user_msg: str, assistant_msg: str):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key: return

        prompt = (
            "Извлеки ключевые факты (цели, ограничения, предпочтения, решения) из последнего обмена сообщениями. "
            "Верни ТОЛЬКО JSON объект с обновленными фактами. "
            "Если факт изменился, обнови его. Если появился новый, добавь. "
            f"Текущие факты: {json.dumps(self.facts, ensure_ascii=False)}\n"
            f"User: {user_msg}\n"
            f"Assistant: {assistant_msg}"
        )

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.FAST_MODEL,
            "messages": [{"role": "system", "content": "Ты — экстрактор фактов. Возвращай только валидный JSON."},
                         {"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Day 10 Facts Extractor"
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as res:
                resp_data = json.loads(res.read().decode("utf-8"))
                if "choices" in resp_data:
                    new_facts = json.loads(resp_data["choices"][0]["message"]["content"])
                    self.facts.update(new_facts)
                    print(f"[{time.strftime('%H:%M:%S')}] Facts updated: {len(self.facts)} keys")
        except Exception as e:
            print(f"Facts update error: {e}")

    def edit_message_and_branch(self, msg_index: int, new_content: str) -> dict:
        if msg_index >= len(self.history):
            return {"error": "Index out of range"}

        prefix = self.history[:msg_index]
        import datetime
        branch_name = f"edit_{datetime.datetime.now().strftime('%m%d_%H%M%S')}"
        self.branches[branch_name] = list(prefix)
        self.current_branch = branch_name
        self.history = self.branches[branch_name]
        return self.chat(new_content)

    def get_message_versions(self, msg_index: int) -> list:
        if msg_index >= len(self.history): return []
        prefix = self.history[:msg_index]
        versions = []
        for b_name, b_hist in self.branches.items():
            if len(b_hist) > msg_index:
                if b_hist[:msg_index] == prefix:
                    versions.append(b_name)
        return versions

    def chat(self, user_message: str) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {"error": "Нет OPENROUTER_API_KEY в .env"}

        # 1. Сохраняем сообщение в историю
        self.history.append({"role": "user", "content": user_message})
        self._save_state()

        # Формирование сообщений в зависимости от стратегии
        messages = [{"role": "system", "content": self.system_prompt}]
        active_history = self.history

        if self.strategy == self.STRATEGY_SLIDING:
            active_history = self.history[-self.WINDOW_SIZE:]
        elif self.strategy == self.STRATEGY_FACTS:
            if self.facts:
                facts_str = "\n".join([f"- {k}: {v}" for k, v in self.facts.items()])
                messages.append({"role": "system", "content": f"Ключевые факты диалога:\n{facts_str}"})
            active_history = self.history[-self.WINDOW_SIZE:]

        messages += active_history

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
            "X-Title": "Day 10 AI Agent"
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

                    if self.strategy == self.STRATEGY_FACTS:
                        self._update_facts(user_message, answer)

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
            "strategy": self.strategy,
            "facts": self.facts,
            "current_branch": self.current_branch,
            "branches": list(self.branches.keys())
        }

    def get_state(self) -> dict:
        history_with_versions = []
        for i, msg in enumerate(self.history):
            msg_copy = dict(msg)
            if msg["role"] == "user":
                versions = self.get_message_versions(i)
                msg_copy["versions"] = versions
                msg_copy["current_version_index"] = versions.index(self.current_branch) if self.current_branch in versions else 0
            history_with_versions.append(msg_copy)

        return {
            "history": history_with_versions,
            "summary_context": self.summary_context,
            "saved_tokens": self.saved_tokens,
            "strategy": self.strategy,
            "facts": self.facts,
            "current_branch": self.current_branch,
            "branches": list(self.branches.keys()),
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "context_compression": self.context_compression,
                "strategy": self.strategy
            },
            "stats": self.get_token_stats()
        }
