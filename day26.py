#!/usr/bin/env python3
"""Local-only Day 26 page, also mounted by day25.py at /local-model."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from day26_local_llm import DEFAULT_BASE_URL, MODEL_REPO, PROMPTS, request_json

PAGE = Path(__file__).with_name("local_llm_ui.html")
MAX_BODY = 48_000
MAX_PROMPT = 6_000


class LocalModelError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def local_request(path: str, payload: dict | None = None, timeout: float = 5) -> dict:
    try:
        result = request_json(DEFAULT_BASE_URL + path, payload, timeout)
        if not isinstance(result, dict):
            raise ValueError("Invalid response")
        return result
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 503:
            raise LocalModelError("Модель загружается или сервер занят. Подождите немного и повторите проверку.", 503) from exc
        raise LocalModelError("Локальный сервер не смог обработать запрос. Попробуйте ещё раз или перезапустите llama.cpp.") from exc
    except TimeoutError as exc:
        raise LocalModelError("Сервер отвечает слишком долго. Попробуйте задать более короткий вопрос.", 504) from exc
    except OSError as exc:
        raise LocalModelError("Нет подключения к локальной модели. Запустите llama.cpp и нажмите «Проверить подключение».", 503) from exc
    except (ValueError, UnicodeError) as exc:
        raise LocalModelError("Сервер вернул непонятный ответ. Повторите запрос.") from exc


def selected_model() -> str:
    local_request("/health")
    models = local_request("/v1/models").get("data")
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        raise LocalModelError("Сервер доступен, но модель пока не выбрана. Проверьте запуск llama.cpp.", 503)
    model = models[0].get("id")
    if not isinstance(model, str) or not model.strip():
        raise LocalModelError("Сервер не сообщил название загруженной модели.")
    return model


def complete_chat(data: dict) -> dict:
    # Each question is independent, making the three difficulty checks comparable.
    prompt = data.get("message")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LocalModelError("Введите вопрос для локальной модели.", 400)
    if len(prompt) > MAX_PROMPT:
        raise LocalModelError("Вопрос слишком длинный. Сократите его до 6 000 символов.", 400)
    model = selected_model()
    started = time.monotonic()
    response = local_request("/v1/chat/completions", {
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай по-русски, кратко и понятно. Дай только итоговый ответ без внутренних рассуждений."},
            {"role": "user", "content": prompt.strip()},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }, timeout=180)
    try:
        choice = response["choices"][0]
        answer = choice["message"]["content"]
        if not isinstance(answer, str):
            raise ValueError("Missing answer")
        # Some builds include Qwen reasoning in content instead of a separate field.
        answer = re.sub(r"<think>.*?(?:</think>|$)", "", answer, flags=re.DOTALL).strip()
        if not answer:
            raise ValueError("Empty answer")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LocalModelError("Модель не вернула готовый ответ. Попробуйте сократить вопрос и отправить его ещё раз.") from exc
    return {
        "answer": answer,
        "model": model,
        "elapsed": round(time.monotonic() - started, 2),
        "truncated": choice.get("finish_reason") == "length",
    }


def send_json(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def handle_local_model(handler: BaseHTTPRequestHandler) -> bool:
    """Return False for existing application routes; no agent/history dependencies."""
    path = urlparse(handler.path).path.rstrip("/")
    if handler.command == "GET" and path == "/local-model":
        presets = json.dumps(PROMPTS, ensure_ascii=False).replace("<", "\\u003c")
        body = PAGE.read_text(encoding="utf-8").replace("__PRESETS__", presets).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if path not in ("/api/local-model/status", "/api/local-model/chat"):
        return False
    try:
        if handler.command == "GET" and path.endswith("/status"):
            model = selected_model()
            send_json(handler, {"connected": True, "model": model, "prompts": PROMPTS})
        elif handler.command == "POST" and path.endswith("/chat"):
            # Disallow cross-origin browser writes to this local proxy.
            origin = handler.headers.get("Origin")
            if origin and origin != "http://" + handler.headers.get("Host", ""):
                raise LocalModelError("Откройте страницу локальной модели в этом приложении.", 403)
            try:
                length = int(handler.headers.get("Content-Length", "0"))
                if length < 1 or length > MAX_BODY:
                    raise LocalModelError("Вопрос слишком длинный или не указан.", 400)
                data = json.loads(handler.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected object")
            except (ValueError, UnicodeError) as exc:
                raise LocalModelError("Не удалось прочитать вопрос. Отправьте его ещё раз.", 400) from exc
            send_json(handler, complete_chat(data))
        else:
            raise LocalModelError("Этот способ обращения не поддерживается.", 405)
    except LocalModelError as exc:
        send_json(handler, {"connected": False, "error": str(exc), "expected_model": MODEL_REPO}, exc.status)
    return True


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path == "/":
            self.send_response(302)
            self.send_header("Location", "/local-model")
            self.end_headers()
        elif not handle_local_model(self):
            self.send_error(404)

    def do_POST(self):
        if not handle_local_model(self):
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"День 26 — Локальная модель: http://127.0.0.1:{args.port}/local-model", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
