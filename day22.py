#!/usr/bin/env python3
"""День 22: Первый RAG-запрос (Сравнение режимов с RAG и без RAG + 10 контрольных вопросов)
   Полная интеграция RAG-пайплайна, переключатель режимов RAG ON/OFF,
   сохранение 100% сайдбара прошлых дней.
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
import copy
import uuid
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from simple_agent import SimpleAgent
from chat_ui import get_chat_page
from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent
PORT = 8001
_LOCK = threading.Lock()
_EVALUATION_LOCK = threading.Lock()
_EVALUATIONS = {}


def _normalize_for_check(text: str) -> str:
    return " ".join((text or "").casefold().replace("ё", "е").split())


def _score_answer(answer: str, criteria: list) -> dict:
    normalized = _normalize_for_check(answer)
    passed = []
    missing = []
    for criterion in criteria:
        terms = criterion.get("any_terms", [])
        (passed if any(_normalize_for_check(term) in normalized for term in terms) else missing).append(
            criterion.get("label", "Критерий")
        )
    total = len(criteria)
    return {
        "passed": len(passed),
        "total": total,
        "percent": round(len(passed) * 100 / total) if total else None,
        "matched": passed,
        "missing": missing,
    }


def _answer_text(result) -> str:
    if not isinstance(result, dict):
        return str(result)
    if result.get("error"):
        return f"Ошибка модели: {result['error']}"
    return result.get("content") or "Модель не вернула текстовый ответ."


def _comparison_agent(base_agent: SimpleAgent, rag_enabled: bool) -> SimpleAgent:
    """Prepare an isolated agent that answers directly from the supplied mode."""
    trial_agent = copy.deepcopy(base_agent)
    trial_agent.rag_mode_enabled = rag_enabled
    trial_agent.planning_mode_enabled = False
    trial_agent.system_prompt = (
        f"{base_agent.system_prompt}\n\n"
        "Для этого сравнения сразу дай законченный ответ на вопрос пользователя. "
        "Не описывай поиск, не обещай выполнить его позже и не проси подождать. "
        "Если приложены фрагменты документов, используй их. Если нужных сведений нет, "
        "скажи об этом прямо и не выдумывай факты. Отвечай по-русски."
    )
    return trial_agent


def _update_evaluation(job_id: str, **changes) -> None:
    with _EVALUATION_LOCK:
        job = _EVALUATIONS.get(job_id)
        if job is not None:
            job.update(changes)


def _run_rag_evaluation(job_id: str, questions: list, base_agent: SimpleAgent) -> None:
    try:
        from document_indexer import DocumentIndexer

        indexer = DocumentIndexer(ROOT)
        results = []
        total = len(questions)
        for index, question_data in enumerate(questions, 1):
            question = question_data["question"]
            criteria = question_data.get("evaluation_criteria", [])
            expected_sources = question_data.get("source_files", [])
            try:
                matches = indexer.search(question, strategy="all", source_prefix="docs/")
                retrieved_sources = list(dict.fromkeys(m.get("source", "") for m in matches[:3] if m.get("source")))
                retrieval_error = None
            except Exception as exc:
                matches = []
                retrieved_sources = []
                retrieval_error = str(exc)

            pair = {"id": question_data.get("id", f"q{index}"), "question": question}
            for mode, rag_enabled in (("without_rag", False), ("with_rag", True)):
                # Each answer gets a pristine conversation and a copy of the
                # current agent configuration; evaluation must not pollute chat.
                trial_agent = _comparison_agent(base_agent, rag_enabled)
                try:
                    result = trial_agent.chat(
                        question,
                        mcp_clients=[],
                        history=[],
                        persist_state=False,
                        rag_source_prefix="docs/",
                    )
                    answer = _answer_text(result)
                except Exception as exc:
                    answer = f"Ошибка модели: {exc}"
                pair[mode] = {
                    "answer": answer,
                    "score": _score_answer(answer, criteria),
                }

            found_sources = [source for source in expected_sources if source in retrieved_sources]
            pair.update({
                "expected": question_data.get("expected_expectation", ""),
                "expected_sources": expected_sources,
                "retrieved_sources": retrieved_sources,
                "matched_sources": found_sources,
                "retrieval_error": retrieval_error,
            })
            results.append(pair)
            _update_evaluation(job_id, completed=index, results=results.copy())

        rag_passed = sum(r["with_rag"]["score"]["passed"] for r in results)
        rag_total = sum(r["with_rag"]["score"]["total"] for r in results)
        no_rag_passed = sum(r["without_rag"]["score"]["passed"] for r in results)
        no_rag_total = sum(r["without_rag"]["score"]["total"] for r in results)
        report = [
            "ОТЧЁТ: СРАВНЕНИЕ RAG ON / OFF",
            f"Вопросов обработано: {len(results)} из {total}",
            "Оценка — доля совпавших контрольных признаков из evaluation_criteria; это ориентир по ключевым понятиям, не семантический судья.",
            f"Без RAG: {no_rag_passed}/{no_rag_total} признаков ({round(no_rag_passed * 100 / no_rag_total) if no_rag_total else 0}%).",
            f"С RAG: {rag_passed}/{rag_total} признаков ({round(rag_passed * 100 / rag_total) if rag_total else 0}%).",
            "",
        ]
        for index, item in enumerate(results, 1):
            off = item["without_rag"]
            on = item["with_rag"]
            report.extend([
                f"Вопрос {index}: {item['question']}",
                f"Ожидание: {item['expected']}",
                f"Ожидаемые источники: {', '.join(item['expected_sources']) or 'не заданы'}",
                f"Источники, найденные RAG: {', '.join(item['retrieved_sources']) or 'не найдены'}",
                f"Совпадение источника: {len(item['matched_sources'])}/{len(item['expected_sources'])}",
                f"Без RAG — признаки: {off['score']['passed']}/{off['score']['total']} ({off['score']['percent'] if off['score']['percent'] is not None else 0}%)",
                f"Без RAG — не найдены: {', '.join(off['score']['missing']) or 'все признаки найдены'}",
                f"Ответ без RAG: {off['answer']}",
                f"С RAG — признаки: {on['score']['passed']}/{on['score']['total']} ({on['score']['percent'] if on['score']['percent'] is not None else 0}%)",
                f"С RAG — не найдены: {', '.join(on['score']['missing']) or 'все признаки найдены'}",
                f"Ответ с RAG: {on['answer']}",
                "",
            ])
        _update_evaluation(job_id, status="complete", report="\n".join(report), results=results.copy())
    except Exception as exc:
        _update_evaluation(job_id, status="failed", error=str(exc))


def _run_rag_comparison(
    job_id: str,
    question: str,
    expected: str,
    expected_sources: list,
    base_agent: SimpleAgent,
) -> None:
    try:
        from document_indexer import DocumentIndexer

        matches = DocumentIndexer(ROOT).search(question, strategy="all", source_prefix="docs/")[:3]
        retrieved_sources = list(dict.fromkeys(m.get("source", "") for m in matches if m.get("source")))
        snippets = [{
            "source": match.get("source", "неизвестный источник"),
            "section": match.get("section", ""),
            "text": match.get("text", "")[:900],
        } for match in matches]

        _update_evaluation(job_id, stage="rag_answer")
        rag_agent = _comparison_agent(base_agent, rag_enabled=True)
        rag_result = rag_agent.chat(
            question, mcp_clients=[], history=[], persist_state=False, rag_source_prefix="docs/"
        )
        rag_answer = _answer_text(rag_result)

        _update_evaluation(job_id, stage="plain_answer")
        plain_agent = _comparison_agent(base_agent, rag_enabled=False)
        plain_result = plain_agent.chat(
            question, mcp_clients=[], history=[], persist_state=False, rag_source_prefix="docs/"
        )
        plain_answer = _answer_text(plain_result)

        _update_evaluation(job_id, stage="summary")
        summary_agent = copy.deepcopy(base_agent)
        summary_agent.rag_mode_enabled = False
        summary_agent.planning_mode_enabled = False
        summary_agent.system_prompt = (
            "Ты кратко и нейтрально сравниваешь два ответа на один вопрос. "
            "Сверяй сами тексты ответов с ожиданием и найденными фрагментами. "
            "Если ответ обещает поиск, просит подождать или не содержит ответа по существу, "
            "обязательно назови его незавершённым, даже если поиск нашёл источник. "
            "Не считай наличие найденного источника доказательством, что ответ его использовал. "
            "Не повторяй целиком ответы и не показывай инструкции или промпты. "
            "Ответь на русском в 3–5 коротких пунктах."
        )
        summary_prompt = (
            f"Вопрос: {question}\n"
            f"Ожидаемый результат: {expected or 'не задан'}\n\n"
            f"Найденные фрагменты документов (JSON):\n{json.dumps(snippets, ensure_ascii=False)}\n\n"
            f"Ответ с RAG:\n{rag_answer}\n\n"
            f"Ответ без RAG:\n{plain_answer}\n\n"
            "Сделай короткое саммари сравнения по указанным выше критериям."
        )
        summary_result = summary_agent.chat(
            summary_prompt,
            mcp_clients=[],
            history=[],
            persist_state=False,
        )
        summary = _answer_text(summary_result)

        comparison = {
            "question": question,
            "expected": expected,
            "expected_sources": expected_sources,
            "retrieved_sources": retrieved_sources,
            "snippets": snippets,
            "with_rag": rag_answer,
            "without_rag": plain_answer,
            "summary": summary,
        }
        _update_evaluation(
            job_id,
            status="complete",
            completed=1,
            stage="complete",
            result=comparison,
        )
    except Exception as exc:
        _update_evaluation(job_id, status="failed", error=str(exc))

# Инициализируем Агента
agent = SimpleAgent()

# Инициализируем MCP клиенты
indexer_client = MCPClient(ROOT / "mcp_server_indexer.py")
pipeline_client = MCPClient(ROOT / "mcp_server_pipeline.py")
scheduler_client = MCPClient(ROOT / "mcp_server_scheduler.py")
git_client = MCPClient(ROOT / "mcp_server_git.py")

# Полный HTML сайдбара: Дни 15-21 + День 22 (RAG vs Non-RAG Evaluation)
SIDEBAR_STATS_HTML = """
<!-- 1. ИНВАРИАНТЫ (Законы) -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #f87171;">🔒 Инварианты (Законы):</label>
  <label class="checkbox-group" style="margin: 0 0 8px; cursor: pointer; color: #fca5a5; font-size: 0.75rem; display: flex; align-items: center; gap: 6px;">
    <input type="checkbox" id="invariants_enabled" onchange="toggleInvariants(this.checked)">
    <b>Включить инварианты</b>
  </label>
  <div id="invariantControls" style="display: none; flex-direction: column; gap: 7px;">
    <select id="invariantPresetSelect" class="input-field" style="font-size: 0.75rem;">
      <option value="">Выберите готовый инвариант…</option>
    </select>
    <button type="button" onclick="addSelectedInvariant()" style="padding: 5px; font-size: 0.75rem; background: rgba(239,68,68,.2); border: 1px solid rgba(239,68,68,.45); border-radius: 5px; color: #fecaca; cursor: pointer;">Добавить выбранный</button>
    <div id="invList" style="font-size: 0.7rem; color: var(--text-dim); background: rgba(239, 68, 68, 0.05); padding: 8px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.2); max-height: 150px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;"></div>
    <button type="button" onclick="resetAllInvariants()" style="padding: 5px; font-size: 0.72rem; background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.4); border-radius: 5px; color: #fca5a5; cursor: pointer;">Сбросить все выбранные</button>
    <details style="padding: 7px; background: rgba(0,0,0,.18); border: 1px dashed var(--border); border-radius: 6px;">
      <summary style="cursor: pointer; color: var(--text-dim); font-size: .7rem;">Добавить свой инвариант</summary>
      <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 7px;">
        <input type="text" id="newInvKey" placeholder="Название" class="input-field" style="font-size: 0.75rem; padding: 4px; height: auto;">
        <textarea id="newInvVal" placeholder="Текст правила…" class="input-field" style="font-size: 0.75rem; padding: 4px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;"></textarea>
        <button onclick="addNewInvariant()" style="padding: 4px; font-size: 0.75rem; background: #ef4444; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">Добавить свой</button>
      </div>
    </details>
  </div>
</div>

<!-- 2. ЖИЗНЕННЫЙ ЦИКЛ (TSM) -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #60a5fa;">🛤 Жизненный цикл (TSM):</label>
  <div style="margin-bottom: 8px; background: rgba(96, 165, 250, 0.1); padding: 6px 8px; border-radius: 6px; border: 1px solid rgba(96, 165, 250, 0.2);">
    <label class="checkbox-group" style="margin: 0; cursor: pointer; color: #93c5fd; font-size: 0.75rem; display: flex; align-items: center; gap: 6px;">
      <input type="checkbox" id="planning_mode_enabled" checked onchange="togglePlanningMode(this.checked)">
      <b>Включить режим планирования (TSM)</b>
    </label>
  </div>
  <div style="display: flex; flex-direction: column; gap: 5px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px; border: 1px solid var(--border);">
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span id="badge_none" class="stage-badge">NONE</span>
      <span class="stage-arrow">➔</span>
      <span id="badge_planning" class="stage-badge">PLAN</span>
      <span class="stage-arrow">➔</span>
      <span id="badge_execution" class="stage-badge">EXEC</span>
      <span class="stage-arrow">➔</span>
      <span id="badge_validation" class="stage-badge">VALID</span>
      <span class="stage-arrow">➔</span>
      <span id="badge_done" class="stage-badge">DONE</span>
    </div>
    <div style="margin-top: 8px; font-size: 0.75rem; color: var(--text-dim); line-height: 1.4;">
      <b style="color: var(--accent);">Шаг:</b> <span id="tsmStepText"></span><br>
      <b style="color: var(--accent);">Действие:</b> <span id="tsmActionText"></span>
    </div>
  </div>
  <div style="display: flex; flex-direction: column; gap: 6px; margin-top: 10px; background: rgba(0,0,0,0.1); padding: 8px; border-radius: 6px; border: 1px dashed var(--border);">
    <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: bold; text-transform: uppercase;">Переход в состояние:</span>
    <div id="transitionButtons" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px;"></div>
  </div>
</div>

<!-- 3. ПЕРСОНАЛИЗАЦИЯ И ПРОФИЛИ -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem; color: #a855f7;">🎭 Персонализация и Профили:</label>
  <select id="profileSelect" class="input-field" style="font-size: 0.8rem; margin-bottom: 8px;"></select>
  <div id="profileDetailsBlock" style="background: rgba(255,255,255,0.03); border: 1px solid var(--border); padding: 8px; border-radius: 6px; font-size: 0.75rem; display: flex; flex-direction: column; gap: 4px;">
    <div><b style="color: var(--accent);">Роль:</b> <span id="profRole" style="color: var(--text-main);"></span></div>
    <div><b style="color: var(--accent);">Стиль:</b> <span id="profStyle" style="color: var(--text-dim);"></span></div>
    <div><b style="color: var(--accent);">Формат:</b> <span id="profFormat" style="color: var(--text-dim);"></span></div>
    <div><b style="color: var(--accent);">Ограничения:</b> <span id="profConstraints" style="color: #f87171;"></span></div>
    <div style="display: flex; gap: 5px; margin-top: 5px;">
      <button onclick="openEditorForUpdate()" style="flex: 1; padding: 4px; font-size: 0.7rem; background: var(--border); border: none; border-radius: 4px; color: white; cursor: pointer;">✎ Редактировать</button>
      <button onclick="openEditorForCreate()" style="flex: 1; padding: 4px; font-size: 0.7rem; background: rgba(99, 102, 241, 0.2); border: 1px solid var(--primary); border-radius: 4px; color: var(--text-main); cursor: pointer;">➕ Создать профиль</button>
    </div>
  </div>
  <div id="profileEditor" style="display: none; flex-direction: column; gap: 6px; margin-top: 8px; background: rgba(0,0,0,0.25); padding: 10px; border-radius: 6px; border: 1px dashed var(--accent);">
    <span id="editorTitle" style="font-size: 0.75rem; font-weight: bold; color: var(--accent); margin-bottom: 2px;">Редактор профиля:</span>
    <input type="text" id="editProfName" class="input-field" style="font-size: 0.75rem; padding: 4px 6px; height: auto;" placeholder="Имя профиля">
    <textarea id="editProfRole" class="input-field" style="font-size: 0.75rem; padding: 4px 6px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;" placeholder="Роль"></textarea>
    <textarea id="editProfStyle" class="input-field" style="font-size: 0.75rem; padding: 4px 6px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;" placeholder="Стиль"></textarea>
    <textarea id="editProfFormat" class="input-field" style="font-size: 0.75rem; padding: 4px 6px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;" placeholder="Формат"></textarea>
    <textarea id="editProfConstraints" class="input-field" style="font-size: 0.75rem; padding: 4px 6px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;" placeholder="Ограничения"></textarea>
    <div style="display: flex; gap: 5px; margin-top: 5px;">
      <button onclick="saveProfileManual()" style="flex: 1; padding: 5px; font-size: 0.75rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">Сохранить</button>
      <button onclick="closeProfileEditor()" style="padding: 5px; font-size: 0.75rem; background: var(--bg-dark); border: 1px solid var(--border); border-radius: 4px; color: white; cursor: pointer;">Отмена</button>
    </div>
  </div>
</div>

<!-- 4. LONG-TERM MEMORY (LTM) -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem; color: #4ade80;">🧠 Long-Term Memory (LTM):</label>
  <div id="ltmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 100px; overflow-y: auto; margin-bottom: 8px;">
    Нет долговременных фактов
  </div>
  <div style="display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.2); padding: 6px; border-radius: 4px;">
    <input type="text" id="manualLtmKey" placeholder="Ключ памяти" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <input type="text" id="manualLtmVal" placeholder="Значение" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <button onclick="pinToLtmManual()" style="padding: 4px; font-size: 0.75rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer;">Зафиксировать в LTM</button>
  </div>
</div>

<!-- 5. WORKING MEMORY (WM) -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem; color: #fbbf24;">🛠 Working Memory (WM):</label>
  <div id="wmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 100px; overflow-y: auto;">
    Нет активных данных задачи
  </div>
</div>

<!-- RAG setting remains in the sidebar; comparison controls live in their own view. -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #f43f5e;">🔬 RAG:</label>
  <label class="checkbox-group" style="margin: 0; cursor: pointer; color: #fda4af; font-size: 0.75rem; display: flex; align-items: center; gap: 6px;">
    <input type="checkbox" id="rag_mode_enabled" checked onchange="toggleRagMode(this.checked)">
    <b>Добавлять найденный контекст в обычный чат</b>
  </label>
</div>

<!-- TOKEN STATS -->
<div class="token-stats" style="margin-top: 20px; border-top: 1px solid var(--border); padding-top: 15px;">
  <div class="token-row">
    <span>Всего токенов (session):</span>
    <span id="statTotal" class="token-val">0</span>
  </div>
  <div class="token-row">
    <span>Цена:</span>
    <span id="statCost" class="token-val" style="color: #4ade80;">$0.000000</span>
  </div>
</div>

<div style="margin-top: 15px; display: flex; flex-direction: column; gap: 8px;">
  <button onclick="clearChat()" style="width: 100%; padding: 8px; background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.8rem; transition: background 0.2s;">🧹 Очистить историю чата</button>
  <button onclick="resetAllData()" style="width: 100%; padding: 8px; background: #ef4444; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.8rem; transition: background 0.2s;">🚨 Сбросить все данные памяти</button>
</div>

<style>
  .sidebar > div[style*="margin-top: auto"] { display: none !important; }
  .stage-badge { font-size: 0.55rem; padding: 2px 4px; border-radius: 4px; background: var(--bg-dark); color: var(--text-dim); border: 1px solid transparent; }
  .stage-badge.active { background: #3b82f6; color: white; font-weight: bold; border-color: #60a5fa; box-shadow: 0 0 8px rgba(59,130,246,0.5); }
  .stage-arrow { color: var(--border); font-size: 0.6rem; }
  .btn-transition { padding: 4px; font-size: 0.65rem; border-radius: 4px; border: 1px solid var(--border); color: white; cursor: pointer; text-align: center; }
  .btn-transition.allowed { background: rgba(59, 130, 246, 0.2); border-color: #3b82f6; color: #93c5fd; }
  .btn-transition.allowed:hover { background: rgba(59, 130, 246, 0.4); }
  .btn-transition.blocked { background: rgba(255,255,255,0.05); color: var(--text-dim); cursor: not-allowed; opacity: 0.5; }
  .invariant-item { padding: 6px; background: rgba(0,0,0,0.2); border-radius: 4px; border-left: 3px solid #ef4444; position: relative; margin-bottom: 4px; }
  .del-inv { position: absolute; top: 2px; right: 5px; color: #ef4444; cursor: pointer; font-weight: bold; font-size: 0.8rem; }
</style>
"""

COMPARISON_VIEW_HTML = """
<nav class="main-tabs" aria-label="Режимы приложения">
  <button id="chatTab" class="main-tab" type="button" onclick="showAppView('chat')">Чат</button>
  <button id="comparisonTab" class="main-tab active" type="button" onclick="showAppView('comparison')">Сравнение</button>
</nav>
<section id="comparisonView" aria-labelledby="comparisonTitle">
  <div class="compare-page">
    <header class="compare-header">
      <div>
        <h1 id="comparisonTitle">Сравнение ответов</h1>
        <p>Один вопрос отправляется модели в двух режимах. Настройки модели и параметры берутся из сайдбара.</p>
      </div>
      <button id="runBenchmarkBtn" class="benchmark-btn" type="button" onclick="runRagEvaluation(this)">Запустить все 10 вопросов</button>
    </header>

    <section class="compare-panel">
      <div class="panel-heading">
        <div><h2>Выберите контрольный вопрос</h2><p>Нажатие сразу запускает сравнение; ожидаемый результат будет показан в отчёте.</p></div>
        <span id="questionCount" class="subtle-label"></span>
      </div>
      <div id="questionBank" class="question-bank"><div class="empty-state">Загружаю вопросы…</div></div>
    </section>

    <details class="compare-panel custom-question-panel">
      <summary>Добавить свой вопрос и ожидание</summary>
      <div class="custom-question-form">
        <label for="customQuestion">Вопрос</label>
        <textarea id="customQuestion" rows="2" placeholder="Например: Сколько воды расходуется за один цикл полива?"></textarea>
        <label for="customExpected">Ожидаемый результат</label>
        <textarea id="customExpected" rows="2" placeholder="Какие факты должны попасть в правильный ответ?"></textarea>
        <button type="button" id="customCompareBtn" class="primary-btn" onclick="runCustomComparison(this)">Сравнить ответы</button>
      </div>
    </details>

    <section id="comparisonResult" class="compare-panel result-panel" aria-live="polite">
      <div id="comparisonEmpty" class="empty-state">Выберите вопрос выше или добавьте свой — здесь появятся ожидаемый результат, ответы и их саммари.</div>
      <div id="comparisonLoading" class="comparison-loading" hidden>
        <div class="loader"></div>
        <div><h2>Сравниваем ответы</h2><p>Не закрывайте эту вкладку, пока идёт обработка.</p></div>
        <ol class="stage-list">
          <li data-stage="rag_answer">Генерируется ответ с RAG</li>
          <li data-stage="plain_answer">Генерируется ответ без RAG</li>
          <li data-stage="summary">Генерируется саммари ответов</li>
        </ol>
      </div>
      <article id="comparisonCard" hidden>
        <div class="result-question-block">
          <span class="result-label">Вопрос</span>
          <h2 id="resultQuestion"></h2>
        </div>
        <div class="expected-block">
          <span class="result-label">Ожидаемый результат</span>
          <div id="resultExpected"></div>
        </div>
        <div class="answer-grid">
          <section class="answer-card rag-answer-card">
            <h3>С RAG</h3>
            <div id="ragAnswer" class="answer-content markdown-content"></div>
            <details id="retrievedDetails" class="sources-details">
              <summary>Найденные источники и фрагменты</summary>
              <div id="retrievedSources"></div>
            </details>
          </section>
          <section class="answer-card plain-answer-card">
            <h3>Без RAG</h3>
            <div id="plainAnswer" class="answer-content markdown-content"></div>
          </section>
        </div>
        <section class="summary-block">
          <h3>Саммари ответов</h3>
          <div id="answerSummary" class="markdown-content"></div>
        </section>
      </article>
      <div id="benchmarkResult" class="benchmark-result" hidden></div>
    </section>
  </div>
</section>
<style>
  .compare-page { width: min(1180px, 100%); margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
  .compare-header, .panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
  .compare-header h1 { margin: 0 0 6px; font-size: 1.55rem; }
  .compare-header p, .panel-heading p { margin: 0; color: var(--text-dim); line-height: 1.5; }
  .panel-heading h2 { margin: 0 0 4px; font-size: 1.05rem; }
  .compare-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
  .subtle-label, .result-label { color: var(--text-dim); font-size: .76rem; text-transform: uppercase; letter-spacing: .04em; font-weight: 700; }
  .question-bank { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-top: 14px; }
  .question-option { display: block; width: 100%; text-align: left; padding: 12px; color: var(--text-main); background: rgba(15,23,42,.75); border: 1px solid var(--border); border-radius: 9px; cursor: pointer; }
  .question-option:hover { border-color: var(--primary); background: rgba(99,102,241,.12); }
  .question-option:disabled, .benchmark-btn:disabled, .primary-btn:disabled { opacity: .55; cursor: wait; }
  .question-option strong { display: block; font-size: .9rem; line-height: 1.4; }
  .question-option span { display: block; margin-top: 6px; color: var(--text-dim); font-size: .76rem; line-height: 1.45; }
  .custom-question-panel summary, .sources-details summary { cursor: pointer; color: #c4b5fd; font-weight: 700; }
  .custom-question-form { display: grid; gap: 8px; margin-top: 14px; }
  .custom-question-form label { color: var(--text-dim); font-size: .82rem; font-weight: 700; }
  .custom-question-form textarea { width: 100%; resize: vertical; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-dark); color: var(--text-main); padding: 10px; font: inherit; }
  .primary-btn, .benchmark-btn { border: 0; border-radius: 8px; color: white; padding: 10px 14px; font-weight: 700; cursor: pointer; background: linear-gradient(135deg, #7c3aed, #2563eb); }
  .benchmark-btn { flex-shrink: 0; background: linear-gradient(135deg, #e11d48, #f97316); }
  .empty-state { padding: 22px; color: var(--text-dim); text-align: center; border: 1px dashed var(--border); border-radius: 9px; }
  .result-panel { scroll-margin-top: 12px; }
  .comparison-loading { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 12px; }
  .comparison-loading .loader { width: 28px; height: 28px; border-color: rgba(255,255,255,.22); border-top-color: #a78bfa; }
  .comparison-loading h2 { margin: 0 0 4px; font-size: 1rem; }
  .comparison-loading p { margin: 0; color: var(--text-dim); font-size: .85rem; }
  .stage-list { grid-column: 1 / -1; list-style: none; padding: 0; margin: 6px 0 0; display: grid; gap: 8px; }
  .stage-list li { padding: 9px 12px; border-radius: 7px; background: rgba(255,255,255,.04); color: var(--text-dim); }
  .stage-list li.active { color: #fff; background: rgba(99,102,241,.2); border: 1px solid #6366f1; }
  .stage-list li.done { color: #86efac; }
  .result-question-block { margin-bottom: 14px; }
  .result-question-block h2 { margin: 5px 0 0; font-size: 1.12rem; line-height: 1.5; }
  .expected-block { border-left: 3px solid #fbbf24; background: rgba(251,191,36,.08); border-radius: 0 8px 8px 0; padding: 12px 14px; margin-bottom: 16px; line-height: 1.55; }
  .expected-block > div { margin-top: 5px; }
  .answer-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
  .answer-card { min-width: 0; border: 1px solid var(--border); border-radius: 10px; padding: 14px; background: rgba(15,23,42,.5); }
  .rag-answer-card { border-top: 3px solid #34d399; }
  .plain-answer-card { border-top: 3px solid #60a5fa; }
  .answer-card h3, .summary-block h3 { margin: 0 0 10px; font-size: 1rem; }
  .answer-content, .summary-block { line-height: 1.6; overflow-wrap: anywhere; }
  .markdown-content p { margin: 0 0 9px; }
  .markdown-content p:last-child { margin-bottom: 0; }
  .sources-details { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--border); font-size: .82rem; }
  .source-chunk { margin-top: 8px; padding: 9px; border-radius: 7px; background: rgba(255,255,255,.04); color: var(--text-dim); white-space: pre-wrap; }
  .source-chunk strong { display: block; color: #a7f3d0; margin-bottom: 5px; }
  .summary-block { margin-top: 14px; border-radius: 10px; border: 1px solid rgba(168,85,247,.45); background: rgba(168,85,247,.08); padding: 14px; }
  .benchmark-result { margin-top: 14px; white-space: pre-wrap; font-size: .84rem; line-height: 1.55; border-top: 1px solid var(--border); padding-top: 14px; }
  @media (max-width: 900px) { .question-bank, .answer-grid { grid-template-columns: 1fr; } .compare-header, .panel-heading { align-items: flex-start; flex-direction: column; } }
</style>
"""

EXTRA_SCRIPTS = """
const PRESET_INVARIANTS = {
    "Архитектура": "Для Android-функций придерживаться Strict MVI и однонаправленного потока данных (UDF); сайд-эффекты отделять от состояния экрана.",
    "Стек проекта": "Для Android-кода использовать Kotlin, Jetpack Compose и Koin; не добавлять Java и устаревшие XML-разметки.",
    "Безопасность": "Не записывать и не передавать пароли, API-токены и приватные ключи в открытом виде.",
    "Бизнес-правило": "Финансовые операции должны проходить двойную проверку до отправки в сеть.",
    "Ответы по базе знаний": "Для фактов об оранжерее Сова-17 опираться на найденные документы; если в них нет ответа, прямо сообщить об этом и не придумывать значения."
};

function populateInvariantPresets() {
    const select = document.getElementById('invariantPresetSelect');
    if (!select || select.dataset.ready === 'true') return;
    Object.keys(PRESET_INVARIANTS).forEach(key => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = key;
        select.appendChild(option);
    });
    select.dataset.ready = 'true';
}

async function refreshUI() {
    try {
        const res = await fetch('/api/state');
        const state = await res.json();

        // 0. Конфиг (Planning Mode & RAG Mode)
        if (state.config) {
            if (state.config.planning_mode_enabled !== undefined) {
                const cb = document.getElementById('planning_mode_enabled');
                if (cb) cb.checked = state.config.planning_mode_enabled;
            }
            if (state.config.rag_mode_enabled !== undefined) {
                const cbRag = document.getElementById('rag_mode_enabled');
                if (cbRag) cbRag.checked = state.config.rag_mode_enabled;
            }
            const invariantsEnabled = Boolean(state.config.invariants_enabled);
            const invariantToggle = document.getElementById('invariants_enabled');
            if (invariantToggle) invariantToggle.checked = invariantsEnabled;
            const invariantControls = document.getElementById('invariantControls');
            if (invariantControls) invariantControls.style.display = invariantsEnabled ? 'flex' : 'none';
        }

        // 1. TSM Pipeline и Кнопки переходов
        if (state.tsm) {
            const t = state.tsm;
            document.getElementById('tsmStepText').textContent = t.step || '---';
            document.getElementById('tsmActionText').textContent = t.action || '---';
            const stages = ['none', 'planning', 'execution', 'validation', 'done'];
            stages.forEach(s => {
                const el = document.getElementById('badge_' + s);
                if (s === t.stage) el.classList.add('active');
                else el.classList.remove('active');
            });
            const btnContainer = document.getElementById('transitionButtons');
            btnContainer.innerHTML = '';
            stages.forEach(s => {
                if (s === 'none') return;
                const isAllowed = t.allowed_next.includes(s);
                const btn = document.createElement('div');
                btn.className = `btn-transition ${isAllowed ? 'allowed' : 'blocked'}`;
                btn.textContent = s.toUpperCase();
                if (isAllowed) btn.onclick = () => forceTransition(s);
                btnContainer.appendChild(btn);
            });
        }

        // 2. Инварианты
        const invContainer = document.getElementById('invList');
        populateInvariantPresets();
        invContainer.innerHTML = '';
        if (state.config && state.config.invariants_enabled) {
            const selectedInvariants = state.invariants || {};
            if (Object.keys(selectedInvariants).length > 0) {
                for (const [key, value] of Object.entries(selectedInvariants)) {
                    const row = document.createElement('div');
                    row.className = 'invariant-item';
                    const title = document.createElement('div');
                    title.style.cssText = 'font-weight:bold; color:#fca5a5; margin-bottom:2px;';
                    title.textContent = key;
                    const description = document.createElement('div');
                    description.style.lineHeight = '1.2';
                    description.textContent = value;
                    const remove = document.createElement('button');
                    remove.type = 'button';
                    remove.className = 'del-inv';
                    remove.textContent = '×';
                    remove.setAttribute('aria-label', `Удалить инвариант ${key}`);
                    remove.addEventListener('click', () => deleteInv(key));
                    row.append(title, description, remove);
                    invContainer.appendChild(row);
                }
            } else {
                invContainer.textContent = 'Пока ни одного инварианта не выбрано.';
            }
        }

        // 3. Профили
        if (state.profiles_list) {
            const sel = document.getElementById('profileSelect');
            sel.innerHTML = '';
            state.profiles_list.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p; opt.textContent = p;
                if (p === state.current_profile) opt.selected = true;
                sel.appendChild(opt);
            });
            const d = state.current_profile_data;
            document.getElementById('profRole').textContent = d.role || '---';
            document.getElementById('profStyle').textContent = d.style || '---';
            document.getElementById('profFormat').textContent = d.format || '---';
            document.getElementById('profConstraints').textContent = d.constraints || '---';
        }

        // 4. Память (LTM / WM)
        const renderMap = (id, data, empty) => {
            const el = document.getElementById(id);
            if (data && Object.keys(data).length > 0) {
                let html = '<ul style="padding-left:15px; margin:0;">';
                for (const [k, v] of Object.entries(data)) html += `<li><b>${k}:</b> ${v}</li>`;
                el.innerHTML = html + '</ul>';
            } else { el.textContent = empty; }
        };
        renderMap('ltmList', state.ltm, "Нет долговременных фактов");
        renderMap('wmList', state.wm, "Нет активных данных задачи");

        // Чат
        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach(m => {
                const isBot = m.role === 'assistant';
                addMessage(isBot ? 'bot' : 'user', m.content, isBot ? {model: m.model, time: m.time, usage: m.usage} : null);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я агент с поддержкой **RAG (День 22)**. Переключай режим RAG ON/OFF в сайдбаре и тестируй качество ответов на контрольных вопросах! 🔬💡</div></div>';
        }

        if (state.stats) {
            document.getElementById('statTotal').textContent = state.stats.total_tokens || 0;
            document.getElementById('statCost').textContent = '$' + (state.stats.cost || 0).toFixed(6);
        }
        if (!window.currentAppView) showAppView('comparison');
        await loadComparisonQuestions();
    } catch (e) { console.error(e); }
}

async function toggleRagMode(enabled) {
    await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rag_mode_enabled: enabled})
    });
}

function showAppView(view) {
    const isComparison = view === 'comparison';
    document.getElementById('chatView').style.display = isComparison ? 'none' : 'flex';
    document.getElementById('comparisonView').style.display = isComparison ? 'block' : 'none';
    document.getElementById('chatTab').classList.toggle('active', !isComparison);
    document.getElementById('comparisonTab').classList.toggle('active', isComparison);
    window.currentAppView = view;
}

async function loadComparisonQuestions() {
    if (window.comparisonQuestionsLoaded) return;
    const bank = document.getElementById('questionBank');
    try {
        const response = await fetch('/api/rag/questions');
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || 'Не удалось загрузить вопросы');
        bank.innerHTML = '';
        const questions = data.questions || [];
        document.getElementById('questionCount').textContent = `${questions.length} вопросов`;
        questions.forEach((item, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'question-option';
            const title = document.createElement('strong');
            title.textContent = `${index + 1}. ${item.question}`;
            const expected = document.createElement('span');
            expected.textContent = `Ожидается: ${item.expected || 'не задано'}`;
            button.append(title, expected);
            button.addEventListener('click', () => startRagComparison(item.question, item.expected, item.sources || [], button));
            bank.appendChild(button);
        });
        if (!questions.length) bank.innerHTML = '<div class="empty-state">В наборе пока нет вопросов.</div>';
        window.comparisonQuestionsLoaded = true;
    } catch (error) {
        bank.textContent = `Не удалось загрузить вопросы: ${error.message}`;
    }
}

function comparisonConfig() {
    const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        temperature: document.getElementById('tempSlider').value,
        top_p: document.getElementById('topPSlider').value,
        top_k: document.getElementById('topKSlider').value
    };
    document.querySelectorAll('.sidebar input[type="checkbox"]').forEach(cb => { config[cb.id] = cb.checked; });
    return config;
}

function setComparisonStage(stage) {
    const order = ['rag_answer', 'plain_answer', 'summary'];
    const activeIndex = order.indexOf(stage);
    document.querySelectorAll('.stage-list li').forEach((item, index) => {
        item.classList.toggle('active', index === activeIndex);
        item.classList.toggle('done', activeIndex > index || stage === 'complete');
    });
}

function setComparisonBusy(isBusy) {
    document.querySelectorAll('.question-option').forEach(button => { button.disabled = isBusy; });
    document.getElementById('customCompareBtn').disabled = isBusy;
    document.getElementById('runBenchmarkBtn').disabled = isBusy;
}

function renderComparison(result) {
    document.getElementById('comparisonLoading').hidden = true;
    document.getElementById('comparisonEmpty').hidden = true;
    document.getElementById('comparisonCard').hidden = false;
    document.getElementById('resultQuestion').textContent = result.question || '';
    document.getElementById('resultExpected').textContent = result.expected || 'Ожидаемый результат не задан для этого вопроса.';
    document.getElementById('ragAnswer').innerHTML = marked.parse(result.with_rag || 'Модель не вернула ответ.');
    document.getElementById('plainAnswer').innerHTML = marked.parse(result.without_rag || 'Модель не вернула ответ.');
    document.getElementById('answerSummary').innerHTML = marked.parse(result.summary || 'Саммари не получено.');

    const sourceContainer = document.getElementById('retrievedSources');
    sourceContainer.innerHTML = '';
    (result.snippets || []).forEach(snippet => {
        const block = document.createElement('div');
        block.className = 'source-chunk';
        const source = document.createElement('strong');
        source.textContent = `${snippet.source || 'Источник'}${snippet.section ? ` — ${snippet.section}` : ''}`;
        const text = document.createElement('span');
        text.textContent = snippet.text || '';
        block.append(source, text);
        sourceContainer.appendChild(block);
    });
    if (!sourceContainer.childElementCount) sourceContainer.textContent = 'По этому вопросу релевантные фрагменты не найдены.';
    const retrieved = new Set(result.retrieved_sources || []);
    const expectedSources = result.expected_sources || [];
    document.getElementById('retrievedDetails').open = false;
    if (expectedSources.length) {
        const sourceStatus = document.createElement('div');
        sourceStatus.className = 'source-chunk';
        sourceStatus.textContent = `Ожидаемые источники: ${expectedSources.join(', ')}. Найдены: ${[...retrieved].join(', ') || 'нет'}.`;
        sourceContainer.prepend(sourceStatus);
    }
    document.getElementById('comparisonResult').scrollIntoView({behavior: 'smooth', block: 'start'});
}

async function startRagComparison(question, expected = '', expectedSources = []) {
    if (!question || window.comparisonRunning) return;
    window.comparisonRunning = true;
    setComparisonBusy(true);
    document.getElementById('comparisonEmpty').hidden = true;
    document.getElementById('comparisonCard').hidden = true;
    document.getElementById('benchmarkResult').hidden = true;
    document.getElementById('comparisonLoading').hidden = false;
    document.getElementById('comparisonResult').scrollIntoView({behavior: 'smooth', block: 'start'});
    setComparisonStage('rag_answer');

    try {
        const response = await fetch('/api/rag/compare', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question, expected, expected_sources: expectedSources, config: comparisonConfig()})
        });
        let job = await response.json();
        if (!response.ok || job.error) throw new Error(job.error || 'Не удалось запустить сравнение');
        while (job.status === 'running') {
            setComparisonStage(job.stage);
            await new Promise(resolve => setTimeout(resolve, 900));
            const statusResponse = await fetch(`/api/rag/evaluate/status?job_id=${encodeURIComponent(job.job_id)}`);
            job = await statusResponse.json();
            if (!statusResponse.ok || job.error) throw new Error(job.error || 'Не удалось получить статус сравнения');
        }
        if (job.status !== 'complete' || !job.result) throw new Error(job.error || 'Сравнение завершилось без результата');
        setComparisonStage('complete');
        renderComparison(job.result);
    } catch (error) {
        document.getElementById('comparisonLoading').hidden = true;
        document.getElementById('comparisonEmpty').hidden = false;
        document.getElementById('comparisonEmpty').textContent = `Не удалось завершить сравнение: ${error.message}`;
    } finally {
        window.comparisonRunning = false;
        setComparisonBusy(false);
    }
}

async function runCustomComparison(button) {
    const question = document.getElementById('customQuestion').value.trim();
    const expected = document.getElementById('customExpected').value.trim();
    if (!question) {
        document.getElementById('customQuestion').focus();
        return;
    }
    await startRagComparison(question, expected, []);
}

async function waitForRagJob(startData, onProgress) {
    let result = startData;
    while (result.status === 'running') {
        if (onProgress) onProgress(result);
        await new Promise(resolve => setTimeout(resolve, 1200));
        const statusRes = await fetch(`/api/rag/evaluate/status?job_id=${encodeURIComponent(startData.job_id)}`);
        result = await statusRes.json();
        if (!statusRes.ok || result.error) throw new Error(result.error || 'Не удалось получить статус');
    }
    return result;
}

async function runRagEvaluation(button) {
    const resultEl = document.getElementById('benchmarkResult');
    resultEl.hidden = false;
    resultEl.textContent = 'Подготовка оценки: по каждому из 10 вопросов генерируются два ответа…';
    setComparisonBusy(true);

    try {
        const startRes = await fetch('/api/rag/evaluate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({})
        });
        const startData = await startRes.json();
        if (!startRes.ok || startData.error) throw new Error(startData.error || 'Не удалось запустить оценку');
        const result = await waitForRagJob(startData, job => {
            resultEl.textContent = `Выполнено вопросов: ${job.completed || 0}/${job.total || 10}. Сравниваются ответы без RAG и с RAG…`;
        });
        if (result.status === 'complete' && result.report) {
            resultEl.textContent = result.report;
        } else {
            resultEl.textContent = `Не удалось завершить оценку: ${result.error || 'нет отчёта'}`;
        }
    } catch(e) {
        resultEl.textContent = `Не удалось запустить оценку: ${e.message}`;
    } finally {
        setComparisonBusy(false);
    }
}

async function forceTransition(stage) {
    await fetch('/api/tsm/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stage: stage, step: "Ручное переключение", action: "Продолжение работы"})
    });
    refreshUI();
}

async function togglePlanningMode(enabled) {
    await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({planning_mode_enabled: enabled})
    });
}

async function toggleInvariants(enabled) {
    const controls = document.getElementById('invariantControls');
    controls.style.display = enabled ? 'flex' : 'none';
    await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({invariants_enabled: enabled})
    });
    if (enabled) refreshUI();
}

async function addSelectedInvariant() {
    const select = document.getElementById('invariantPresetSelect');
    const key = select.value;
    if (!key || !PRESET_INVARIANTS[key]) return;
    const response = await fetch('/api/invariants/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key, value: PRESET_INVARIANTS[key]})
    });
    const data = await response.json();
    if (data.error) return alert(data.error);
    select.value = '';
    refreshUI();
}

async function addNewInvariant() {
    const key = document.getElementById('newInvKey').value.trim();
    const val = document.getElementById('newInvVal').value.trim();
    if (!key || !val) return alert('Заполните название и текст закона');
    await fetch('/api/invariants/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, value: val})
    });
    document.getElementById('newInvKey').value = '';
    document.getElementById('newInvVal').value = '';
    refreshUI();
}

async function deleteInv(key) {
    if (!confirm(`Удалить закон "${key}"?`)) return;
    await fetch('/api/invariants/delete', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key: key}) });
    refreshUI();
}

async function resetAllInvariants() {
    if (!confirm('Сбросить все выбранные инварианты?')) return;
    await fetch('/api/invariants/reset', { method: 'POST' });
    refreshUI();
}

function openEditorForUpdate() {
    fetch('/api/state').then(r => r.json()).then(s => {
        const d = s.current_profile_data;
        document.getElementById('profileEditor').style.display = 'flex';
        document.getElementById('editorTitle').textContent = "📝 Редактировать профиль:";
        document.getElementById('editProfName').value = s.current_profile;
        document.getElementById('editProfName').disabled = true;
        document.getElementById('editProfRole').value = d.role || '';
        document.getElementById('editProfStyle').value = d.style || '';
        document.getElementById('editProfFormat').value = d.format || '';
        document.getElementById('editProfConstraints').value = d.constraints || '';
    });
}

function openEditorForCreate() {
    document.getElementById('profileEditor').style.display = 'flex';
    document.getElementById('editorTitle').textContent = "✨ Создать новый профиль:";
    document.getElementById('editProfName').value = ""; document.getElementById('editProfName').disabled = false;
    ['editProfRole', 'editProfStyle', 'editProfFormat', 'editProfConstraints'].forEach(id => document.getElementById(id).value = "");
    document.getElementById('editProfName').focus();
}

function closeProfileEditor() { document.getElementById('profileEditor').style.display = 'none'; }

async function saveProfileManual() {
    const name = document.getElementById('editProfName').value.trim();
    const data = {
        role: document.getElementById('editProfRole').value,
        style: document.getElementById('editProfStyle').value,
        format: document.getElementById('editProfFormat').value,
        constraints: document.getElementById('editProfConstraints').value
    };
    if (!name) return alert("Укажите имя профиля");
    await fetch('/api/profile/save', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: name, data: data}) });
    closeProfileEditor(); refreshUI();
}

async function pinToLtmManual() {
    const key = document.getElementById('manualLtmKey').value.trim();
    const val = document.getElementById('manualLtmVal').value.trim();
    if (!key || !val) return alert("Заполните ключ и значение");
    await fetch('/api/memory/pin_ltm', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key: key, value: val}) });
    document.getElementById('manualLtmKey').value = ''; document.getElementById('manualLtmVal').value = '';
    refreshUI();
}

async function clearChat() {
    if (!confirm('Очистить только историю? (Память и Законы сохранятся)')) return;
    await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: false}) });
    refreshUI();
}

async function resetAllData() {
    if (!confirm('🚨 Сбросить ВСЁ? Это удалит инварианты, память, профили и TSM!')) return;
    await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: true}) });
    refreshUI();
}

document.getElementById('profileSelect').addEventListener('change', async (e) => {
    await fetch('/api/profile/switch', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: e.target.value}) });
    refreshUI();
});

const originalAddMessage = addMessage;
addMessage = function(role, content, meta) {
    const res = originalAddMessage(role, content, meta);
    if (role === 'bot' && content) {
        if (content.includes('❌ ОТКАЗ ВЫПОЛНЕНИЯ') || content.includes('утвердить план')) {
            const bubble = res.querySelector('.msg-bubble');
            if (bubble) {
                bubble.style.border = '2px solid #3b82f6';
                bubble.style.background = 'rgba(59, 130, 246, 0.1)';
            }
        }
        let ind = "";
        if (content.includes("🧠")) ind += `<span style="background:rgba(168,85,247,0.2); border:1px solid var(--accent); padding:2px 6px; border-radius:4px; font-size:0.75rem; margin-right:5px;">🧠 LTM</span>`;
        if (content.includes("🛠")) ind += `<span style="background:rgba(59,130,246,0.2); border:1px solid #3b82f6; padding:2px 6px; border-radius:4px; font-size:0.75rem; margin-right:5px;">🛠 WM</span>`;
        if (content.includes("🔬") || content.includes("RAG") || content.includes("тестирования")) ind += `<span style="background:rgba(244,63,94,0.2); border:1px solid #f43f5e; padding:2px 6px; border-radius:4px; font-size:0.75rem;">🔬 RAG Evaluation</span>`;
        if (ind) {
            const m = res.querySelector('.msg-meta');
            if (m) { const c = document.createElement('div'); c.style="margin-top:5px; display:flex; gap:5px;"; c.innerHTML=ind; res.insertBefore(c, m); }
        }
    }
    return res;
};

initApp = refreshUI;
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path.rstrip('/')
        if path == "/api/rag/questions":
            eval_file = ROOT / "rag_evaluation_questions.json"
            try:
                eval_data = json.loads(eval_file.read_text(encoding="utf-8"))
                questions = [{
                    "id": item.get("id", ""),
                    "question": item.get("question", ""),
                    "expected": item.get("expected_expectation", ""),
                    "sources": item.get("source_files", []),
                } for item in eval_data.get("questions", [])]
                self._send_json({"questions": questions})
            except Exception as exc:
                self._send_json({"error": f"Не удалось загрузить контрольные вопросы: {exc}"})
            return

        if path == "/api/rag/evaluate/status":
            job_id = parse_qs(parsed_url.query).get("job_id", [""])[0]
            with _EVALUATION_LOCK:
                job = dict(_EVALUATIONS.get(job_id, {}))
            if not job:
                self._send_json({"error": "Задача оценки не найдена"})
                return
            response = {
                "job_id": job_id,
                "status": job.get("status"),
                "completed": job.get("completed", 0),
                "total": job.get("total", 10),
                "stage": job.get("stage", ""),
            }
            if job.get("status") == "complete":
                if job.get("result") is not None:
                    response["result"] = job.get("result")
                response["report"] = job.get("report", "")
            if job.get("status") == "failed":
                response["error"] = job.get("error", "Неизвестная ошибка оценки")
            self._send_json(response)
            return

        if path == "/api/state":
            with _LOCK:
                state = agent.get_state()
                tools_list = indexer_client.refresh_tools()
                state["indexer_mcp"] = {
                    "is_connected": indexer_client.is_connected,
                    "server_info": indexer_client.server_info,
                    "tools": tools_list
                }
                self._send_json(state)
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        page_html = get_chat_page(
            title="RAG vs Non-RAG Evaluation — День 22",
            extra_sidebar_html=SIDEBAR_STATS_HTML,
            extra_scripts=EXTRA_SCRIPTS,
            extra_main_html=COMPARISON_VIEW_HTML,
        )
        body = page_html.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8")
        path = urlparse(self.path).path.rstrip('/')
        try:
            if path == "/api/chat":
                data = json.loads(raw_body)
                user_msg = data.get("message", "")
                with _LOCK:
                    agent.set_config(data.get("config", {}))
                    result = agent.chat(
                        user_msg,
                        mcp_clients=[indexer_client, pipeline_client, scheduler_client, git_client],
                        rag_source_prefix="docs/",
                    )
                self._send_json(result)

            elif path == "/api/rag/compare":
                data = json.loads(raw_body)
                question = str(data.get("question", "")).strip()
                if not question:
                    self._send_json({"error": "Введите вопрос для сравнения"})
                    return
                expected = str(data.get("expected", "")).strip()
                expected_sources = data.get("expected_sources", [])
                config = data.get("config", {})
                with _EVALUATION_LOCK:
                    if any(job.get("status") == "running" for job in _EVALUATIONS.values()):
                        self._send_json({"error": "Другая RAG-оценка уже выполняется"})
                        return
                    job_id = uuid.uuid4().hex
                    _EVALUATIONS[job_id] = {
                        "status": "running",
                        "completed": 0,
                        "total": 1,
                        "report": "",
                        "results": [],
                    }
                with _LOCK:
                    if isinstance(config, dict):
                        agent.set_config(config)
                    base_agent = copy.deepcopy(agent)
                worker = threading.Thread(
                    target=_run_rag_comparison,
                    args=(job_id, question, expected, expected_sources, base_agent),
                    daemon=True,
                    name=f"rag-comparison-{job_id[:8]}",
                )
                worker.start()
                self._send_json({
                    "job_id": job_id,
                    "status": "running",
                    "completed": 0,
                    "total": 1,
                    "stage": "rag_answer",
                })

            elif path == "/api/rag/evaluate":
                eval_file = ROOT / "rag_evaluation_questions.json"
                if not eval_file.exists():
                    self._send_json({"error": "rag_evaluation_questions.json not found"})
                    return

                eval_data = json.loads(eval_file.read_text(encoding="utf-8"))
                questions = eval_data.get("questions", [])
                if len(questions) != 10:
                    self._send_json({"error": f"В наборе должно быть ровно 10 вопросов; найдено {len(questions)}"})
                    return
                if any(not q.get("evaluation_criteria") for q in questions):
                    self._send_json({"error": "У каждого вопроса должны быть заданы критерии оценки"})
                    return

                with _EVALUATION_LOCK:
                    if any(job.get("status") == "running" for job in _EVALUATIONS.values()):
                        self._send_json({"error": "Оценка уже выполняется"})
                        return
                    job_id = uuid.uuid4().hex
                    _EVALUATIONS[job_id] = {
                        "status": "running",
                        "completed": 0,
                        "total": len(questions),
                        "report": "",
                        "results": [],
                    }
                with _LOCK:
                    base_agent = copy.deepcopy(agent)
                worker = threading.Thread(
                    target=_run_rag_evaluation,
                    args=(job_id, copy.deepcopy(questions), base_agent),
                    daemon=True,
                    name=f"rag-evaluation-{job_id[:8]}",
                )
                worker.start()
                self._send_json({
                    "job_id": job_id,
                    "status": "running",
                    "completed": 0,
                    "total": len(questions),
                })

            elif path == "/api/config":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.set_config(data)
                self._send_json({"status": "config_updated"})

            elif path == "/api/clear":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.clear_history(clear_all=data.get("clear_all", False))
                self._send_json({"status": "cleared"})

            elif path == "/api/invariants/add":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.pin_invariant(data.get("key", ""), data.get("value", ""))
                self._send_json({"status": "added"})

            elif path == "/api/invariants/delete":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.delete_invariant(data.get("key", ""))
                self._send_json({"status": "deleted"})

            elif path == "/api/invariants/reset":
                with _LOCK:
                    agent.clear_invariants()
                self._send_json({"status": "reset"})

            elif path == "/api/profile/switch":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.switch_profile(data.get("name", ""))
                self._send_json({"status": "switched"})

            elif path == "/api/profile/save":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.save_profile_data(data.get("name", ""), data.get("data", {}))
                self._send_json({"status": "profile_saved"})

            elif path == "/api/memory/pin_ltm":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.pin_to_ltm(data.get("key", ""), data.get("value", ""))
                self._send_json({"status": "pinned"})

            elif path == "/api/tsm/update":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.update_tsm_manually(data.get("stage", "none"), data.get("step", ""), data.get("action", ""))
                self._send_json({"status": "tsm_updated"})

            else:
                self.send_error(404)
        except Exception as e:
            self._send_json({"error": str(e)})

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args): pass

def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if __name__ == "__main__":
    load_env()
    print(f"🚀 День 22 RAG Evaluation Agent & Sidebar: http://127.0.0.1:{PORT}")
    class ReusableThreadingHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
    try:
        ReusableThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        indexer_client.close()
        pipeline_client.close()
        scheduler_client.close()
        git_client.close()
        sys.exit(0)
