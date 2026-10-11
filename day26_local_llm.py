#!/usr/bin/env python3
"""Run three progressively harder prompts against a local llama.cpp server."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


MODEL_REPO = "Qwen/Qwen3-4B-GGUF:Q4_K_M"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
PROMPTS = [
    (
        "Простой запрос",
        "Ответь по-русски одним коротким предложением: что такое локальная языковая модель?",
    ),
    (
        "Запрос с вычислением",
        "В теплице 4 ряда по 7 грядок. На каждой грядке посадили по 3 куста. "
        "Сколько всего кустов? Покажи вычисление и ответ.",
    ),
    (
        "Запрос на анализ и план",
        "Составь короткий план проверки аварийного датчика: сначала зафиксировать время сбоя, "
        "затем сверить показания с резервным термометром, повторить измерение через пять минут, "
        "записать оба результата и сообщить ответственному. Не добавляй действий, которых нет в условии. "
        "Выведи нумерованный список и отдельно назови, какие данные нужно сохранить.",
    ),
]


def request_json(url: str, payload: dict | None = None, timeout: float = 180) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    # Local requests must not travel through a system HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_until_ready(base_url: str, process: subprocess.Popen | None) -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"llama-server завершился с кодом {process.returncode}.")
        try:
            request_json(f"{base_url}/health", timeout=3)
            return
        except (OSError, ValueError):
            time.sleep(2)
    raise TimeoutError("Локальный сервер не запустился за 10 минут.")


def run_prompts(base_url: str) -> None:
    for number, (label, prompt) in enumerate(PROMPTS, start=1):
        started = time.monotonic()
        result = request_json(
            f"{base_url}/v1/chat/completions",
            {
                "model": MODEL_REPO,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 400,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        elapsed = time.monotonic() - started
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError(f"Запрос {number}: сервер вернул ответ без choices: {result}")
        answer = choices[0].get("message", {}).get("content", "").strip()
        usage = result.get("usage") or {}
        print(f"\n{'=' * 72}\n{number}. {label}\nЗапрос: {prompt}\n\nОтвет локальной модели:\n{answer}")
        print(f"\nВремя: {elapsed:.2f} с; токены: {usage.get('total_tokens', 'нет данных')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="запустить llama-server и при первом запуске скачать GGUF-модель из Hugging Face",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    server: subprocess.Popen | None = None

    try:
        if args.start_server:
            binary = shutil.which("llama-server")
            if not binary:
                raise RuntimeError("llama-server не найден. Установите llama.cpp через Homebrew.")
            print(f"Запускаю локальный сервер с моделью {MODEL_REPO} на {base_url}.")
            print("При первом запуске llama.cpp скачает файл модели; он останется в локальном кэше.")
            server = subprocess.Popen(
                [binary, "-hf", MODEL_REPO, "--jinja", "--host", "127.0.0.1", "--port", base_url.rsplit(":", 1)[-1]],
            )
        wait_until_ready(base_url, server)
        print(f"Локальный HTTP API доступен: {base_url}")
        run_prompts(base_url)
        return 0
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        print(f"Ошибка локального API HTTP {error.code}: {details}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"Не удалось выполнить демо: {error}", file=sys.stderr)
        if not args.start_server:
            print("Запустите llama-server или повторите команду с --start-server.", file=sys.stderr)
        return 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
