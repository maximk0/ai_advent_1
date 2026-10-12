#!/usr/bin/env python3
"""День 30: приватный локальный RAG-чат с HTTP API и сетевым доступом."""

from __future__ import annotations

import json
import ipaddress
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from chat_ui import get_chat_page
from day29 import _index_info, _local_status
from simple_agent import SimpleAgent

ROOT = Path(__file__).resolve().parent
HOST = os.getenv("DAY30_HOST", "127.0.0.1")
PORT = int(os.getenv("DAY30_PORT", "8030"))
MAX_BODY_BYTES = 64_000
MAX_QUESTION_CHARS = 6_000
MAX_DIALOGUE_CONTEXT_CHARS = 16_000  # приблизительно 4k токенов текста диалога
RATE_LIMIT_REQUESTS = 8
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_STABILITY_TURNS = 5
LOCAL_MODEL = "local/qwen3-4b"
PRIVATE_IPV4_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

_lock = threading.RLock()
_rate_lock = threading.Lock()
_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)
_agent = SimpleAgent()
_agent.model = LOCAL_MODEL
_agent.model_supported_parameters = ["temperature", "top_p", "top_k"]
_agent.rag_mode_enabled = True

# When the app listens beyond loopback, require a per-run key. The page itself
# is public on the LAN; all state and inference endpoints require the key.
_network_bind = HOST not in {"127.0.0.1", "localhost", "::1"}
_api_key = os.getenv("DAY30_API_KEY", "").strip()
if _network_bind and not _api_key:
    _api_key = secrets.token_urlsafe(24)


class ApiError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _rate_check(client: str) -> int | None:
    now = time.monotonic()
    with _rate_lock:
        bucket = _requests_by_ip[client]
        while bucket and now - bucket[0] >= RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_REQUESTS:
            return max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        bucket.append(now)
    return None


def _estimate_tokens(text: str) -> int:
    # Roughly one token per four characters for a mixed Russian/English prompt.
    return (len(text) + 3) // 4


def _network_ipv4_addresses() -> list[str]:
    """Get real interface addresses; hostname DNS often resolves to loopback on macOS."""
    try:
        result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    found: list[tuple[int, str]] = []
    if result and result.returncode == 0:
        interface = ""
        for line in result.stdout.splitlines():
            if line and not line[0].isspace() and ":" in line:
                interface = line.split(":", 1)[0]
            match = re.match(r"\s+inet (\d+(?:\.\d+){3})\b", line)
            if not match:
                continue
            address = match.group(1)
            parsed = ipaddress.ip_address(address)
            if any(parsed in network for network in PRIVATE_IPV4_NETWORKS):
                priority = 0 if interface in {"en0", "en1", "wlan0", "eth0"} else 1
                found.append((priority, address))
    try:
        resolved = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        resolved = []
    for result_item in resolved:
        address = result_item[4][0]
        parsed = ipaddress.ip_address(address)
        if any(parsed in network for network in PRIVATE_IPV4_NETWORKS):
            found.append((2, address))
    return list(dict.fromkeys(address for _, address in sorted(found)))


def _local_service_status() -> dict:
    model = _local_status()
    addresses: list[str] = []
    public_url = os.getenv("DAY30_PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        addresses.append(public_url)
    if _network_bind:
        for ip in _network_ipv4_addresses():
            url = f"http://{ip}:{PORT}"
            if url not in addresses:
                addresses.append(url)
    elif not addresses:
        addresses = [f"http://127.0.0.1:{PORT}"]
    return {
        "service": "AI Advent · День 30",
        "host": HOST,
        "port": PORT,
        "network_access": _network_bind,
        "urls": addresses,
        "api_key_required": bool(_api_key),
        "model": model,
        "index": _index_info(),
        "limits": {
            "requests": RATE_LIMIT_REQUESTS,
            "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            "question_chars": MAX_QUESTION_CHARS,
            "dialogue_context_chars": MAX_DIALOGUE_CONTEXT_CHARS,
            "dialogue_context_approx_tokens": _estimate_tokens("x" * MAX_DIALOGUE_CONTEXT_CHARS),
            "stability_turns_max": MAX_STABILITY_TURNS,
        },
    }


def _prepare_local_chat(config: dict | None = None) -> None:
    if config:
        safe_config = dict(config)
        safe_config["model"] = LOCAL_MODEL
        _agent.set_config(safe_config)
    _agent.model = LOCAL_MODEL
    _agent.model_supported_parameters = ["temperature", "top_p", "top_k"]


def _chat(message: str, config: dict | None = None, *, history: list | None = None, persist: bool = True, system_prompt: str | None = None, generation: dict | None = None) -> dict:
    prompt = message.strip()
    if not prompt:
        raise ApiError(400, "Введите вопрос.")
    if len(prompt) > MAX_QUESTION_CHARS:
        raise ApiError(413, f"Вопрос слишком длинный: максимум {MAX_QUESTION_CHARS} символов.")
    with _lock:
        _prepare_local_chat(config)
        original_prompt = _agent.system_prompt
        original_generation = (_agent.temperature, _agent.top_p, _agent.top_k)
        try:
            if system_prompt is not None:
                _agent.system_prompt = system_prompt[:MAX_QUESTION_CHARS]
            if generation:
                _agent.temperature = max(0.0, min(float(generation.get("temperature", _agent.temperature)), 2.0))
                _agent.top_p = max(0.0, min(float(generation.get("top_p", _agent.top_p)), 1.0))
                _agent.top_k = max(0, min(int(generation.get("top_k", _agent.top_k)), 100))
            result = _agent.chat(
                prompt,
                history=history,
                persist_state=persist,
                rag_source_prefix="docs/",
                context_char_limit=MAX_DIALOGUE_CONTEXT_CHARS,
                max_tokens=(max(1, min(int(generation.get("max_tokens", 1000)), 2000)) if generation else 2000),
            )
        finally:
            if system_prompt is not None:
                _agent.system_prompt = original_prompt
            if generation:
                _agent.temperature, _agent.top_p, _agent.top_k = original_generation
        if result.get("error"):
            raise ApiError(502, str(result["error"]))
        return result


def _demo_stability(data: dict) -> dict:
    turns = data.get("turns", [])
    if not isinstance(turns, list) or not turns:
        turns = [
            "Сколько гряд в куполе «Иней»?",
            "Как называется основной сорт фасоли?",
            "Когда включается автоматический полив «Инея»?",
        ]
    turns = [str(value).strip() for value in turns[:MAX_STABILITY_TURNS]]
    turns = [value for value in turns if value]
    if not turns:
        raise ApiError(400, "Добавьте хотя бы один проверочный вопрос.")
    if any(len(value) > MAX_QUESTION_CHARS for value in turns):
        raise ApiError(413, f"Каждый вопрос должен быть не длиннее {MAX_QUESTION_CHARS} символов.")
    results = []
    temporary_history: list[dict] = []
    started = time.monotonic()
    for question in turns:
        try:
            answer = _chat(question, {"model": LOCAL_MODEL, "rag_mode_enabled": True}, history=temporary_history, persist=False)
            results.append({
                "question": question,
                "answer": answer.get("content", ""),
                "rag_evidence": answer.get("rag_evidence", ""),
                "model": answer.get("model", LOCAL_MODEL),
                "elapsed": answer.get("time", 0),
                "ok": True,
            })
        except ApiError as exc:
            results.append({"question": question, "error": str(exc), "ok": False})
            break
    return {
        "results": results,
        "successful": sum(bool(item.get("ok")) for item in results),
        "total": len(turns),
        "elapsed": round(time.monotonic() - started, 2),
        "context_limit_chars": MAX_DIALOGUE_CONTEXT_CHARS,
        "note": "Вопросы выполнялись последовательно на локальной модели и с локальным поиском по документам.",
    }


def _page() -> str:
    sidebar = f"""
    <details class="sidebar-disclosure" open>
      <summary>День 30 · приватный сервис</summary>
      <div class="control-help" style="margin-top:8px">Чат и HTTP API используют локальную Qwen и локальный поиск по документам. Вопросы ограничены {MAX_QUESTION_CHARS} символами; история для запроса — примерно {MAX_DIALOGUE_CONTEXT_CHARS // 4_000}k токенов.</div>
      <div id="day30AuthBox" style="margin-top:10px" hidden>
        <label for="day30ApiKey" style="display:block;font-size:.75rem;color:var(--text-dim);margin-bottom:5px">Ключ доступа сервера</label>
        <input id="day30ApiKey" type="password" autocomplete="off" placeholder="Вставьте ключ из окна запуска" style="width:100%;background:var(--bg-dark);border:1px solid var(--border);color:var(--text-main);padding:9px;border-radius:7px">
        <button type="button" id="day30Connect" style="margin-top:7px;width:100%;padding:8px;border:1px solid var(--border);border-radius:7px;background:var(--bg-card);color:var(--text-main);cursor:pointer">Подключиться</button>
      </div>
      <p id="day30SidebarStatus" class="control-help">Проверяю модель…</p>
    </details>
    """
    main = f"""
    <style>
      .day30-tabs{{display:flex;gap:8px;align-items:center;padding:12px 20px 0;border-bottom:1px solid var(--border);background:var(--bg-dark)}}
      .day30-tab{{border:1px solid var(--border);border-bottom:0;border-radius:9px 9px 0 0;padding:9px 16px;background:transparent;color:var(--text-dim);cursor:pointer;font:inherit}}
      .day30-tab.active{{background:var(--bg-card);color:var(--text-main);border-color:var(--primary)}}
      #day30View{{flex:1;min-height:0;overflow:auto;padding:24px;background:radial-gradient(ellipse at top,#1a2a3c 0,#0d1117 55%)}}
      .d30-panel{{max-width:1000px;margin:0 auto;background:linear-gradient(160deg,rgba(24,32,44,.98),rgba(17,23,32,.98));border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:16px}}
      .d30-panel h2{{margin:0 0 8px;font-size:1.1rem}}.d30-muted{{color:var(--text-dim);font-size:.84rem;line-height:1.5}}
      .d30-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0}}
      .d30-metric{{padding:12px;border:1px solid var(--border);border-radius:9px;background:#101721;overflow-wrap:anywhere}}
      .d30-metric small{{display:block;color:var(--text-dim);font-size:.72rem}}.d30-metric strong{{display:block;margin-top:5px;font-size:.9rem}}
      .d30-button{{border:0;border-radius:8px;padding:10px 15px;background:var(--primary);color:white;font-weight:650;cursor:pointer}}.d30-button:disabled{{opacity:.55;cursor:wait}}
      .d30-question{{width:100%;min-height:80px;margin:8px 0 12px;background:var(--bg-dark);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text-main);font:inherit}}
      .d30-result{{padding:12px;margin:10px 0;border:1px solid var(--border);background:#101721;border-radius:9px;white-space:pre-wrap;overflow-wrap:anywhere}}
      .d30-result.ok{{border-color:#315b48}}.d30-result.fail{{border-color:#693c3c}}.d30-endpoint{{font:12px ui-monospace,monospace;overflow-wrap:anywhere}}
      @media(max-width:760px){{.d30-grid{{grid-template-columns:1fr}}}}
    </style>
    <div class="day30-tabs" role="tablist" aria-label="Разделы приложения">
      <button id="day30ChatTab" class="day30-tab active" role="tab" aria-selected="true">Чат</button>
      <button id="day30ServiceTab" class="day30-tab" role="tab" aria-selected="false">День 30 · сервис</button>
      <span id="day30TopStatus" class="control-help" style="margin-left:auto"></span>
    </div>
    <section id="day30View" class="app-view" hidden>
      <article class="d30-panel"><h2>Приватный локальный AI-сервис</h2><p class="d30-muted">Сервис принимает HTTP-запросы в домашней сети, ищет контекст в локальном индексе и отправляет его локальной модели. История и документы остаются на этом компьютере.</p><div id="day30Metrics" class="d30-grid"></div><p id="day30ServiceNote" class="d30-muted">Проверяю подключение к локальной модели…</p></article>
      <article class="d30-panel"><h2>Проверка нескольких запросов подряд</h2><p class="d30-muted">Серия проверит ответы локальной модели и RAG, добавляя каждый вопрос в временную историю теста.</p><label class="d30-muted" for="day30Turns">Один вопрос на строку · до {MAX_STABILITY_TURNS} вопросов</label><textarea id="day30Turns" class="d30-question">Сколько гряд в куполе «Иней»?
Как называется основной сорт фасоли?
Когда включается автоматический полив «Инея»?</textarea><button id="day30RunStability" class="d30-button">Запустить проверку серии запросов</button><div id="day30StabilityResult" aria-live="polite"></div></article>
      <article class="d30-panel"><h2>HTTP API</h2><p class="d30-muted">OpenAI-совместимый endpoint для локального чата:</p><p class="d30-endpoint">POST <span id="day30Endpoint">/v1/chat/completions</span></p><p class="d30-muted">Запросы ограничены по частоте и размеру. Для внешнего клиента передайте ключ доступа в заголовке <code>Authorization: Bearer …</code>.</p><details><summary>Пример запроса</summary><pre id="day30Curl" class="d30-endpoint"></pre></details></article>
    </section>
    """
    script = f"""
    const DAY30_KEY_REQUIRED = {str(bool(_api_key)).lower()};
    const DAY30_DEFAULT_URL = location.origin;
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init={{}}) => {{
      const url = typeof input === 'string' ? input : input.url;
      if ((url.startsWith('/api/') || url.startsWith('/v1/')) && sessionStorage.getItem('day30-api-key')) {{
        const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
        headers.set('Authorization', `Bearer ${{sessionStorage.getItem('day30-api-key')}}`);
        init = {{...init, headers}};
      }}
      return originalFetch(input, init);
    }};
    const day30KeyBox=document.getElementById('day30AuthBox');
    if(DAY30_KEY_REQUIRED && !sessionStorage.getItem('day30-api-key')) day30KeyBox.hidden=false;
    document.getElementById('day30Connect').addEventListener('click',async()=>{{
      sessionStorage.setItem('day30-api-key',document.getElementById('day30ApiKey').value.trim());
      const response=await originalFetch('/api/day30/status',{{headers:{{'Authorization':`Bearer ${{sessionStorage.getItem('day30-api-key')}}`}}}});
      if(response.ok){{day30KeyBox.hidden=true;await loadDay30Status();await initApp();}}else{{alert('Ключ доступа не подошёл. Скопируйте ключ из окна запуска сервера.');sessionStorage.removeItem('day30-api-key');}}
    }});
    const day30ChatTab=document.getElementById('day30ChatTab'), day30ServiceTab=document.getElementById('day30ServiceTab');
    function day30Show(view){{const chat=view==='chat';document.getElementById('chatView').hidden=!chat;document.getElementById('day30View').hidden=chat;day30ChatTab.classList.toggle('active',chat);day30ServiceTab.classList.toggle('active',!chat);day30ChatTab.setAttribute('aria-selected',String(chat));day30ServiceTab.setAttribute('aria-selected',String(!chat));}}
    day30ChatTab.addEventListener('click',()=>day30Show('chat'));day30ServiceTab.addEventListener('click',()=>day30Show('service'));
    function day30Escape(value){{return String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
    async function loadDay30Status(){{
      try{{const response=await fetch('/api/day30/status');if(!response.ok)throw new Error('Требуется ключ сервера');const data=await response.json();const model=data.model||{{}};const limits=data.limits||{{}};
        document.getElementById('day30Metrics').innerHTML=[
          ['Локальная модель',model.connected?model.model:'не подключена'],['Контекст модели',model.context_window?`${{model.context_window}} токенов`:'не определён'],['Индекс',`${{data.index.chunks}} фрагментов · локально`],
          ['Лимит частоты',`${{limits.requests}} запросов / ${{Math.round(limits.window_seconds/60)}} мин`],['Максимум вопроса',`${{limits.question_chars}} символов`],['История в запросе',`до ~${{limits.dialogue_context_approx_tokens}} токенов`]
        ].map(([a,b])=>`<div class="d30-metric"><small>${{day30Escape(a)}}</small><strong>${{day30Escape(b)}}</strong></div>`).join('');
        const urls=data.urls&&data.urls.length?data.urls:[location.origin];document.getElementById('day30Endpoint').textContent=`${{urls[0]}}/v1/chat/completions`;
        document.getElementById('day30Curl').textContent=`curl -X POST '${{urls[0]}}/v1/chat/completions' -H 'Content-Type: application/json' -H 'Authorization: Bearer YOUR_DAY30_KEY' -d '{{"messages":[{{"role":"user","content":"Сколько гряд в куполе Иней?"}}]}}'`;
        const status=model.connected?'Модель подключена. Чат использует локальную Qwen; RAG-поиск выполняется на этом компьютере.':'Запустите llama-server на порту 8080, чтобы отвечать на вопросы.';
        document.getElementById('day30ServiceNote').textContent=status;document.getElementById('day30SidebarStatus').textContent=model.connected?'🟢 Локальная модель подключена':'🔴 Локальная модель недоступна';document.getElementById('day30TopStatus').textContent=model.connected?'Модель доступна':'Модель не подключена';
      }}catch(error){{document.getElementById('day30ServiceNote').textContent=error.message;document.getElementById('day30SidebarStatus').textContent=error.message;}}
    }}
    document.getElementById('day30RunStability').addEventListener('click',async()=>{{
      const button=document.getElementById('day30RunStability'),out=document.getElementById('day30StabilityResult');const turns=document.getElementById('day30Turns').value.split(String.fromCharCode(10)).map(s=>s.trim()).filter(Boolean);
      button.disabled=true;button.textContent='Выполняю запросы по очереди…';out.textContent='Локальная модель отвечает на вопросы серии.';
      try{{const response=await fetch('/api/day30/stability',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{turns}})}});const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка серии');
        out.innerHTML=`<p class="d30-muted">Успешно: ${{data.successful}} из ${{data.total}} · общее время ${{data.elapsed}} с</p>`+(data.results||[]).map((item,i)=>`<div class="d30-result ${{item.ok?'ok':'fail'}}"><b>${{i+1}}. ${{day30Escape(item.question)}}</b><br>${{day30Escape(item.answer||item.error)}}${{item.rag_evidence?'<br><br>Источник и цитата:<br>'+day30Escape(item.rag_evidence):''}}</div>`).join('')+`<p class="d30-muted">${{day30Escape(data.note||'')}}</p>`;
      }}catch(error){{out.innerHTML=`<div class="d30-result fail">${{day30Escape(error.message)}}</div>`;}}finally{{button.disabled=false;button.textContent='Запустить проверку серии запросов';}}
    }});
    const modelSelect=document.getElementById('modelSelect');
    for(const option of Array.from(modelSelect.options)) if(!option.value.startsWith('local/')) option.remove();
    modelSelect.value='DAY30_LOCAL_MODEL';
    document.addEventListener('DOMContentLoaded',()=>{{if(!DAY30_KEY_REQUIRED||sessionStorage.getItem('day30-api-key')){{loadDay30Status();}}}});
    """.replace("DAY30_LOCAL_MODEL", LOCAL_MODEL)
    return get_chat_page(
        title="AI Advent · День 30 · приватный локальный чат",
        extra_sidebar_html=sidebar,
        extra_scripts=script,
        extra_main_html=main,
    )


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


class Handler(BaseHTTPRequestHandler):
    server_version = "Day30LocalAI/1.0"

    def _send_json(self, data: dict, status: int = 200, headers: dict | None = None) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if headers:
            for key, value in headers.items():
                self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not _api_key:
            return True
        supplied = self.headers.get("X-API-Key", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        import hmac
        return hmac.compare_digest(supplied, _api_key)

    def _limited(self) -> bool:
        retry_after = _rate_check(self.client_address[0])
        if retry_after is None:
            return False
        self._send_json({"error": "Превышен лимит запросов. Подождите и повторите."}, 429, {"Retry-After": retry_after})
        return True

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ApiError(400, "Некорректный размер запроса.") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ApiError(413, f"Тело запроса должно быть от 1 до {MAX_BODY_BYTES} байт.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, "Тело запроса должно содержать JSON.") from exc
        if not isinstance(value, dict):
            raise ApiError(400, "Ожидается JSON-объект.")
        return value

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in {"/", "/day30"}:
            page = _page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)
            return
        if path.startswith("/api/") or path.startswith("/v1/") or path == "/health":
            if not self._authorized():
                self._send_json({"error": "Требуется ключ доступа сервера."}, 401)
                return
            if path == "/api/day30/status":
                self._send_json(_local_service_status())
                return
            if path == "/api/state":
                with _lock:
                    self._send_json(_agent.get_state())
                return
            if path == "/health":
                self._send_json({"ok": True, "service": "day30"})
                return
            if path == "/v1/models":
                self._send_json({"object": "list", "data": [{"id": LOCAL_MODEL, "object": "model", "owned_by": "local"}]})
                return
        self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if not self._authorized():
            self._send_json({"error": "Требуется ключ доступа сервера."}, 401)
            return
        if path not in {"/api/chat", "/api/config", "/api/clear", "/api/day30/stability", "/v1/chat/completions"}:
            self._send_json({"error": "Not found"}, 404)
            return
        if path in {"/api/chat", "/api/day30/stability", "/v1/chat/completions"} and self._limited():
            return
        try:
            body_length = self.headers.get("Content-Length", "0")
            data = {} if path == "/api/clear" and body_length in {"", "0"} else self._read_json()
            if path == "/api/chat":
                message = data.get("message")
                if not isinstance(message, str):
                    raise ApiError(400, "Поле message должно быть строкой.")
                answer = _chat(message, data.get("config") if isinstance(data.get("config"), dict) else None)
                self._send_json({
                    "content": answer.get("content", ""),
                    "rag_evidence": answer.get("rag_evidence", ""),
                    "model": answer.get("model", LOCAL_MODEL),
                    "time": answer.get("time", 0),
                    "usage": answer.get("usage", {}),
                    "stats": answer.get("stats", {}),
                })
                return
            if path == "/api/config":
                config = {key: value for key, value in data.items() if key != "model"}
                config["model"] = LOCAL_MODEL
                with _lock:
                    _agent.set_config(config)
                self._send_json({"ok": True})
                return
            if path == "/api/clear":
                with _lock:
                    _agent.clear_history(clear_all=bool(data.get("clear_all", False)))
                self._send_json({"ok": True})
                return
            if path == "/api/day30/stability":
                self._send_json(_demo_stability(data))
                return
            if path == "/v1/chat/completions":
                messages = data.get("messages")
                if not isinstance(messages, list):
                    raise ApiError(400, "Поле messages должно быть массивом.")
                user_messages = [item for item in messages if isinstance(item, dict) and item.get("role") == "user"]
                if not user_messages or not isinstance(user_messages[-1].get("content"), str):
                    raise ApiError(400, "Добавьте текстовое сообщение пользователя.")
                total_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
                if total_chars > MAX_DIALOGUE_CONTEXT_CHARS + MAX_QUESTION_CHARS:
                    raise ApiError(413, "История чата превышает установленный размер контекста.")
                history = []
                for item in messages[:-1]:
                    if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                        continue
                    content = item.get("content")
                    if isinstance(content, str):
                        history.append({"role": item["role"], "content": content})
                system_prompt = next((item.get("content") for item in messages if isinstance(item, dict) and item.get("role") == "system" and isinstance(item.get("content"), str)), None)
                generation = {key: data[key] for key in ("temperature", "top_p", "top_k", "max_tokens") if key in data}
                result = _chat(user_messages[-1]["content"], {"model": LOCAL_MODEL, "rag_mode_enabled": True}, history=history, persist=False, system_prompt=system_prompt, generation=generation)
                content = str(result.get("content", ""))
                evidence = str(result.get("rag_evidence", ""))
                if evidence:
                    content += "\n\n" + evidence
                self._send_json({
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}", "object": "chat.completion", "created": int(time.time()),
                    "model": result.get("model", LOCAL_MODEL),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": result.get("usage", {}),
                })
                return
        except ApiError as exc:
            headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
            self._send_json({"error": str(exc)}, exc.status, headers)
        except Exception as exc:
            self._send_json({"error": f"Ошибка сервиса: {exc}"}, 500)

    def log_message(self, fmt: str, *args) -> None:
        # Avoid logging message bodies, model prompts, or credentials.
        message = fmt % args
        if "Bad request version" in message or "Bad request syntax" in message:
            print(f"[Day 30] {self.address_string()} - некорректный HTTP-запрос; проверьте, что открываете адрес с http://, а не https://")
            return
        print(f"[Day 30] {self.address_string()} - {message[:300]}")


def main() -> None:
    index = _index_info()
    server = Server((HOST, PORT), Handler)
    print(f"День 30: локальный чат и HTTP API готовы: http://127.0.0.1:{PORT}/")
    print(f"Привязка сервера: {HOST}:{PORT}; лимит {RATE_LIMIT_REQUESTS} запросов/{RATE_LIMIT_WINDOW_SECONDS} с; вопрос до {MAX_QUESTION_CHARS} символов.")
    print(f"Локальный индекс: {index['chunks']} фрагментов; локальная модель ожидается на http://127.0.0.1:8080.")
    if _network_bind:
        network_urls = _local_service_status()["urls"]
        if network_urls:
            print("Сетевые адреса:", ", ".join(network_urls))
        else:
            print("Не удалось определить IP-адрес сети. На Mac проверьте `ifconfig en0` и откройте http://<IP>:8030.")
        if _api_key:
            print(f"Ключ доступа (вставьте в веб-интерфейс на другом устройстве): {_api_key}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервис остановлен.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
