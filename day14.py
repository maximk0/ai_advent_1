#!/usr/bin/env python3
"""День 14: Инварианты и ограничения состояния.
   Система жестких 'законов проекта', которые ассистент обязан соблюдать.
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
PORT = 8014
_LOCK = threading.Lock()

agent = SimpleAgent()

SIDEBAR_STATS_HTML = """
<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem; color: #f87171;">🔒 Инварианты (Законы):</label>
  <div id="invList" style="font-size: 0.7rem; color: var(--text-dim); background: rgba(239, 68, 68, 0.05); padding: 8px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.2); max-height: 150px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px;">
    <!-- Инварианты загрузятся сюда -->
  </div>
  <div style="display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-top: 8px; border: 1px dashed var(--border);">
    <span style="font-size: 0.65rem; font-weight: bold; color: var(--text-dim); text-transform: uppercase;">Новый закон:</span>
    <input type="text" id="newInvKey" placeholder="Название (напр: Безопасность)" class="input-field" style="font-size: 0.75rem; padding: 4px; height: auto;">
    <textarea id="newInvVal" placeholder="Текст закона..." class="input-field" style="font-size: 0.75rem; padding: 4px; min-height: 40px; height: 40px; resize: vertical; font-family: inherit;"></textarea>
    <button onclick="addNewInvariant()" style="padding: 4px; font-size: 0.75rem; background: #ef4444; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">Утвердить закон 🔒</button>
  </div>
</div>

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 8px; font-size: 0.85rem;">🤖 Конечный автомат задачи (TSM):</label>
  <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; margin-bottom: 8px; border: 1px solid var(--border);">
    <span id="stageBadge_none" style="font-size: 0.65rem; padding: 2px 4px; border-radius: 3px; color: var(--text-dim); background: var(--bg-dark);">NONE</span>
    <span style="color: var(--text-dim); font-size: 0.6rem;">➔</span>
    <span id="stageBadge_planning" style="font-size: 0.65rem; padding: 2px 4px; border-radius: 3px; color: var(--text-dim); background: var(--bg-dark);">PLAN</span>
    <span style="color: var(--text-dim); font-size: 0.6rem;">➔</span>
    <span id="stageBadge_execution" style="font-size: 0.65rem; padding: 2px 4px; border-radius: 3px; color: var(--text-dim); background: var(--bg-dark);">EXEC</span>
    <span style="color: var(--text-dim); font-size: 0.6rem;">➔</span>
    <span id="stageBadge_validation" style="font-size: 0.65rem; padding: 2px 4px; border-radius: 3px; color: var(--text-dim); background: var(--bg-dark);">VALID</span>
    <span style="color: var(--text-dim); font-size: 0.6rem;">➔</span>
    <span id="stageBadge_done" style="font-size: 0.65rem; padding: 2px 4px; border-radius: 3px; color: var(--text-dim); background: var(--bg-dark);">DONE</span>
  </div>
  <div id="tsmDetailsBlock" style="background: rgba(255,255,255,0.03); border: 1px solid var(--border); padding: 8px; border-radius: 6px; font-size: 0.75rem; display: flex; flex-direction: column; gap: 4px; line-height: 1.4;">
    <div><b style="color: var(--accent);">Текущий шаг:</b> <span id="tsmStepText" style="color: var(--text-main);"></span></div>
    <div><b style="color: var(--accent);">Ожидаемое действие:</b> <span id="tsmActionText" style="color: var(--text-dim);"></span></div>
  </div>
  <div style="display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.15); padding: 6px; border-radius: 4px; border: 1px dashed var(--border); margin-top: 6px;">
    <span style="font-size: 0.7rem; color: var(--text-dim); font-weight: bold;">Ручное управление TSM:</span>
    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px;">
      <button onclick="forceTsmStage('planning')" style="padding: 3px; font-size: 0.65rem; background: var(--border); color: white; border: none; border-radius: 3px; cursor: pointer;">PLAN</button>
      <button onclick="forceTsmStage('execution')" style="padding: 3px; font-size: 0.65rem; background: var(--border); color: white; border: none; border-radius: 3px; cursor: pointer;">EXEC</button>
      <button onclick="forceTsmStage('validation')" style="padding: 3px; font-size: 0.65rem; background: var(--border); color: white; border: none; border-radius: 3px; cursor: pointer;">VALID</button>
    </div>
    <input type="text" id="manualTsmStep" placeholder="Изменить шаг" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <input type="text" id="manualTsmAction" placeholder="Изменить действие" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <button onclick="submitManualTsm()" style="padding: 4px; font-size: 0.75rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: bold;">Обновить TSM</button>
  </div>
</div>

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">🎭 Персонализация и Профили:</label>
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

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">🧠 Long-Term Memory (LTM):</label>
  <div id="ltmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 100px; overflow-y: auto; margin-bottom: 8px;">
    Нет долговременных фактов
  </div>
  <div style="display: flex; flex-direction: column; gap: 4px; background: rgba(0,0,0,0.2); padding: 6px; border-radius: 4px;">
    <input type="text" id="manualLtmKey" placeholder="Ключ памяти" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <input type="text" id="manualLtmVal" placeholder="Значение" class="input-field" style="font-size: 0.75rem; padding: 3px 6px; height: auto;">
    <button onclick="pinToLtmManual()" style="padding: 4px; font-size: 0.75rem; background: var(--primary); border: none; border-radius: 4px; color: white; cursor: pointer;">Зафиксировать в LTM</button>
  </div>
</div>

<div class="config-group" style="margin-top: 15px; border-top: 1px solid var(--border); padding-top: 10px;">
  <label style="font-weight: 600; display: block; margin-bottom: 5px; font-size: 0.85rem;">🛠 Working Memory (WM):</label>
  <div id="wmList" style="font-size: 0.75rem; color: var(--text-dim); background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px; line-height: 1.4; max-height: 100px; overflow-y: auto;">
    Нет активных данных задачи
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
  .invariant-item {
     padding: 6px;
     background: rgba(0,0,0,0.2);
     border-radius: 4px;
     border-left: 3px solid #ef4444;
     position: relative;
  }
  .del-inv {
     position: absolute;
     top: 2px;
     right: 5px;
     color: #ef4444;
     cursor: pointer;
     font-weight: bold;
     font-size: 0.8rem;
  }
  .del-inv:hover { color: #f87171; }
</style>
"""

EXTRA_SCRIPTS = """
let forcedStage = null;

function forceTsmStage(stage) {
    forcedStage = stage;
    ['none', 'planning', 'execution', 'validation', 'done'].forEach(s => {
        document.getElementById('stageBadge_' + s).style.background = 'var(--bg-dark)';
        document.getElementById('stageBadge_' + s).style.color = 'var(--text-dim)';
    });
    const activeColors = {
        planning: { bg: 'rgba(234, 179, 8, 0.2)', text: '#fde047' },
        execution: { bg: 'rgba(99, 102, 241, 0.2)', text: '#a5b4fc' },
        validation: { bg: 'rgba(168, 85, 247, 0.2)', text: '#d8b4fe' },
        done: { bg: 'rgba(34, 197, 94, 0.2)', text: '#86efac' }
    };
    if (activeColors[stage]) {
        document.getElementById('stageBadge_' + stage).style.background = activeColors[stage].bg;
        document.getElementById('stageBadge_' + stage).style.color = activeColors[stage].text;
    }
}

async function submitManualTsm() {
    const stage = forcedStage || 'none';
    const step = document.getElementById('manualTsmStep').value.trim();
    const action = document.getElementById('manualTsmAction').value.trim();
    const response = await fetch('/api/tsm/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stage: stage, step: step, action: action})
    });
    if (response.ok) {
        document.getElementById('manualTsmStep').value = '';
        document.getElementById('manualTsmAction').value = '';
        forcedStage = null;
        refreshUI();
    }
}

async function refreshUI() {
    try {
        const res = await fetch('/api/state');
        const state = await res.json();

        // 1. Рендеринг инвариантов
        const invContainer = document.getElementById('invList');
        invContainer.innerHTML = '';
        if (state.invariants && Object.keys(state.invariants).length > 0) {
            for (const [k, v] of Object.entries(state.invariants)) {
                const div = document.createElement('div');
                div.className = 'invariant-item';
                div.innerHTML = `
                    <div style="font-weight:bold; color:#fca5a5; margin-bottom:2px;">${k}</div>
                    <div style="line-height:1.2;">${v}</div>
                    <span class="del-inv" onclick="deleteInv('${k}')">×</span>
                `;
                invContainer.appendChild(div);
            }
        } else {
            invContainer.textContent = 'Нет активных законов';
        }

        // 2. TSM Pipeline
        if (state.tsm) {
            const t = state.tsm;
            document.getElementById('tsmStepText').textContent = t.step || 'Нет активного шага';
            document.getElementById('tsmActionText').textContent = t.action || 'Нет ожидаемого действия';

            const stages = ['none', 'planning', 'execution', 'validation', 'done'];
            stages.forEach(s => {
                const b = document.getElementById('stageBadge_' + s);
                b.style.background = (s === t.stage) ? '#ef4444' : 'var(--bg-dark)';
                b.style.color = (s === t.stage) ? 'white' : 'var(--text-dim)';
                b.style.fontWeight = (s === t.stage) ? 'bold' : 'normal';
            });
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
            document.getElementById('profRole').textContent = d.role || '';
            document.getElementById('profStyle').textContent = d.style || '';
            document.getElementById('profFormat').textContent = d.format || '';
            document.getElementById('profConstraints').textContent = d.constraints || '';
        }

        // 4. Память (LTM / WM)
        if (state.ltm && Object.keys(state.ltm).length > 0) {
            let html = '<ul style="padding-left: 15px; margin: 0;">';
            for (const [k, v] of Object.entries(state.ltm)) html += `<li><b>${k}:</b> ${v}</li>`;
            html += '</ul>';
            document.getElementById('ltmList').innerHTML = html;
        } else {
            document.getElementById('ltmList').textContent = "Нет долговременных фактов";
        }

        if (state.wm && Object.keys(state.wm).length > 0) {
            let html = '<ul style="padding-left: 15px; margin: 0;">';
            for (const [k, v] of Object.entries(state.wm)) html += `<li><b>${k}:</b> ${v}</li>`;
            html += '</ul>';
            document.getElementById('wmList').innerHTML = html;
        } else {
            document.getElementById('wmList').textContent = "Нет активных данных задачи";
        }

        // Чат
        chatLog.innerHTML = '';
        if (state.history && state.history.length > 0) {
            state.history.forEach(m => {
                const isBot = m.role === 'assistant';
                addMessage(isBot ? 'bot' : 'user', m.content, isBot ? {model: m.model, time: m.time, usage: m.usage} : null);
            });
        } else {
            chatLog.innerHTML = '<div class="msg-wrapper msg-bot"><div class="msg-bubble">Привет! Я агент, работающий под строгим контролем Инвариантов. Попробуй заставить меня нарушить законы проекта в Sidebar! 🔒</div></div>';
        }

        if (state.stats) {
            document.getElementById('statTotal').textContent = state.stats.total_tokens || 0;
            document.getElementById('statCost').textContent = '$' + (state.stats.cost || 0).toFixed(6);
        }

    } catch (e) { console.error(e); }
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
    document.getElementById('editProfName').value = "";
    document.getElementById('editProfName').disabled = false;
    document.getElementById('editProfRole').value = "";
    document.getElementById('editProfStyle').value = "";
    document.getElementById('editProfFormat').value = "";
    document.getElementById('editProfConstraints').value = "";
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
    const res = await fetch('/api/profile/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, data: data})
    });
    if (res.ok) { closeProfileEditor(); refreshUI(); }
}

async function pinToLtmManual() {
    const key = document.getElementById('manualLtmKey').value.trim();
    const val = document.getElementById('manualLtmVal').value.trim();
    if (!key || !val) return alert("Заполните ключ и значение");
    const res = await fetch('/api/memory/pin_ltm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, value: val})
    });
    if (res.ok) {
        document.getElementById('manualLtmKey').value = '';
        document.getElementById('manualLtmVal').value = '';
        refreshUI();
    }
}

async function addNewInvariant() {
    const key = document.getElementById('newInvKey').value.trim();
    const val = document.getElementById('newInvVal').value.trim();
    if (!key || !val) return alert('Заполните название и текст закона');
    const res = await fetch('/api/invariants/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, value: val})
    });
    if (res.ok) {
        document.getElementById('newInvKey').value = '';
        document.getElementById('newInvVal').value = '';
        refreshUI();
    }
}

async function deleteInv(key) {
    if (!confirm(`Удалить закон "${key}"?`)) return;
    await fetch('/api/invariants/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key})
    });
    refreshUI();
}

async function clearChat() {
    if (!confirm('Очистить только историю? (Законы и память сохранятся)')) return;
    await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: false}) });
    refreshUI();
}

async function resetAllData() {
    if (!confirm('🚨 Сбросить ВСЕ? Это удалит инварианты, память и чат!')) return;
    await fetch('/api/clear', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({clear_all: true}) });
    refreshUI();
}

document.getElementById('profileSelect').addEventListener('change', async (e) => {
    await fetch('/api/profile/switch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: e.target.value})
    });
    refreshUI();
});

// Перехват сообщения об отказе для красной подсветки
const originalAddMessage = addMessage;
addMessage = function(role, content, meta) {
    const res = originalAddMessage(role, content, meta);
    if (role === 'bot' && content) {
        if (content.includes('❌ ОТКАЗ ВЫПОЛНЕНИЯ')) {
            const bubble = res.querySelector('.msg-bubble');
            bubble.style.border = '2px solid #ef4444';
            bubble.style.background = 'rgba(239, 68, 68, 0.1)';
        }

        let indicatorsHtml = "";
        if (content.includes("🧠")) indicatorsHtml += `<span style="background: rgba(168,85,247,0.2); border: 1px solid var(--accent); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 5px;">🧠 LTM</span>`;
        if (content.includes("🛠")) indicatorsHtml += `<span style="background: rgba(59,130,246,0.2); border: 1px solid #3b82f6; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem;">🛠 WM</span>`;

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

initApp = refreshUI;
"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.rstrip('/')
        if path == "/api/state":
            with _LOCK: self._send_json(agent.get_state()); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        page_html = get_chat_page(title="Invariant Agent — День 14", extra_sidebar_html=SIDEBAR_STATS_HTML, extra_scripts=EXTRA_SCRIPTS)
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
            elif path == "/api/clear":
                data = json.loads(raw_body)
                with _LOCK: agent.clear_history(clear_all=data.get("clear_all", False))
                self._send_json({"status": "cleared"})
            elif path == "/api/invariants/add":
                data = json.loads(raw_body)
                with _LOCK: agent.pin_invariant(data.get("key", ""), data.get("value", ""))
                self._send_json({"status": "added"})
            elif path == "/api/invariants/delete":
                data = json.loads(raw_body)
                with _LOCK: agent.delete_invariant(data.get("key", ""))
                self._send_json({"status": "deleted"})
            elif path == "/api/profile/switch":
                data = json.loads(raw_body)
                with _LOCK: agent.switch_profile(data.get("name", ""))
                self._send_json({"status": "switched"})
            elif path == "/api/profile/save":
                data = json.loads(raw_body)
                with _LOCK: agent.save_profile_data(data.get("name", ""), data.get("data", {}))
                self._send_json({"status": "profile_saved"})
            elif path == "/api/memory/pin_ltm":
                data = json.loads(raw_body)
                with _LOCK: agent.pin_to_ltm(data.get("key", ""), data.get("value", ""))
                self._send_json({"status": "pinned"})
            elif path == "/api/tsm/update":
                data = json.loads(raw_body)
                with _LOCK: agent.update_tsm_manually(data.get("stage", "none"), data.get("step", ""), data.get("action", ""))
                self._send_json({"status": "tsm_updated"})
            else: self.send_error(404)
        except Exception as e: self._send_json({"error": str(e)})

    def _send_json(self, data: dict):
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(data).encode("utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, format, *args): pass

def load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if __name__ == "__main__":
    load_env()
    print(f"🚀 День 14 Инварианты проекта: http://127.0.0.1:{PORT}")
    try: ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt: sys.exit(0)
