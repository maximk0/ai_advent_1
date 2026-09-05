#!/usr/bin/env python3
"""CLI и веб-чат: Сравнение моделей (Weak, Medium, Strong).
   День 5: Замер времени, токенов и качества.
"""

from __future__ import annotations

import html
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history_day5.json"
PORT = 8003
_LOCK = threading.Lock()

# ============================================
# МОДЕЛИ И ПРОМПТЫ
# ============================================
SUMMARY_PROMPT = (
    "Ты — экспертный аналитик данных и технический арбитр. Твоя задача — объективно сравнить три ответа на один запрос. "
    "Веди себя как строгий рецензент: "
    "1. ПРОВЕРКА ФАКТОВ: Если модели делают специфические утверждения (инструкции, API, даты, формулы), проверь их на согласованность. "
    "Если одна модель приводит детали, которые кажутся выдуманными или противоречат общепринятой логике, отметь это как 'потенциальную галлюцинацию'. "
    "2. ЛОГИКА И СТРУКТУРА: Оцени, насколько последовательны рассуждения. Не давай бонус за сложность, если она избыточна или ошибочна. "
    "3. КРОСС-ВАЛИДАЦИЯ: Используй информацию из всех трех ответов, чтобы выявить ошибки в каждом из них. "
    "Верни СТРОГО JSON объект: "
    "{\"scores\": {\"Вариант А\": N, \"Вариант Б\": N, \"Вариант В\": N}, "
    "\"comparison\": [{\"aspect\": \"Критерий\", \"Вариант А\": \"...\", \"Вариант Б\": \"...\", \"Вариант В\": \"...\"}], "
    "\"conclusion\": \"Сделай краткий критический разбор. Подсвети сильные стороны и ОБЯЗАТЕЛЬНО укажи на подозрительные или ошибочные моменты, если они есть. Кто был наиболее точен?\"}"
)

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>OpenRouter — День 5: Битва Моделей</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
      margin: 0; padding: 20px;
      background: #0f172a;
      color: #f1f5f9;
    }
    .container { max-width: 1400px; margin: 0 auto; }
    h1 {
      display: flex; align-items: center; gap: 12px; margin-bottom: 5px;
    }
    .subtitle { color: #94a3b8; margin-bottom: 25px; }
    .badge {
      background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
      color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px;
      font-weight: bold;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 20px;
      margin-bottom: 30px;
    }

    .card {
      background: #1e293b;
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);
      display: flex;
      flex-direction: column;
      height: 100%;
      border: 1px solid #334155;
    }
    .card-header {
      margin-bottom: 15px;
      border-bottom: 1px solid #334155;
      padding-bottom: 10px;
    }
    .card-title {
      font-weight: 800;
      font-size: 16px;
      color: #818cf8;
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    .model-name {
      font-size: 12px;
      color: #94a3b8;
      margin-top: 4px;
      font-family: monospace;
      word-break: break-all;
    }
    .metrics {
      display: flex;
      gap: 10px;
      margin-bottom: 15px;
      font-size: 12px;
    }
    .metric-tag {
      background: #334155;
      padding: 4px 8px;
      border-radius: 6px;
      color: #cbd5e1;
    }
    .card-content {
      font-size: 14px;
      line-height: 1.6;
      overflow-y: auto;
      flex-grow: 1;
    }
    /* Стили для Markdown внутри карточек */
    .md-content p { margin-top: 0; margin-bottom: 8px; }
    .md-content p:last-child { margin-bottom: 0; }
    .comparison-table td p { margin: 0; }

    .md-content code {
      background: #334155;
      color: #e2e8f0;
      padding: 2px 5px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.9em;
      border: 1px solid #475569;
    }
    .md-content pre {
      background: #334155;
      padding: 16px;
      border-radius: 12px;
      overflow-x: auto;
      border: 1px solid #475569;
      margin: 10px 0;
    }
    .md-content pre code {
      background: transparent;
      padding: 0;
      border: none;
      color: #f1f5f9;
    }
    .card-content ul, .card-content ol { padding-left: 20px; }

    .summary-box {
      background: #1e293b;
      border-radius: 16px;
      padding: 25px;
      margin-bottom: 40px;
      box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
      border: 1px solid #334155;
    }
    .summary-title {
      font-weight: bold;
      font-size: 18px;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .comparison-table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 25px;
      font-size: 14px;
    }
    .comparison-table th, .comparison-table td {
      padding: 12px 15px;
      border: 1px solid #334155;
      text-align: left;
    }
    .comparison-table th {
      background: #0f172a;
      color: #94a3b8;
      font-weight: 600;
    }
    .conclusion {
      padding: 15px;
      background: #1e1b4b;
      border-left: 4px solid #818cf8;
      border-radius: 4px;
      font-size: 15px;
      color: #c7d2fe;
      line-height: 1.5;
    }

    .input-area {
      position: sticky;
      bottom: 20px;
      background: #1e293b;
      padding: 25px;
      border-radius: 20px;
      box-shadow: 0 -10px 25px -5px rgba(0,0,0,0.3);
      z-index: 10;
      border: 1px solid #334155;
    }
    .model-config {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 15px;
      margin-bottom: 15px;
    }
    .model-config-item {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .model-config-item label {
      font-size: 12px;
      font-weight: 600;
      color: #94a3b8;
    }
    select, textarea {
      padding: 12px;
      border: 1px solid #334155;
      border-radius: 10px;
      font-size: 14px;
      outline: none;
      width: 100%;
      font-family: inherit;
      background: #0f172a;
      color: #f1f5f9;
    }
    select:focus, textarea:focus {
      border-color: #6366f1;
    }
    textarea {
      min-height: 80px;
      resize: vertical;
    }
    .main-form {
      display: flex;
      gap: 10px;
    }
    button.submit-btn {
      padding: 0 40px;
      border: none;
      border-radius: 10px;
      background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
      color: white;
      font-weight: bold;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    button.submit-btn:hover { opacity: 0.9; }
    button.submit-btn:disabled { background: #334155; color: #64748b; cursor: not-allowed; }

    #loader {
      display: none;
      position: fixed; inset: 0; z-index: 100;
      background: rgba(15, 23, 42, 0.9);
      flex-direction: column; align-items: center; justify-content: center;
    }
    .spinner {
      width: 50px; height: 50px;
      border: 5px solid #334155; border-top: 5px solid #6366f1;
      border-radius: 50%; animation: spin 1s linear infinite;
      margin-bottom: 15px;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

    .user-query {
      background: #1e293b;
      padding: 15px 20px;
      border-radius: 12px;
      margin-bottom: 25px;
      font-weight: 600;
      border-left: 5px solid #475569;
    }
    .history-item {
      margin-bottom: 60px;
      padding-bottom: 30px;
      border-bottom: 2px solid #1e293b;
    }

    #active-battle {
      margin-bottom: 40px;
      display: none;
    }
    .loading-pulse {
      animation: pulse 1.5s infinite;
      color: #64748b;
    }
    @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }

    /* Скроллбары */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <div id="loader-text">Сравниваем умы...</div>
  </div>

  <div class="container">
    <h1>🔥 День 5 <span class="badge">Битва Моделей</span></h1>
    <p class="subtitle">Сравниваем Слабую, Среднюю и Сильную модели на одном запросе</p>

    <div id="active-battle"></div>

    <div id="history">
      {history}
    </div>

    <div class="input-area">
      <div class="model-config">
        <div class="model-config-item">
          <label>🤏 Слабая (Weak)</label>
          <select id="modelWeak">
            <option value="liquid/lfm-2.5-2.6b:free">LiquidAI LFM 2.6B (Free)</option>
            <option value="thinkingmachines/inkling-small:free">Inkling Small (Free)</option>
            <option value="poolside/laguna-xs-2.1:free">Laguna XS 2.1 (Free)</option>
          </select>
        </div>
        <div class="model-config-item">
          <label>⚖️ Средняя (Medium)</label>
          <select id="modelMedium">
            <option value="openai/gpt-4o-mini">GPT-4o mini</option>
            <option value="nvidia/nemotron-3.5-lightning:free">Nemotron 3.5 Lightning (Free)</option>
            <option value="google/gemma-4-26b-a4b-it:free">Gemma 4 26B A4B (Free)</option>
          </select>
        </div>
        <div class="model-config-item">
          <label>💪 Сильная (Strong)</label>
          <select id="modelStrong">
            <option value="nvidia/nemotron-3-ultra-550b-a55b:free">Nemotron 3 Ultra 550B (Free)</option>
            <option value="google/gemma-4-31b-it:free">Gemma 4 31B (Free)</option>
            <option value="z-ai/glm-5.2:free">GLM 5.2 (Free)</option>
          </select>
        </div>
      </div>
      <form id="compareForm" class="main-form">
        <textarea id="promptInput" placeholder="Введите сложную логическую задачу или творческий запрос..." required autocomplete="off"></textarea>
        <button type="submit" id="submitBtn" class="submit-btn">🚀 Сравнить</button>
      </form>
      <div style="margin-top: 15px; display: flex; gap: 10px;">
        <button onclick="setExample('logic')" style="font-size: 11px; padding: 5px 10px; cursor:pointer;">🧩 Логика</button>
        <button onclick="setExample('creative')" style="font-size: 11px; padding: 5px 10px; cursor:pointer;">🎨 Творчество</button>
        <form method="post" action="/" style="margin-left: auto;">
            <button type="submit" name="action" value="clear" style="background: #fee2e2; color: #991b1b; padding: 5px 15px; font-size: 11px; border:none; border-radius:5px; cursor:pointer;">🗑️ Очистить</button>
        </form>
      </div>
    </div>
  </div>

  <script>
    const examples = {
      logic: 'В комнате 4 человека. Каждый пожимает руку каждому один раз. Но два человека (А и Б) решили не пожимать руки друг другу. Сколько всего рукопожатий произошло? Объясни пошагово.',
      creative: 'Напиши сценарий для 30-секундного рекламного ролика зубной пасты, которую рекламирует средневековый рыцарь в разгаре битвы.'
    };

    function setExample(key) {
      document.getElementById('promptInput').value = examples[key];
      document.getElementById('promptInput').focus();
    }

    const compareForm = document.getElementById('compareForm');
    const promptInput = document.getElementById('promptInput');
    const loader = document.getElementById('loader');
    const loaderText = document.getElementById('loader-text');
    const submitBtn = document.getElementById('submitBtn');

    promptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        compareForm.requestSubmit();
      }
    });

    function renderMarkdown() {
      document.querySelectorAll('.md-content').forEach(el => {
        if (!el.dataset.rendered) {
          const raw = el.textContent;
          el.innerHTML = marked.parse(raw);
          el.dataset.rendered = 'true';
        }
      });
    }

    document.addEventListener('DOMContentLoaded', renderMarkdown);

    function createPlaceholderCard(tier) {
      return `
        <div class="card" id="card-${tier}">
          <div class="card-header">
            <div class="card-title">${tier.toUpperCase()}</div>
            <div class="model-name loading-pulse">Ожидание ответа...</div>
          </div>
          <div class="metrics">
            <span class="metric-tag">⏱️ --</span>
            <span class="metric-tag">🪙 --</span>
          </div>
          <div class="card-content md-content loading-pulse">...</div>
        </div>
      `;
    }

    function updateCard(tier, data) {
      const card = document.getElementById(`card-${tier}`);
      if (!card) return;

      const usage = data.usage || {};
      card.querySelector('.model-name').textContent = data.model;
      card.querySelector('.model-name').classList.remove('loading-pulse');

      const metrics = card.querySelector('.metrics');
      metrics.innerHTML = `
        <span class="metric-tag">⏱️ ${data.time}s</span>
        <span class="metric-tag">🪙 ${usage.total_tokens || 0} (${usage.prompt_tokens || 0}/${usage.completion_tokens || 0})</span>
      `;

      const content = card.querySelector('.card-content');
      content.innerHTML = marked.parse(data.text);
      content.classList.remove('loading-pulse');
      content.dataset.rendered = 'true';
    }

    compareForm.onsubmit = async (e) => {
      e.preventDefault();
      const prompt = document.getElementById('promptInput').value.trim();
      const mWeak = document.getElementById('modelWeak').value;
      const mMedium = document.getElementById('modelMedium').value;
      const mStrong = document.getElementById('modelStrong').value;

      if (!prompt) return;

      // Очищаем поле ввода сразу после считывания
      document.getElementById('promptInput').value = '';

      const activeBattle = document.getElementById('active-battle');
      activeBattle.style.display = 'block';
      activeBattle.innerHTML = `
        <div class="user-query">💬 Запрос: <span id="active-prompt-text" class="md-content"></span></div>
        <div class="grid">
          ${createPlaceholderCard('weak')}
          ${createPlaceholderCard('medium')}
          ${createPlaceholderCard('strong')}
        </div>
        <div id="active-summary" class="summary-box" style="display:none">
          <div class="summary-title loading-pulse">📝 Анализ...</div>
        </div>
      `;
      document.getElementById('active-prompt-text').textContent = prompt;
      renderMarkdown();
      window.scrollTo(0, activeBattle.offsetTop - 20);

      submitBtn.disabled = true;
      const results = {};

      const tiers = [
        {id: 'weak', model: mWeak},
        {id: 'medium', model: mMedium},
        {id: 'strong', model: mStrong}
      ];

      try {
        const promises = tiers.map(t =>
          fetch('/', {
            method: 'POST',
            body: new URLSearchParams({action: 'api_solve', prompt: prompt, model: t.model})
          })
          .then(res => res.json())
          .then(data => {
            results[t.id] = data;
            updateCard(t.id, data);
            return data;
          })
        );

        await Promise.all(promises);

        const summaryBox = document.getElementById('active-summary');
        summaryBox.style.display = 'block';

        const resSum = await fetch('/', {
          method: 'POST',
          body: new URLSearchParams({
            action: 'api_solve',
            method: 'summary',
            prompt: prompt,
            context: JSON.stringify(results)
          })
        });
        const dataSum = await resSum.json();

        let summaryData = {};
        try {
          const jsonMatch = dataSum.result.match(/\{[\s\S]*\}/);
          summaryData = JSON.parse(jsonMatch ? jsonMatch[0] : dataSum.result);
        } catch(e) {
          summaryData = {conclusion: dataSum.result, comparison: []};
        }

        results['summary'] = summaryData;
        results['summary_model'] = dataSum.model;
        results['label_mapping'] = dataSum.mapping;

        // Render Summary
        const mapping = dataSum.mapping || {};
        const compRows = (summaryData.comparison || []).map(row =>
          `<tr><td>${row.aspect || ''}</td><td><div class='md-content'>${row.weak || ''}</div></td><td><div class='md-content'>${row.medium || ''}</div></td><td><div class='md-content'>${row.strong || ''}</div></td></tr>`
        ).join('');

        summaryBox.innerHTML = `
          <div class="summary-title">📝 Вердикт (${dataSum.model})</div>
          <div style="font-size: 11px; color: #94a3b8; margin-bottom: 15px; padding: 8px; background: #0f172a; border-radius: 6px; border: 1px dashed #334155;">🛡️ <strong>Слепое тестирование:</strong> Модель-арбитр не знала названий и силы моделей. Ответы были представлены как "Вариант А", "Б" и "В".</div>
          <table class="comparison-table">
            <thead>
              <tr>
                <th>Аспект</th>
                <th>Weak (${mapping.weak || ''})</th>
                <th>Medium (${mapping.medium || ''})</th>
                <th>Strong (${mapping.strong || ''})</th>
              </tr>
            </thead>
            <tbody>${compRows}</tbody>
          </table>
          <div class="conclusion">
            <strong>Вывод:</strong> <div id="summary-conclusion-text" class="md-content" style="display:inline-block; margin-left:5px;"></div>
          </div>
        `;
        document.getElementById('summary-conclusion-text').innerHTML = marked.parse(summaryData.conclusion || '');

        // Render Markdown for comparison table cells
        summaryBox.querySelectorAll('tbody div.md-content').forEach(el => {
          el.innerHTML = marked.parse(el.textContent);
          el.dataset.rendered = 'true';
        });

        await fetch('/', {
          method: 'POST',
          body: new URLSearchParams({action: 'api_save', prompt: prompt, results: JSON.stringify(results)})
        });

        submitBtn.disabled = false;
        // Scroll to summary
        window.scrollTo(0, summaryBox.offsetTop - 20);
      } catch (err) {
        alert('Ошибка: ' + err);
        submitBtn.disabled = false;
      }
    };
  </script>
</body>
</html>
"""

def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def load_history() -> list:
    with _LOCK:
        if not HISTORY_PATH.exists(): return []
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except: return []

def save_history(data: list) -> None:
    with _LOCK:
        HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def ask_llm(system: str, user_text: str, temperature: float = 0.7, model_name: str = "openrouter/free") -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key: return {"text": "Ошибка: Нет OPENROUTER_API_KEY", "model": "error", "time": 0, "usage": {}}

    url = "https://openrouter.ai/api/v1/chat/completions"
    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text}
        ],
        "temperature": temperature
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost:8003",
        "X-Title": "Day 5 Model Battle"
    }

    start_time = time.time()
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as res:
            elapsed = time.time() - start_time
            resp_data = json.loads(res.read().decode("utf-8"))
            if "choices" in resp_data and len(resp_data["choices"]) > 0:
                text = resp_data["choices"][0]["message"]["content"]
                model_used = resp_data.get("model", model_name)
                usage = resp_data.get("usage", {})
                return {
                    "text": text,
                    "model": model_used,
                    "time": round(elapsed, 2),
                    "usage": usage
                }
            return {"text": f"Error: {json.dumps(resp_data)}", "model": "error", "time": elapsed, "usage": {}}
    except Exception as e:
        return {"text": f"Error: {str(e)}", "model": "error", "time": 0, "usage": {}}

def format_history_html(history: list) -> str:
    if not history:
        return '<div style="text-align:center; color:#94a3b8; padding:80px; font-size: 18px;">Битва еще не началась. Сделайте первый ход!</div>'

    html_out = []
    for item in reversed(history):
        q = html.escape(item["query"])
        res = item["results"]
        summary = res.get("summary", {})
        mapping = res.get("label_mapping", {})

        cards_html = ""
        for tier in ["weak", "medium", "strong"]:
            data = res.get(tier, {})
            usage = data.get("usage", {})
            label_suffix = f" ({mapping.get(tier)})" if tier in mapping else ""
            metrics = f"""
                <div class="metrics">
                    <span class="metric-tag">⏱️ {data.get('time', 0)}s</span>
                    <span class="metric-tag">🪙 {usage.get('total_tokens', 0)} ({usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)})</span>
                </div>
            """
            cards_html += f"""
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">{tier.upper()}{html.escape(label_suffix)}</div>
                        <div class="model-name">{html.escape(data.get('model', ''))}</div>
                    </div>
                    {metrics}
                    <div class="card-content md-content">{html.escape(data.get('text', ''))}</div>
                </div>
            """

        comp_rows = "".join([
            f"<tr><td>{html.escape(row.get('aspect',''))}</td><td><div class='md-content'>{html.escape(row.get('weak',''))}</div></td><td><div class='md-content'>{html.escape(row.get('medium',''))}</div></td><td><div class='md-content'>{html.escape(row.get('strong',''))}</div></td></tr>"
            for row in summary.get("comparison", [])
        ])

        blind_note = '<div style="font-size: 11px; color: #64748b; margin-bottom: 15px; padding: 8px; background: #0f172a; border-radius: 6px; border: 1px dashed #334155;">🛡️ <strong>Слепое тестирование:</strong> Модель-арбитр не знала названий и силы моделей. Ответы были представлены как "Вариант А", "Б" и "В".</div>' if mapping else ""

        item_html = f"""
        <div class="history-item">
            <div class="user-query">💬 Запрос: <span class="md-content">{q}</span></div>
            <div class="grid">
                {cards_html}
            </div>
            <div class="summary-box">
                <div class="summary-title">📝 Вердикт ({html.escape(res.get('summary_model', ''))})</div>
                {blind_note}
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>Аспект</th>
                            <th>Weak {html.escape(mapping.get('weak', ''))}</th>
                            <th>Medium {html.escape(mapping.get('medium', ''))}</th>
                            <th>Strong {html.escape(mapping.get('strong', ''))}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {comp_rows}
                    </tbody>
                </table>
                <div class="conclusion">
                    <strong>Вывод:</strong> <div class="md-content" style="display:inline-block; margin-left:5px;">{html.escape(summary.get('conclusion', ''))}</div>
                </div>
            </div>
        </div>
        """
        html_out.append(item_html)
    return "".join(html_out)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send(PAGE.replace("{history}", format_history_html(load_history())))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        action = fields.get("action", [""])[0]

        if action == "clear":
            save_history([])
        elif action == "api_solve":
            prompt = fields.get("prompt", [""])[0]
            method = fields.get("method", [""])[0]

            if method == "summary":
                context = json.loads(fields.get("context", ["{}"])[0])
                tiers = ["weak", "medium", "strong"]
                shuffled = tiers[:]
                random.shuffle(shuffled)

                # Вариант А, Б, В
                labels = ["Вариант А", "Вариант Б", "Вариант В"]
                tier_to_label = {tier: labels[shuffled.index(tier)] for tier in tiers}
                label_to_tier = {v: k for k, v in tier_to_label.items()}

                summary_input = ""
                for label in labels:
                    tier = label_to_tier[label]
                    data = context.get(tier, {})
                    summary_input += f"### {label}:\\n{data.get('text')}\\n\\n"

                llm_res = ask_llm(SUMMARY_PROMPT, f"Query: {prompt}\\n\\nResponses:\\n{summary_input}", temperature=0.3, model_name="openai/gpt-4o-mini")

                # Обратный маппинг ключей в JSON
                text = llm_res["text"]
                try:
                    json_match = re.search(r'\{[\s\S]*\}', text)
                    if json_match:
                        data = json.loads(json_match.group(0))

                        # Исправляем scores
                        if "scores" in data:
                            new_scores = {}
                            for lbl, score in data["scores"].items():
                                if lbl in label_to_tier:
                                    new_scores[label_to_tier[lbl]] = score
                            data["scores"] = new_scores

                        # Исправляем comparison
                        if "comparison" in data:
                            for row in data["comparison"]:
                                for lbl in labels:
                                    if lbl in row:
                                        row[label_to_tier[lbl]] = row.pop(lbl)

                        text = json.dumps(data, ensure_ascii=False)
                except Exception as e:
                    print(f"Mapping error: {e}")

                self._send_json({"result": text, "model": llm_res["model"], "mapping": tier_to_label})
                return
            else:
                model = fields.get("model", [""])[0]
                llm_res = ask_llm("You are a helpful assistant. Be concise and precise.", prompt, model_name=model)
                self._send_json(llm_res)
                return
        elif action == "api_save":
            prompt = fields.get("prompt", [""])[0]
            results = json.loads(fields.get("results", ["{}"])[0])
            history = load_history()
            history.append({"query": prompt, "results": results})
            save_history(history)
            self._send_json({"status": "ok"})
            return

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _send(self, content: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        body = content.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(data).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args): pass

if __name__ == "__main__":
    load_env()
    print(f"🚀 День 5 Битва Моделей: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
