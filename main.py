#!/usr/bin/env python3
"""CLI и веб-чат: запрос в Gemini API, история отдельно от поля ввода."""

from __future__ import annotations

import html
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history.json"
MODEL = "gemini-flash-lite-latest"
PORT = 8001
_LOCK = threading.Lock()

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Gemini</title>
  <style>
    body { font-family: sans-serif; max-width: 720px; margin: 24px auto; }
    .log { display: flex; flex-direction: column; gap: 10px; min-height: 200px;
           margin-bottom: 16px; }
    .msg { padding: 10px 12px; border-radius: 10px; white-space: pre-wrap; }
    .user { background: #dbeafe; align-self: flex-end; max-width: 80%; }
    .model { background: #f3f4f6; align-self: flex-start; max-width: 80%; }
    .who { font-size: 12px; color: #555; margin-bottom: 4px; }
    form.ask { display: flex; gap: 8px; }
    input[name="prompt"] { flex: 1; padding: 10px; }
    button { padding: 8px 16px; }
    button:disabled { opacity: 0.6; }
    #loader {
      display: none; position: fixed; inset: 0; z-index: 20;
      background: rgba(255,255,255,.82);
      flex-direction: column; align-items: center; justify-content: center; gap: 12px;
    }
    #loader.show { display: flex; }
    .spinner {
      width: 36px; height: 36px; border: 3px solid #e5e7eb;
      border-top-color: #2563eb; border-radius: 50%;
      animation: spin .7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div id="loader" aria-live="polite">
    <div class="spinner" aria-hidden="true"></div>
    <p>Ждём ответ Gemini…</p>
  </div>
  <h1>Чат с Gemini</h1>
  <div class="log">{messages}</div>
  <form class="ask" method="post" action="/" onsubmit="showLoader()">
    <input type="hidden" name="action" value="send">
    <input type="text" name="prompt" placeholder="Новый запрос" autocomplete="off" autofocus>
    <button type="submit" id="go">Отправить</button>
  </form>
  <form method="post" action="/" style="margin-top:8px">
    <button type="submit" name="action" value="clear">Очистить историю</button>
  </form>
  <script>
    function showLoader() {
      document.getElementById("loader").classList.add("show");
      document.getElementById("go").textContent = "Ждём…";
    }
  </script>
</body>
</html>
"""


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_history() -> list[dict[str, str]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_history(messages: list[dict[str, str]]) -> None:
    HISTORY_PATH.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ask_llm(messages: list[dict[str, str]]) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Нет GEMINI_API_KEY в .env")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={api_key}"
    )
    contents = [
        {"role": m["role"], "parts": [{"text": m["text"]}]}
        for m in messages
    ]
    body = json.dumps({"contents": contents}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8", errors="replace")) from exc

    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


def send_prompt(prompt: str) -> list[dict[str, str]]:
    with _LOCK:
        messages = load_history()
        messages.append({"role": "user", "text": prompt})
        answer = ask_llm(messages)
        messages.append({"role": "model", "text": answer})
        save_history(messages)
        return messages


def clear_history() -> None:
    with _LOCK:
        save_history([])


def run_cli() -> None:
    print("Пустая строка или /exit — выход, /clear — очистить историю.")
    while True:
        prompt = input("Вы: ").strip()
        if not prompt or prompt == "/exit":
            break
        if prompt == "/clear":
            clear_history()
            print("История очищена.")
            continue
        messages = send_prompt(prompt)
        print("Gemini:", messages[-1]["text"])


def html_page(messages: list[dict[str, str]] | None = None) -> bytes:
    if messages is None:
        messages = load_history()
    if messages:
        blocks = []
        for msg in messages:
            who = "Вы" if msg["role"] == "user" else "Gemini"
            css = "user" if msg["role"] == "user" else "model"
            blocks.append(
                f'<div class="msg {css}"><div class="who">{who}</div>'
                f"{html.escape(msg['text'])}</div>"
            )
        log = "".join(blocks)
    else:
        log = "<p>Истории пока нет. Напишите первый запрос ниже.</p>"
    return PAGE.replace("{messages}", log).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send(html_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
        action = fields.get("action", ["send"])[0]
        if action == "clear":
            clear_history()
            self._send(html_page([]))
            return
        prompt = fields.get("prompt", [""])[0].strip()
        if prompt:
            send_prompt(prompt)
        self._send(html_page())

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(format % args)


def run_web() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Открой http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    load_env()
    if "--web" in sys.argv:
        run_web()
    else:
        run_cli()
