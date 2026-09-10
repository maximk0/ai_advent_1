#!/usr/bin/env python3
"""День 7: Сохранение контекста.
   Веб-интерфейс с персистентной историей и настройками.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8005
_LOCK = threading.Lock()

from simple_agent import SimpleAgent

# Глобальный экземпляр агента
agent = SimpleAgent()

# ============================================
# WEB ИНТЕРФЕЙС (HTML/CSS/JS)
# ============================================

PAGE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>Simple Agent — День 7 (Контекст)</title>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <style>
    :root {
      --bg-dark: #0f172a;
      --bg-card: #1e293b;
      --border: #334155;
      --text-main: #f1f5f9;
      --text-dim: #94a3b8;
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --accent: #a855f7;
    }

    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      margin: 0; padding: 0;
      background: var(--bg-dark);
      color: var(--text-main);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    /* Sidebar */
    .sidebar {
      width: 320px;
      flex-shrink: 0;
      background: var(--bg-card);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      padding: 20px;
      overflow-y: auto;
    }
    .sidebar h2 { font-size: 1.2rem; margin-top: 0; color: var(--text-main); }
    .config-group { margin-bottom: 20px; }
    .config-group label {
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-dim);
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .config-group input[type="text"],
    .config-group textarea,
    .config-group select {
      width: 100%;
      background: var(--bg-dark);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 10px;
      border-radius: 8px;
      font-family: inherit;
      font-size: 0.9rem;
    }
    .config-group textarea { min-height: 100px; resize: vertical; }

    .slider-container { display: flex; align-items: center; gap: 10px; }
    .slider-container input { flex: 1; }
    .slider-val { min-width: 35px; font-size: 0.8rem; font-family: monospace; }

    /* Main Area */
    .main {
      flex: 1;
      display: flex;
      flex-direction: column;
      position: relative;
      min-width: 0;
    }

    /* Chat Area */
    #chat-log {
      flex: 1;
      overflow-y: auto;
      padding: 40px 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .msg-wrapper {
      display: flex;
      flex-direction: column;
      max-width: 85%;
    }
    .msg-user { align-self: flex-end; }
    .msg-bot { align-self: flex-start; }

    .msg-bubble {
      padding: 12px 18px;
      border-radius: 16px;
      font-size: 0.95rem;
      line-height: 1.6;
      box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
      word-wrap: break-word;
      overflow-wrap: break-word;
    }
    .msg-user .msg-bubble {
      background: var(--primary);
      color: white;
      border-bottom-right-radius: 4px;
    }
    .msg-bot .msg-bubble {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-bottom-left-radius: 4px;
    }

    .msg-meta {
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-top: 6px;
      display: flex;
      gap: 10px;
    }
    .msg-user .msg-meta { justify-content: flex-end; }

    /* Input Area */
    .input-container {
      padding: 20px;
      background: var(--bg-dark);
      border-top: 1px solid var(--border);
    }
    .input-box {
      max-width: 900px;
      margin: 0 auto;
      display: flex;
      gap: 12px;
      background: var(--bg-card);
      padding: 8px;
      border-radius: 12px;
      border: 1px solid var(--border);
      align-items: flex-end;
    }
    .input-box textarea {
      flex: 1;
      background: transparent;
      border: none;
      color: var(--text-main);
      padding: 10px;
      font-family: inherit;
      font-size: 1rem;
      resize: none;
      max-height: 200px;
      outline: none;
    }
    .send-btn {
      background: var(--primary);
      color: white;
      border: none;
      width: 40px;
      height: 40px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
    }
    .send-btn:hover { background: var(--primary-hover); }
    .send-btn:disabled { background: var(--border); cursor: not-allowed; }

    /* Markdown Styling */
    .msg-bubble pre {
      background: #0f172a;
      padding: 12px;
      border-radius: 8px;
      overflow-x: auto;
      margin: 10px 0;
    }
    .msg-bubble code { font-family: 'JetBrains Mono', monospace; font-size: 0.9em; }
    .msg-bubble p { margin: 0 0 10px 0; }
    .msg-bubble p:last-child { margin-bottom: 0; }
    .msg-bubble ul, .msg-bubble ol { margin: 10px 0; padding-left: 20px; }

    /* Animations */
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    .msg-wrapper { animation: fadeIn 0.3s ease-out; }

    /* Scrollbars */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

    .loader {
      display: inline-block;
      width: 20px;
      height: 20px;
      border: 2px solid rgba(255,255,255,0.3);
      border-radius: 50%;
      border-top-color: #fff;
      animation: spin 1s ease-in-out infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Shimmer Effect */
    .shimmer-msg {
      width: 240px;
      height: 60px;
      position: relative;
      overflow: hidden;
      background: #1e293b;
      border-radius: 12px;
      border-bottom-left-radius: 4px;
      border: 1px solid #334155;
    }

    .shimmer-msg::after {
      content: "";
      position: absolute;
      top: 0;
      left: -150%;
      width: 150%;
      height: 100%;
      background: linear-gradient(
        to right,
        transparent 0%,
        rgba(255, 255, 255, 0.08) 50%,
        transparent 100%
      );
      animation: shimmer-anim 1.5s infinite linear;
    }

    @keyframes shimmer-anim {
      to {
        left: 100%;
      }
    }
  </style>
</head>
<body>

  <aside class="sidebar">
    <h2>⚙️ Настройки Агента</h2>

    <div class="config-group">
      <label>Системный промпт</label>
      <textarea id="sysPrompt" placeholder="Напр: Ты опытный программист...">Ты — полезный AI-ассистент.</textarea>
    </div>

    <div class="config-group">
      <label>Модель (OpenRouter)</label>
      <select id="modelSelect">
        <option value="openrouter/free" selected>Auto (Router Free)</option>
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
        <option value="ling/ling-3.0-flash-fin:free">Ling 3.0 Flash Fin (free)</option>
        <option value="dots/dots3-note-preview:free">Dots Studio: Dots3-Note Preview (free)</option>
      </select>
    </div>

    <div class="config-group">
      <label>Temperature: <span id="tempVal" class="slider-val">0.7</span></label>
      <div class="slider-container">
        <input type="range" id="tempSlider" min="0" max="2" step="0.1" value="0.7">
      </div>
    </div>

    <div class="config-group">
      <label>Top P: <span id="topPVal" class="slider-val">1.0</span></label>
      <div class="slider-container">
        <input type="range" id="topPSlider" min="0" max="1" step="0.05" value="1.0">
      </div>
    </div>

    <div class="config-group">
      <label>Top K: <span id="topKVal" class="slider-val">0</span></label>
      <div class="slider-container">
        <input type="range" id="topKSlider" min="0" max="100" step="1" value="0">
      </div>
    </div>

    <div style="margin-top: auto;">
      <button onclick="clearChat()" style="width: 100%; padding: 10px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">🗑️ Очистить историю</button>
    </div>
  </aside>

  <main class="main">
    <div id="chat-log">
      <div class="msg-wrapper msg-bot">
        <div class="msg-bubble">Привет! Я твой персональный агент (День 7). Я помню всё, что мы обсуждали, даже если ты перезагрузишь сервер. О чем хочешь поговорить?</div>
      </div>
    </div>

    <div class="input-container">
      <form id="chatForm" class="input-box">
        <textarea id="userInput" placeholder="Напишите сообщение..." rows="1" required autocomplete="off"></textarea>
        <button type="submit" id="sendBtn" class="send-btn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
      </form>
    </div>
  </main>

  <script>
    const chatLog = document.getElementById('chat-log');
    const chatForm = document.getElementById('chatForm');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');

    // Sliders
    const tempSlider = document.getElementById('tempSlider');
    const tempVal = document.getElementById('tempVal');
    tempSlider.oninput = () => tempVal.textContent = tempSlider.value;

    const topPSlider = document.getElementById('topPSlider');
    const topPVal = document.getElementById('topPVal');
    topPSlider.oninput = () => topPVal.textContent = topPSlider.value;

    const topKSlider = document.getElementById('topKSlider');
    const topKVal = document.getElementById('topKVal');
    topKSlider.oninput = () => topKVal.textContent = topKSlider.value;

    // Auto-resize textarea
    userInput.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = (this.scrollHeight) + 'px';
    });

    userInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.requestSubmit();
      }
    });

    marked.setOptions({
      highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
      },
      breaks: true
    });

    function addMessage(role, content, meta = null) {
      const wrapper = document.createElement('div');
      wrapper.className = `msg-wrapper msg-${role === 'user' ? 'user' : 'bot'}`;

      const bubble = document.createElement('div');
      bubble.className = 'msg-bubble';

      if (content === null) {
        // Loading state
        bubble.classList.add('shimmer-msg');
      } else {
        bubble.innerHTML = role === 'user' ? content.replace(/\\n/g, '<br>') : marked.parse(content);
      }

      wrapper.appendChild(bubble);

      if (meta) {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'msg-meta';
        metaDiv.innerHTML = `<span>🤖 ${meta.model}</span> <span>⏱️ ${meta.time}s</span>`;
        wrapper.appendChild(metaDiv);
      }

      chatLog.appendChild(wrapper);
      chatLog.scrollTop = chatLog.scrollHeight;
      return wrapper;
    }

    chatForm.onsubmit = async (e) => {
      e.preventDefault();
      const text = userInput.value.trim();
      if (!text) return;

      userInput.value = '';
      userInput.style.height = 'auto';
      addMessage('user', text);

      // Показываем шиммер перед запросом
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

        // Удаляем шиммер-сообщение перед добавлением реального
        chatLog.removeChild(loadingMsg);

        if (data.error) {
          addMessage('bot', '❌ Ошибка: ' + data.error);
          userInput.value = text; // Возвращаем текст при ошибке API
          userInput.dispatchEvent(new Event('input')); // Триггерим ресайз
        } else {
          addMessage('bot', data.content, { model: data.model, time: data.time });
        }
      } catch (err) {
        if (loadingMsg.parentNode) chatLog.removeChild(loadingMsg);
        addMessage('bot', '❌ Ошибка сети: ' + err.message);
        userInput.value = text; // Возвращаем текст при сетевой ошибке
        userInput.dispatchEvent(new Event('input')); // Триггерим ресайз
      } finally {
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
        userInput.focus();
      }
    };

    function saveCurrentConfig() {
      const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        temperature: tempSlider.value,
        top_p: topPSlider.value,
        top_k: topKSlider.value
      };
      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
    }

    // Навешиваем автосохранение на изменение настроек
    ['sysPrompt', 'modelSelect', 'tempSlider', 'topPSlider', 'topKSlider'].forEach(id => {
      const el = document.getElementById(id);
      el.addEventListener('change', saveCurrentConfig);
      if (el.tagName === 'TEXTAREA') {
        el.addEventListener('input', saveCurrentConfig);
        el.addEventListener('blur', saveCurrentConfig);
      }
    });

    async function clearChat() {
      if (!confirm('Очистить историю чата?')) return;
      await fetch('/api/clear', { method: 'POST' });
      chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">История очищена. О чем поговорим?</div></div>';
    }

    async function initApp() {
      try {
        const res = await fetch('/api/state');
        const state = await res.json();

        // 1. Восстанавливаем настройки
        if (state.config) {
          const c = state.config;
          document.getElementById('sysPrompt').value = c.system_prompt || '';
          document.getElementById('modelSelect').value = c.model || 'openrouter/free';

          tempSlider.value = c.temperature ?? 0.7;
          tempVal.textContent = tempSlider.value;

          topPSlider.value = c.top_p ?? 1.0;
          topPVal.textContent = topPSlider.value;

          topKSlider.value = c.top_k ?? 0;
          topKVal.textContent = topKSlider.value;
        }

        // 2. Восстанавливаем историю
        if (state.history && state.history.length > 0) {
          chatLog.innerHTML = ''; // Очищаем приветствие, если есть история
          state.history.forEach(m => {
            const isBot = m.role === 'assistant';
            const meta = (isBot && m.model) ? { model: m.model, time: m.time } : null;
            addMessage(isBot ? 'bot' : 'user', m.content, meta);
          });
        }
      } catch (e) {
        console.error("Failed to load state", e);
      }
    }

    window.addEventListener('DOMContentLoaded', initApp);
  </script>
</body>
</html>
"""

# ============================================
# СЕРВЕРНАЯ ЛОГИКА
# ============================================

def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip('/')
        if path == "/api/state":
            with _LOCK:
                self._send_json(agent.get_state())
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        body = PAGE.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8")

        # Определяем действие по пути, игнорируя лишние слэши
        path = self.path.rstrip('/')

        try:
            if path == "/api/chat":
                data = json.loads(raw_body)
                config = data.get("config", {})
                message = data.get("message", "")

                with _LOCK:
                    agent.set_config(config)
                    result = agent.chat(message)
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
                self.send_error(404, f"Endpoint {self.path} not found")
        except Exception as e:
            # Возвращаем JSON с ошибкой, чтобы фронтенд мог её отобразить
            self._send_json({"error": str(e)})

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(data).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    load_env()
    print(f"🚀 День 7 Simple Agent: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\\nСервер остановлен.")
        sys.exit(0)
