#!/usr/bin/env python3
"""День 17: Первый инструмент MCP (Точечный Git Push & Комментарии с кнопкой скопировать)
   Интеграция точечного Git MCP сервера, сохранение 100% сайдбара и диалога с нейросетью.
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
PORT = 8017
_LOCK = threading.Lock()

# Инициализируем Агента
agent = SimpleAgent()

# Инициализируем MCP клиент для общения с mcp_server_git.py
mcp_client = MCPClient(ROOT / "mcp_server_git.py")

# Полный HTML сайдбара: День 15 + День 16 + День 17 (Git MCP)
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

<!-- 6. ДЕНЬ 17: GIT MCP ASSIGNMENT & COPY COMMENTS -->
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #38bdf8;">🐙 Git MCP Assignment (Точечный Пуш & Скопировать):</label>
  <div style="background: rgba(56, 189, 248, 0.05); padding: 8px; border-radius: 6px; border: 1px solid rgba(56, 189, 248, 0.2); font-size: 0.75rem; margin-bottom: 8px; display: flex; flex-direction: column; gap: 4px;">
    <div><b style="color: var(--accent);">Статус Git MCP:</b> <span id="mcpStatus" style="color: #4ade80;">...</span></div>
    <div><b style="color: var(--accent);">Сервер:</b> <span id="mcpServerName" style="color: var(--text-main);">...</span></div>
  </div>

  <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px;">
    <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: bold; text-transform: uppercase;">Параметры сдачи:</span>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
      <input type="text" id="gitDayNum" value="17" placeholder="День (17)" class="input-field" style="font-size: 0.7rem; padding: 3px 6px; height: auto;">
      <input type="text" id="gitBranch" value="day17" placeholder="Ветка (day17)" class="input-field" style="font-size: 0.7rem; padding: 3px 6px; height: auto;">
    </div>
    <input type="text" id="gitTargetFiles" value="day17.py, mcp_server_git.py, README.md" placeholder="Файлы (day17.py, mcp_server_git.py)" class="input-field" style="font-size: 0.7rem; padding: 3px 6px; height: auto;">
    <input type="text" id="gitVideoLink" value="https://youtu.be/day17_git_mcp" placeholder="Ссылка на видео" class="input-field" style="font-size: 0.7rem; padding: 3px 6px; height: auto;">
    <textarea id="gitLearnedInfo" placeholder="Новые концепции для README..." class="input-field" style="font-size: 0.7rem; padding: 4px; min-height: 40px; height: 40px; resize: vertical;">Первый инструмент MCP, точечный Git commit & push выбранных файлов, автогенерация README.md для веток и кнопки быстрой вставки комментариев в Google Таблицу.</textarea>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-top: 4px;">
      <button onclick="runGitStatusCheck()" style="padding: 4px; font-size: 0.65rem; background: var(--border); border: none; border-radius: 4px; color: white; cursor: pointer;">🔍 Статус Git</button>
      <button onclick="runCreateReadme()" style="padding: 4px; font-size: 0.65rem; background: #4ade80; border: none; border-radius: 4px; color: #000; font-weight: bold; cursor: pointer;">📝 Создать README</button>
      <button onclick="runGitPush()" style="padding: 4px; font-size: 0.65rem; background: #38bdf8; border: none; border-radius: 4px; color: #000; font-weight: bold; cursor: pointer; grid-column: span 2;">🚀 Точечный Git Push выбранных файлов</button>
      <button onclick="runFormatComments()" style="padding: 4px; font-size: 0.65rem; background: #a855f7; border: none; border-radius: 4px; color: white; font-weight: bold; cursor: pointer; grid-column: span 2;">📋 Сформировать комментарии для Таблицы</button>
    </div>
  </div>

  <!-- БЛОК С ГОТОВЫМИ КОММЕНТАРИЯМИ И КНОПКАМИ СКОПИРОВАТЬ -->
  <div id="commentsOutputBlock" style="display: none; background: rgba(168, 85, 247, 0.1); border: 1px solid var(--accent); padding: 8px; border-radius: 6px; margin-bottom: 8px; flex-direction: column; gap: 8px;">
    <span style="font-size: 0.7rem; font-weight: bold; color: var(--accent);">Готовые комментарии для Google Таблицы:</span>

    <div style="display: flex; flex-direction: column; gap: 2px;">
      <span style="font-size: 0.65rem; color: var(--text-dim);">1. Комментарий с кодом:</span>
      <div style="display: flex; gap: 4px;">
        <input type="text" id="codeCommentTxt" readonly class="input-field" style="font-size: 0.65rem; padding: 2px 4px; flex: 1; height: auto; background: #000; color: #4ade80; font-family: monospace;">
        <button onclick="copyToClipboard('codeCommentTxt', 'btnCopyCode')" id="btnCopyCode" style="padding: 2px 6px; font-size: 0.65rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">📋 Скопировать</button>
      </div>
    </div>

    <div style="display: flex; flex-direction: column; gap: 2px;">
      <span style="font-size: 0.65rem; color: var(--text-dim);">2. Комментарий с видео:</span>
      <div style="display: flex; gap: 4px;">
        <input type="text" id="videoCommentTxt" readonly class="input-field" style="font-size: 0.65rem; padding: 2px 4px; flex: 1; height: auto; background: #000; color: #a855f7; font-family: monospace;">
        <button onclick="copyToClipboard('videoCommentTxt', 'btnCopyVideo')" id="btnCopyVideo" style="padding: 2px 6px; font-size: 0.65rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">📋 Скопировать</button>
      </div>
    </div>
  </div>

  <div id="mcpConsole" style="display: none; background: #000; padding: 6px; border-radius: 6px; font-family: monospace; font-size: 0.65rem; max-height: 120px; overflow-y: auto; color: #38bdf8; white-space: pre-wrap; border: 1px solid var(--border); line-height: 1.3;"></div>
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

        // 5. ДЕНЬ 17: Git MCP Tools
        if (state.mcp) {
            document.getElementById('mcpStatus').textContent = state.mcp.is_connected ? '🟢 Активен (stdio)' : '🔴 Отключен';
            document.getElementById('mcpStatus').style.color = state.mcp.is_connected ? '#4ade80' : '#f87171';
            const sInfo = state.mcp.server_info || {};
            document.getElementById('mcpServerName').textContent = `${sInfo.name || 'git-server'} v${sInfo.version || '1.0.0'}`;
        }

        // Чат
        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach(m => {
                const isBot = m.role === 'assistant';
                addMessage(isBot ? 'bot' : 'user', m.content, isBot ? {model: m.model, time: m.time, usage: m.usage} : null);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я агент с **Точечным Git MCP Сервером**. Попроси меня «Сдай задание» — я проверю статус Git, помогу выбрать ветку и файлы, сделаю push на GitHub и дам готовые комментарии с кнопками скопировать! 🐙🚀</div></div>';
        }

        if (state.stats) {
            document.getElementById('statTotal').textContent = state.stats.total_tokens || 0;
            document.getElementById('statCost').textContent = '$' + (state.stats.cost || 0).toFixed(6);
        }
    } catch (e) { console.error(e); }
}

async function callMcpTool(toolName, args = {}) {
    const consoleEl = document.getElementById('mcpConsole');
    consoleEl.style.display = 'block';
    consoleEl.textContent = `⏳ Выполнение Git MCP инструмента ${toolName}...`;
    try {
        const res = await fetch('/api/mcp/call', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tool: toolName, args: args})
        });
        const data = await res.json();
        consoleEl.textContent = `> ${toolName}(${JSON.stringify(args)})\n` + (data.result || data.error || 'Нет ответа');

        if (toolName === 'format_submission_comments' && data.result) {
            try {
                const parsed = JSON.parse(data.result);
                if (parsed.code_comment && parsed.video_comment) {
                    document.getElementById('commentsOutputBlock').style.display = 'flex';
                    document.getElementById('codeCommentTxt').value = parsed.code_comment;
                    document.getElementById('videoCommentTxt').value = parsed.video_comment;
                }
            } catch(e) {}
        }

    } catch(e) {
        consoleEl.textContent = `❌ Ошибка: ${e.message}`;
    }
}

function runGitStatusCheck() {
    callMcpTool('git_status_check', {});
}

function runCreateReadme() {
    const day = document.getElementById('gitDayNum').value || '17';
    const branch = document.getElementById('gitBranch').value || 'day17';
    const info = document.getElementById('gitLearnedInfo').value || '';
    const video = document.getElementById('gitVideoLink').value || '';
    const code = `https://github.com/user/ai_advent_1/blob/${branch}/day${day}.py`;

    callMcpTool('create_branch_readme', {
        day_number: day,
        topic: "Первый инструмент MCP",
        learned_info: info,
        branch_name: branch,
        code_link: code,
        video_link: video
    });
}

function runGitPush() {
    const branch = document.getElementById('gitBranch').value || 'day17';
    const rawFiles = document.getElementById('gitTargetFiles').value || 'day17.py, mcp_server_git.py, README.md';
    const targetFilesList = rawFiles.split(',').map(s => s.trim()).filter(Boolean);

    callMcpTool('git_commit_and_push', {
        branch_name: branch,
        target_files: targetFilesList,
        commit_message: `AI Advent submission for branch ${branch}`
    });
}

function runFormatComments() {
    const day = document.getElementById('gitDayNum').value || '17';
    const branch = document.getElementById('gitBranch').value || 'day17';
    const video = document.getElementById('gitVideoLink').value || '';
    const code = `https://github.com/user/ai_advent_1/blob/${branch}/day${day}.py`;

    callMcpTool('format_submission_comments', {
        day_number: day,
        branch_name: branch,
        code_link: code,
        video_link: video
    });
}

function copyToClipboard(inputId, btnId) {
    const inputEl = document.getElementById(inputId);
    inputEl.select();
    inputEl.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(inputEl.value).then(() => {
        const btn = document.getElementById(btnId);
        const origText = btn.textContent;
        btn.textContent = '✅ Скопировано!';
        btn.style.background = '#4ade80';
        btn.style.color = '#000';
        setTimeout(() => {
            btn.textContent = origText;
            btn.style.background = 'var(--primary)';
            btn.style.color = 'white';
        }, 2000);
    });
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
        if (content.includes("🐙") || content.includes("Git") || content.includes("код (ветка")) ind += `<span style="background:rgba(56,189,248,0.2); border:1px solid #38bdf8; padding:2px 6px; border-radius:4px; font-size:0.75rem;">🐙 Git MCP</span>`;
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
                tools_list = mcp_client.refresh_tools()
                state["mcp"] = {
                    "is_connected": mcp_client.is_connected,
                    "server_info": mcp_client.server_info,
                    "tools": tools_list
                }
                self._send_json(state)
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        page_html = get_chat_page(title="Git MCP Assignment Agent — День 17", extra_sidebar_html=SIDEBAR_STATS_HTML, extra_scripts=EXTRA_SCRIPTS)
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

                    # Автоматический диалоговый сценарий сдачи задания через Git MCP
                    mcp_context = ""
                    lower_msg = user_msg.lower()

                    if any(k in lower_msg for k in ["сдай", "сдать", "задани", "день 17", "пуш", "запуш", "push", "коммит"]):
                        # 1. Извлекаем имя ветки
                        branch_name = "day17"
                        if "ветк" in lower_msg:
                            words = lower_msg.replace(":", " ").replace(",", " ").split()
                            for idx, w in enumerate(words):
                                if w in ["ветку", "ветка", "ветке"] and idx + 1 < len(words):
                                    branch_name = words[idx + 1]
                                elif w.startswith("day") or w.startswith("feature/"):
                                    branch_name = w

                        # 2. Выполняем проверку Git статуса
                        status_res = mcp_client.call_tool("git_status_check", {})
                        mcp_context += f"\n[MCP Tool: git_status_check] ->\n{status_res}\n"

                        # 3. Выполняем ТОЧЕЧНЫЙ коммит и git push на GitHub
                        push_res = mcp_client.call_tool("git_commit_and_push", {
                            "branch_name": branch_name,
                            "target_files": ["day17.py", "mcp_server_git.py", "mcp_client.py", "simple_agent.py", "assignments_state.json", "README.md"],
                            "commit_message": f"AI Advent Day 17 submission for branch {branch_name}"
                        })
                        mcp_context += f"\n[MCP Tool: git_commit_and_push] ->\n{push_res}\n"

                        # 4. Формируем комментарии для Google Таблицы
                        comments_res = mcp_client.call_tool("format_submission_comments", {
                            "day_number": "17",
                            "branch_name": branch_name,
                            "code_link": f"https://github.com/user/ai_advent_1/blob/{branch_name}/day17.py",
                            "video_link": "https://youtu.be/day17_mcp_demo"
                        })
                        mcp_context += f"\n[MCP Tool: format_submission_comments] ->\n{comments_res}\n"

                    if mcp_context:
                        augmented_msg = f"{user_msg}\n\n=== КОНТЕКСТ ИЗ GIT MCP СЕРВЕРА ==={mcp_context}"
                        result = agent.chat(augmented_msg)
                    else:
                        result = agent.chat(user_msg)

                self._send_json(result)

            elif path == "/api/config":
                data = json.loads(raw_body)
                with _LOCK:
                    agent.set_config(data)
                self._send_json({"status": "config_updated"})

            elif path == "/api/mcp/call":
                data = json.loads(raw_body)
                tool_name = data.get("tool", "")
                args = data.get("args", {})
                res = mcp_client.call_tool(tool_name, args)
                self._send_json({"result": res})

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
    print(f"🚀 День 17 Git MCP Agent & Sidebar: http://127.0.0.1:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        mcp_client.close()
        sys.exit(0)
