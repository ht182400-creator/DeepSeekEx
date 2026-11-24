/**
 * HT182400 前端应用逻辑
 * 以原站 UI 为基础,连接真实 FastAPI 后端,扩展功能作为可开关增强层
 */

'use strict';

const appState = {
  chats: [], currentChatId: null, thinking: false, search: false,
  generating: false, attachments: [],
  settings: {
    provider: 'official', api_key_set: false, web_token_set: false,
    model: DEFAULT_MODEL, enhancements: { tools: true, context: false },
  },
  currentProvider: 'official',
};

let ui = {};
let abortController = null;

/**
 * 初始化应用
 */
async function init() {
  try {
    cacheUI();
    injectChameleons();
    restoreTheme();
    bindEvents();
    await loadSettings();
    await loadChats();
    renderHistory();
    renderPrompts();
    logInfo('应用初始化完成');
  } catch (exc) {
    logError('初始化失败', exc);
    showToast('初始化失败,请刷新页面');
  }
}

/**
 * 缓存 DOM 元素
 */
function cacheUI() {
  ui = {
    sidebar: document.getElementById('sidebar'),
    welcome: document.getElementById('welcome'),
    chatArea: document.getElementById('chat-area'),
    messages: document.getElementById('messages'),
    historyList: document.getElementById('history-list'),
    chatTitle: document.getElementById('chat-title-top'),
    input: document.getElementById('message-input'),
    sendBtn: document.getElementById('btn-send'),
    stopBtn: document.getElementById('btn-stop'),
    chipThinking: document.getElementById('chip-thinking'),
    chipSearch: document.getElementById('chip-search'),
    attachBtn: document.getElementById('btn-attach'),
    fileInput: document.getElementById('file-input'),
    attachmentList: document.getElementById('attachment-list'),
    settingsModal: document.getElementById('settings-modal'),
    promptLibrary: document.getElementById('prompt-library'),
    promptList: document.getElementById('prompt-list'),
    providerBadge: document.getElementById('provider-badge'),
    enhanceTools: document.getElementById('enhance-tools'),
    toast: document.getElementById('toast'),
  };
}

/**
 * 从后端加载配置
 */
async function loadSettings() {
  try {
    const resp = await fetch('/api/settings');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    appState.settings = await resp.json();
    appState.currentProvider = appState.settings.provider || 'official';
    // 后端配置的思考/联网状态同步到前端 chip,避免显示与实际请求不一致
    appState.thinking = !!appState.settings.thinking_enabled;
    appState.search = !!appState.settings.search_enabled;
    if (ui.chipThinking) ui.chipThinking.classList.toggle('active', appState.thinking);
    if (ui.chipSearch) ui.chipSearch.classList.toggle('active', appState.search);
    updateProviderBadge();
    applyEnhancements();
    updateContextMeter();
    // 填充设置表单
    document.getElementById('setting-api-key').value = '';
    document.getElementById('setting-web-token').value = '';
    const modelSel = document.getElementById('setting-model');
    modelSel.value = appState.settings.model || 'deepseek-flash';
    modelSel.disabled = appState.currentProvider === 'web';
    document.querySelectorAll('.provider-tab').forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.provider === appState.currentProvider);
    });
    const officialCfg = document.getElementById('official-config');
    const webCfg = document.getElementById('web-config');
    if (appState.currentProvider === 'web') {
      officialCfg.classList.add('hidden');
      webCfg.classList.remove('hidden');
      document.getElementById('provider-hint').textContent = '使用已登录的网页端接口(免费),需填入 userToken';
    }
  } catch (exc) {
    logError('加载配置失败', exc);
    showToast('无法连接后端服务');
  }
}

/**
 * 从后端加载会话列表
 */
async function loadChats() {
  try {
    const resp = await fetch('/api/chats');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const chats = await resp.json();
    appState.chats = chats.length ? chats : [...PRESET_HISTORY];
    logDebug('加载会话', appState.chats.length);
  } catch (exc) {
    logError('加载会话失败', exc);
    appState.chats = [...PRESET_HISTORY];
  }
}

/**
 * 绑定事件
 */
function bindEvents() {
  // 侧边栏
  document.getElementById('btn-collapse').addEventListener('click', toggleSidebar);
  document.getElementById('btn-expand').addEventListener('click', toggleSidebar);
  document.getElementById('btn-new-chat').addEventListener('click', newChat);
  document.getElementById('btn-new-top').addEventListener('click', newChat);

  // 搜索历史
  document.getElementById('btn-search-history').addEventListener('click', openSearch);
  document.getElementById('btn-search-top').addEventListener('click', openSearch);
  document.getElementById('search-modal').querySelector('.modal-mask').addEventListener('click', closeSearch);

  // 用户菜单
  document.getElementById('btn-user-menu').addEventListener('click', () => {
    document.getElementById('user-menu').classList.toggle('hidden');
  });
  document.querySelectorAll('#user-menu .menu-item').forEach((item) => {
    item.addEventListener('click', () => {
      document.getElementById('user-menu').classList.add('hidden');
      const action = item.dataset.action;
      if (action === 'theme') {
        const isDark = document.body.classList.toggle('dark-theme');
        try { localStorage.setItem(THEME_KEY, isDark ? 'dark' : 'light'); } catch (exc) { logWarning('主题持久化失败', exc); }
        showToast(isDark ? '已切换深色主题' : '已切换浅色主题');
      } else if (action === 'settings') {
        openSettings();
      } else if (action === 'logout') {
        resetLocalUi();
      }
    });
  });

  // 输入区
  ui.input.addEventListener('input', handleInput);
  ui.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  ui.sendBtn.addEventListener('click', send);
  if (ui.stopBtn) ui.stopBtn.addEventListener('click', stopGeneration);
  ui.chipThinking.addEventListener('click', () => {
    appState.thinking = !appState.thinking;
    ui.chipThinking.classList.toggle('active', appState.thinking);
  });
  ui.chipSearch.addEventListener('click', () => {
    appState.search = !appState.search;
    ui.chipSearch.classList.toggle('active', appState.search);
  });
  ui.attachBtn.addEventListener('click', () => ui.fileInput.click());
  ui.fileInput.addEventListener('change', async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) {
      // 文本类附件读取内容随消息发送,二进制文件仅能标记名称(模型无法读取)
      const isText = f.type.startsWith('text/') || /\.(txt|md|csv|json|log|py|js|ts|html|css|xml|ya?ml)$/i.test(f.name);
      if (f.size > MAX_ATTACHMENT_BYTES) {
        showToast(`附件 ${f.name} 超过 ${MAX_ATTACHMENT_BYTES / 1024 / 1024}MB,已跳过`);
        continue;
      }
      let content = '';
      if (isText) {
        try {
          content = await f.text();
        } catch (exc) {
          logWarning('读取附件失败', exc);
          showToast(`读取 ${f.name} 失败`);
          continue;
        }
      }
      addAttachmentChip(f.name, content, isText);
    }
    ui.fileInput.value = '';
    if (files.length) showToast(`已添加 ${files.length} 个附件`);
  });

  // 设置弹层
  document.getElementById('btn-settings').addEventListener('click', openSettings);
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
  document.getElementById('btn-validate').addEventListener('click', () => validate('official'));
  document.getElementById('btn-validate-web').addEventListener('click', () => validate('web'));
  document.querySelectorAll('.provider-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.provider-tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      const isWeb = tab.dataset.provider === 'web';
      document.getElementById('official-config').classList.toggle('hidden', isWeb);
      document.getElementById('web-config').classList.toggle('hidden', !isWeb);
      document.getElementById('provider-hint').textContent = isWeb
        ? '使用已登录的网页端接口(免费),需填入 userToken。网页端仅提供 default 模型,模型选择对其无效'
        : '使用 DeepSeek 官方 API,需填入 API Key(按量计费)';
      // 网页端接口只有一个模型,选择框对其无意义,禁用避免误导
      const modelSel = document.getElementById('setting-model');
      if (modelSel) modelSel.disabled = isWeb;
    });
  });
  document.querySelectorAll('[data-close]').forEach((el) => {
    el.addEventListener('click', () => document.getElementById(el.dataset.close).classList.add('hidden'));
  });

  // 增强功能
  document.getElementById('btn-prompt-lib').addEventListener('click', () => ui.promptLibrary.classList.remove('hidden'));
  document.getElementById('btn-export').addEventListener('click', exportConversation);
  document.getElementById('btn-share').addEventListener('click', shareConversation);
  document.getElementById('btn-focus').addEventListener('click', toggleFocus);

  // 全局快捷键
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') {
      // 输入框聚焦时不新建对话,避免误触丢失未发送内容
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea') return;
      e.preventDefault();
      newChat();
    }
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal').forEach((m) => m.classList.add('hidden'));
      document.getElementById('user-menu').classList.add('hidden');
    }
  });
}

/**
 * 切换侧边栏
 */
function toggleSidebar() {
  ui.sidebar.classList.toggle('collapsed');
}

/**
 * 开启新对话
 */
function newChat() {
  appState.currentChatId = null;
  ui.messages.innerHTML = '';
  ui.input.value = '';
  ui.attachmentList.innerHTML = '';
  appState.attachments = [];
  ui.chatTitle.textContent = '';
  ui.welcome.classList.remove('hidden');
  ui.chatArea.classList.add('hidden');
  updateSendButton();
  updateContextMeter();
  renderOutline();
  renderHistory();
}

/**
 * 处理输入变化
 */
function handleInput() {
  ui.input.style.height = 'auto';
  ui.input.style.height = Math.min(ui.input.scrollHeight, 180) + 'px';
  updateSendButton();
}

/**
 * 更新发送按钮状态
 */
function updateSendButton() {
  // 生成中隐藏发送按钮、显示停止按钮,让用户可中断
  if (appState.generating) {
    ui.sendBtn.classList.add('hidden');
    if (ui.stopBtn) ui.stopBtn.classList.remove('hidden');
    return;
  }
  ui.sendBtn.classList.remove('hidden');
  if (ui.stopBtn) ui.stopBtn.classList.add('hidden');
  ui.sendBtn.disabled = (ui.input.value.trim().length === 0 && appState.attachments.length === 0);
}

/** 从 localStorage 恢复主题(失败不影响主流程) */
function restoreTheme() {
  try {
    if (localStorage.getItem(THEME_KEY) === 'dark') document.body.classList.add('dark-theme');
  } catch (exc) {
    logWarning('恢复主题失败', exc);
  }
}

/**
 * 添加附件标签,文本内容随消息发送
 * @param {string} name 文件名
 * @param {string} content 文本内容(二进制为空)
 * @param {boolean} isText 是否为文本文件
 */
function addAttachmentChip(name, content, isText) {
  const att = { name, content, isText };
  appState.attachments.push(att);
  const tag = document.createElement('span');
  tag.className = 'attachment-tag';
  tag.textContent = `📎 ${name}${isText ? '' : ' (仅名称)'}`;
  const btn = document.createElement('button');
  btn.textContent = '×';
  btn.addEventListener('click', () => {
    const i = appState.attachments.indexOf(att);
    if (i >= 0) appState.attachments.splice(i, 1);
    tag.remove();
    updateSendButton();
  });
  tag.appendChild(btn);
  ui.attachmentList.appendChild(tag);
  updateSendButton();
}

/**
 * 把附件文本内容拼接到用户消息,使模型真正可见
 * @param {string} text 原始输入
 * @returns {string} 拼接后的提示词
 */
function buildPromptWithAttachments(text) {
  const parts = appState.attachments.filter((a) => a.isText && a.content);
  if (!parts.length) return text;
  const block = parts.map((a) => `【附件:${a.name}】\n${a.content}`).join('\n\n');
  return `${text}\n\n--- 以下为附件内容 ---\n${block}`.trim();
}

/**
 * 发送消息(核心:调用真实后端 SSE 接口)
 */
async function send() {
  const text = ui.input.value.trim();
  if ((!text && !appState.attachments.length) || appState.generating) return;

  try {
    appState.generating = true;
    updateSendButton();

    ui.welcome.classList.add('hidden');
    ui.chatArea.classList.remove('hidden');

    // 把附件文本拼入实际发送给模型的提示词,气泡仅显示用户原文
    const fullPrompt = buildPromptWithAttachments(text);
    appendUserMessage(text, fullPrompt);

    // 清空输入与附件状态
    ui.input.value = '';
    ui.input.style.height = 'auto';
    ui.attachmentList.innerHTML = '';
    appState.attachments = [];

    // 确保有会话
    if (!appState.currentChatId) {
      const chat = await createChat(text.slice(0, 12) || '新对话');
      appState.currentChatId = chat.id;
      ui.chatTitle.textContent = chat.title;
      await loadChats();
      renderHistory();
    }

    // 构造消息历史(从 DOM 提取,避免额外请求)
    const messages = extractMessages();

    // 调用流式接口
    await streamResponse(messages);

    // 保存会话到后端
    await saveCurrentChat();

    logInfo('对话完成');
  } catch (exc) {
    logError('发送失败', exc);
    showToast(`发送失败: ${exc.message || exc}`);
  } finally {
    appState.generating = false;
    updateSendButton();
  }
}

/**
 * 从 DOM 提取对话消息
 * @returns {Array} messages 数组
 */
function extractMessages() {
  const result = [];
  ui.messages.querySelectorAll('.message').forEach((el) => {
    const isUser = el.classList.contains('message-user');
    const bubble = el.querySelector('.bubble');
    if (!bubble) return;
    // content 为完整提示词(回传),display 为气泡原文
    if (isUser && bubble.dataset.full) {
      result.push({ role: 'user', content: bubble.dataset.full,
        display: bubble.dataset.display || bubble.dataset.full });
      return;
    }
    // 取正文(排除思考面板、来源卡、操作栏)
    const body = bubble.querySelector('.md-body');
    const text = (body ? body.innerText : bubble.innerText).trim();
    if (!text) return;
    result.push(isUser ? { role: 'user', content: text, display: text }
                       : buildAssistantMessage(el, text));
  });
  return result;
}

/**
 * 流式接收 AI 回复
 * @param {Array} messages 对话历史
 */
async function streamResponse(messages) {
  abortController = new AbortController();

  // 创建 AI 消息容器
  const wrapper = createAiMessage();
  const bodyEl = wrapper.querySelector('.md-body');
  const actionsEl = wrapper.querySelector('.msg-actions');
  let contentBuffer = '';
  let thinkingBuffer = '';
  let thinkingPanel = null;
  let searchBadge = null;

  try {
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages,
        thinking: appState.thinking,
        search: appState.search,
        provider: appState.currentProvider,
        model: appState.settings.model,
        chat_id: appState.currentChatId || '',
      }),
      signal: abortController.signal,
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    // 读取 SSE 流
    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (data === '[DONE]') continue;

        let event;
        try {
          event = JSON.parse(data);
        } catch {
          continue;
        }

        if (event.type === 'thinking') {
          if (!thinkingPanel) {
            thinkingPanel = createThinkingPanel();
            bodyEl.before(thinkingPanel);
          }
          thinkingBuffer += event.text || '';
          thinkingPanel.querySelector('.thinking-content').textContent = thinkingBuffer;
          thinkingPanel.classList.add('expanded');
        } else if (event.type === 'content') {
          contentBuffer += event.text || '';
          bodyEl.textContent = contentBuffer;
          scrollToBottom();
        } else if (event.type === 'error') {
          bodyEl.textContent = `⚠️ ${event.text || '未知错误'}`;
          showToast(event.text || '对话出错');
        } else if (event.type === 'thinking_elapsed') {
          // 真实思考耗时(后端 elapsed_secs),显示 "Thought for X seconds"
          if (!thinkingPanel) {
            thinkingPanel = createThinkingPanel();
            bodyEl.before(thinkingPanel);
          }
          const secs = Number(event.seconds) || 0;
          const label = thinkingPanel.querySelector('.thinking-label');
          if (label) label.textContent = `思考耗时 ${secs.toFixed(1)} 秒`;
        } else if (event.type === 'search_state') {
          // 真实搜索触发状态(search_triggered),显示搜索徽章
          if (event.triggered && !searchBadge) {
            searchBadge = createSearchBadge();
            bodyEl.before(searchBadge);
          }
        } else if (event.type === 'sources') {
          // 后端返回真实来源数据时才渲染来源卡,不造数据
          const pill = createSourcesPill(event.items || []);
          actionsEl.before(pill);
          // 搜索触发但返回了来源,用真实条数更新徽章
          if (searchBadge) setSearchBadgeCount(searchBadge, (event.items || []).length);
        } else if (event.type === 'done') {
          // 完成
        }
      }
    }

    // 渲染最终 Markdown
    if (contentBuffer) {
      bodyEl.innerHTML = renderMarkdown(contentBuffer);
      bindMessageActions(wrapper, contentBuffer);
    }
    updateContextMeter();
    renderOutline();
  } catch (exc) {
    if (exc.name === 'AbortError') {
      logInfo('用户停止生成');
    } else {
      logError('流式响应异常', exc);
      bodyEl.textContent = `⚠️ 连接异常: ${exc.message || exc}`;
    }
  }
}

/**
 * 创建 AI 消息容器
 * @returns {HTMLElement}
 */
function createAiMessage() {
  const wrapper = document.createElement('div');
  wrapper.className = 'message message-ai';
  wrapper.innerHTML = `
    <div class="msg-avatar ai-avatar cham-slot" title="HT182400 模型回复"></div>
    <div class="bubble">
      <div class="md-body"></div>
      <div class="msg-actions">
        <button data-action="copy" title="复制"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
        <button data-action="regen" title="重新生成"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 10-2 6M20 5v6h-6"/></svg></button>
        <button data-action="like" title="赞"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 10v11H3a2 2 0 01-2-2v-7a2 2 0 012-2h4zM7 10l5-8a2 2 0 013 2l-1 6h6a2 2 0 012 2l-2 9a2 2 0 01-2 2H7"/></svg></button>
        <button data-action="edit" title="编辑"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20h4l10-10-4-4L4 16v4zM14 6l4 4"/></svg></button>
        <button data-action="delete" title="删除"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></button>
        <button data-action="speak" title="朗读"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M11 5L6 9H3v6h3l5 4V5zM15 9a4 4 0 010 6M18 6a8 8 0 010 12"/></svg></button>
      </div>
    </div>
  `;
  ui.messages.appendChild(wrapper);
  injectChameleons(wrapper);
  scrollToBottom();
  return wrapper;
}

/**
 * 创建思考面板
 */
function createThinkingPanel() {
  const el = document.createElement('div');
  el.className = 'thinking-panel';
  el.innerHTML = `
    <div class="thinking-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3a6 6 0 00-6 6c0 2 1 3 2 4-1 1-2 2-2 4a6 6 0 006 6 6 6 0 006-6c0-2-1-3-2-4 1-1 2-2 2-4a6 6 0 00-6-6z"/></svg>
      <span class="thinking-label">思考过程</span>
      <svg class="thinking-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="thinking-content"></div>
  `;
  el.querySelector('.thinking-header').addEventListener('click', () => el.classList.toggle('expanded'));
  return el;
}

/**
 * 绑定消息操作按钮
 */
function bindMessageActions(wrapper, text) {
  wrapper.querySelectorAll('.msg-actions button').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const a = btn.dataset.action;
      if (a === 'copy') {
        await copyText(text);
      } else if (a === 'speak') {
        speakText(text);
      } else if (a === 'regen') {
        await regenerateFrom(wrapper);
      } else if (a === 'like') {
        const liked = btn.classList.toggle('liked');
        showToast(liked ? '已点赞' : '已取消点赞');
      } else if (a === 'edit') {
        editAiMessage(wrapper, text);
      } else if (a === 'delete') {
        deleteMessage(wrapper);
      }
    });
  });
}

/**
 * 添加用户消息到界面
 */
function appendUserMessage(text, fullPrompt) {
  const wrapper = document.createElement('div');
  wrapper.className = 'message message-user';
  // data-full 保存含附件的完整提示词(回传模型),data-display 保存原文(气泡显示)
  const full = fullPrompt || text;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.dataset.full = full;
  bubble.dataset.display = text;
  bubble.textContent = text;
  // 用户消息增加编辑/删除按钮
  const actions = document.createElement('div');
  actions.className = 'msg-actions user-actions';
  actions.innerHTML = `
    <button data-action="edit" title="编辑"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20h4l10-10-4-4L4 16v4zM14 6l4 4"/></svg></button>
    <button data-action="delete" title="删除"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></button>`;
  actions.querySelectorAll('button').forEach((btn) => {
    btn.addEventListener('click', () => {
      const a = btn.dataset.action;
      if (a === 'edit') editUserMessage(wrapper, full);
      else deleteMessage(wrapper);
    });
  });
  bubble.appendChild(actions);
  wrapper.appendChild(bubble);
  // 用户头像(右侧),与模型头像区分身份
  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar user-avatar';
  avatar.title = '你的提问';
  avatar.textContent = '你';
  wrapper.appendChild(avatar);
  ui.messages.appendChild(wrapper);
  scrollToBottom();
}

/**
 * 创建新会话(后端)
 */
async function createChat(title) {
  const resp = await fetch('/api/chats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!resp.ok) throw new Error('创建会话失败');
  return resp.json();
}

/**
 * 保存当前会话消息到后端
 */
async function saveCurrentChat() {
  if (!appState.currentChatId) return;
  const messages = extractMessages();
  try {
    const resp = await fetch(`/api/chats/${appState.currentChatId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: ui.chatTitle.textContent || '新对话',
        messages,
      }),
    });
    if (!resp.ok) logWarning('保存会话返回异常状态', resp.status);
  } catch (exc) {
    logError('保存会话失败', exc);
    throw exc;
  }
}

/**
 * 渲染历史列表
 */
function renderHistory() {
  try {
    ui.historyList.innerHTML = '';
    HISTORY_GROUPS.forEach((group) => {
      const items = appState.chats.filter((c) => groupOf(c) === group);
      if (!items.length) return;
      const groupEl = document.createElement('div');
      groupEl.className = 'history-group';
      groupEl.innerHTML = `<div class="history-group-label">${group}</div>`;
      items.forEach((item) => {
        const el = document.createElement('div');
        el.className = 'history-item' + (item.id === appState.currentChatId ? ' active' : '');
        const createdText = formatFullTime(item.created_at);
        const updatedText = formatFullTime(item.updated_at);
        el.innerHTML = `<div class="history-item-main">
            ${createdText ? `<div class="history-item-time">创建时间：${createdText}</div>` : ''}
            <div class="history-item-text" title="双击重命名">${esc(item.title)}</div>
            ${updatedText ? `<div class="history-item-time">最近聊天时间：${updatedText}</div>` : ''}
          </div>
          <span class="history-item-actions">
            <button data-action="rename" title="重命名">✎</button>
            <button data-action="delete" title="删除">🗑</button>
          </span>`;
        el.querySelector('.history-item-text').addEventListener('dblclick', (e) => {
          e.stopPropagation();
          renameChat(item);
        });
        el.addEventListener('click', (e) => {
          const actionBtn = e.target.closest('button[data-action]');
          if (actionBtn) {
            e.stopPropagation();
            if (actionBtn.dataset.action === 'delete') deleteChat(item.id);
            else if (actionBtn.dataset.action === 'rename') renameChat(item);
            return;
          }
          loadChat(item);
        });
        groupEl.appendChild(el);
      });
      ui.historyList.appendChild(groupEl);
    });
  } catch (exc) {
    logError('渲染历史失败', exc);
  }
}

/**
 * 获取会话分组(按创建时间)
 */
function groupOf(chat) {
  if (!chat.created_at) return HISTORY_GROUPS[0];
  const days = (Date.now() - new Date(chat.created_at).getTime()) / MS_PER_DAY;
  if (days < 1) return HISTORY_GROUPS[0];
  if (days < 7) return HISTORY_GROUPS[1];
  if (days < 30) return HISTORY_GROUPS[2];
  return HISTORY_GROUPS[3];
}

/**
 * 加载会话
 */
async function loadChat(chat) {
  appState.currentChatId = chat.id;
  ui.chatTitle.textContent = chat.title;
  ui.messages.innerHTML = '';
  ui.welcome.classList.add('hidden');
  ui.chatArea.classList.remove('hidden');

  // 渲染历史消息
  const messages = chat.messages || [];
  messages.forEach((m) => {
    if (m.role === 'user') {
      // 用 display(原文)显示、content(含附件)回传,避免刷新后显示附件全文
      appendUserMessage(m.display || m.content, m.content);
    } else {
      restoreAiMessage(m);
    }
  });
  scrollToBottom();
  renderOutline();
  renderHistory();
}

/**
 * 删除会话
 */
async function deleteChat(id) {
  if (!confirm('确定删除此对话?')) return;
  try {
    await fetch(`/api/chats/${id}`, { method: 'DELETE' });
    appState.chats = appState.chats.filter((c) => c.id !== id);
    if (appState.currentChatId === id) newChat();
    renderHistory();
  } catch (exc) {
    logError('删除会话失败: ' + exc);
    showToast('删除失败');
  }
}

/**
 * 重命名会话(后端 PUT + 本地同步)
 * @param {Object} chat 会话对象
 */
async function renameChat(chat) {
  const newTitle = window.prompt('请输入新的对话标题', chat.title || '');
  if (newTitle === null) return;
  const title = newTitle.trim();
  if (!title) {
    showToast('标题不能为空');
    return;
  }
  try {
    const resp = await fetch(`/api/chats/${chat.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    chat.title = title;
    if (appState.currentChatId === chat.id) ui.chatTitle.textContent = title;
    renderHistory();
    showToast('已重命名');
  } catch (exc) {
    logError('重命名失败', exc);
    showToast(`重命名失败: ${exc.message || exc}`);
  }
}

/**
 * 打开搜索弹层
 */
function openSearch() {
  document.getElementById('search-modal').classList.remove('hidden');
  const input = document.getElementById('search-history-input');
  input.value = '';
  input.focus();
  renderSearchResults();
}

function closeSearch() {
  document.getElementById('search-modal').classList.add('hidden');
}

function renderSearchResults() {
  const q = document.getElementById('search-history-input').value.trim().toLowerCase();
  const results = appState.chats.filter((c) => c.title.toLowerCase().includes(q));
  const box = document.getElementById('search-results');
  if (!results.length) {
    box.innerHTML = '<div class="search-empty">没有找到相关对话</div>';
    return;
  }
  box.innerHTML = results.map((c) => `<div class="search-result-item" data-id="${c.id}">${esc(c.title)}</div>`).join('');
  box.querySelectorAll('.search-result-item').forEach((el) => {
    el.addEventListener('click', () => {
      closeSearch();
      const chat = appState.chats.find((c) => c.id === el.dataset.id);
      if (chat) loadChat(chat);
    });
  });
}

// 搜索输入事件(在 init 后绑定)
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('search-history-input');
  if (searchInput) searchInput.addEventListener('input', renderSearchResults);
});

/**
 * 打开设置弹层
 */
function openSettings() {
  ui.settingsModal.classList.remove('hidden');
}

/**
 * 保存设置到后端
 */
async function saveSettings() {
  try {
    const provider = document.querySelector('.provider-tab.active').dataset.provider;
    const apiKey = document.getElementById('setting-api-key').value.trim();
    const webToken = document.getElementById('setting-web-token').value.trim();
    // 模型选择框为空(如选项不匹配)时回退默认值,避免把空 model 写入配置
    const model = document.getElementById('setting-model').value || DEFAULT_MODEL;

    const payload = {
      provider,
      model,
      thinking_enabled: appState.thinking,
      search_enabled: appState.search,
      enhancements: {
        tools: document.getElementById('enhance-tools-switch').checked,
        context: document.getElementById('enhance-context-switch').checked,
      },
    };
    // 只有填了才更新(空字符串表示保持原值)
    if (apiKey) payload.api_key = apiKey;
    if (webToken) payload.web_token = webToken;

    const resp = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const result = await resp.json();
    if (!result.ok) throw new Error(result.error || '保存失败');

    ui.settingsModal.classList.add('hidden');
    showToast('设置已保存到服务端');
    await loadSettings();
  } catch (exc) {
    logError('保存设置失败', exc);
    showToast(`保存失败: ${exc.message}`);
  }
}

/**
 * 验证 provider 凭据
 */
async function validate(provider) {
  const resultEl = document.getElementById('validate-result');
  resultEl.textContent = '验证中...';
  try {
    const apiKey = document.getElementById('setting-api-key').value.trim();
    const webToken = document.getElementById('setting-web-token').value.trim();
    const resp = await fetch('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey, web_token: webToken }),
    });
    const result = await resp.json();
    resultEl.textContent = result.message;
    resultEl.style.color = result.ok ? 'var(--color-primary)' : COLOR_ERROR;
  } catch (exc) {
    resultEl.textContent = `验证失败: ${exc.message}`;
    resultEl.style.color = COLOR_ERROR;
  }
}

/**
 * 更新 Provider 状态标识
 */
function updateProviderBadge() {
  if (!ui.providerBadge) return;
  const isWeb = appState.currentProvider === 'web';
  ui.providerBadge.textContent = isWeb ? '网页登录态' : '官方 API';
  ui.providerBadge.title = isWeb ? '当前使用网页端登录态(免费)' : '当前使用官方 DeepSeek API';
}

/**
 * 应用增强功能开关
 */
function applyEnhancements() {
  const enh = appState.settings.enhancements || {};
  // 兼容两代字段名:context(新) / context_meter(旧默认配置)
  const contextOn = enh.context !== undefined ? !!enh.context : !!enh.context_meter;
  if (ui.enhanceTools) {
    ui.enhanceTools.classList.toggle('hidden', enh.tools === false);
  }
  const contextEl = document.getElementById('context-meter');
  if (contextEl) contextEl.classList.toggle('hidden', !contextOn);
  document.getElementById('enhance-tools-switch').checked = enh.tools !== false;
  document.getElementById('enhance-context-switch').checked = contextOn;
}

/**
 * 渲染提示词库
 */
function renderPrompts() {
  ui.promptList.innerHTML = PROMPTS.map((p, i) => `
    <div class="prompt-item" data-i="${i}">
      <div class="prompt-item-title">${esc(p.title)}</div>
      <span class="prompt-item-cat">${esc(p.cat)}</span>
      <div class="prompt-item-text">${esc(p.text)}</div>
    </div>
  `).join('');
  ui.promptList.querySelectorAll('.prompt-item').forEach((el) => {
    el.addEventListener('click', () => {
      ui.input.value = PROMPTS[el.dataset.i].text;
      handleInput();
      ui.promptLibrary.classList.add('hidden');
      ui.input.focus();
    });
  });
}

/**
 * 切换专注模式
 */
function toggleFocus() {
  document.body.classList.toggle('focus-mode');
  showToast(document.body.classList.contains('focus-mode') ? '专注模式已开启' : '已退出专注模式');
}

/**
 * 导出对话为 Markdown
 */
function exportConversation() {
  const messages = extractMessages();
  if (!messages.length) {
    showToast('当前没有可导出的对话');
    return;
  }
  const title = ui.chatTitle.textContent || '对话';
  const md = messages.map((m) => `## ${m.role === 'user' ? '用户' : 'HT182400'}\n\n${m.content}`).join('\n\n---\n\n');
  const blob = new Blob([`# ${title}\n\n${md}`], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.md`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('已导出 Markdown');
}

document.addEventListener('DOMContentLoaded', init);
