#!/usr/bin/env python3
"""День 11: Многоуровневая система памяти агента (STM, WM, LTM).
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
PORT = 8011
_LOCK = threading.Lock()

agent = SimpleAgent()

SIDEBAR_STATS_HTML = """
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">🧠 Long-Term Memory (LTM):</label>
  <div id="ltmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 150px; overflow-y: auto; margin-bottom: 8px;">
    Нет долговременных фактов
  </div>

  <div style="display: flex; flex-direction: column; gap: 5px; background: rgba(0,0,0,0.2); padding: 6px; border-radius: 4px;">
    <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: bold;">Ручная фиксация в LTM:</span>
    <input type="text" id="manualLtmKey" placeholder="Ключ (напр. Стиль)" class="input-field" style="font-size: 0.75rem; padding: 4px 8px; height: auto; background: var(--bg-dark); color: white; border: 1px solid var(--border); border-radius: 4px;">
    <input type="text" id="manualLtmVal" placeholder="Значение (напр. Type Hints)" class="input-field" style="font-size: 0.75rem; padding: 4px 8px; height: auto; background: var(--bg-dark); color: white; border: 1px solid var(--border); border-radius: 4px;">
    <button onclick="pinToLtmManual()" style="padding: 4px; font-size: 0.75rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: 600;">Зафиксировать в LTM</button>
  </div>
</div>

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">🛠 Working Memory (WM):</label>
  <div id="wmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 150px; overflow-y: auto;">
    Нет активных данных задачи
  </div>
</div>

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">⏱ Short-Term Memory (STM):</label>
  <div id="stmStatus" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4;">
    Записей в STM: 0 (Окно: 6 реплик)
  </div>
</div>

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
</style>
"""

EXTRA_SCRIPTS = """
async function refreshUI() {
    try {
        const res = await fetch('/api/state');
        const state = await res.json();

        if (state.config) {
            const c = state.config;
            document.getElementById('sysPrompt').value = c.system_prompt || '';
            document.getElementById('modelSelect').value = c.model || 'openrouter/free';
            document.getElementById('tempSlider').value = c.temperature ?? 0.7;
            document.getElementById('tempVal').textContent = document.getElementById('tempSlider').value;
            document.getElementById('topPSlider').value = c.top_p ?? 1.0;
            document.getElementById('topPVal').textContent = document.getElementById('topPSlider').value;
            document.getElementById('topKSlider').value = c.top_k ?? 0;
            document.getElementById('topKVal').textContent = document.getElementById('topKSlider').value;
        }

        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach((m) => {
                const isBot = m.role === 'assistant';
                const meta = isBot ? { model: m.model, time: m.time, usage: m.usage } : null;
                addMessage(isBot ? 'bot' : 'user', m.content, meta);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я твой многоуровневый агент памяти. Давайте протестируем STM, WM и LTM!</div></div>';
        }

        if (state.stats) updateMemoryStats(state.stats);

    } catch (e) {
        console.error("Failed to refresh UI", e);
    }
}

async function pinToLtmManual() {
    const keyInput = document.getElementById('manualLtmKey');
    const valInput = document.getElementById('manualLtmVal');
    const key = keyInput.value.trim();
    const val = valInput.value.trim();
    if (!key || !val) return alert("Заполните ключ и значение");

    const response = await fetch('/api/memory/pin_ltm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, value: val})
    });
    if (response.ok) {
        keyInput.value = '';
        valInput.value = '';
        refreshUI();
    }
}

function updateMemoryStats(stats) {
    if (!stats) return;

    // Обновление LTM
    if (stats.ltm && Object.keys(stats.ltm).length > 0) {
        let html = '<ul style="padding-left: 15px; margin: 0;">';
        for (const [k, v] of Object.entries(stats.ltm)) {
            html += `<li><b>${k}:</b> ${v}</li>`;
        }
        html += '</ul>';
        document.getElementById('ltmList').innerHTML = html;
    } else {
        document.getElementById('ltmList').textContent = "Нет долговременных фактов";
    }

    // Обновление WM
    if (stats.wm && Object.keys(stats.wm).length > 0) {
        let html = '<ul style="padding-left: 15px; margin: 0;">';
        for (const [k, v] of Object.entries(stats.wm)) {
            html += `<li><b>${k}:</b> ${v}</li>`;
        }
        html += '</ul>';
        document.getElementById('wmList').innerHTML = html;
    } else {
        document.getElementById('wmList').textContent = "Нет активных данных задачи";
    }

    // Обновление STM
    const historyLen = stats.history_len || 0;
    document.getElementById('stmStatus').textContent = `Записей в STM: ${historyLen} (Окно: 6 реплик)`;

    document.getElementById('statTotal').textContent = stats.total_tokens || 0;
    if (stats.cost !== undefined) {
        document.getElementById('statCost').textContent = '$' + stats.cost.toFixed(6);
    }
}

// Кастомизируем addMessage для красивого отображения источников знаний
const originalAddMessage = addMessage;
addMessage = function(role, content, meta) {
    const res = originalAddMessage(role, content, meta);

    if (role === 'bot' && content) {
        let indicatorsHtml = "";
        if (content.includes("🧠")) {
            indicatorsHtml += `<span style="background: rgba(168,85,247,0.2); border: 1px solid var(--accent); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 5px;">🧠 LTM</span>`;
        }
        if (content.includes("🛠")) {
            indicatorsHtml += `<span style="background: rgba(59,130,246,0.2); border: 1px solid #3b82f6; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem;">🛠 WM</span>`;
        }

        if (indicatorsHtml) {
            const metaDiv = res.querySelector('.msg-meta');
            if (metaDiv) {
                const indContainer = document.createElement('div');
                indContainer.style = "margin-top: 5px; display: flex; gap: 5px; align-items: center;";
                indContainer.innerHTML = `<span style="font-size: 0.7rem; color: var(--text-dim); margin-right: 5px;">Источник:</span> ${indicatorsHtml}`;
                res.insertBefore(indContainer, metaDiv);
            }
        }
    }
    return res;
};

chatForm.onsubmit = async (e) => {
  e.preventDefault();
  const text = userInput.value.trim();
  if (!text) return;

  userInput.value = '';
  userInput.style.height = 'auto';

  addMessage('user', text);
  const loadingMsg = addMessage('bot', null);

  sendBtn.disabled = true;
  sendBtn.innerHTML = '<div class="loader"></div>';

  const config = {
    system_prompt: document.getElementById('sysPrompt').value,
    model: document.getElementById('modelSelect').value,
    temperature: tempSlider.value,
    top_p: topPSlider.value,
    top_k: topKSlider.value
  };

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, config: config })
    });
    const data = await response.json();

    chatLog.removeChild(loadingMsg);

    if (data.error) {
      addMessage('bot', '❌ Ошибка: ' + data.error);
    } else {
      addMessage('bot', data.content, {
          model: data.model,
          time: data.time,
          usage: data.usage
      });
      refreshUI();
    }
  } catch (err) {
    if (loadingMsg.parentNode) chatLog.removeChild(loadingMsg);
    addMessage('bot', '❌ Ошибка сети: ' + err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
    userInput.focus();
  }
};

clearChat = async function() {
  if (!confirm('Очистить историю чата? (Память WM и LTM сохранится)')) return;
  await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: false}) });
  refreshUI();
};

resetAllData = async function() {
  if (!confirm('Вы уверены, что хотите сбросить ВСЕ данные? Это удалит историю чата, рабочую память (WM) и долговременную память (LTM)!')) return;
  await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: true}) });
  refreshUI();
};

initApp = refreshUI;
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
            title="Multi-Layer Memory Agent — День 11",
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
                data = {}
                if raw_body:
                    try: data = json.loads(raw_body)
                    except: pass
                with _LOCK:
                    agent.clear_history(clear_all=data.get("clear_all", False))
                self._send_json({"status": "cleared"})

            elif path == "/api/memory/pin_ltm":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.pin_to_ltm(data.get("key", ""), data.get("value", ""))
                self._send_json({"status": "pinned"})

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
    print(f"🚀 День 11 Многоуровневая память агента: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
