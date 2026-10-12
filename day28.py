#!/usr/bin/env python3
"""Совместимый запускатель основного чата для задания Дня 28."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from document_indexer import DocumentIndexer
from simple_agent import format_rag_evidence

ROOT = Path(__file__).resolve().parent
PORT = 8028
LOCAL_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
DEFAULT_LOCAL_MODEL = "Qwen/Qwen3-4B-GGUF:Q4_K_M"
MAX_BODY = 64_000
MAX_QUESTION = 6_000
PROMPT_TEMPLATE = (
    "Ты — помощник, отвечающий по внутренней базе документов. Отвечай по-русски. "
    "Используй только факты из предоставленных фрагментов, не додумывай. Если фрагменты не дают ответа, "
    "скажи: «Не знаю по найденным документам» и попроси уточнить вопрос. "
    "Для ключевых утверждений указывай chunk_id в квадратных скобках. Дай завершённый ответ сразу."
)


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


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None, timeout: float = 180) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if data is not None else "GET",
    )
    # Local model traffic must not be routed through a system proxy.
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
        _http_json(f"{LOCAL_BASE_URL}/health", timeout=3)
        models = _http_json(f"{LOCAL_BASE_URL}/v1/models", timeout=5).get("data", [])
        if not models:
            return {"connected": False, "error": "llama.cpp доступен, но модель не найдена."}
        return {"connected": True, "model": models[0].get("id", DEFAULT_LOCAL_MODEL)}
    except Exception as exc:
        return {"connected": False, "error": f"Не удалось подключиться к llama.cpp на {LOCAL_BASE_URL}: {exc}"}


def _index_info() -> dict:
    chunks = DocumentIndexer()._load_chunks()
    return {
        "file": "document_index.json",
        "documents": len({str(chunk.get("source", "")) for chunk in chunks if chunk.get("source")}),
        "chunks": len(chunks),
        "retrieval": "локальный лексический поиск по совпадению слов; без эмбеддингов",
    }


def _local_answer(question: str, context: str) -> dict:
    status = _local_status()
    if not status.get("connected"):
        raise RuntimeError(status.get("error", "Локальная модель недоступна."))
    payload = {
        "model": status["model"],
        "messages": [
            {"role": "system", "content": PROMPT_TEMPLATE + "\n\nФРАГМЕНТЫ БАЗЫ:\n" + context},
            {"role": "user", "content": question},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.monotonic()
    response = _http_json(f"{LOCAL_BASE_URL}/v1/chat/completions", payload, timeout=240)
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Локальная модель вернула пустой ответ.")
    choice = choices[0]
    answer = str(choice.get("message", {}).get("content", ""))
    answer = re.sub(r"<think>.*?(?:</think>|$)", "", answer, flags=re.DOTALL).strip()
    if not answer:
        raise RuntimeError("Локальная модель не вернула текст ответа.")
    return {
        "answer": answer,
        "model": response.get("model", status["model"]),
        "elapsed": round(time.monotonic() - started, 2),
        "usage": response.get("usage", {}),
        "ok": True,
    }


def _cloud_answer(question: str, context: str, model: str) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Не найден OPENROUTER_API_KEY в .env; облачное сравнение отключено.")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT_TEMPLATE + "\n\nФРАГМЕНТЫ БАЗЫ:\n" + context},
            {"role": "user", "content": question},
        ],
        "temperature": 0.2,
        "max_tokens": 1000,
    }
    started = time.monotonic()
    response = _http_json(
        "https://openrouter.ai/api/v1/chat/completions",
        payload,
        {"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost", "X-Title": "AI Advent Day 28"},
        timeout=180,
    )
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Облачная модель вернула пустой ответ.")
    answer = str(choices[0].get("message", {}).get("content", "")).strip()
    if not answer:
        raise RuntimeError("Облачная модель не вернула текст ответа.")
    return {
        "answer": answer,
        "model": response.get("model", model),
        "elapsed": round(time.monotonic() - started, 2),
        "usage": response.get("usage", {}),
        "ok": True,
    }


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().replace("ё", "е").split())


def _evaluate(answer: str, chunks: list[dict], criteria: list[dict], expected_sources: list[str]) -> dict:
    normalized_answer = _normalize(answer)
    quote_text = _normalize(" ".join(chunk.get("text", "") for chunk in chunks))
    criteria = criteria if isinstance(criteria, list) else []
    expected_sources = expected_sources if isinstance(expected_sources, list) else []
    matched = []
    missing = []
    supported = []
    unsupported = []
    for criterion in criteria:
        terms = criterion.get("any_terms", [])
        label = criterion.get("label", "Факт")
        answer_hit = any(_normalize(term) in normalized_answer for term in terms)
        evidence_hit = any(_normalize(term) in quote_text for term in terms)
        if answer_hit:
            matched.append(label)
            (supported if evidence_hit else unsupported).append(label)
        else:
            missing.append(label)
    sources = {str(chunk.get("source", "")) for chunk in chunks}
    expected_found = [source for source in expected_sources if source in sources]
    return {
        "matched": matched,
        "missing": missing,
        "supported": supported,
        "unsupported": unsupported,
        "score": f"{len(matched)}/{len(criteria)}" if criteria else "не задано",
        "expected_sources_found": expected_found,
        "expected_sources_missing": [source for source in expected_sources if source not in sources],
    }


def _run_model(mode: str, question: str, context: str, cloud_model: str) -> dict:
    try:
        if mode == "local":
            return _local_answer(question, context)
        return _cloud_answer(question, context, cloud_model)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed": None, "answer": ""}


def run_comparison(data: dict) -> dict:
    question = str(data.get("question", "")).strip()
    if not question:
        raise ValueError("Введите вопрос.")
    if len(question) > MAX_QUESTION:
        raise ValueError(f"Сократите вопрос до {MAX_QUESTION} символов.")
    top_k_before = max(1, min(int(data.get("top_k_before", 10)), 50))
    top_k_after = max(1, min(int(data.get("top_k_after", 3)), top_k_before))
    threshold = max(0.0, min(float(data.get("similarity_threshold", 0.25)), 1.0))
    rewrite = bool(data.get("query_rewrite_enabled", True))
    repeats = max(1, min(int(data.get("repeats", 1)), 3))
    cloud_enabled = bool(data.get("cloud_enabled", False))
    cloud_model = str(data.get("cloud_model", "openrouter/free")).strip()[:160] or "openrouter/free"

    retrieval_started = time.monotonic()
    retrieval = DocumentIndexer().compare_retrieval(
        question,
        source_prefix="docs/",
        top_k_before=top_k_before,
        top_k_after=top_k_after,
        similarity_threshold=threshold,
        query_rewrite_enabled=rewrite,
    )
    retrieval_elapsed = round(time.monotonic() - retrieval_started, 4)
    chunks = retrieval["filtered_results"]
    evidence = format_rag_evidence(chunks)
    context = "\n\n".join(
        f"Источник: {chunk.get('source')}\nРаздел: {chunk.get('section')}\n"
        f"chunk_id: {chunk.get('chunk_id')}\nФрагмент:\n{chunk.get('text', '')}"
        for chunk in chunks
    )
    if not chunks:
        no_context = "Не знаю по найденным документам: релевантных фрагментов выше порога не найдено. Уточните вопрос или проверьте базу знаний."
        empty_eval = _evaluate(no_context, [], data.get("criteria", []), data.get("expected_sources", []))
        return {
            "question": question,
            "expected": str(data.get("expected", "")),
            "expected_sources": data.get("expected_sources", []),
            "retrieval": {
                "elapsed": retrieval_elapsed,
                "original_query": question,
                "rewritten_query": retrieval["rewritten_query"],
                "query_rewrite_enabled": rewrite,
                "top_k_before": top_k_before,
                "top_k_after": top_k_after,
                "similarity_threshold": threshold,
                "candidate_count": len(retrieval["candidates_before_filter"]),
                "passed_threshold_count": retrieval["passed_threshold_count"],
                "dropped_by_threshold_count": retrieval["dropped_by_threshold_count"],
                "chunks": [],
                "evidence": "По заданному порогу подходящие фрагменты не найдены.",
            },
            "local": {"no_context": True, "message": no_context, "model": _local_status().get("model", DEFAULT_LOCAL_MODEL)},
            "cloud": {"no_context": True, "message": no_context, "model": cloud_model} if cloud_enabled else None,
            "repeats": 1,
            "index_info": _index_info(),
        }

    modes = ["local"] + (["cloud"] if cloud_enabled else [])
    results = {mode: [] for mode in modes}
    # Keep inference sequential: the local 4B model has limited shared memory,
    # and simultaneous calls make the speed comparison less representative.
    for mode in modes:
        for _ in range(repeats):
            item = _run_model(mode, question, context, cloud_model)
            if item.get("ok"):
                item["evaluation"] = _evaluate(item["answer"], chunks, data.get("criteria", []), data.get("expected_sources", []))
            results[mode].append(item)

    def summarize_attempts(attempts: list[dict]) -> dict:
        ok = [item for item in attempts if item.get("ok")]
        scores = [item.get("evaluation", {}).get("score") for item in ok]
        scored = [score for score in scores if score and score != "не задано"]
        return {
            "success_count": len(ok),
            "attempt_count": len(attempts),
            "success_rate": f"{len(ok)}/{len(attempts)}",
            "scores": scores,
            "stable_score": len(set(scored)) <= 1 if scored else None,
            "same_answer": len({_normalize(item.get("answer")) for item in ok}) <= 1 if ok else False,
            "elapsed_total": round(sum(item.get("elapsed") or 0 for item in ok), 2),
        }

    retrieval_result = {
        "elapsed": retrieval_elapsed,
        "original_query": question,
        "rewritten_query": retrieval["rewritten_query"],
        "query_rewrite_enabled": rewrite,
        "top_k_before": top_k_before,
        "top_k_after": top_k_after,
        "similarity_threshold": threshold,
        "candidate_count": len(retrieval["candidates_before_filter"]),
        "passed_threshold_count": retrieval["passed_threshold_count"],
        "dropped_by_threshold_count": retrieval["dropped_by_threshold_count"],
        "chunks": [{
            "source": chunk.get("source"),
            "section": chunk.get("section"),
            "chunk_id": chunk.get("chunk_id"),
            "similarity": chunk.get("similarity"),
            "text": chunk.get("text", ""),
        } for chunk in chunks],
        "evidence": evidence,
    }
    response = {
        "question": question,
        "expected": str(data.get("expected", "")),
        "expected_sources": data.get("expected_sources", []),
        "retrieval": retrieval_result,
        "repeats": repeats,
        "local": {"attempts": results["local"], "stability": summarize_attempts(results["local"]), "model": _local_status().get("model", DEFAULT_LOCAL_MODEL)},
        "cloud": {"attempts": results["cloud"], "stability": summarize_attempts(results["cloud"]), "model": cloud_model} if cloud_enabled else None,
        "index_info": _index_info(),
    }
    return response


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/day28/status":
            local = _local_status()
            self._send_json({"local": local, "cloud_available": bool(os.environ.get("OPENROUTER_API_KEY")), "index": _index_info()})
            return
        if path == "/api/day28/questions":
            try:
                suite = json.loads((ROOT / "rag_evaluation_questions.json").read_text(encoding="utf-8"))
                self._send_json({"questions": suite.get("questions", [])})
            except Exception as exc:
                self._send_json({"error": f"Не удалось загрузить контрольные вопросы: {exc}"}, 500)
            return
        if path in ("", "/day28"):
            try:
                html = (ROOT / "day28_ui.html").read_text(encoding="utf-8")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError as exc:
                self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path.rstrip("/") != "/api/day28/compare":
            self._send_json({"error": "Not found"}, 404)
            return
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self._send_json({"error": "Откройте страницу День 28 в этом же приложении."}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("Запрос пустой или слишком большой.")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Не удалось прочитать параметры запроса.")
            self._send_json(run_comparison(data))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": f"Не удалось выполнить RAG-сравнение: {exc}"}, 500)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[Day 28] {self.address_string()} - {fmt % args}")


def main() -> None:
    # Keep the established chat and sidebar as the primary app entry point.
    # Day 28 local/cloud comparison is integrated in the existing comparison tab.
    from day25 import main as run_main_chat

    run_main_chat()


if __name__ == "__main__":
    main()
