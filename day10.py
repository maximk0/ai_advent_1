#!/usr/bin/env python3
"""День 10: Управление контекстом — разные стратегии.
   Sliding Window, Sticky Facts, Branching.
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
PORT = 8010
_LOCK = threading.Lock()

agent = SimpleAgent()

# Дополнительный HTML для Sidebar
SIDEBAR_STATS_HTML = """
<div class="config-group">
  <label for="strategySelect">Стратегия контекста:</label>
  <select id="strategySelect" class="input-field" style="margin-top: 5px;">
    <option value="sliding">Sliding Window</option>
    <option value="facts">Sticky Facts</option>
    <option value="branching">Branching (Ветки)</option>
  </select>
</div>

<div id="factsBlock" class="config-group" style="display: none; margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">Sticky Facts (Memory):</label>
  <div id="factsList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4;">
    Нет извлеченных фактов
  </div>
</div>

<div id="branchingBlock" class="config-group" style="display: none; margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">Управление ветками:</label>
  <div style="display: flex; gap: 5px; margin-bottom: 8px;">
    <input type="text" id="newBranchName" placeholder="Имя ветки" class="input-field" style="flex: 1; font-size: 0.8rem;">
    <button onclick="createBranch()" class="btn-primary" style="padding: 4px 8px; font-size: 0.8rem;">+</button>
  </div>
  <div style="display: flex; gap: 5px; margin-bottom: 8px;">
    <select id="branchSelect" class="input-field" style="font-size: 0.8rem; flex: 1;"></select>
    <button onclick="deleteCurrentBranch()" class="btn-primary" style="padding: 4px 8px; font-size: 0.8rem; background: #ef4444;">×</button>
  </div>
  <div style="font-size: 0.7rem; color: var(--text-dim); margin-top: 5px; display: flex; justify-content: space-between; align-items: center;">
    <span>Текущая: <span id="currentBranchName" style="color: var(--primary);">main</span></span>
    <button onclick="clearAllBranches()" style="background: none; border: none; color: #ef4444; cursor: pointer; font-size: 0.7rem; text-decoration: underline; padding: 0;">Удалить все ветки</button>
  </div>
</div>

<div class="token-stats" style="margin-top: 20px; border-top: 1px solid var(--border); padding-top: 15px;">
  <div class="token-row">
    <span>Сэкономлено (от сжатия):</span>
    <span id="statSaved" class="token-val" style="color: #60a5fa;">0</span>
  </div>
  <div class="token-row">
    <span>Всего токенов (session):</span>
    <span id="statTotal" class="token-val">0</span>
  </div>
  <div class="token-row">
    <span>Цена:</span>
    <span id="statCost" class="token-val" style="color: #4ade80;">$0.000000</span>
  </div>
  <div class="progress-bar-container">
    <div id="ctxProgress" class="progress-bar-fill"></div>
  </div>
</div>
"""

EXTRA_SCRIPTS = """
document.getElementById('strategySelect').addEventListener('change', function() {
    saveCurrentConfig();
});

document.getElementById('branchSelect').addEventListener('change', function() {
    switchBranch(this.value);
});

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
            if (c.strategy) document.getElementById('strategySelect').value = c.strategy;
        }

        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach((m, i) => {
                const isBot = m.role === 'assistant';
                const meta = isBot ? { model: m.model, time: m.time, usage: m.usage } : {...m, historyIndex: i};
                addMessage(isBot ? 'bot' : 'user', m.content, meta);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я твой персональный агент. О чем хочешь поговорить?</div></div>';
        }

        if (typeof updateStats === 'function' && state.stats) updateStats(state.stats);

    } catch (e) {
        console.error("Failed to refresh UI", e);
    }
}

async function switchBranch(name) {
    const response = await fetch('/api/branch/switch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
    if (response.ok) refreshUI();
}

async function createBranch() {
    const nameInput = document.getElementById('newBranchName');
    const name = nameInput.value.trim();
    if (!name) return;
    const response = await fetch('/api/branch/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
    if (response.ok) {
        nameInput.value = '';
        refreshUI();
    }
}

async function clearAllBranches() {
    if (!confirm('Удалить ВСЕ ветки и очистить историю?')) return;
    const response = await fetch('/api/clear', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({clear_branches: true})
    });
    if (response.ok) refreshUI();
}

async function deleteCurrentBranch() {
    const branch = document.getElementById('branchSelect').value;
    if (branch === 'main') {
        alert("Главную ветку 'main' нельзя удалить.");
        return;
    }
    if (!confirm(`Удалить ветку "${branch}"?`)) return;

    const response = await fetch('/api/branch/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: branch})
    });
    if (response.ok) refreshUI();
}

function startEdit(index, btn) {
    const wrapper = btn.closest('.msg-wrapper');
    const bubble = wrapper.querySelector('.msg-bubble');
    const originalHTML = bubble.innerHTML;
    const originalText = bubble.innerText;

    bubble.innerHTML = `
        <textarea class="input-field" style="width:100%; min-height:60px; margin-bottom:5px; background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border); border-radius:4px; padding:5px;">${originalText}</textarea>
        <div style="display:flex; gap:5px; justify-content:flex-end;">
            <button class="cancel-edit-btn" style="padding:2px 8px; font-size:0.7rem; cursor:pointer; background:var(--bg-card); color:var(--text-dim); border:1px solid var(--border); border-radius:4px;">Отмена</button>
            <button class="save-edit-btn" onclick="saveEdit(${index}, this)" style="padding:2px 8px; font-size:0.7rem; cursor:pointer; background:var(--primary); color:white; border:none; border-radius:4px;">Сохранить</button>
        </div>
    `;

    const metaDiv = wrapper.querySelector('.msg-meta');
    const switcher = wrapper.querySelector('.version-switcher');
    if (metaDiv) metaDiv.style.display = 'none';
    if (switcher) switcher.style.display = 'none';

    bubble.querySelector('.cancel-edit-btn').onclick = () => {
        bubble.innerHTML = originalHTML;
        if (metaDiv) metaDiv.style.display = 'flex';
        if (switcher) switcher.style.display = 'flex';
    };
}

async function saveEdit(index, btn) {
    const bubble = btn.closest('.msg-bubble');
    const newContent = bubble.querySelector('textarea').value;
    const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        strategy: document.getElementById('strategySelect').value,
        temperature: document.getElementById('tempSlider').value,
        top_p: document.getElementById('topPSlider').value,
        top_k: document.getElementById('topKSlider').value
    };

    btn.disabled = true;
    btn.innerHTML = '<div class="loader" style="width:12px; height:12px; border-width:1px; display:inline-block;"></div>';
    const cancelBtn = bubble.querySelector('.cancel-edit-btn');
    if (cancelBtn) cancelBtn.style.display = 'none';

    try {
        const response = await fetch('/api/chat/edit', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ index: index, message: newContent, config: config })
        });

        if (response.ok) {
            refreshUI();
        } else {
            alert("Ошибка при сохранении");
            refreshUI();
        }
    } catch (e) {
        console.error(e);
        refreshUI();
    }
}

function updateStats(stats) {
    if (!stats) return;

    if (stats.strategy) {
        document.getElementById('strategySelect').value = stats.strategy;
    }

    const strategy = document.getElementById('strategySelect').value;
    document.getElementById('factsBlock').style.display = (strategy === 'facts') ? 'block' : 'none';
    document.getElementById('branchingBlock').style.display = (strategy === 'branching') ? 'block' : 'none';

    if (stats.facts && Object.keys(stats.facts).length > 0) {
        let html = '<ul style="padding-left: 15px; margin: 0;">';
        for (const [k, v] of Object.entries(stats.facts)) {
            html += `<li><b>${k}:</b> ${v}</li>`;
        }
        html += '</ul>';
        document.getElementById('factsList').innerHTML = html;
    } else {
        document.getElementById('factsList').textContent = "Нет извлеченных фактов";
    }

    if (stats.branches) {
        const sel = document.getElementById('branchSelect');
        const current = stats.current_branch || 'main';
        sel.innerHTML = '';
        stats.branches.forEach(b => {
            const opt = document.createElement('option');
            opt.value = b;
            opt.textContent = b;
            if (b === current) opt.selected = true;
            sel.appendChild(opt);
        });
        document.getElementById('currentBranchName').textContent = current;
    }

    document.getElementById('statTotal').textContent = stats.total_tokens || 0;
    document.getElementById('statSaved').textContent = stats.saved_tokens || 0;
    if (stats.cost !== undefined) {
        document.getElementById('statCost').textContent = '$' + stats.cost.toFixed(6);
    }

    const percent = Math.min((stats.total_tokens / 16000) * 100, 100);
    const fill = document.getElementById('ctxProgress');
    if (fill) fill.style.width = percent + '%';
}

const originalAddMessage = addMessage;
addMessage = function(role, content, meta) {
    const greeting = chatLog.querySelector('.msg-wrapper.msg-bot');
    if (greeting && greeting.innerText.includes("Привет! Я твой персональный агент") && role === 'user') {
        chatLog.removeChild(greeting);
    }

    const res = originalAddMessage(role, content, meta);

    if (role === 'user' && content !== null) {
        let metaDiv = res.querySelector('.msg-meta');
        if (!metaDiv) {
            metaDiv = document.createElement('div');
            metaDiv.className = 'msg-meta';
            res.appendChild(metaDiv);
        }

        const editBtn = document.createElement('span');
        editBtn.innerHTML = '✎ Изменить';
        editBtn.style = "cursor:pointer; color:var(--text-dim); font-size:0.7rem; border: 1px solid var(--border); padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.05); margin-left: 10px;";

        const historyIndex = (meta && meta.historyIndex !== undefined) ? meta.historyIndex : Array.from(chatLog.querySelectorAll('.msg-wrapper')).indexOf(res);

        editBtn.onclick = () => startEdit(historyIndex, editBtn);
        metaDiv.appendChild(editBtn);

        if (meta && meta.versions && meta.versions.length > 1) {
            const switcher = document.createElement('div');
            switcher.className = 'version-switcher';
            switcher.style = "font-size:0.7rem; color:var(--text-dim); margin-top:4px; display:flex; gap:8px; align-items:center; justify-content: flex-end; padding-right: 5px;";

            const prevBtn = document.createElement('span');
            prevBtn.innerHTML = '◀';
            prevBtn.style.cursor = 'pointer';
            prevBtn.style.padding = '2px 5px';

            const nextBtn = document.createElement('span');
            nextBtn.innerHTML = '▶';
            nextBtn.style.cursor = 'pointer';
            nextBtn.style.padding = '2px 5px';

            const curIdx = meta.current_version_index || 0;
            switcher.innerHTML = `<span>Версия ${curIdx + 1} / ${meta.versions.length}</span>`;
            switcher.prepend(prevBtn);
            switcher.append(nextBtn);

            prevBtn.onclick = () => {
                const newIdx = (curIdx - 1 + meta.versions.length) % meta.versions.length;
                switchBranch(meta.versions[newIdx]);
            };
            nextBtn.onclick = () => {
                const newIdx = (curIdx + 1) % meta.versions.length;
                switchBranch(meta.versions[newIdx]);
            };

            res.insertBefore(switcher, metaDiv);
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
  document.getElementById('charCount').textContent = 'Символов: 0';
  document.getElementById('tokenCount').textContent = '~0 токенов';

  addMessage('user', text);
  const loadingMsg = addMessage('bot', null);

  sendBtn.disabled = true;
  sendBtn.innerHTML = '<div class="loader"></div>';

  const config = {
    system_prompt: document.getElementById('sysPrompt').value,
    model: document.getElementById('modelSelect').value,
    temperature: tempSlider.value,
    top_p: topPSlider.value,
    top_k: topKSlider.value,
    strategy: document.getElementById('strategySelect').value
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
      userInput.value = text;
      userInput.dispatchEvent(new Event('input'));
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
    userInput.value = text;
    userInput.dispatchEvent(new Event('input'));
  } finally {
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
    userInput.focus();
  }
};

clearChat = async function() {
  if (!confirm('Очистить историю чата?')) return;
  const currentStrategy = document.getElementById('strategySelect').value;
  await fetch('/api/clear', { method: 'POST' });
  chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">История очищена. О чем поговорим?</div></div>';
  if (typeof updateStats === 'function') updateStats({total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, cost: 0, strategy: currentStrategy});
};

initApp = refreshUI;

saveCurrentConfig = function() {
    const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        temperature: document.getElementById('tempSlider').value,
        top_p: document.getElementById('topPSlider').value,
        top_k: document.getElementById('topKSlider').value,
        strategy: document.getElementById('strategySelect').value
    };
    fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    }).then(r => r.json()).then(data => {
        if (data.status === 'config_updated') {
           const strategy = config.strategy;
           document.getElementById('factsBlock').style.display = (strategy === 'facts') ? 'block' : 'none';
           document.getElementById('branchingBlock').style.display = (strategy === 'branching') ? 'block' : 'none';
        }
    });
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
            title="Simple Agent — День 10 (Strategies)",
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
                    agent.clear_history(clear_branches=data.get("clear_branches", False))
                self._send_json({"status": "cleared"})

            elif path == "/api/branch/create":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.create_branch(data.get("name", "new_branch"))
                self._send_json({"status": "branch_created"})

            elif path == "/api/branch/switch":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.switch_branch(data.get("name", "main"))
                self._send_json({"status": "branch_switched"})

            elif path == "/api/branch/delete":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.delete_branch(data.get("name", ""))
                self._send_json({"status": "branch_deleted"})

            elif path == "/api/chat/edit":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.set_config(data.get("config", {}))
                    result = agent.edit_message_and_branch(data.get("index"), data.get("message"))
                self._send_json(result)

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
    print(f"🚀 День 10 Стратегии контекста: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
