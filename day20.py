#!/usr/bin/env python3
"""День 20: Orchestration MCP (Многосерверная оркестрация)
   Одновременная регистрация и вызов инструментов из 4 разных MCP-серверов:
   1. Project Inspector (mcp_server_project.py)
   2. Git Manager (mcp_server_git.py)
   3. 24/7 Scheduler (mcp_server_scheduler.py)
   4. Composed Pipeline (mcp_server_pipeline.py)
   С сохранением 100% сайдбара прошлых дней.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from simple_agent import SimpleAgent
from chat_ui import get_chat_page
from mcp_client import MCPClient

ROOT = Path(__file__).resolve().parent
PORT = 8020
_LOCK = threading.Lock()

# Инициализируем Агента
agent = SimpleAgent()

# Инициализируем ВСЕ 4 MCP КЛИЕНТА ДЛЯ ОРКЕСТРАЦИИ
project_client = MCPClient(ROOT / "mcp_server_project.py")
git_client = MCPClient(ROOT / "mcp_server_git.py")
scheduler_client = MCPClient(ROOT / "mcp_server_scheduler.py")
pipeline_client = MCPClient(ROOT / "mcp_server_pipeline.py")

# Полный HTML сайдбара: Дни 15-19 + День 20 (Multi-Server Orchestrator)
SIDEBAR_STATS_HTML = """
<!-- 1. ИНВАРИАНТЫ (Законы) -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #f87171;">🔒 Инварианты (Законы):</label>
  <div id="invList" style="font-size: 0.7rem; color: var(--text-dim); background: rgba(239, 68, 68, 0.05); padding: 8px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.2); max-height: 120px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;">
    <!-- Инварианты -->
  </div>
  <div style="display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-top: 8px; border: 1px dashed var(--border);">
    <span style="font-size: 0.65rem; font-weight: bold; color: var(--text-dim); text-transform: uppercase;">Новый закон:</span>
    <input type="text" id="newInvKey" placeholder="Название" class="input-field" style="font-size: 0.75rem; padding: 4px; height: auto;">
    <textarea id="newInvVal" placeholder="Текст закона..." class="input-field" style="font-size: 0.75rem; padding: 4px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;"></textarea>
    <button onclick="addNewInvariant()" style="padding: 4px; font-size: 0.75rem; background: #ef4444; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">Утвердить закон 🔒</button>
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

<!-- 6. ДЕНЬ 20: MULTI-SERVER ORCHESTRATOR -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #06b6d4;">🎛️ MCP Multi-Server Orchestrator (День 20):</label>
  <div style="background: rgba(6, 182, 212, 0.05); padding: 8px; border-radius: 6px; border: 1px solid rgba(6, 182, 212, 0.2); font-size: 0.75rem; margin-bottom: 8px; display: flex; flex-direction: column; gap: 4px;">
    <div><b style="color: var(--accent);">🔌 Серверов подключено:</b> <span id="orchServersCount" style="color: #4ade80;">4 / 4 (Active)</span></div>
    <div><b style="color: var(--accent);">🛠️ Всего инструментов:</b> <span id="orchToolsCount" style="color: #38bdf8;">14 tools</span></div>
  </div>

  <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px;">
    <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: bold; text-transform: uppercase;">Кросс-серверный сценарий:</span>
    <button onclick="runOrchestratedWorkflow()" style="width:100%; padding: 6px; font-size: 0.75rem; background: linear-gradient(135deg, #06b6d4, #3b82f6); border: none; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; box-shadow: 0 0 10px rgba(6,182,212,0.3);">⚡ Запустить оркестрацию (Project + Pipeline + Scheduler + Git)</button>
  </div>

  <div id="orchConsole" style="display: none; background: #000; padding: 6px; border-radius: 6px; font-family: monospace; font-size: 0.65rem; max-height: 130px; overflow-y: auto; color: #06b6d4; white-space: pre-wrap; border: 1px solid var(--border); line-height: 1.3;"></div>
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

EXTRA_SCRIPTS = """
async function refreshUI() {
    try {
        const res = await fetch('/api/state');
        const state = await res.json();

        // 0. Режим планирования
        if (state.config && state.config.planning_mode_enabled !== undefined) {
            const cb = document.getElementById('planning_mode_enabled');
            if (cb) cb.checked = state.config.planning_mode_enabled;
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
        invContainer.innerHTML = '';
        if (state.invariants && Object.keys(state.invariants).length > 0) {
            for (const [k, v] of Object.entries(state.invariants)) {
                const div = document.createElement('div');
                div.className = 'invariant-item';
                div.innerHTML = `<div style="font-weight:bold; color:#fca5a5; margin-bottom:2px;">${k}</div><div style="line-height:1.2;">${v}</div><span class="del-inv" onclick="deleteInv('${k}')">×</span>`;
                invContainer.appendChild(div);
            }
        } else { invContainer.textContent = 'Нет активных законов'; }

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

        // 5. ДЕНЬ 20: Orchestrator Status
        if (state.orchestrator_mcp) {
            const activeCount = state.orchestrator_mcp.active_servers || 4;
            const toolsCount = state.orchestrator_mcp.total_tools || 14;
            document.getElementById('orchServersCount').textContent = `${activeCount} / 4 (Active)`;
            document.getElementById('orchToolsCount').textContent = `${toolsCount} tools`;
        }

        // Чат
        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach(m => {
                const isBot = m.role === 'assistant';
                addMessage(isBot ? 'bot' : 'user', m.content, isBot ? {model: m.model, time: m.time, usage: m.usage} : null);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я агент с **Многосерверной Оркестрацией MCP (День 20)**. Подключено 4 независимых сервера (Project Inspector, Git Manager, Scheduler, Pipeline). Напиши сложную задачу, и я сам выберу нужные инструменты с разных серверов! 🎛️⚡</div></div>';
        }

        if (state.stats) {
            document.getElementById('statTotal').textContent = state.stats.total_tokens || 0;
            document.getElementById('statCost').textContent = '$' + (state.stats.cost || 0).toFixed(6);
        }
    } catch (e) { console.error(e); }
}

async function checkPopups() {
    try {
        const res = await fetch('/api/mcp/scheduler/call', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tool: 'get_unshown_popups', args: {}})
        });
        const data = await res.json();
        if (data.result) {
            const parsed = JSON.parse(data.result);
            if (parsed.popups && parsed.popups.length > 0) {
                parsed.popups.forEach(p => {
                    showToastNotification(`⏰ ${p.text} (${p.target_time})`);
                });
                refreshUI();
            }
        }
    } catch(e) {}
}

function showToastNotification(text) {
    let toast = document.getElementById('toastNotification');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toastNotification';
        toast.style = 'position:fixed; top:20px; right:20px; z-index:9999; background:#f59e0b; color:#000; padding:12px 18px; border-radius:10px; font-weight:bold; font-size:0.85rem; box-shadow:0 4px 15px rgba(245,158,11,0.5); border:2px solid #fff; max-width:320px;';
        document.body.appendChild(toast);
    }
    toast.innerHTML = `🔔 <b>СРАБОТАЛО НАПОМИНАНИЕ 24/7:</b><br>${text}`;
    toast.style.display = 'block';
    setTimeout(() => { if (toast) toast.style.display = 'none'; }, 8000);
}

setInterval(checkPopups, 3000);

async function runOrchestratedWorkflow() {
    const consoleEl = document.getElementById('orchConsole');
    consoleEl.style.display = 'block';
    consoleEl.textContent = `⚡ Запуск кросс-серверного оркестрационного сценария...\\n( Project Inspector ➔ Pipeline Search ➔ Scheduler Reminder ➔ Git Push )`;

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message: "Проверь структуру проекта через Project Inspector, выполни поиск и сохранение отчета через Pipeline, поставь напоминание через 30 секунд в Scheduler и сделай git push в ветку day20!",
                config: {
                    system_prompt: document.getElementById('sysPrompt').value,
                    model: document.getElementById('modelSelect').value
                }
            })
        });
        const data = await res.json();
        consoleEl.textContent += `\\n\\n✅ Флоу оркестрации завершен!\\nОтвет агента:\\n${data.content || data.error}`;
        refreshUI();
    } catch(e) {
        consoleEl.textContent += `\\n❌ Ошибка оркестрации: ${e.message}`;
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
        if (content.includes("🎛️") || content.includes("Оркестратор") || content.includes("пайплайн")) ind += `<span style="background:rgba(6,182,212,0.2); border:1px solid #06b6d4; padding:2px 6px; border-radius:4px; font-size:0.75rem;">🎛️ Orchestration MCP</span>`;
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
        path = self.path.rstrip('/')
        if path == "/api/state":
            with _LOCK:
                state = agent.get_state()
                # Собираем инструменты со ВСЕХ 4 серверов
                t1 = project_client.refresh_tools()
                t2 = git_client.refresh_tools()
                t3 = scheduler_client.refresh_tools()
                t4 = pipeline_client.refresh_tools()
                all_tools = t1 + t2 + t3 + t4

                state["orchestrator_mcp"] = {
                    "active_servers": sum([1 for c in [project_client, git_client, scheduler_client, pipeline_client] if c.is_connected]),
                    "total_tools": len(all_tools)
                }
                self._send_json(state)
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        page_html = get_chat_page(title="Multi-Server Orchestrator MCP — День 20", extra_sidebar_html=SIDEBAR_STATS_HTML, extra_scripts=EXTRA_SCRIPTS)
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
                user_msg = data.get("message", "")
                with _LOCK:
                    agent.set_config(data.get("config", {}))
                    # Передаем ВСЕ 4 клиента в нативный Tool Calling Loop
                    result = agent.chat(user_msg, mcp_clients=[
                        project_client,
                        git_client,
                        scheduler_client,
                        pipeline_client
                    ])

                self._send_json(result)

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

            elif path == "/api/mcp/scheduler/call":
                data = json.loads(raw_body)
                tool_name = data.get("tool", "")
                args = data.get("args", {})
                res = scheduler_client.call_tool(tool_name, args)

                if tool_name == "get_unshown_popups":
                    try:
                        parsed = json.loads(res)
                        popups = parsed.get("popups", [])
                        if popups:
                            with _LOCK:
                                for p in popups:
                                    popup_text = f"🔔 **[СРАБОТАЛО НАПОМИНАНИЕ ПЛАНИРОВЩИКА 24/7]**:\n\n⏰ **{p.get('text')}**\n*(Время срабатывания: {p.get('target_time')})*"
                                    agent.history.append({
                                        "role": "assistant",
                                        "content": popup_text,
                                        "model": "24/7 MCP Scheduler",
                                        "time": 0.01,
                                        "usage": {}
                                    })
                                agent._save_state()
                    except Exception as e:
                        print(f"Error handling popups in history: {e}")

                self._send_json({"result": res})

            elif path == "/api/mcp/git/call":
                data = json.loads(raw_body)
                tool_name = data.get("tool", "")
                args = data.get("args", {})
                res = git_client.call_tool(tool_name, args)
                self._send_json({"result": res})

            elif path == "/api/mcp/pipeline/call":
                data = json.loads(raw_body)
                tool_name = data.get("tool", "")
                args = data.get("args", {})
                res = pipeline_client.call_tool(tool_name, args)
                self._send_json({"result": res})

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
    print(f"🚀 День 20 Multi-Server Orchestrator MCP Agent & Sidebar: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        project_client.close()
        git_client.close()
        scheduler_client.close()
        pipeline_client.close()
        sys.exit(0)
