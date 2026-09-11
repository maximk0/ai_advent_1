#!/usr/bin/env python3
"""День 8: Работа с токенами.
   Рефакторинг UI и визуализация потребления контекста.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from simple_agent import SimpleAgent
from chat_ui import get_chat_page

ROOT = Path(__file__).resolve().parent
PORT = 8006
_LOCK = threading.Lock()

agent = SimpleAgent()

# Дополнительный HTML для Sidebar
SIDEBAR_STATS_HTML = """
<div class="token-stats">
  <div class="token-row">
    <span>Всего токенов:</span>
    <span id="statTotal" class="token-val">0</span>
  </div>
  <div class="token-row">
    <span>Входящие (last):</span>
    <span id="statIn" class="token-val">0</span>
  </div>
  <div class="token-row">
    <span>Исходящие (last):</span>
    <span id="statOut" class="token-val">0</span>
  </div>
  <div class="token-row" style="margin-top: 8px; border-top: 1px solid var(--border); padding-top: 4px;">
    <span>Примерная цена:</span>
    <span id="statCost" class="token-val" style="color: #4ade80;">$0.000000</span>
  </div>
  <div class="progress-bar-container">
    <div id="ctxProgress" class="progress-bar-fill"></div>
  </div>
  <div style="font-size: 0.6rem; text-align: center; color: var(--text-dim); margin-top: 4px;">Заполнение окна (8k)</div>
</div>

<div class="config-group" style="margin-top: 10px;">
  <label class="checkbox-group">
    <input type="checkbox" id="context_compression" checked>
    <span>Сжимать токены (OpenRouter)</span>
  </label>
</div>
"""

# Дополнительный JS для обновления статистики
EXTRA_SCRIPTS = """
function updateStats(stats) {
  if (!stats) return;
  document.getElementById('statTotal').textContent = stats.total_tokens || 0;
  document.getElementById('statIn').textContent = stats.last_prompt_tokens || 0;

  if (stats.cost !== undefined) {
    document.getElementById('statCost').textContent = '$' + stats.cost.toFixed(6);
  }

  const percent = Math.min((stats.total_tokens / 8000) * 100, 100);
  const fill = document.getElementById('ctxProgress');
  fill.style.width = percent + '%';

  if (percent > 90) fill.style.background = '#ef4444';
  else if (percent > 70) fill.style.background = '#f59e0b';
  else fill.style.background = 'linear-gradient(to right, #6366f1, #a855f7)';
}

// Слушатель для нового чекбокса
document.getElementById('context_compression').addEventListener('change', saveCurrentConfig);

// Обновление Out tokens
const originalAddMessage = addMessage;
addMessage = function(role, content, meta) {
    const res = originalAddMessage(role, content, meta);
    if (meta && meta.usage) {
        const el = document.getElementById('statOut');
        if (el) el.textContent = meta.usage.completion_tokens || 0;
    }
    return res;
};
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip('/')
        if path == "/api/state":
            with _LOCK:
                self._send_json(agent.get_state())
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")

        page_html = get_chat_page(
            title="Simple Agent — День 8 (Токены)",
            extra_sidebar_html=SIDEBAR_STATS_HTML,
            extra_scripts=EXTRA_SCRIPTS
        )

        body = page_html.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8")
        path = self.path.rstrip('/')

        try:
            if path == "/api/chat":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.set_config(data.get("config", {}))
                    result = agent.chat(data.get("message", ""))
                self._send_json(result)

            elif path == "/api/config":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.set_config(data)
                self._send_json({"status": "config_updated"})

            elif path == "/api/clear":
                with _LOCK:
                    agent.clear_history()
                self._send_json({"status": "cleared"})

            else:
                self.send_error(404)
        except Exception as e:
            self._send_json({"error": str(e)})

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(data).encode("utf-8")
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
    print(f"🚀 День 8 Работа с токенами: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
