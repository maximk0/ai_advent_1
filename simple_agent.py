import json
import os
import time
import urllib.request
import urllib.error

class SimpleAgent:
    MODEL_DEFAULT = "openrouter/free"
    # Путь к файлу состояния относительно файла скрипта
    STATE_FILE = os.path.join(os.path.dirname(__file__), "history_day7.json")

    def __init__(self):
        self.history = []
        self.system_prompt = "Ты — полезный AI-ассистент."
        self.model = self.MODEL_DEFAULT
        self.temperature = 0.7
        self.top_p = 1.0
        self.top_k = 0
        self._load_state()

    def _save_state(self):
        state = {
            "history": self.history,
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k
            }
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
                self.history = state.get("history", [])
                config = state.get("config", {})
                self.system_prompt = config.get("system_prompt", self.system_prompt)
                self.model = config.get("model", self.model)
                self.temperature = config.get("temperature", self.temperature)
                self.top_p = config.get("top_p", self.top_p)
                self.top_k = config.get("top_k", self.top_k)
            print(f"[{time.strftime('%H:%M:%S')}] State loaded from {self.STATE_FILE} ({len(self.history)} msgs)")
        except Exception as e:
            print(f"Error loading state: {e}")

    def set_config(self, config: dict):
        self.system_prompt = config.get("system_prompt", self.system_prompt)
        self.model = config.get("model", self.model)
        self.temperature = float(config.get("temperature", self.temperature))
        self.top_p = float(config.get("top_p", self.top_p))
        self.top_k = int(config.get("top_k", self.top_k))
        self._save_state()

    def clear_history(self):
        self.history = []
        self._save_state()

    def chat(self, user_message: str) -> dict:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return {"error": "Нет OPENROUTER_API_KEY в .env"}

        self.history.append({"role": "user", "content": user_message})
        self._save_state() # Сохраняем сразу после ввода пользователя

        messages = [{"role": "system", "content": self.system_prompt}] + self.history

        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Day 7 Simple Agent"
        }

        start_time = time.time()
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as res:
                raw_response = res.read().decode("utf-8")
                elapsed = time.time() - start_time # Теперь замер после полного прочтения
                resp_data = json.loads(raw_response)

                if "choices" in resp_data and len(resp_data["choices"]) > 0:
                    answer = resp_data["choices"][0]["message"]["content"]
                    model_used = resp_data.get("model", self.model)
                    exec_time = round(elapsed, 2)

                    # Сохраняем расширенную историю
                    self.history.append({
                        "role": "assistant",
                        "content": answer,
                        "model": model_used,
                        "time": exec_time
                    })
                    self._save_state()

                    return {
                        "role": "assistant",
                        "content": answer,
                        "model": model_used,
                        "time": exec_time,
                        "usage": resp_data.get("usage", {})
                    }
                return {"error": f"API Error: {json.dumps(resp_data)}"}
        except Exception as e:
            return {"error": str(e)}

    def get_state(self) -> dict:
        return {
            "history": self.history,
            "config": {
                "system_prompt": self.system_prompt,
                "model": self.model,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k
            }
        }
