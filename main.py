#!/usr/bin/env python3
"""Веб-приложение AI Advent: чат, локальный RAG и помощь по проекту."""

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
import urllib.error
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from chat_ui import get_chat_page
from document_indexer import DocumentIndexer
from mcp_client import MCPClient
from project_rag import ProjectKnowledgeBase
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
PROJECT_HELP_HISTORY_FILE = ROOT / "history_project_help.json"
LOCAL_MODEL = "local/qwen3-4b"
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
PRIVATE_IPV4_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

_lock = threading.RLock()
_rate_lock = threading.Lock()
_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)
_agent = SimpleAgent()
_agent.rag_mode_enabled = True
_project_help_history: list[dict] = []
_project_help_history_lock = threading.RLock()
_project_knowledge: ProjectKnowledgeBase | None = None
_git_mcp: MCPClient | None = None
_mcp_init_lock = threading.Lock()


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _http_json(url: str, timeout: float = 5) -> dict:
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if url.startswith("http://127.0.0.1") else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {message[:1200]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def _local_status() -> dict:
    try:
        _http_json(f"{LOCAL_LLM_BASE_URL}/health", timeout=3)
        models = _http_json(f"{LOCAL_LLM_BASE_URL}/v1/models", timeout=5).get("data", [])
        if not models:
            return {"connected": False, "error": "llama.cpp доступен, но модель не найдена."}
        model_id = models[0].get("id", "Qwen/Qwen3-4B-GGUF:Q4_K_M")
        context_window = None
        try:
            slots = _http_json(f"{LOCAL_LLM_BASE_URL}/slots", timeout=3)
            if isinstance(slots, list):
                values = [int(slot.get("n_ctx")) for slot in slots if isinstance(slot, dict) and slot.get("n_ctx")]
                context_window = min(values) if values else None
        except Exception:
            pass
        quantization_match = re.search(r"Q[2-8]_[K0-9]+(?:_[A-Z0-9]+)?", str(model_id), re.IGNORECASE)
        return {
            "connected": True,
            "model": model_id,
            "context_window": context_window,
            "quantization": quantization_match.group(0).upper() if quantization_match else "не определено по ID модели",
        }
    except Exception as exc:
        return {"connected": False, "error": f"Не удалось подключиться к llama.cpp на {LOCAL_LLM_BASE_URL}: {exc}"}


def _index_info() -> dict:
    chunks = DocumentIndexer()._load_chunks()
    return {
        "file": "document_index.json",
        "documents": len({str(chunk.get("source", "")) for chunk in chunks if chunk.get("source")}),
        "chunks": len(chunks),
        "retrieval": "локальный лексический поиск по совпадению слов; без эмбеддингов",
    }


def _save_project_help_history() -> None:
    try:
        PROJECT_HELP_HISTORY_FILE.write_text(
            json.dumps(_project_help_history[-200:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"Не удалось сохранить историю помощи по проекту: {exc}")


def _load_project_help_history() -> None:
    global _project_help_history
    try:
        stored = json.loads(PROJECT_HELP_HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(stored, list):
            _project_help_history = [
                item for item in stored
                if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
            ][-200:]
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Не удалось прочитать историю помощи по проекту: {exc}")

    # Move /help turns saved by older versions out of the general chat history.
    migrated: list[dict] = []
    remaining: list[dict] = []
    is_help_turn = False
    for item in _agent.history:
        if item.get("role") == "user" and str(item.get("content", "")).strip().casefold().startswith("/help"):
            content = str(item.get("content", "")).strip()
            question = content[5:].strip()
            migrated.append({**item, "content": question or "Кратко опиши назначение и структуру проекта."})
            is_help_turn = True
        elif is_help_turn and item.get("role") == "assistant":
            migrated.append(item)
            is_help_turn = False
        else:
            remaining.append(item)
            is_help_turn = False
    if migrated:
        _project_help_history = (migrated + _project_help_history)[-200:]
        _agent.history = remaining
        _agent._save_state()
        _save_project_help_history()


_load_project_help_history()

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
        "service": "AI Advent",
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


def _project_kb() -> ProjectKnowledgeBase:
    global _project_knowledge
    if _project_knowledge is None:
        _project_knowledge = ProjectKnowledgeBase(ROOT)
    return _project_knowledge


def _git_status_via_mcp() -> dict:
    global _git_mcp
    with _mcp_init_lock:
        if _git_mcp is None or not _git_mcp.is_connected:
            _git_mcp = MCPClient(str(ROOT / "mcp_server_git.py"))
    if not _git_mcp.is_connected:
        raise RuntimeError("Git MCP не подключён.")
    tool_names = {item.get("name") for item in _git_mcp.refresh_tools()}
    if "git_status_check" not in tool_names:
        raise RuntimeError("Git MCP не предоставляет инструмент git_status_check.")
    raw = _git_mcp.call_tool("git_status_check", {})
    status = json.loads(raw)
    if not isinstance(status, dict) or not status.get("current_branch"):
        raise RuntimeError("Git MCP не вернул текущую ветку.")
    return status


def _project_help(message: str) -> dict:
    question = message.strip()[len("/help"):].strip()
    if not question:
        question = "Кратко опиши назначение проекта, его структуру и запуск приложения."
    knowledge = _project_kb()
    chunks = knowledge.search(question, top_k=4)
    git_status: dict | None = None
    mcp_error = ""
    try:
        git_status = _git_status_via_mcp()
    except Exception as exc:
        mcp_error = str(exc)
    if git_status:
        chunks.insert(0, {
            "chunk_id": "mcp_git_status",
            "source": "MCP · git_status_check",
            "title_or_file": "Git MCP",
            "section": "Текущая ветка и статус",
            "strategy": "mcp_live_context",
            "similarity": 1.0,
            "search_score": 1,
            "matched_terms": ["git", "branch"],
            "text": json.dumps(git_status, ensure_ascii=False, indent=2),
        })
    if not chunks:
        return {
            "role": "assistant",
            "content": "Не нашёл подходящих фрагментов в README, docs или файлах проекта. Уточните, о каком компоненте спросить.",
            "rag_evidence": "",
            "model": LOCAL_MODEL,
            "time": 0,
            "usage": {},
            "stats": _agent.get_token_stats(),
        }
    prompt = f"Вопрос о текущем проекте: {question}"
    if mcp_error:
        prompt += f"\nGit MCP сейчас недоступен ({mcp_error}); не утверждай, что проверил текущую ветку."
    project_system_prompt = (
        "Ты — помощник разработчика этого репозитория. Отвечай по-русски, используя переданные фрагменты README, docs, кода "
        "и живой информации от Git MCP. Не придумывай файлы, команды, API или состояние Git. Если документация не отвечает, "
        "обозначь это прямо. Для ключевых фактов используй chunk_id; приложение отдельно добавит источники и цитаты. "
        "Когда спрашивают текущую ветку, используй только результат инструмента git_status_check."
    )
    with _project_help_history_lock:
        answer = _chat(
            prompt,
            {"rag_mode_enabled": True, "rag_top_k_before": 10, "rag_top_k_after": 5},
            history=_project_help_history,
            persist=False,
            rag_chunks=chunks[:5],
            rag_source_prefix=None,
            system_prompt=project_system_prompt,
        )
        _save_project_help_history()
        return answer


def _prepare_local_chat(config: dict | None = None) -> None:
    if config:
        _agent.set_config(dict(config))


def _chat(message: str, config: dict | None = None, *, history: list | None = None, persist: bool = True, system_prompt: str | None = None, generation: dict | None = None, rag_chunks: list | None = None, rag_source_prefix: str | None = "docs/") -> dict:
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
                rag_source_prefix=rag_source_prefix,
                rag_chunks=rag_chunks,
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


SIDEBAR_SETTINGS_HTML = """
<section class="sidebar-setting">
  <label class="checkbox-group"><input id="rag_mode_enabled" type="checkbox" checked><span>Включать поиск по документам (RAG)</span></label>
  <div id="ragControls" style="display:none;flex-direction:column;gap:8px;margin-top:10px">
    <label class="checkbox-group"><input id="rag_query_rewrite_enabled" type="checkbox" checked><span>Переформулировать запрос перед поиском</span></label>
    <label class="control-help" for="ragTopKBefore">Кандидатов до фильтра (Top-K)</label><input id="ragTopKBefore" type="number" min="1" max="50" value="10">
    <label class="control-help" for="ragSimilarityThreshold">Порог similarity</label><input id="ragSimilarityThreshold" type="number" min="0" max="1" step="0.01" value="0.25">
    <label class="control-help" for="ragTopKAfter">Фрагментов после фильтра</label><input id="ragTopKAfter" type="number" min="1" max="10" value="3">
    <span class="control-help">Top-K задаёт число отбираемых фрагментов. Порог отсекает результаты со слабым совпадением.</span>
  </div>
</section>

<section class="sidebar-setting">
  <label class="checkbox-group"><input id="invariants_enabled" type="checkbox"><span>Включить инварианты</span></label>
  <div id="invariantControls" style="display:none;flex-direction:column;gap:7px;margin-top:9px">
    <select id="invariantPresetSelect"><option value="">Выберите готовый инвариант…</option></select>
    <button type="button" class="d30-button" onclick="addSelectedInvariant()">Добавить выбранный</button>
    <div id="invList" class="control-help">Пока ни одного инварианта не выбрано.</div>
    <button type="button" onclick="resetAllInvariants()">Сбросить все инварианты</button>
    <details><summary>Добавить свой</summary><input id="newInvKey" type="text" placeholder="Название"><textarea id="newInvVal" rows="3" placeholder="Текст правила"></textarea><button type="button" onclick="addNewInvariant()">Добавить</button></details>
  </div>
</section>

<section class="sidebar-setting">
  <label class="checkbox-group"><input id="planning_mode_enabled" type="checkbox"><span>Жизненный цикл задачи</span></label>
  <div id="lifecycleControls" style="display:none;flex-direction:column;gap:8px;margin-top:9px">
    <div class="control-help">Этапы: <span id="badge_none">NONE</span> → <span id="badge_planning">PLAN</span> → <span id="badge_execution">EXEC</span> → <span id="badge_validation">VALID</span> → <span id="badge_done">DONE</span></div>
    <div class="control-help">Шаг: <span id="tsmStepText">—</span><br>Действие: <span id="tsmActionText">—</span></div>
    <div id="transitionButtons" style="display:grid;grid-template-columns:repeat(2,1fr);gap:5px"></div>
  </div>
</section>

<details class="sidebar-disclosure">
  <summary>Персонализация и профили</summary>
  <select id="profileSelect" style="width:100%;margin:10px 0"></select>
  <div id="profileDetailsBlock" class="control-help">Роль: <span id="profRole"></span><br>Стиль: <span id="profStyle"></span><br>Формат: <span id="profFormat"></span><br>Ограничения: <span id="profConstraints"></span></div>
  <div style="display:flex;gap:6px;margin-top:8px"><button type="button" onclick="openEditorForUpdate()">Редактировать</button><button type="button" onclick="openEditorForCreate()">Создать профиль</button></div>
  <div id="profileEditor" style="display:none;flex-direction:column;gap:6px;margin-top:8px"><b id="editorTitle">Профиль</b><input id="editProfName" placeholder="Имя профиля"><textarea id="editProfRole" placeholder="Роль"></textarea><textarea id="editProfStyle" placeholder="Стиль"></textarea><textarea id="editProfFormat" placeholder="Формат"></textarea><textarea id="editProfConstraints" placeholder="Ограничения"></textarea><div style="display:flex;gap:6px"><button type="button" onclick="saveProfileManual()">Сохранить</button><button type="button" onclick="closeProfileEditor()">Отмена</button></div></div>
</details>

<details class="sidebar-disclosure">
  <summary>Управление памятью</summary>
  <b class="control-help">Долговременная память</b><div id="ltmList" class="control-help">Нет сохранённых фактов</div>
  <div style="display:flex;flex-direction:column;gap:5px;margin:8px 0"><input id="manualLtmKey" placeholder="Название факта"><input id="manualLtmVal" placeholder="Значение"><button type="button" onclick="pinToLtmManual()">Сохранить факт</button></div>
  <b class="control-help">Рабочая память задачи</b><pre id="wmList" class="control-help" style="white-space:pre-wrap">Нет активных данных задачи</pre>
</details>

<details class="sidebar-disclosure"><summary>Статистика токенов</summary><div class="token-row"><span>Всего токенов</span><span id="statTotal" class="token-val">0</span></div><div class="token-row"><span>Стоимость</span><span id="statCost" class="token-val">$0.000000</span></div></details>
<style>
  .stage-active{color:#fff;background:#315f95;border-radius:4px;padding:2px 4px}
  .sidebar-setting{margin:0 0 16px;border-top:1px solid var(--border);padding-top:10px}
  .sidebar-setting > .checkbox-group{color:var(--text-main);font-size:.85rem;font-weight:700;line-height:1.35}
  #invList{max-height:150px;overflow:auto;white-space:pre-wrap;padding:8px;border:1px solid var(--border);border-radius:6px}
  .invariant-item{padding:7px;border-left:3px solid #ef7777;background:var(--bg-dark);margin-bottom:5px;border-radius:4px}
  .invariant-item button{float:right}
  #profileEditor input,#profileEditor textarea,#manualLtmKey,#manualLtmVal,#ragControls input,#invariantControls input,#invariantControls textarea,#invariantControls select,#profileSelect{width:100%;background:var(--bg-dark);border:1px solid var(--border);color:var(--text-main);padding:7px;border-radius:6px;font:inherit}
  #profileEditor textarea,#invariantControls textarea{min-height:48px}
  #invariantControls button,#profileEditor button,#invariantControls details button,#transitionButtons button{background:var(--bg-card);color:var(--text-main);border:1px solid var(--border);border-radius:6px;padding:6px;cursor:pointer}
</style>
"""


def _page() -> str:
    sidebar = f"""
      <div id="day30AuthBox" class="config-group" style="margin-top:10px" hidden>
        <label for="day30ApiKey" style="display:block;font-size:.75rem;color:var(--text-dim);margin-bottom:5px">Ключ доступа сервера</label>
        <input id="day30ApiKey" type="password" autocomplete="off" placeholder="Вставьте ключ из окна запуска" style="width:100%;background:var(--bg-dark);border:1px solid var(--border);color:var(--text-main);padding:9px;border-radius:7px">
        <button type="button" id="day30Connect" style="margin-top:7px;width:100%;padding:8px;border:1px solid var(--border);border-radius:7px;background:var(--bg-card);color:var(--text-main);cursor:pointer">Подключиться</button>
      </div>
    """
    sidebar += SIDEBAR_SETTINGS_HTML
    main = f"""
    <style>
      .day30-tabs{{display:flex;gap:8px;align-items:center;padding:12px 20px 0;border-bottom:1px solid var(--border);background:var(--bg-dark);overflow-x:auto}}
      .day30-tab{{border:1px solid var(--border);border-bottom:0;border-radius:9px 9px 0 0;padding:9px 16px;background:transparent;color:var(--text-dim);cursor:pointer;font:inherit}}
      .day30-tab.active{{background:var(--bg-card);color:var(--text-main);border-color:var(--primary)}}
      #day30View{{flex:1;min-height:0;overflow:auto;padding:24px;background:radial-gradient(ellipse at top,#1a2a3c 0,#0d1117 55%)}}
      #day31HelpView{{display:flex;flex:1;min-height:0;overflow:hidden;padding:24px;background:radial-gradient(ellipse at top,#1a2a3c 0,#0d1117 55%)}}
      .d31-help-shell{{width:100%;max-width:1000px;min-height:0;flex:1;margin:0 auto;display:flex;flex-direction:column;gap:16px}}
      .d31-help-intro{{padding:18px 20px;border:1px solid var(--border);border-radius:14px;background:linear-gradient(160deg,rgba(24,32,44,.98),rgba(17,23,32,.98))}}
      .d31-help-intro h2{{margin:0 0 7px;font-size:1.1rem}}.d31-help-intro p{{margin:0;color:var(--text-dim);font-size:.85rem;line-height:1.5}}
      .d31-help-topics{{display:flex;flex-wrap:wrap;gap:8px}}
      .d31-help-topic{{padding:8px 11px;border:1px solid var(--border);border-radius:999px;background:var(--bg-card);color:var(--text-main);cursor:pointer;font:inherit;font-size:.8rem}}
      .d31-help-topic:hover{{border-color:var(--primary)}}
      #d31HelpLog{{display:flex;flex-direction:column;align-items:stretch;gap:12px;flex:1;min-height:0;overflow-y:auto;padding:2px 6px 12px;scrollbar-gutter:stable}}
      .d31-help-message{{max-width:min(82%,780px);padding:13px 15px;border:1px solid var(--border);border-radius:12px;background:var(--bg-card);color:var(--text-main);white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55}}
      .d31-help-message.user{{align-self:flex-end;background:#18324a;border-color:#315b7c}}.d31-help-message.assistant{{align-self:flex-start}}
      .d31-help-message h1,.d31-help-message h2,.d31-help-message h3{{margin:0 0 10px;line-height:1.3}}
      .d31-help-message h1{{font-size:1.2rem}}.d31-help-message h2{{font-size:1.08rem}}.d31-help-message h3{{font-size:.98rem}}
      .d31-help-message pre{{max-width:100%;overflow:auto;padding:10px;border-radius:7px;background:#0d1117}}
      .d31-help-message code{{font-family:ui-monospace,SFMono-Regular,monospace;background:rgba(0,0,0,.2);padding:1px 4px;border-radius:4px}}
      .d31-help-message details{{margin-top:10px;border-top:1px solid var(--border);padding-top:8px;color:var(--text-dim);font-size:.8rem}}
      .d31-help-message details pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:var(--text-dim)}}
      .rag-evidence-card{{background:#101923;border-color:#3d536b;border-left-color:#75a9df;color:#d6e1ee}}
      .rag-evidence-card summary{{color:#a9d0ff}}
      .d31-help-compose{{position:relative;z-index:2;flex:0 0 auto;display:flex;gap:9px;padding:10px;margin-bottom:2px;background:#0d1117;border:1px solid var(--border);border-radius:12px;box-shadow:0 -10px 24px rgba(0,0,0,.35)}}
      #d31HelpQuestion{{flex:1;min-height:44px;max-height:150px;resize:vertical;background:var(--bg-dark);border:0;color:var(--text-main);font:inherit;outline:none}}
      #d31HelpSend{{padding:9px 15px;border:0;border-radius:8px;background:var(--primary);color:#fff;font-weight:650;cursor:pointer}}#d31HelpSend:disabled{{opacity:.6;cursor:wait}}
      .d31-help-message.loading{{display:flex;align-items:center;gap:10px;color:var(--text-dim)}}
      .d31-help-spinner{{width:16px;height:16px;flex:0 0 16px;border:2px solid #526174;border-top-color:#8cc8ff;border-radius:50%;animation:d31-spin .8s linear infinite}}
      @keyframes d31-spin{{to{{transform:rotate(360deg)}}}}
      @media(max-width:760px){{#day31HelpView{{padding:14px}}.d31-help-shell{{gap:12px}}}}
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
      <button id="day31HelpTab" class="day30-tab" role="tab" aria-selected="false">Помощь по проекту</button>
      <button id="day30ServiceTab" class="day30-tab" role="tab" aria-selected="false">Сервис и API</button>
      <span id="day30TopStatus" class="control-help" style="margin-left:auto"></span>
    </div>
    <section id="day30View" class="app-view" hidden>
      <article class="d30-panel"><h2>Локальный сервис и API</h2><p class="d30-muted">Эта вкладка показывает доступность локального HTTP-сервиса, его сетевые ограничения и проверку запросов. Она не переключает модель чата: модель выбирается в сайдбаре.</p><div id="day30Metrics" class="d30-grid"></div><p id="day30ServiceNote" class="d30-muted">Проверяю подключение к локальной модели…</p></article>
      <article class="d30-panel"><h2>Проверка нескольких запросов подряд</h2><p class="d30-muted">Серия проверит ответы локальной модели и RAG, добавляя каждый вопрос в временную историю теста.</p><label class="d30-muted" for="day30Turns">Один вопрос на строку · до {MAX_STABILITY_TURNS} вопросов</label><textarea id="day30Turns" class="d30-question">Сколько гряд в куполе «Иней»?
Как называется основной сорт фасоли?
Когда включается автоматический полив «Инея»?</textarea><button id="day30RunStability" class="d30-button">Запустить проверку серии запросов</button><div id="day30StabilityResult" aria-live="polite"></div></article>
      <article class="d30-panel"><h2>HTTP API</h2><p class="d30-muted">OpenAI-совместимый endpoint для локального чата:</p><p class="d30-endpoint">POST <span id="day30Endpoint">/v1/chat/completions</span></p><p class="d30-muted">Запросы ограничены по частоте и размеру. Для внешнего клиента передайте ключ доступа в заголовке <code>Authorization: Bearer …</code>.</p><details><summary>Пример запроса</summary><pre id="day30Curl" class="d30-endpoint"></pre></details></article>
    </section>
    <section id="day31HelpView" class="app-view" hidden>
      <div class="d31-help-shell">
        <article class="d31-help-intro"><h2>Помощь по проекту</h2><p>Задайте вопрос обычным языком. Ответ будет найден в README, документации и исходниках проекта. Для вопросов о текущей Git-ветке помощник проверит Git через MCP и покажет источники.</p></article>
        <div class="d31-help-topics" aria-label="Популярные вопросы">
          <button type="button" class="d31-help-topic" data-question="Кратко опиши структуру проекта и назначение основных файлов.">Структура проекта</button>
          <button type="button" class="d31-help-topic" data-question="Как запустить приложение и локальную модель?">Как запустить</button>
          <button type="button" class="d31-help-topic" data-question="Где находится обработчик HTTP API и какие у него основные endpoints?">HTTP API</button>
          <button type="button" class="d31-help-topic" data-question="Какая сейчас Git-ветка?">Текущая Git-ветка</button>
        </div>
        <div id="d31HelpLog" aria-live="polite"><div class="d31-help-message assistant">Выберите тему или задайте свой вопрос о проекте.</div></div>
        <form id="d31HelpForm" class="d31-help-compose"><textarea id="d31HelpQuestion" rows="1" placeholder="Спросите о структуре, запуске, API или Git…" required></textarea><button id="d31HelpSend" type="submit">Спросить</button></form>
      </div>
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
      if(response.ok){{day30KeyBox.hidden=true;await loadDay30Status();await initApp();await loadProjectHelpHistory();}}else{{alert('Ключ доступа не подошёл. Скопируйте ключ из окна запуска сервера.');sessionStorage.removeItem('day30-api-key');}}
    }});
    const day30ChatTab=document.getElementById('day30ChatTab'), day30ServiceTab=document.getElementById('day30ServiceTab'), day31HelpTab=document.getElementById('day31HelpTab');
    function day30Show(view){{window.day30ActiveView=view;const tabs=[['chat',day30ChatTab,document.getElementById('chatView')],['help',day31HelpTab,document.getElementById('day31HelpView')],['service',day30ServiceTab,document.getElementById('day30View')]];for(const [name,tab,section] of tabs){{const active=view===name;section.hidden=!active;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));}}}}
    day30ChatTab.addEventListener('click',()=>day30Show('chat'));day30ServiceTab.addEventListener('click',()=>day30Show('service'));day31HelpTab.addEventListener('click',()=>day30Show('help'));
    function day30Escape(value){{return String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));}}
    const d31HelpView=document.getElementById('day31HelpView'),d31HelpForm=document.getElementById('d31HelpForm'),d31HelpQuestion=document.getElementById('d31HelpQuestion'),d31HelpLog=document.getElementById('d31HelpLog'),d31HelpSend=document.getElementById('d31HelpSend');
    function d31HelpScrollToLatest(){{d31HelpLog.scrollTo({{top:d31HelpLog.scrollHeight,behavior:'smooth'}});}}
    function d31HelpAddMessage(role,text,evidence=''){{const node=document.createElement('div');node.className=`d31-help-message ${{role}}`;if(role==='assistant')node.innerHTML=marked.parse(String(text));else node.textContent=text;if(evidence){{const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='Источники и цитаты';pre.textContent=evidence;details.append(summary,pre);node.append(details);}}d31HelpLog.append(node);d31HelpScrollToLatest();return node;}}
    function d31HelpAddLoader(){{const node=document.createElement('div');node.className='d31-help-message assistant loading';node.setAttribute('role','status');node.setAttribute('aria-live','polite');const spinner=document.createElement('span');spinner.className='d31-help-spinner';spinner.setAttribute('aria-hidden','true');const text=document.createElement('span');text.textContent='Ищу материалы проекта и готовлю ответ…';node.append(spinner,text);d31HelpLog.append(node);d31HelpScrollToLatest();return node;}}
    async function loadProjectHelpHistory(){{try{{const response=await fetch('/api/help/history');if(!response.ok)return;const data=await response.json();if(!Array.isArray(data.history)||!data.history.length)return;d31HelpLog.replaceChildren();data.history.forEach(item=>d31HelpAddMessage(item.role,item.content,item.role==='assistant'?item.rag_evidence||'':''));d31HelpLog.scrollTop=d31HelpLog.scrollHeight;}}catch(error){{console.warn('Не удалось загрузить историю помощи по проекту:',error);}}}}
    async function d31AskHelp(question){{const text=question.trim();if(!text||d31HelpSend.disabled)return;d31HelpAddMessage('user',text);const loading=d31HelpAddLoader();d31HelpSend.disabled=true;d31HelpQuestion.value='';try{{const response=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:`/help ${{text}}`}})}});const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||'Не удалось получить ответ');loading.remove();d31HelpAddMessage('assistant',data.content||'Ответ не получен.',data.rag_evidence||'');}}catch(error){{loading.classList.remove('loading');loading.replaceChildren();loading.textContent=`Не удалось получить ответ: ${{error.message}}`;}}finally{{d31HelpSend.disabled=false;d31HelpQuestion.focus();}}}}
    d31HelpForm.addEventListener('submit',event=>{{event.preventDefault();d31AskHelp(d31HelpQuestion.value);}});
    document.querySelectorAll('.d31-help-topic').forEach(button=>button.addEventListener('click',()=>d31AskHelp(button.dataset.question||'')));
    document.addEventListener('DOMContentLoaded',loadProjectHelpHistory);
    const SIDEBAR_INVARIANT_PRESETS={{
      'Архитектура':'Для Android-функций придерживаться Strict MVI и однонаправленного потока данных (UDF); сайд-эффекты отделять от состояния экрана.',
      'Стек проекта':'Для Android-кода использовать Kotlin, Jetpack Compose и Koin; не добавлять Java и устаревшие XML-разметки.',
      'Безопасность':'Не записывать и не передавать пароли, API-токены и приватные ключи в открытом виде.',
      'Ответы по базе знаний':'Для фактов об оранжерее Сова-17 опираться на найденные документы; если в них нет ответа, прямо сообщить об этом и не придумывать значения.'
    }};
    const sidebarConfig=async config=>{{const response=await fetch('/api/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(config)}});if(!response.ok)throw new Error('Не удалось сохранить настройку');}};
    function showSidebarControls(id,show){{const element=document.getElementById(id);if(element)element.style.display=show?'flex':'none';}}
    async function toggleRagMode(enabled){{showSidebarControls('ragControls',enabled);await sidebarConfig({{rag_mode_enabled:enabled}});}}
    async function toggleInvariants(enabled){{showSidebarControls('invariantControls',enabled);await sidebarConfig({{invariants_enabled:enabled}});if(enabled)refreshSidebarState();}}
    async function togglePlanningMode(enabled){{showSidebarControls('lifecycleControls',enabled);await sidebarConfig({{planning_mode_enabled:enabled}});}}
    async function addSelectedInvariant(){{const key=document.getElementById('invariantPresetSelect').value;if(!key||!SIDEBAR_INVARIANT_PRESETS[key])return;await fetch('/api/invariants/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key,value:SIDEBAR_INVARIANT_PRESETS[key]}})}});document.getElementById('invariantPresetSelect').value='';refreshSidebarState();}}
    async function addNewInvariant(){{const key=document.getElementById('newInvKey').value.trim(),value=document.getElementById('newInvVal').value.trim();if(!key||!value)return alert('Заполните название и текст инварианта');await fetch('/api/invariants/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key,value}})}});document.getElementById('newInvKey').value='';document.getElementById('newInvVal').value='';refreshSidebarState();}}
    async function deleteInv(key){{await fetch('/api/invariants/delete',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key}})}});refreshSidebarState();}}
    async function resetAllInvariants(){{await fetch('/api/invariants/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{}})}});refreshSidebarState();}}
    async function forceTransition(stage){{await fetch('/api/tsm/update',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{stage,step:'Ручное переключение',action:'Продолжение работы'}})}});refreshSidebarState();}}
    async function pinToLtmManual(){{const key=document.getElementById('manualLtmKey').value.trim(),value=document.getElementById('manualLtmVal').value.trim();if(!key||!value)return alert('Заполните название и значение факта');await fetch('/api/memory/pin_ltm',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key,value}})}});document.getElementById('manualLtmKey').value='';document.getElementById('manualLtmVal').value='';refreshSidebarState();}}
    async function refreshSidebarState(){{try{{const response=await fetch('/api/state');if(!response.ok)return;const state=await response.json(),config=state.config||{{}};
      for(const [id,key] of [['rag_mode_enabled','rag_mode_enabled'],['rag_query_rewrite_enabled','rag_query_rewrite_enabled'],['invariants_enabled','invariants_enabled'],['planning_mode_enabled','planning_mode_enabled']]){{const input=document.getElementById(id);if(input)input.checked=Boolean(config[key]);}}
      for(const [id,key,fallback] of [['ragTopKBefore','rag_top_k_before',10],['ragTopKAfter','rag_top_k_after',3],['ragSimilarityThreshold','rag_similarity_threshold',0.25]]){{const input=document.getElementById(id);if(input)input.value=config[key]??fallback;}}
      showSidebarControls('ragControls',Boolean(config.rag_mode_enabled));showSidebarControls('invariantControls',Boolean(config.invariants_enabled));showSidebarControls('lifecycleControls',Boolean(config.planning_mode_enabled));
      const select=document.getElementById('invariantPresetSelect');if(select&&select.options.length===1)Object.keys(SIDEBAR_INVARIANT_PRESETS).forEach(key=>{{const option=document.createElement('option');option.value=key;option.textContent=key;select.appendChild(option);}});
      const invList=document.getElementById('invList');if(invList){{invList.replaceChildren();const entries=Object.entries(state.invariants||{{}});if(!entries.length)invList.textContent='Пока ни одного инварианта не выбрано.';entries.forEach(([key,value])=>{{const row=document.createElement('div');row.className='invariant-item';const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Удалить '+key);remove.onclick=()=>deleteInv(key);const title=document.createElement('b');title.textContent=key;const text=document.createElement('div');text.textContent=value;row.append(remove,title,text);invList.append(row);}});}}
      const stage=state.tsm||{{}},stages=['none','planning','execution','validation','done'];stages.forEach(name=>{{const badge=document.getElementById('badge_'+name);if(badge)badge.classList.toggle('stage-active',stage.stage===name);}});
      document.getElementById('tsmStepText').textContent=stage.step||'—';document.getElementById('tsmActionText').textContent=stage.action||'—';const transitions=document.getElementById('transitionButtons');transitions.replaceChildren();(stage.allowed_next||[]).forEach(name=>{{const button=document.createElement('button');button.type='button';button.textContent=name.toUpperCase();button.onclick=()=>forceTransition(name);transitions.append(button);}});
      const profiles=document.getElementById('profileSelect');profiles.replaceChildren();(state.profiles_list||[]).forEach(name=>{{const option=document.createElement('option');option.value=name;option.textContent=name;option.selected=name===state.current_profile;profiles.append(option);}});const profile=state.current_profile_data||{{}};for(const [id,key] of [['profRole','role'],['profStyle','style'],['profFormat','format'],['profConstraints','constraints']])document.getElementById(id).textContent=profile[key]||'—';
      const renderMemory=(id,data,empty)=>{{const node=document.getElementById(id),entries=Object.entries(data||{{}});node.textContent=entries.length?entries.map(([key,value])=>key+': '+(typeof value==='string'?value:JSON.stringify(value))).join('\\n'):empty;}};renderMemory('ltmList',state.ltm,'Нет сохранённых фактов');renderMemory('wmList',state.wm,'Нет активных данных задачи');
      if(state.stats){{document.getElementById('statTotal').textContent=state.stats.total_tokens||0;document.getElementById('statCost').textContent='$'+Number(state.stats.cost||0).toFixed(6);}}
    }}catch(error){{console.warn('Не удалось обновить сайдбар:',error);}}}}
    async function switchProfile(name){{await fetch('/api/profile/switch',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name}})}});refreshSidebarState();}}
    function openEditorForUpdate(){{fetch('/api/state').then(response=>response.json()).then(state=>{{const profile=state.current_profile_data||{{}};document.getElementById('profileEditor').style.display='flex';document.getElementById('editorTitle').textContent='Редактировать профиль';document.getElementById('editProfName').value=state.current_profile||'';document.getElementById('editProfName').disabled=true;for(const [id,key] of [['editProfRole','role'],['editProfStyle','style'],['editProfFormat','format'],['editProfConstraints','constraints']])document.getElementById(id).value=profile[key]||'';}});}}
    function openEditorForCreate(){{document.getElementById('profileEditor').style.display='flex';document.getElementById('editorTitle').textContent='Создать профиль';document.getElementById('editProfName').value='';document.getElementById('editProfName').disabled=false;['editProfRole','editProfStyle','editProfFormat','editProfConstraints'].forEach(id=>document.getElementById(id).value='');}}
    function closeProfileEditor(){{document.getElementById('profileEditor').style.display='none';}}
    async function saveProfileManual(){{const name=document.getElementById('editProfName').value.trim();if(!name)return alert('Укажите название профиля');const data={{role:document.getElementById('editProfRole').value,style:document.getElementById('editProfStyle').value,format:document.getElementById('editProfFormat').value,constraints:document.getElementById('editProfConstraints').value}};await fetch('/api/profile/save',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,data}})}});closeProfileEditor();refreshSidebarState();}}
    document.getElementById('rag_mode_enabled').addEventListener('change',event=>toggleRagMode(event.target.checked));
    document.getElementById('invariants_enabled').addEventListener('change',event=>toggleInvariants(event.target.checked));
    document.getElementById('planning_mode_enabled').addEventListener('change',event=>togglePlanningMode(event.target.checked));
    document.getElementById('rag_query_rewrite_enabled').addEventListener('change',event=>sidebarConfig({{rag_query_rewrite_enabled:event.target.checked}}));
    ['ragTopKBefore','ragTopKAfter','ragSimilarityThreshold'].forEach(id=>document.getElementById(id).addEventListener('change',event=>{{const before=Number(document.getElementById('ragTopKBefore').value),after=Number(document.getElementById('ragTopKAfter').value);if(after>before)document.getElementById('ragTopKAfter').value=before;sidebarConfig({{rag_top_k_before:Number(document.getElementById('ragTopKBefore').value),rag_top_k_after:Number(document.getElementById('ragTopKAfter').value),rag_similarity_threshold:Number(document.getElementById('ragSimilarityThreshold').value)}});}}));
    document.getElementById('profileSelect').addEventListener('change',event=>switchProfile(event.target.value));
    document.addEventListener('DOMContentLoaded',refreshSidebarState);
    async function loadDay30Status(){{
      try{{const response=await fetch('/api/day30/status');if(!response.ok)throw new Error('Требуется ключ сервера');const data=await response.json();const model=data.model||{{}};const limits=data.limits||{{}};
        document.getElementById('day30Metrics').innerHTML=[
          ['Локальная модель',model.connected?model.model:'не подключена'],['Контекст модели',model.context_window?`${{model.context_window}} токенов`:'не определён'],['Индекс',`${{data.index.chunks}} фрагментов · локально`],
          ['Лимит частоты',`${{limits.requests}} запросов / ${{Math.round(limits.window_seconds/60)}} мин`],['Максимум вопроса',`${{limits.question_chars}} символов`],['История в запросе',`до ~${{limits.dialogue_context_approx_tokens}} токенов`]
        ].map(([a,b])=>`<div class="d30-metric"><small>${{day30Escape(a)}}</small><strong>${{day30Escape(b)}}</strong></div>`).join('');
        const urls=data.urls&&data.urls.length?data.urls:[location.origin];document.getElementById('day30Endpoint').textContent=`${{urls[0]}}/v1/chat/completions`;
        document.getElementById('day30Curl').textContent=`curl -X POST '${{urls[0]}}/v1/chat/completions' -H 'Content-Type: application/json' -H 'Authorization: Bearer YOUR_DAY30_KEY' -d '{{"messages":[{{"role":"user","content":"Сколько гряд в куполе Иней?"}}]}}'`;
        const status=model.connected?'Локальная Qwen подключена и доступна в списке моделей. HTTP API и проверка серии используют её напрямую.':'Запустите llama-server на порту 8080, чтобы использовать локальную Qwen. Модели OpenRouter доступны независимо.';
        document.getElementById('day30ServiceNote').textContent=status;document.getElementById('day30TopStatus').textContent=model.connected?'Локальная Qwen подключена':'Локальная Qwen не подключена';
      }}catch(error){{document.getElementById('day30ServiceNote').textContent=error.message;document.getElementById('day30TopStatus').textContent=error.message;}}
    }}
    document.getElementById('day30RunStability').addEventListener('click',async()=>{{
      const button=document.getElementById('day30RunStability'),out=document.getElementById('day30StabilityResult');const turns=document.getElementById('day30Turns').value.split(String.fromCharCode(10)).map(s=>s.trim()).filter(Boolean);
      button.disabled=true;button.textContent='Выполняю запросы по очереди…';out.textContent='Локальная модель отвечает на вопросы серии.';
      try{{const response=await fetch('/api/day30/stability',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{turns}})}});const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка серии');
        out.innerHTML=`<p class="d30-muted">Успешно: ${{data.successful}} из ${{data.total}} · общее время ${{data.elapsed}} с</p>`+(data.results||[]).map((item,i)=>`<div class="d30-result ${{item.ok?'ok':'fail'}}"><b>${{i+1}}. ${{day30Escape(item.question)}}</b><br>${{day30Escape(item.answer||item.error)}}${{item.rag_evidence?'<br><br>Источник и цитата:<br>'+day30Escape(item.rag_evidence):''}}</div>`).join('')+`<p class="d30-muted">${{day30Escape(data.note||'')}}</p>`;
      }}catch(error){{out.innerHTML=`<div class="d30-result fail">${{day30Escape(error.message)}}</div>`;}}finally{{button.disabled=false;button.textContent='Запустить проверку серии запросов';}}
    }});
    document.addEventListener('DOMContentLoaded',()=>{{if(!DAY30_KEY_REQUIRED||sessionStorage.getItem('day30-api-key')){{loadDay30Status();}}}});
    """
    return get_chat_page(
        title="AI Advent · чат и помощь по проекту",
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
            if path == "/api/day31/status":
                try:
                    kb = _project_kb()
                    git = _git_status_via_mcp()
                    self._send_json({"project_index": {"documents": kb.data["documents"], "chunks": kb.data["total_chunks"], "sources": kb.data["sources"]}, "mcp": {"connected": True, "tool": "git_status_check", "current_branch": git["current_branch"]}})
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 503)
                return
            if path == "/api/help/history":
                with _project_help_history_lock:
                    self._send_json({"history": _project_help_history})
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
        if path not in {"/api/chat", "/api/config", "/api/clear", "/api/help/clear", "/api/day30/stability", "/v1/chat/completions", "/api/invariants/add", "/api/invariants/delete", "/api/invariants/reset", "/api/profile/switch", "/api/profile/save", "/api/memory/pin_ltm", "/api/tsm/update"}:
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
                if message.strip().casefold() == "/help" or message.strip().casefold().startswith("/help "):
                    answer = _project_help(message)
                else:
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
                config = dict(data)
                with _lock:
                    _agent.set_config(config)
                self._send_json({"ok": True})
                return
            if path == "/api/clear":
                with _lock:
                    clear_all = bool(data.get("clear_all", False))
                    _agent.clear_history(clear_all=clear_all)
                    if clear_all:
                        with _project_help_history_lock:
                            _project_help_history.clear()
                            _save_project_help_history()
                        builtin_profiles = {"Android Developer", "Data Scientist", "Technical Writer"}
                        _agent.profiles = {name: profile for name, profile in _agent.profiles.items() if name in builtin_profiles}
                        _agent.current_profile = "Android Developer" if "Android Developer" in _agent.profiles else next(iter(_agent.profiles), "")
                        _agent.set_config({
                            "system_prompt": "Ты — полезный AI-ассистент.",
                            "model": SimpleAgent.MODEL_DEFAULT,
                            "model_supported_parameters": ["temperature", "top_p", "top_k"],
                            "temperature": 0.7,
                            "top_p": 1.0,
                            "top_k": 0,
                            "context_compression": True,
                            "planning_mode_enabled": False,
                            "rag_mode_enabled": True,
                            "rag_settings_visible": False,
                            "invariants_enabled": False,
                            "rag_query_rewrite_enabled": True,
                            "rag_top_k_before": 10,
                            "rag_top_k_after": 3,
                            "rag_similarity_threshold": 0.25,
                        })
                self._send_json({"ok": True})
                return
            if path == "/api/help/clear":
                with _project_help_history_lock:
                    _project_help_history.clear()
                    _save_project_help_history()
                self._send_json({"ok": True})
                return
            if path == "/api/invariants/add":
                with _lock:
                    _agent.pin_invariant(str(data.get("key", "")), str(data.get("value", "")))
                self._send_json({"ok": True})
                return
            if path == "/api/invariants/delete":
                with _lock:
                    _agent.delete_invariant(str(data.get("key", "")))
                self._send_json({"ok": True})
                return
            if path == "/api/invariants/reset":
                with _lock:
                    _agent.clear_invariants()
                self._send_json({"ok": True})
                return
            if path == "/api/profile/switch":
                with _lock:
                    _agent.switch_profile(str(data.get("name", "")))
                self._send_json({"ok": True})
                return
            if path == "/api/profile/save":
                with _lock:
                    _agent.save_profile_data(str(data.get("name", "")), data.get("data", {}) if isinstance(data.get("data"), dict) else {})
                self._send_json({"ok": True})
                return
            if path == "/api/memory/pin_ltm":
                with _lock:
                    _agent.pin_to_ltm(str(data.get("key", "")), str(data.get("value", "")))
                self._send_json({"ok": True})
                return
            if path == "/api/tsm/update":
                stage = str(data.get("stage", "none"))
                with _lock:
                    if stage not in _agent.TSM_ALLOWED_TRANSITIONS.get(_agent.tsm_stage, []):
                        raise ApiError(409, "Такой переход жизненного цикла сейчас недоступен.")
                    _agent.update_tsm_manually(stage, str(data.get("step", "")), str(data.get("action", "")))
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
                result = _chat(user_messages[-1]["content"], {"model": LOCAL_MODEL, "model_supported_parameters": ["temperature", "top_p", "top_k"], "rag_mode_enabled": True}, history=history, persist=False, system_prompt=system_prompt, generation=generation)
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
    # Day 29 loaded this file in its entry point. Day 30 imports its helpers,
    # so load the same project .env here before any OpenRouter request is made.
    _load_dotenv()
    index = _index_info()
    project_index = _project_kb().data
    server = Server((HOST, PORT), Handler)
    print(f"AI Advent: чат, HTTP API и помощь по проекту готовы: http://127.0.0.1:{PORT}/")
    print(f"Привязка сервера: {HOST}:{PORT}; лимит {RATE_LIMIT_REQUESTS} запросов/{RATE_LIMIT_WINDOW_SECONDS} с; вопрос до {MAX_QUESTION_CHARS} символов.")
    print(f"Локальный индекс: {index['chunks']} фрагментов; локальная модель ожидается на http://127.0.0.1:8080.")
    print(f"Индекс проекта для /help: {project_index['documents']} файлов, {project_index['total_chunks']} чанков; включает README, docs, API и исходники.")
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        print("Ключ OpenRouter не найден: облачные модели будут недоступны; локальная модель продолжит работать.")
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
        if _git_mcp is not None:
            _git_mcp.close()


if __name__ == "__main__":
    main()
