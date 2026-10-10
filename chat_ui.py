"""
Переиспользуемый интерфейс чата для проекта AI Advent.
"""

def get_chat_page(title="AI Agent", extra_sidebar_html="", extra_scripts="", extra_main_html=""):
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{{TITLE}}</title>
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
    [hidden] { display: none !important; }
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
    .sidebar-disclosure { margin: 0 0 16px; border-top: 1px solid var(--border); padding-top: 10px; }
    .sidebar-disclosure > summary { cursor: pointer; color: var(--text-main); font-size: .85rem; font-weight: 700; }
    .generation-controls { display: flex; flex-direction: column; gap: 5px; margin-top: 10px; }
    .control-help { margin: -2px 0 7px; color: var(--text-dim); font-size: .68rem; line-height: 1.35; }

    .checkbox-group {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 0.85rem;
      cursor: pointer;
      user-select: none;
    }
    .checkbox-group input { width: auto; cursor: pointer; }

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
      height: 100%;
    }
    .app-view { flex: 1; min-height: 0; display: flex; flex-direction: column; }
    .main-tabs { display: flex; gap: 8px; padding: 12px 20px 0; border-bottom: 1px solid var(--border); background: var(--bg-dark); }
    .main-tab { border: 1px solid var(--border); border-bottom: 0; border-radius: 9px 9px 0 0; padding: 9px 16px; background: transparent; color: var(--text-dim); cursor: pointer; font: inherit; }
    .main-tab.active { background: var(--bg-card); color: var(--text-main); border-color: var(--primary); }
    #comparisonView { display: none; flex: 1; min-height: 0; overflow-y: auto; padding: 24px; }

    /* Chat Area */
    .scenario-practice { margin: 8px 20px 0; padding: 10px 12px; background: rgba(56,189,248,.07); border: 1px solid rgba(56,189,248,.25); border-radius: 8px; }
    .scenario-practice summary { cursor: pointer; font-size: .82rem; font-weight: 700; }
    .scenario-practice button, .scenario-practice select { margin-top: 7px; padding: 7px; border-radius: 6px; background: var(--bg-card); color: var(--text-main); border: 1px solid var(--border); }
    .scenario-practice p { margin: 6px 0; color: var(--text-dim); font-size: .75rem; line-height: 1.4; }
    #chat-log {
      flex: 1;
      overflow-y: auto;
      padding: 40px 20px;
      display: flex;
      flex-direction: column;
      gap: 20px;
      min-height: 0; /* Важно для прокрутки во flex-контейнере */
    }
    .msg-wrapper {
      display: flex;
      flex-direction: column;
      max-width: 85%;
      flex-shrink: 0; /* Предотвращаем сжатие сообщений */
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

    .rag-evidence-card {
      margin-top: 10px;
      padding: 12px 15px;
      border: 1px solid rgba(52, 211, 153, 0.35);
      border-left: 3px solid #34d399;
      border-radius: 10px;
      background: rgba(16, 185, 129, 0.07);
      color: var(--text-dim);
      font-size: 0.84rem;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .rag-evidence-card summary {
      margin-bottom: 7px;
      color: #6ee7b7;
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: .02em;
      cursor: pointer;
      user-select: none;
    }
    .rag-evidence-content { padding-top: 5px; }
    .rag-evidence-card p { margin: 0 0 7px; }
    .rag-evidence-card p:last-child { margin-bottom: 0; }

    /* Input Area */
    .input-container {
      padding: 20px;
      background: var(--bg-dark);
      border-top: 1px solid var(--border);
      flex-shrink: 0;
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

    .input-info {
      max-width: 900px;
      margin: 6px auto 0;
      display: flex;
      justify-content: flex-end;
      font-size: 0.7rem;
      color: var(--text-dim);
      padding: 0 10px;
      gap: 15px;
    }

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

    /* Token Stats */
    .token-stats {
      background: #0f172a;
      border-radius: 10px;
      padding: 12px;
      margin-bottom: 20px;
      border: 1px dashed var(--border);
    }
    .token-row {
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      margin-bottom: 4px;
      color: var(--text-dim);
    }
    .token-val { font-family: monospace; color: var(--accent); }
    .progress-bar-container {
      width: 100%;
      height: 4px;
      background: var(--border);
      border-radius: 2px;
      margin-top: 8px;
      overflow: hidden;
    }
    .progress-bar-fill {
      height: 100%;
      background: linear-gradient(to right, #6366f1, #a855f7);
      width: 0%;
      transition: width 0.3s ease;
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
        <option value="openrouter/free" selected data-supported-parameters='["temperature","top_p","top_k"]'>OpenRouter Free (автовыбор доступной модели)</option>
        <option value="z-ai/glm-4.5" data-supported-parameters='["temperature","top_p","top_k"]'>Z.ai GLM 4.5 · $0.60/M вход · $2.20/M выход</option>
        <option value="openai/gpt-4o-mini" data-supported-parameters='["temperature","top_p","top_k"]'>OpenAI GPT-4o mini · $0.15/M вход · $0.60/M выход</option>
        <option value="meta-llama/llama-3.2-3b-instruct:free" data-supported-parameters='["temperature","top_p","top_k"]'>Meta Llama 3.2 3B Instruct (free)</option>
        <option value="qwen/qwen3.6-flash" data-supported-parameters='["temperature","top_p","top_k"]'>Qwen3.6 Flash · $0.1875/M вход · $1.125/M выход</option>
        <option value="x-ai/grok-stt-1.0" disabled title="Требуется отдельный режим распознавания аудио; этот пункт не предназначен для текстового чата">x-ai/Grok STT 1.0 · $0.10/час · только распознавание аудио</option>
        <option value="nvidia/nemotron-3-ultra-550b-a55b-20260604:free" data-supported-parameters='[]'>NVIDIA Nemotron 3 Ultra (free) · nvidia/nemotron-3-ultra-550b-a55b-20260604:free</option>
        <option value="poolside/laguna-s-2.1:free" data-supported-parameters='[]'>Poolside Laguna S 2.1 (free) · poolside/laguna-s-2.1:free</option>
        <option value="nvidia/nemotron-3.5-lightning:free" data-supported-parameters='[]'>NVIDIA Nemotron 3.5 Lightning (free) · nvidia/nemotron-3.5-lightning:free</option>
      </select>
      <div class="control-help">Бесплатные модели загружаются из каталога OpenRouter; избранные модели показаны отдельно с ценой. Grok STT распознаёт аудио и не работает как текстовый чат.</div>
    </div>

    <details class="sidebar-disclosure">
      <summary>Параметры генерации</summary>
      <div class="generation-controls">
        <div class="config-group">
          <label>Температура: <span id="tempVal" class="slider-val">0.7</span></label>
          <div class="slider-container"><input type="range" id="tempSlider" min="0" max="2" step="0.1" value="0.7"></div>
          <div class="control-help">Ниже — ответы стабильнее, выше — разнообразнее. Для точных ответов обычно используют невысокую температуру.</div>
        </div>
        <div class="config-group">
          <label>Top P: <span id="topPVal" class="slider-val">1.0</span></label>
          <div class="slider-container"><input type="range" id="topPSlider" min="0" max="1" step="0.05" value="1.0"></div>
          <div class="control-help">Ограничивает выбор наиболее вероятными продолжениями. Обычно оставляют 1.0, если настраивают температуру.</div>
        </div>
        <div class="config-group">
          <label>Top K: <span id="topKVal" class="slider-val">0</span></label>
          <div class="slider-container"><input type="range" id="topKSlider" min="0" max="100" step="1" value="0"></div>
          <div class="control-help">Оставляет для выбора K наиболее вероятных токенов. Ноль передаёт выбор провайдеру; часть моделей не поддерживает параметр.</div>
        </div>
      </div>
    </details>

    {{EXTRA_SIDEBAR_HTML}}

    <div style="margin-top: auto;">
      <button onclick="clearChat()" style="width: 100%; padding: 10px; background: #ef4444; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">🗑️ Очистить историю</button>
    </div>
  </aside>

  <main class="main">
    {{EXTRA_MAIN_HTML}}
    <section id="chatView" class="app-view">
      <div id="chat-log">
        <div class="msg-wrapper msg-bot">
          <div class="msg-bubble">Привет! Я твой персональный агент. О чем хочешь поговорить?</div>
        </div>
      </div>

      <div class="input-container">
        <form id="chatForm" class="input-box">
          <textarea id="userInput" placeholder="Напишите сообщение..." rows="1" required autocomplete="off"></textarea>
          <button type="submit" id="sendBtn" class="send-btn">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
          </button>
        </form>
        <div class="input-info">
          <span id="charCount">Символов: 0</span>
          <span id="tokenCount">~0 токенов</span>
        </div>
      </div>
    </section>
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

      // Update counters
      const len = this.value.length;
      document.getElementById('charCount').textContent = `Символов: ${len}`;
      document.getElementById('tokenCount').textContent = `~${Math.ceil(len/4)} токенов`;
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

      let evidence = meta?.rag_evidence || '';
      if (role !== 'user' && !evidence && typeof content === 'string') {
        const legacyEvidenceMarker = '\\n### Источники и цитаты';
        const markerIndex = content.indexOf(legacyEvidenceMarker);
        if (markerIndex >= 0) {
          evidence = content.slice(markerIndex + 1);
          content = content.slice(0, markerIndex).trimEnd();
        }
      }

      const bubble = document.createElement('div');
      bubble.className = 'msg-bubble';

      if (content === null) {
        bubble.classList.add('shimmer-msg');
      } else {
        bubble.innerHTML = role === 'user' ? content.replace(/\\n/g, '<br>') : marked.parse(content);
      }

      wrapper.appendChild(bubble);

      if (evidence) {
        const evidenceCard = document.createElement('details');
        evidenceCard.className = 'rag-evidence-card';
        evidenceCard.setAttribute('aria-label', 'Источники и цитаты, добавленные приложением');
        const evidenceTitle = document.createElement('summary');
        evidenceTitle.textContent = '📚 Источники и цитаты · добавлены приложением';
        const evidenceContent = document.createElement('div');
        evidenceContent.className = 'rag-evidence-content';
        evidenceContent.innerHTML = marked.parse(String(evidence).replace(/^### Источники и цитаты\\s*/, ''));
        evidenceCard.append(evidenceTitle, evidenceContent);
        wrapper.appendChild(evidenceCard);
      }

      if (meta) {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'msg-meta';
        let metaHtml = `<span>🤖 ${meta.model}</span> <span>⏱️ ${meta.time}s</span>`;
        if (meta.usage) {
            metaHtml += ` <span>🪙 ${meta.usage.total_tokens || 0} tokens</span>`;
        }
        metaDiv.innerHTML = metaHtml;
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
      document.getElementById('charCount').textContent = 'Символов: 0';
      document.getElementById('tokenCount').textContent = '~0 токенов';

      addMessage('user', text);


      const loadingMsg = addMessage('bot', null);

      sendBtn.disabled = true;
      sendBtn.innerHTML = '<div class="loader"></div>';

      const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        model_supported_parameters: JSON.parse(document.getElementById('modelSelect').selectedOptions[0]?.dataset.supportedParameters || '[]'),
        temperature: tempSlider.value,
        top_p: topPSlider.value,
        top_k: topKSlider.value
      };

      if (document.getElementById('ragRewriteEnabled')) {
        config.rag_query_rewrite_enabled = document.getElementById('ragRewriteEnabled').checked;
        config.rag_top_k_before = document.getElementById('ragTopKBefore').value;
        config.rag_top_k_after = document.getElementById('ragTopKAfter').value;
        config.rag_similarity_threshold = document.getElementById('ragSimilarityThreshold').value;
      }

      // Сбор дополнительных чекбоксов (если есть)
      document.querySelectorAll('.sidebar input[type="checkbox"]').forEach(cb => {
        config[cb.id] = cb.checked;
      });

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
              usage: data.usage,
              rag_evidence: data.rag_evidence
          });
          if (typeof updateStats === 'function') updateStats(data.stats);
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

    function saveCurrentConfig() {
      const config = {
        system_prompt: document.getElementById('sysPrompt').value,
        model: document.getElementById('modelSelect').value,
        model_supported_parameters: JSON.parse(document.getElementById('modelSelect').selectedOptions[0]?.dataset.supportedParameters || '[]'),
        temperature: tempSlider.value,
        top_p: topPSlider.value,
        top_k: topKSlider.value
      };

      if (document.getElementById('ragRewriteEnabled')) {
        config.rag_query_rewrite_enabled = document.getElementById('ragRewriteEnabled').checked;
        config.rag_top_k_before = document.getElementById('ragTopKBefore').value;
        config.rag_top_k_after = document.getElementById('ragTopKAfter').value;
        config.rag_similarity_threshold = document.getElementById('ragSimilarityThreshold').value;
      }

      document.querySelectorAll('.sidebar input[type="checkbox"]').forEach(cb => {
        config[cb.id] = cb.checked;
      });

      fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
    }

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
      if (typeof updateStats === 'function') updateStats({total_tokens: 0, prompt_tokens: 0, completion_tokens: 0, cost: 0});
    }

    async function initApp() {
      try {
        const res = await fetch('/api/state');
        const state = await res.json();

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

          // Restore checkboxes
          Object.keys(c).forEach(key => {
            const el = document.getElementById(key);
            if (el && el.type === 'checkbox') {
              el.checked = c[key];
            }
          });
        }

        if (state.history && state.history.length > 0) {
          chatLog.innerHTML = '';
          state.history.forEach(m => {
            const isBot = m.role === 'assistant';
            const meta = (isBot && m.model) ? { model: m.model, time: m.time, usage: m.usage, rag_evidence: m.rag_evidence } : null;
            addMessage(isBot ? 'bot' : 'user', m.content, meta);
          });
        }
        if (typeof updateStats === 'function' && state.stats) updateStats(state.stats);
      } catch (e) {
        console.error("Failed to load state", e);
      }
    }

    {{EXTRA_SCRIPTS}}

    window.addEventListener('DOMContentLoaded', initApp);
  </script>
</body>
</html>"""
    return html.replace("{{TITLE}}", title).replace("{{EXTRA_SIDEBAR_HTML}}", extra_sidebar_html).replace("{{EXTRA_MAIN_HTML}}", extra_main_html).replace("{{EXTRA_SCRIPTS}}", extra_scripts)
