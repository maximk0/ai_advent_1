#!/usr/bin/env python3
"""CLI и веб-чат: исследование параметра Temperature.
   День 4: Сравнение ответов при temperature = 0, 0.7, 1.2.
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history_day4.json"
MODEL_DEFAULT = "openrouter/free"
EXCLUDED_MODELS = [
    "nvidia/nemotron-3.5-content-safety:free",
    "inclusion-ai/ling-3.0-flash-fin:free",
    "thinkingmachines/inkling:free"
]
PORT = 8002

# ============================================
# ПРОМПТЫ ДЛЯ ДНЯ 4
# ============================================
SUMMARY_PROMPT = (
    "Анализируй 3 ответа на задачу, полученных с разной температурой (0, 0.7, 1.2). "
    "Оцени каждый ответ по шкале от 0 до 10 по критериям: точность (accuracy), креативность (creativity), разнообразие (diversity). "
    "Верни СТРОГО JSON объект следующего вида (без лишнего текста и markdown): "
    "{\"scores\": {\"temp0\": {\"accuracy\": N, \"creativity\": N, \"diversity\": N}, "
    "\"temp07\": {\"accuracy\": N, \"creativity\": N, \"diversity\": N}, "
    "\"temp12\": {\"accuracy\": N, \"creativity\": N, \"diversity\": N}}, "
    "\"table\": [{\"temp\": \"T\", \"names\": \"Варианты названий\", \"desc\": \"Описание\"}], "
    "\"conclusion\": \"Краткое описание (1-2 предложения) того, как меняется креативность и предсказуемость при росте температуры.\"}"
)

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>OpenRouter — День 4: Температура</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
      margin: 0; padding: 20px;
      background: #f0f2f5;
      color: #1a1a2e;
    }
    .container { max-width: 1400px; margin: 0 auto; }
    h1 {
      display: flex; align-items: center; gap: 12px; margin-bottom: 5px;
    }
    .subtitle { color: #666; margin-bottom: 25px; }
    .badge {
      background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%);
      color: #333; padding: 4px 12px; border-radius: 20px; font-size: 14px;
      font-weight: bold;
    }

    /* Сетка для 3-х колонок */
    .grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 15px;
      margin-bottom: 20px;
    }

    .card {
      background: white;
      border-radius: 12px;
      padding: 15px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .card-title {
      font-weight: bold;
      font-size: 14px;
      color: #d63384;
      margin-bottom: 5px;
      padding-bottom: 5px;
      border-bottom: 1px solid #eee;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .model-badge {
      font-size: 10px;
      background: #f3f4f6;
      color: #6b7280;
      padding: 2px 6px;
      border-radius: 4px;
      display: inline-block;
      margin-bottom: 10px;
      font-family: monospace;
    }
    .card-content {
      font-size: 14px;
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-y: auto;
    }

    /* Блок Графика */
    .summary-box {
      background: #fff;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 30px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .short-summary {
      font-style: italic;
      color: #555;
      text-align: left;
      max-width: 800px;
      line-height: 1.4;
      padding-top: 15px;
      width: 100%;
    }
    .summary-table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 20px;
      font-size: 14px;
    }
    .summary-table th, .summary-table td {
      padding: 10px;
      border: 1px solid #eee;
      text-align: left;
    }
    .summary-table th {
      background: #fff5f5;
      color: #d63384;
    }

    /* Форма ввода */
    .input-area {
      position: sticky;
      bottom: 20px;
      background: white;
      padding: 20px;
      border-radius: 15px;
      box-shadow: 0 -5px 20px rgba(0,0,0,0.05);
      z-index: 10;
    }
    form { display: flex; gap: 10px; }
    input[type="text"] {
      flex: 1;
      padding: 15px;
      border: 2px solid #eef;
      border-radius: 10px;
      font-size: 16px;
      outline: none;
    }
    select {
      padding: 0 15px;
      border: 2px solid #eef;
      border-radius: 10px;
      background: white;
      font-family: inherit;
      cursor: pointer;
    }
    input:focus, select:focus { border-color: #ff9a9e; }

    .temp-config {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
      font-size: 13px;
      color: #666;
    }
    .temp-config input[type="number"] {
      width: 60px;
      padding: 5px;
      border: 1px solid #ddd;
      border-radius: 5px;
    }

    button {
      padding: 0 30px;
      border: none;
      border-radius: 10px;
      background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 100%);
      color: #333;
      font-weight: bold;
      cursor: pointer;
    }

    .task-history-item {
      margin-bottom: 40px;
      padding-bottom: 20px;
      border-bottom: 2px dashed #ccc;
    }
    .user-query {
      background: #fff5f5;
      padding: 10px 15px;
      border-radius: 8px;
      margin-bottom: 15px;
      font-weight: 500;
      border: 1px solid #ffe3e3;
    }

    #loader {
      display: none;
      position: fixed; inset: 0; z-index: 100;
      background: rgba(255,255,255,0.9);
      flex-direction: column; align-items: center; justify-content: center;
    }
    .spinner {
      width: 50px; height: 50px;
      border: 5px solid #f3f3f3; border-top: 5px solid #ff9a9e;
      border-radius: 50%; animation: spin 1s linear infinite;
      margin-bottom: 15px;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

    @media (max-width: 1000px) {
      .grid { grid-template-columns: 1fr; }
    }

    .toolbar {
      display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap;
    }
    .example-btn {
      padding: 8px 15px; background: #fff; border: 1px solid #ddd;
      border-radius: 8px; cursor: pointer; font-size: 13px;
      transition: all 0.2s;
    }
    .example-btn:hover {
      background: #fff5f5; border-color: #ff9a9e; color: #d63384;
    }
  </style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <div id="loader-text">Разогреваем нейросеть...</div>
  </div>

    <div class="container">
    <h1>🔥 День 4 <span class="badge">Температура (0, 0.7, 1.2)</span></h1>
    <p class="subtitle">Исследуем влияние случайности на точность и креативность ответов</p>

    <div class="toolbar">
      <button class="example-btn" onclick="setExample('creative')">🎨 Творческая</button>
      <button class="example-btn" onclick="setExample('logical')">🧩 Логическая</button>
      <button class="example-btn" onclick="setExample('code')">💻 Код</button>
      <button class="example-btn" onclick="setExample('poem')">✍️ Стихи</button>
    </div>

    <div id="history">
      {history}
    </div>

    <div class="input-area">
      <div class="temp-config">
        🌡️ Настроить температуры:
        <input type="number" id="t1" value="0" step="0.1" min="0" max="2" onchange="saveTemps()">
        <input type="number" id="t2" value="0.7" step="0.1" min="0" max="2" onchange="saveTemps()">
        <input type="number" id="t3" value="1.2" step="0.1" min="0" max="2" onchange="saveTemps()">
      </div>
      <form id="solveForm">
        <select id="modelSelect" onchange="saveModel()">
          <option value="openai/gpt-4o-mini">GPT-4o mini</option>
          <option value="google/gemma-4-31b-it:free">Gemma 4 31B (free)</option>
          <option value="google/gemma-4-26b-a4b-it:free">Gemma 4 26B A4B (free)</option>
          <option value="nvidia/nemotron-3-ultra-550b-a55b:free">Nemotron 3 Ultra (free)</option>
          <option value="nvidia/nemotron-3.5-lightning:free">Nemotron 3.5 Lightning (free)</option>
          <option value="minimax/minimax-m3:free">MiniMax M3 (free)</option>
          <option value="minimax/minimax-m2.7:free">MiniMax M2.7 (free)</option>
          <option value="z-ai/glm-5.2:free">GLM 5.2 (free)</option>
          <option value="liquid/lfm-2.5-2.6b:free">LiquidAI LFM2.5 2.6B (free)</option>
          <option value="thinkingmachines/inkling-small:free">Inkling Small (free)</option>
          <option value="poolside/laguna-s-2.1:free">Laguna S 2.1 (free)</option>
          <option value="poolside/laguna-xs-2.1:free">Laguna XS 2.1 (free)</option>
          <option value="cohere/north-mini-code:free">North Mini Code (free)</option>
          <option value="openrouter/free">Auto (Router Free)</option>
        </select>
        <input type="text" name="prompt" id="promptInput" placeholder="Введите запрос..." required autocomplete="off">
        <button type="submit" id="submitBtn">🚀 Сравнить</button>
      </form>
      <div style="margin-top: 10px;">
        <form method="post" action="/" style="display:inline;">
            <button type="submit" name="action" value="clear" style="background: #fee; color: #c33; padding: 5px 15px; font-size: 12px;">🗑️ Очистить</button>
        </form>
      </div>
    </div>
  </div>

  <script>
    const examples = {
      creative: 'Придумай концепцию нового фрукта, который растет на Марсе. Опиши вкус, вид и побочные эффекты.',
      logical: 'Если в комнате 3 человека, и каждый пожимает руку каждому, сколько всего рукопожатий будет? Объясни решение.',
      code: 'Напиши функцию на Python для вычисления чисел Фибоначчи, но используй только рекурсию и странные имена переменных.',
      poem: 'Напиши короткое хокку о программировании в пятницу вечером.'
    };

    function setExample(type) {
      document.getElementById('promptInput').value = examples[type];
      document.getElementById('promptInput').focus();
    }

    const solveForm = document.getElementById('solveForm');
    const loader = document.getElementById('loader');
    const loaderText = document.getElementById('loader-text');
    const submitBtn = document.getElementById('submitBtn');

    solveForm.onsubmit = async (e) => {
      e.preventDefault();
      const prompt = document.getElementById('promptInput').value.trim();
      const model = document.getElementById('modelSelect').value;
      if (!prompt) return;

      loader.style.display = 'flex';
      submitBtn.disabled = true;

      const t1 = document.getElementById('t1').value;
      const t2 = document.getElementById('t2').value;
      const t3 = document.getElementById('t3').value;

      const methods = [
        {id: 'temp0', label: `1/4: Температура ${t1}...`, value: t1},
        {id: 'temp07', label: `2/4: Температура ${t2}...`, value: t2},
        {id: 'temp12', label: `3/4: Температура ${t3}...`, value: t3}
      ];

      const results = {
        meta: { t1: t1, t2: t2, t3: t3 }
      };

      try {
        for (const m of methods) {
          loaderText.textContent = m.label;
          const res = await fetch('/', {
            method: 'POST',
            body: new URLSearchParams({action: 'api_solve', temperature: m.value, prompt: prompt, model: model})
          });
          const data = await res.json();
          results[m.id] = data.result;
          results[m.id + '_model'] = data.model;
        }

        loaderText.textContent = '4/4: Анализ и построение таблицы...';
        const resSum = await fetch('/', {
          method: 'POST',
          body: new URLSearchParams({
            action: 'api_solve',
            method: 'summary',
            prompt: prompt,
            model: model,
            context: JSON.stringify(results)
          })
        });
        const dataSum = await resSum.json();
        // Пытаемся распарсить JSON из ответа
        let summaryData = {};
        try {
          const jsonMatch = dataSum.result.match(/\{[\s\S]*\}/);
          summaryData = JSON.parse(jsonMatch ? jsonMatch[0] : dataSum.result);
        } catch(e) {
          summaryData = {conclusion: dataSum.result, scores: null, table: []};
        }
        results['chart'] = summaryData.scores;
        results['summary_table'] = summaryData.table;
        results['summary'] = summaryData.conclusion;
        results['summary_model'] = dataSum.model;

        // Сохраняем в историю
        await fetch('/', {
          method: 'POST',
          body: new URLSearchParams({action: 'api_save', prompt: prompt, results: JSON.stringify(results)})
        });

        window.location.reload();
      } catch (err) {
        alert('Ошибка при выполнении: ' + err);
        loader.style.display = 'none';
        submitBtn.disabled = false;
      }
    };

    // Функция инициализации сохраненных настроек
    function initSettings() {
      // Загружаем сохраненную модель
      const savedModel = localStorage.getItem('selectedModel');
      if (savedModel) {
        const select = document.getElementById('modelSelect');
        if (select) select.value = savedModel;
      }

      // Загружаем сохраненные температуры
      const t1 = localStorage.getItem('temp_t1');
      const t2 = localStorage.getItem('temp_t2');
      const t3 = localStorage.getItem('temp_t3');
      if (t1 !== null) document.getElementById('t1').value = t1;
      if (t2 !== null) document.getElementById('t2').value = t2;
      if (t3 !== null) document.getElementById('t3').value = t3;
    }

    function saveModel() {
      const select = document.getElementById('modelSelect');
      if (select) {
        localStorage.setItem('selectedModel', select.value);
      }
    }

    function saveTemps() {
      localStorage.setItem('temp_t1', document.getElementById('t1').value);
      localStorage.setItem('temp_t2', document.getElementById('t2').value);
      localStorage.setItem('temp_t3', document.getElementById('t3').value);
    }

    document.addEventListener('DOMContentLoaded', initSettings);
    window.scrollTo(0, document.body.scrollHeight);
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
    if not HISTORY_PATH.exists(): return []
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except: return []

def save_history(data: list) -> None:
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def ask_llm(system: str, user_text: str, temperature: float = 0.7, model_name: str | None = None) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key: return {"text": "Ошибка: Нет OPENROUTER_API_KEY в .env", "model": "error"}

    target_model = model_name or MODEL_DEFAULT
    url = "https://openrouter.ai/api/v1/chat/completions"
    print(f"[OpenRouter] Запрос к {target_model} (Temp: {temperature})...")

    body = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text}
        ],
        "temperature": temperature
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost:8002",
        "X-Title": "Day 4 Temperature Experiment"
    }

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=90) as res:
                resp_data = json.loads(res.read().decode("utf-8"))
                if "choices" in resp_data and len(resp_data["choices"]) > 0:
                    text = resp_data["choices"][0]["message"]["content"]
                    model_used = resp_data.get("model", target_model)
                    if model_used in EXCLUDED_MODELS:
                        print(f"[OpenRouter] Исключенная модель {model_used}. Попытка {attempt+1}/3...")
                        continue
                    return {"text": text, "model": model_used}
                return {"text": f"Ошибка: {json.dumps(resp_data)}", "model": "error"}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(err_body).get("error", {}).get("message", err_body)
            except: msg = err_body
            return {"text": f"Ошибка API ({e.code}): {msg}", "model": "error"}
        except Exception as e:
            return {"text": f"Ошибка: {str(e)}", "model": "error"}
    return {"text": "Ошибка после 3-х попыток", "model": "error"}

def format_history_html(history: list) -> str:
    if not history:
        return '<div style="text-align:center; color:#999; padding:50px;">Результаты эксперимента появятся здесь...</div>'

    html_out = []
    for item in history:
        if not isinstance(item, dict) or "query" not in item: continue
        q = html.escape(item["query"])
        res = item["results"]
        meta = res.get("meta", {"t1":"0","t2":"0.7","t3":"1.2"})

        block = f"""
        <div class="task-history-item">
            <div class="user-query">💬 Запрос: {q}</div>

            <div class="grid">
                <div class="card">
                    <div class="card-title">Температура {html.escape(str(meta.get('t1')))}</div>
                    <div class="model-badge">{html.escape(res.get('temp0_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('temp0',''))}</div>
                </div>
                <div class="card">
                    <div class="card-title">Температура {html.escape(str(meta.get('t2')))}</div>
                    <div class="model-badge">{html.escape(res.get('temp07_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('temp07',''))}</div>
                </div>
                <div class="card">
                    <div class="card-title">Температура {html.escape(str(meta.get('t3')))}</div>
                    <div class="model-badge">{html.escape(res.get('temp12_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('temp12',''))}</div>
                </div>
            </div>

            <div class="summary-box">
                <table class="summary-table">
                    <thead>
                        <tr>
                            <th>Температура</th>
                            <th>Варианты названий</th>
                            <th>Описание</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join([f"<tr><td>{html.escape(str(row.get('temp','')))}</td><td>{html.escape(str(row.get('names','')))}</td><td>{html.escape(str(row.get('desc','')))}</td></tr>" for row in res.get('summary_table', [])])}
                    </tbody>
                </table>

                <div class="short-summary">
                    <strong>Итог ({html.escape(res.get('summary_model',''))}):</strong> {html.escape(res.get('summary',''))}
                </div>
            </div>
        </div>
        """
        html_out.append(block)
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
            temp = float(fields.get("temperature", [0.7])[0])
            prompt = fields.get("prompt", [""])[0]
            method = fields.get("method", [""])[0]
            model = fields.get("model", [MODEL_DEFAULT])[0]

            if method == "summary":
                context = json.loads(fields.get("context", ["{}"])[0])
                meta = context.get("meta", {"t1":"0","t2":"0.7","t3":"1.2"})
                summary_input = "\\n\\n".join([f"TEMP {m.replace('temp','')}:\\n{res}" for m, res in context.items() if not m.endswith('_model') and m != 'meta'])

                # Делаем промпт динамическим
                dynamic_summary_prompt = SUMMARY_PROMPT.replace("(0, 0.7, 1.2)", f"({meta['t1']}, {meta['t2']}, {meta['t3']})")

                llm_res = ask_llm(dynamic_summary_prompt, f"Задача: {prompt}\\n\\nОтветы:\\n{summary_input}", temperature=0.3, model_name=model)
            else:
                llm_res = ask_llm("Ты — нейтральный помощник.", prompt, temperature=temp, model_name=model)

            self._send_json({"result": llm_res["text"], "model": llm_res["model"]})
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
    print(f"🌐 День 4 Запущен: http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
