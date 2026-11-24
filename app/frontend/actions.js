/**
 * 消息操作增强模块
 * 提供编辑/删除/重新生成/停止生成/上下文用量等交互
 * 依赖 app.js 的全局状态(appState/ui)与函数(saveCurrentChat/streamResponse/showToast 等)
 */

'use strict';

/** 重新生成:删除指定 AI 回复及其后消息,重新发起流式请求 */
async function regenerateFrom(wrapper) {
  if (appState.generating) {
    showToast('正在生成中,请先停止');
    return;
  }
  // 删除该回复及其之后的所有消息(重新生成会覆盖从这里开始的内容)
  let node = wrapper;
  while (node) {
    const next = node.nextElementSibling;
    node.remove();
    node = next;
  }
  try {
    const messages = extractMessages();
    if (!messages.length) return;
    appState.generating = true;
    updateSendButton();
    await streamResponse(messages);
    await saveCurrentChat();
  } catch (exc) {
    logError('重新生成失败', exc);
    showToast(`重新生成失败: ${exc.message || exc}`);
  } finally {
    appState.generating = false;
    updateSendButton();
    updateContextMeter();
    renderOutline();
  }
}

/** 编辑 AI 回复:允许手工修改正文(本地修订),保存后提示 */
function editAiMessage(wrapper, text) {
  const body = wrapper.querySelector('.md-body');
  if (!body) return;
  const original = body.innerText;
  const revised = window.prompt('编辑回复内容(仅本地修订,不会重新请求模型):', original);
  if (revised === null || revised === original) return;
  body.textContent = revised;
  // 同步更新操作按钮绑定的文本(重新绑定)
  bindMessageActions(wrapper, revised);
  saveCurrentChat().then(() => showToast('回复已修改并保存')).catch((exc) => {
    logError('编辑回复后保存失败', exc);
    showToast('回复已修改,但保存失败');
  });
}

/** 编辑用户消息:修改后删除该消息之后的所有回复并重新发送 */
async function editUserMessage(wrapper, fullText) {
  if (appState.generating) {
    showToast('正在生成中,请先停止');
    return;
  }
  const revised = window.prompt('编辑消息内容:', fullText);
  if (revised === null || !revised.trim()) return;
  const bubble = wrapper.querySelector('.bubble');
  if (bubble) {
    bubble.dataset.full = revised.trim();
    // 只替换文本显示,保留操作按钮子节点(此前 textContent 会清空按钮)
    const textNode = bubble.childNodes[0];
    if (textNode && textNode.nodeType === Node.TEXT_NODE) {
      textNode.nodeValue = revised.trim();
    } else {
      bubble.insertBefore(document.createTextNode(revised.trim()), bubble.firstChild);
    }
  }
  // 删除该消息之后的所有消息,再重新生成
  let node = wrapper.nextElementSibling;
  while (node) {
    const next = node.nextElementSibling;
    node.remove();
    node = next;
  }
  try {
    const messages = extractMessages();
    appState.generating = true;
    updateSendButton();
    await streamResponse(messages);
    await saveCurrentChat();
  } catch (exc) {
    logError('编辑后重发失败', exc);
    showToast(`编辑后重发失败: ${exc.message || exc}`);
  } finally {
    appState.generating = false;
    updateSendButton();
    updateContextMeter();
    renderOutline();
  }
}

/** 删除单条消息并保存会话 */
function deleteMessage(wrapper) {
  wrapper.remove();
  saveCurrentChat().then(() => showToast('消息已删除')).catch((exc) => {
    logError('删除消息后保存失败', exc);
    showToast('消息已删除,但保存失败');
  });
  updateContextMeter();
  renderOutline();
}

/** 停止生成:中断正在进行的流式请求 */
function stopGeneration() {
  if (abortController) {
    abortController.abort();
    showToast('已停止生成');
    if (ui.stopBtn) ui.stopBtn.classList.add('hidden');
    if (ui.sendBtn) ui.sendBtn.classList.remove('hidden');
  }
}

/** 重置本地界面状态(用户菜单"退出登录"的真实行为) */
function resetLocalUi() {
  try {
    localStorage.removeItem(THEME_KEY);
  } catch (exc) {
    logWarning('清除主题失败', exc);
  }
  document.body.classList.remove('dark-theme', 'focus-mode');
  newChat();
  showToast('已重置界面状态');
}

/** 更新上下文用量条:按当前消息的估算 token 数与阈值计算百分比 */
function updateContextMeter() {
  const meter = document.getElementById('context-meter');
  const bar = document.getElementById('context-meter-bar');
  if (!meter || !bar) return;
  // 开关关闭时隐藏
  const enh = (appState.settings && appState.settings.enhancements) || {};
  const contextOn = enh.context !== undefined ? enh.context === true : enh.context_meter === true;
  if (!contextOn) {
    meter.classList.add('hidden');
    return;
  }
  meter.classList.remove('hidden');
  const messages = extractMessages();
  const chars = messages.reduce((sum, m) => sum + (m.content || '').length, 0);
  const estimatedTokens = Math.ceil(chars / CHARS_PER_TOKEN);
  const ratio = Math.min(estimatedTokens / CONTEXT_WINDOW_TOKENS, 1);
  bar.style.width = `${(ratio * 100).toFixed(1)}%`;
  bar.style.background = ratio > CONTEXT_WARN_RATIO
    ? `var(--color-danger, ${COLOR_ERROR})`
    : `var(--color-primary, ${COLOR_PRIMARY})`;
  meter.title = `上下文用量约 ${estimatedTokens} / ${CONTEXT_WINDOW_TOKENS} tokens`;
}

/**
 * 创建来源聚合卡(基于后端返回的真实来源数据)
 * @param {Array} items 来源项,每项含 title/url/snippet
 */
function createSourcesPill(items) {
  const el = document.createElement('div');
  el.className = 'sources-card';
  const list = Array.isArray(items) ? items : [];
  const count = list.length;
  if (!count) {
    el.innerHTML = '<span class="sources-card-empty">🌐 本次搜索未返回可展示来源</span>';
    return el;
  }
  const head = document.createElement('div');
  head.className = 'sources-card-head';
  head.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M10 13a5 5 0 007.5.5l2-2a5 5 0 00-7-7l-1 1M14 11a5 5 0 00-7.5-.5l-2 2a5 5 0 007 7l1-1"/></svg><span>${count} 条来源</span><span class="sources-arrow">▾</span>`;
  const body = document.createElement('div');
  body.className = 'sources-card-body';
  body.style.display = 'none';
  list.forEach((it, i) => {
    const row = document.createElement('div');
    row.className = 'sources-card-item';
    const title = it.title || it.url || '来源';
    const url = it.url || '';
    const snippet = it.snippet || '';
    row.innerHTML = `<span class="sources-idx">${i + 1}</span>
      <div class="sources-item-main">
        ${url ? `<a href="${escAttr(url)}" target="_blank" rel="noopener noreferrer" class="sources-title">${esc(title)}</a>` : `<span class="sources-title">${esc(title)}</span>`}
        ${url ? `<div class="sources-url">${esc(url)}</div>` : ''}
        ${snippet ? `<div class="sources-snippet">${esc(snippet)}</div>` : ''}
      </div>`;
    body.appendChild(row);
  });
  head.addEventListener('click', () => {
    const open = body.style.display === 'none';
    body.style.display = open ? 'block' : 'none';
    head.querySelector('.sources-arrow').textContent = open ? '▴' : '▾';
  });
  el.appendChild(head);
  el.appendChild(body);
  return el;
}

/** 创建搜索徽章(web pages 数量来自真实来源条数) */
function createSearchBadge() {
  const el = document.createElement('div');
  el.className = 'search-badge';
  el.innerHTML = '<span class="search-badge-icon">🌐</span><span class="search-badge-text">正在搜索…</span>';
  return el;
}

/** 用真实来源条数更新搜索徽章 */
function setSearchBadgeCount(el, count) {
  const text = el.querySelector('.search-badge-text');
  if (text) text.textContent = `${count} web pages`;
}

/** HTML 属性转义,防止链接注入 */
function escAttr(s) { return esc(s).replace(/"/g, '&quot;'); }

/**
 * 分享对话:把当前对话整理为文本复制到剪贴板
 */
async function shareConversation() {
  const messages = extractMessages();
  if (!messages.length) {
    showToast('当前没有可分享的对话');
    return;
  }
  const title = ui.chatTitle.textContent || 'HT182400 对话';
  const text = messages.map((m) => `${m.role === 'user' ? '我' : 'HT182400'}：${m.content}`).join('\n\n');
  try {
    await navigator.clipboard.writeText(`【${title}】\n\n${text}`);
    showToast('对话已复制,可直接粘贴分享');
  } catch (exc) {
    logWarning('分享复制失败', exc);
    showToast('复制失败,请使用导出功能');
  }
}

/**
 * 渲染右侧消息大纲:每个用户提问一个可定位锚点
 */
function renderOutline() {
  const nav = document.getElementById('outline-nav');
  if (!nav) return;
  const userMsgs = Array.from(document.querySelectorAll('#messages .message-user'));
  if (userMsgs.length < 2) {
    nav.innerHTML = '';
    nav.classList.toggle('hidden', true);
    return;
  }
  nav.classList.remove('hidden');
  nav.innerHTML = userMsgs.map((_, i) => `<button data-i="${i}" title="跳转到第 ${i + 1} 轮提问" class="${i === 0 ? 'active' : ''}"></button>`).join('');
  nav.querySelectorAll('button').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.i);
      const target = userMsgs[idx];
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        nav.querySelectorAll('button').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
      }
    });
  });
}

/**
 * 从 AI 消息 DOM 构建完整消息对象(含思考过程与来源)
 * @param {HTMLElement} el 消息节点
 * @param {string} text 正文文本
 * @returns {Object} 消息对象
 */
function buildAssistantMessage(el, text) {
  const msg = { role: 'assistant', content: text };
  const thinkingEl = el.querySelector('.thinking-content');
  if (thinkingEl && thinkingEl.innerText.trim()) msg.thinking = thinkingEl.innerText.trim();
  const sourcesEl = el.querySelector('.sources-card');
  if (sourcesEl) {
    const items = Array.from(sourcesEl.querySelectorAll('.sources-card-item')).map((row) => {
      const a = row.querySelector('a.sources-title');
      return {
        title: row.querySelector('.sources-title')?.textContent || '',
        url: a ? a.href : '',
        snippet: row.querySelector('.sources-snippet')?.textContent || '',
      };
    });
    if (items.length) msg.sources = items;
  }
  return msg;
}

/**
 * 恢复 AI 消息(正文 + 思考 + 来源)到对话区
 * @param {Object} m 消息对象
 */
function restoreAiMessage(m) {
  const wrapper = createAiMessage();
  wrapper.querySelector('.md-body').innerHTML = renderMarkdown(m.content);
  if (m.thinking) {
    const panel = createThinkingPanel();
    panel.querySelector('.thinking-content').textContent = m.thinking;
    wrapper.querySelector('.md-body').before(panel);
  }
  if (m.sources && m.sources.length) {
    wrapper.querySelector('.msg-actions').before(createSourcesPill(m.sources));
  }
  bindMessageActions(wrapper, m.content);
}
