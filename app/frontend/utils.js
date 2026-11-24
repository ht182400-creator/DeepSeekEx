/**
 * 通用工具模块:HTML 转义、滚动、复制、朗读、Markdown 渲染、Toast、日志
 * 作为全局函数供 app.js / actions.js 调用
 */

'use strict';

/** HTML 转义,防止 XSS */
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

/** 滚动对话区到底部 */
function scrollToBottom() { if (ui.chatArea) ui.chatArea.scrollTop = ui.chatArea.scrollHeight; }

/** 复制文本到剪贴板(带 execCommand 兜底) */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('已复制');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    showToast('已复制');
  }
}

/** 使用浏览器语音合成朗读文本 */
function speakText(text) {
  if (!('speechSynthesis' in window)) { showToast('浏览器不支持朗读'); return; }
  const u = new SpeechSynthesisUtterance(text.replace(/[#*`]/g, ''));
  u.lang = SPEECH_LANG;
  speechSynthesis.speak(u);
}

/**
 * 简易 Markdown 渲染(标题/加粗/行内代码/代码块/列表)
 * @param {string} text 原始 Markdown
 * @returns {string} HTML
 */
function renderMarkdown(text) {
  try {
    const blocks = [];
    let h = text.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => {
      blocks.push(`<pre><code>${esc(code.trim())}</code></pre>`);
      return `\u0000B${blocks.length - 1}\u0000`;
    });
    h = esc(h);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/(?:^\d+\. .+\n?)+/gm, (b) => `<ol>${b.trim().split('\n').map((l) => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('')}</ol>`);
    h = h.replace(/(?:^- .+\n?)+/gm, (b) => `<ul>${b.trim().split('\n').map((l) => `<li>${l.replace(/^- /, '')}</li>`).join('')}</ul>`);
    h = h.split('\n').map((line) => {
      const t = line.trim();
      if (!t) return '';
      if (/^<(h\d|ul|ol|li|pre)/.test(t)) return line;
      return `<p>${line}</p>`;
    }).join('\n');
    blocks.forEach((b, i) => { h = h.replace(`\u0000B${i}\u0000`, b); });
    return h;
  } catch { return esc(text); }
}

/** 显示 Toast 提示 */
function showToast(msg) {
  if (!ui.toast) return;
  ui.toast.textContent = msg;
  ui.toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => ui.toast.classList.add('hidden'), TOAST_MS);
}

const LOG = '[HT182400]';
function logDebug(m, d) { d !== undefined ? console.debug(LOG, m, d) : console.debug(LOG, m); }
function logInfo(m, d) { d !== undefined ? console.info(LOG, m, d) : console.info(LOG, m); }
function logWarning(m, e) { console.warn(LOG, m, e); }
function logError(m, e) { console.error(LOG, m, e); }

/**
 * 把精细变色龙 SVG 注入到所有占位节点(静态 + 动态)
 * @param {HTMLElement} root 查找范围,默认整个文档
 */
function injectChameleons(root) {
  const scope = root || document;
  scope.querySelectorAll('.cham-slot').forEach((el) => {
    if (el.dataset.chamInjected) return;
    el.innerHTML = CHAMELEON_SVG;
    el.dataset.chamInjected = '1';
  });
}
