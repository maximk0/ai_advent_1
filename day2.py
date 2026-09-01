#!/usr/bin/env python3
"""День 2: один запрос, переключатели формата / длины / stop, сравнение через API."""

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL = "gemini-flash-lite-latest"
PORT = 8002
DEFAULT_PROMPT = "Дай рецепт греческого салата."
STOP_MARK = "###END"
MAX_TOKENS = 400

RECIPE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "dish": {"type": "STRING"},
        "ingredients": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "weight": {"type": "STRING"},
                    "order": {"type": "INTEGER"},
                },
                "required": ["name", "weight", "order"],
            },
        },
    },
    "required": ["dish", "ingredients"],
}

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>День 2 — формат ответа</title>
  <style>
    body { font-family: sans-serif; max-width: 1100px; margin: 24px auto; }
    textarea { width: 100%; min-height: 72px; box-sizing: border-box; }
    .toggles { display: flex; gap: 16px; flex-wrap: wrap; margin: 12px 0; }
    button { padding: 8px 16px; }
    button:disabled { opacity: 0.6; }
    .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    pre { background: #f3f4f6; padding: 12px; white-space: pre-wrap; min-height: 180px; }
    .meta { color: #555; font-size: 13px; }
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
    @media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div id="loader" aria-live="polite">
    <div class="spinner" aria-hidden="true"></div>
    <p>Сравниваю ответы Gemini…</p>
  </div>
  <h1>День 2. Формат ответа</h1>
  <p>Один и тот же запрос уходит в Gemini дважды: без ограничений и с выбранными.</p>
  <form method="post" action="/" onsubmit="showLoader()">
    <textarea name="prompt" placeholder="Запрос">{prompt}</textarea>
    <div class="toggles">
      <label><input type="checkbox" name="format" value="1"{format_on}> JSON-схема (блюдо + ингредиенты)</label>
      <label><input type="checkbox" name="limit" value="1"{limit_on}> Лимит длины ({max_tokens} токенов)</label>
      <label><input type="checkbox" name="stop" value="1"{stop_on}> Stop sequence ({stop_mark})</label>
    </div>
    <button type="submit" id="go">Сравнить</button>
  </form>
  {results}
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


def ask_llm(
    prompt: str,
    *,
    use_format: bool,
    use_limit: bool,
    use_stop: bool,
) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Нет GEMINI_API_KEY в .env")

    rules: list[str] = []
    config: dict = {}
    if use_format:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = RECIPE_SCHEMA
        rules.append(
            "Ответ — JSON с полями dish и ingredients. "
            "У каждого ингредиента: name, weight, order (порядок в блюде, с 1)."
        )
    if use_limit:
        config["maxOutputTokens"] = MAX_TOKENS
        rules.append("Не больше 6 ингредиентов, без длинных пояснений.")
    else:
        config["maxOutputTokens"] = 2048
    if use_stop:
        config["stopSequences"] = [STOP_MARK]
        rules.append(
            f"Когда рецепт готов, сразу напиши {STOP_MARK} и ничего после."
        )

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }
    if rules:
        payload["systemInstruction"] = {
            "parts": [{"text": " ".join(rules)}]
        }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={api_key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail) from exc

    candidate = data["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts)
    pretty = text
    parsed_ok = False
    try:
        pretty = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        parsed_ok = True
    except json.JSONDecodeError:
        pass

    usage = data.get("usageMetadata") or {}
    return {
        "text": text,
        "pretty": pretty,
        "json_ok": parsed_ok,
        "finish": candidate.get("finishReason", ""),
        "tokens": usage.get("candidatesTokenCount", usage.get("totalTokenCount", "")),
        "rules": rules,
        "config": config,
    }


def compare(prompt: str, use_format: bool, use_limit: bool, use_stop: bool) -> tuple[dict, dict]:
    free = ask_llm(prompt, use_format=False, use_limit=False, use_stop=False)
    controlled = ask_llm(
        prompt,
        use_format=use_format,
        use_limit=use_limit,
        use_stop=use_stop,
    )
    return free, controlled


def print_block(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print(f"finishReason: {result['finish']}  tokens: {result['tokens']}")
    if result["rules"]:
        print("правила:", " | ".join(result["rules"]))
    print(result["pretty"])


def run_cli(args: argparse.Namespace) -> None:
    prompt = args.prompt or DEFAULT_PROMPT
    if args.free_only:
        print_block("без ограничений", ask_llm(prompt, use_format=False, use_limit=False, use_stop=False))
        return
    if not args.compare and (args.format or args.limit or args.stop):
        print_block(
            "с ограничениями",
            ask_llm(prompt, use_format=args.format, use_limit=args.limit, use_stop=args.stop),
        )
        return
    free, controlled = compare(prompt, args.format, args.limit, args.stop)
    print("запрос:", prompt)
    print_block("без ограничений", free)
    print_block("с ограничениями", controlled)


def html_page(
    prompt: str = DEFAULT_PROMPT,
    use_format: bool = True,
    use_limit: bool = True,
    use_stop: bool = True,
    free: dict | None = None,
    controlled: dict | None = None,
    error: str = "",
) -> bytes:
    results = ""
    if error:
        results = f"<p class='meta'>{html.escape(error)}</p>"
    elif free and controlled:
        results = f"""
        <div class="cols">
          <section>
            <h2>Без ограничений</h2>
            <p class="meta">finishReason: {html.escape(str(free['finish']))}; tokens: {html.escape(str(free['tokens']))}</p>
            <pre>{html.escape(free['pretty'])}</pre>
          </section>
          <section>
            <h2>С ограничениями</h2>
            <p class="meta">finishReason: {html.escape(str(controlled['finish']))}; tokens: {html.escape(str(controlled['tokens']))}; json: {controlled['json_ok']}</p>
            <pre>{html.escape(controlled['pretty'])}</pre>
          </section>
        </div>
        """
    return (
        PAGE.replace("{prompt}", html.escape(prompt))
        .replace("{format_on}", " checked" if use_format else "")
        .replace("{limit_on}", " checked" if use_limit else "")
        .replace("{stop_on}", " checked" if use_stop else "")
        .replace("{max_tokens}", str(MAX_TOKENS))
        .replace("{stop_mark}", html.escape(STOP_MARK))
        .replace("{results}", results)
        .encode("utf-8")
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send(html_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
        prompt = (fields.get("prompt") or [DEFAULT_PROMPT])[0].strip() or DEFAULT_PROMPT
        use_format = "format" in fields
        use_limit = "limit" in fields
        use_stop = "stop" in fields
        try:
            free, controlled = compare(prompt, use_format, use_limit, use_stop)
            body = html_page(prompt, use_format, use_limit, use_stop, free, controlled)
        except Exception as exc:
            body = html_page(prompt, use_format, use_limit, use_stop, error=str(exc))
        self._send(body)

    def _send(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(format % args)


def run_web() -> None:
    server = None
    port = PORT
    for port in range(PORT, PORT + 12):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit("Нет свободного порта")
    print(f"Открой http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="День 2: контроль формата ответа Gemini")
    parser.add_argument("prompt", nargs="?", help="Один и тот же запрос")
    parser.add_argument("--web", action="store_true", help="Веб с переключателями")
    parser.add_argument("--compare", action="store_true", help="Показать оба варианта (по умолчанию, если нет --free-only)")
    parser.add_argument("--free-only", action="store_true", help="Только без ограничений")
    parser.add_argument("--format", action="store_true", default=True, help="JSON-схема (вкл. по умолчанию)")
    parser.add_argument("--no-format", action="store_false", dest="format")
    parser.add_argument("--limit", action="store_true", default=True, help="Лимит токенов (вкл. по умолчанию)")
    parser.add_argument("--no-limit", action="store_false", dest="limit")
    parser.add_argument("--stop", action="store_true", default=True, help="Stop sequence (вкл. по умолчанию)")
    parser.add_argument("--no-stop", action="store_false", dest="stop")
    return parser.parse_args()


if __name__ == "__main__":
    load_env()
    args = parse_args()
    if args.web:
        run_web()
    else:
        args.compare = True
        run_cli(args)
