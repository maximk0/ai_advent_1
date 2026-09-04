#!/usr/bin/env python3
"""CLI и веб-чат: запрос в Gemini API, история отдельно от поля ввода.
   День 3: 5 чатов (4 способа в колонках + Саммари).
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
HISTORY_PATH = ROOT / "history.json"
MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
EXCLUDED_MODELS = ["nvidia/nemotron-3.5-content-safety:free"]
PORT = 8001

# ============================================
# ПРОМПТЫ ДЛЯ 4-Х МЕТОДОВ
# ============================================
PROMPTS = {
    "direct": "Дай прямой ответ на задачу БЕЗ пояснений и рассуждений. Только финальный результат.",
    "cot": "Реши задачу пошагово (Chain-of-Thought). Распиши каждое действие максимально подробно.",
    "prompt": "Сначала составь оптимальный и четкий промпт для решения этой задачи. Затем, используя этот промпт, реши задачу.",
    "experts": (
        "Представь, что ты — группа экспертов: Аналитик (ищет условия), Инженер (строит решение) и Критик (ищет ошибки). "
        "Дай итоговое согласованное решение от лица всей группы."
    ),
    "summary": (
        "Проведи сравнительный анализ 4-х вариантов решения одной и той же задачи (ниже). "
        "Ответь: 1. Отличаются ли ответы? 2. Какой способ дал наиболее точный результат и почему? "
        "3. Сделай итоговый вывод: какой метод лучше всего подходит для этой задачи."
    )
}

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>OpenRouter — День 3: 5 Чатов</title>
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
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px;
    }

    /* Сетка для 4-х колонок */
    .grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
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
      color: #764ba2;
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

    /* Блок Саммари */
    .summary-box {
      background: #fff;
      border-left: 5px solid #764ba2;
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 30px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .summary-title {
      font-weight: bold;
      font-size: 18px;
      margin-bottom: 15px;
      display: flex;
      align-items: center;
      gap: 8px;
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
    input:focus { border-color: #667eea; }
    button {
      padding: 0 30px;
      border: none;
      border-radius: 10px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      font-weight: bold;
      cursor: pointer;
    }

    .task-history-item {
      margin-bottom: 40px;
      padding-bottom: 20px;
      border-bottom: 2px dashed #ccc;
    }
    .user-query {
      background: #dbeafe;
      padding: 10px 15px;
      border-radius: 8px;
      margin-bottom: 15px;
      font-weight: 500;
    }
    
    #loader {
      display: none;
      position: fixed; inset: 0; z-index: 100;
      background: rgba(255,255,255,0.9);
      flex-direction: column; align-items: center; justify-content: center;
    }
    .spinner {
      width: 50px; height: 50px;
      border: 5px solid #f3f3f3; border-top: 5px solid #764ba2;
      border-radius: 50%; animation: spin 1s linear infinite;
      margin-bottom: 15px;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }

    @media (max-width: 1000px) {
      .grid { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 600px) {
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
      background: #eef; border-color: #764ba2; color: #764ba2;
    }
  </style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <div id="loader-text">Спрашиваем 4 экспертов...</div>
  </div>

    <div class="container">
    <h1>🧪 День 3 <span class="badge">5 чатов / 4 колонки</span></h1>
    <p class="subtitle">Сравнение четырех методов решения одной задачи в реальном времени</p>

    <div class="toolbar">
      <button class="example-btn" onclick="setExample('logical')">🧩 Логическая</button>
      <button class="example-btn" onclick="setExample('algorithm')">📊 Алгоритмическая</button>
      <button class="example-btn" onclick="setExample('analytical')">📈 Аналитическая</button>
      <button class="example-btn" onclick="setExample('riddle')">🧠 Загадка</button>
    </div>

    <div id="history">
      {history}
    </div>

    <div class="input-area">
      <form id="solveForm">
        <input type="text" name="prompt" id="promptInput" placeholder="Введите задачу..." required autocomplete="off">
        <button type="submit" id="submitBtn">🚀 Решить</button>
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
      logical: 'В городе 3 дома и 3 колодца. Можно ли проложить дорожки от каждого дома к каждому колодцу так, чтобы дорожки не пересекались?',
      algorithm: 'Дан массив чисел [3, 1, 4, 1, 5, 9, 2, 6, 5]. Отсортируйте его методом быстрой сортировки и объясните каждый шаг.',
      analytical: 'Компания продаёт товары онлайн. В прошлом месяце было 1000 посетителей, конверсия 3%, средний чек 5000 рублей. Рассчитайте выручку и предложите 3 способа увеличить её на 20%.',
      riddle: 'Что тяжелее: килограмм пуха или килограмм железа? Объясните свой ответ.'
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
      const prompt = document.getElementById('promptInput').value.strip ?
                     document.getElementById('promptInput').value.trim() :
                     document.getElementById('promptInput').value;
      if (!prompt) return;

      loader.style.display = 'flex';
      submitBtn.disabled = true;

      const methods = [
        {id: 'direct', label: '1/5: Прямой ответ...'},
        {id: 'cot', label: '2/5: Пошаговое решение...'},
        {id: 'prompt', label: '3/5: Создание промпта...'},
        {id: 'experts', label: '4/5: Консилиум экспертов...'}
      ];

      const results = {};

      try {
        for (const m of methods) {
          loaderText.textContent = m.label;
          const res = await fetch('/', {
            method: 'POST',
            body: new URLSearchParams({action: 'api_solve', method: m.id, prompt: prompt})
          });
          const data = await res.json();
          results[m.id] = data.result;
          results[m.id + '_model'] = data.model;
        }

        loaderText.textContent = '5/5: Сравнительный анализ...';
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
        results['summary'] = dataSum.result;
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

    // Скролл вниз
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

def ask_llm(system: str, user_text: str) -> dict:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key: return {"text": "Ошибка: Нет OPENROUTER_API_KEY в .env", "model": "error"}

    url = "https://openrouter.ai/api/v1/chat/completions"
    print(f"[OpenRouter] Запрос к {MODEL}...")

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text}
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost:8001",
        "X-Title": "Day 3 Adventure Chat"
    }

    # Попытки исключить нежелательные модели
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as res:
                resp_data = json.loads(res.read().decode("utf-8"))
                if "choices" in resp_data and len(resp_data["choices"]) > 0:
                    text = resp_data["choices"][0]["message"]["content"]
                    model_name = resp_data.get("model", MODEL)

                    # Если попалась модель из черного списка - пробуем еще раз
                    if model_name in EXCLUDED_MODELS:
                        print(f"[OpenRouter] Попалась исключенная модель {model_name}. Попытка {attempt+1}/3...")
                        continue

                    return {
                        "text": text,
                        "model": model_name
                    }
                return {"text": f"Ошибка: Некорректный ответ: {json.dumps(resp_data)}", "model": "error"}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except:
                msg = err_body
            return {"text": f"Ошибка API ({e.code}): {msg}", "model": "error"}
        except Exception as e:
            return {"text": f"Ошибка: {str(e)}", "model": "error"}

    return {"text": "Ошибка: Не удалось получить ответ после нескольких попыток.", "model": "error"}

def format_history_html(history: list) -> str:
    if not history:
        return '<div style="text-align:center; color:#999; padding:50px;">Здесь будут ваши решения...</div>'
    
    html_out = []
    for item in history:
        # Пропускаем старые записи, которые не соответствуют новому формату (для обратной совместимости)
        if not isinstance(item, dict) or "query" not in item or "results" not in item:
            continue

        q = html.escape(item["query"])
        res = item["results"]
        
        block = f"""
        <div class="task-history-item">
            <div class="user-query">❓ Задача: {q}</div>

            <div class="grid">
                <div class="card">
                    <div class="card-title">1. Прямой ответ</div>
                    <div class="model-badge">{html.escape(res.get('direct_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('direct',''))}</div>
                </div>
                <div class="card">
                    <div class="card-title">2. Chain-of-Thought</div>
                    <div class="model-badge">{html.escape(res.get('cot_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('cot',''))}</div>
                </div>
                <div class="card">
                    <div class="card-title">3. Prompt-First</div>
                    <div class="model-badge">{html.escape(res.get('prompt_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('prompt',''))}</div>
                </div>
                <div class="card">
                    <div class="card-title">4. Консилиум</div>
                    <div class="model-badge">{html.escape(res.get('experts_model',''))}</div>
                    <div class="card-content">{html.escape(res.get('experts',''))}</div>
                </div>
            </div>

            <div class="summary-box">
                <div class="summary-title">📊 Сравнительный анализ (Саммари)</div>
                <div class="model-badge">{html.escape(res.get('summary_model',''))}</div>
                <div class="card-content">{html.escape(res.get('summary',''))}</div>
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
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if action == "api_solve":
            method_id = fields.get("method", [""])[0]
            prompt = fields.get("prompt", [""])[0]

            if method_id == "summary":
                context_raw = fields.get("context", ["{}"])[0]
                context = json.loads(context_raw)
                summary_input = "\n\n".join([f"МЕТОД {m.upper()}:\n{res}" for m, res in context.items() if not m.endswith('_model')])
                llm_res = ask_llm(PROMPTS["summary"], f"Задача: {prompt}\n\nВарианты ответов:\n{summary_input}")
            else:
                system = PROMPTS.get(method_id, "")
                llm_res = ask_llm(system, prompt)

            self._send_json({"result": llm_res["text"], "model": llm_res["model"]})
            return

        if action == "api_save":
            prompt = fields.get("prompt", [""])[0]
            results_raw = fields.get("results", ["{}"])[0]
            results = json.loads(results_raw)

            history = load_history()
            history.append({"query": prompt, "results": results})
            save_history(history)

            self._send_json({"status": "ok"})
            return

        # Fallback
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
    print(f"🌐 Запуск: http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
