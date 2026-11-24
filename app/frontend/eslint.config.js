// ESLint 10 扁平配置（Flat Config）
// 项目为浏览器原生脚本（4 个 js 文件通过 <script> 顺序加载，无模块系统），
// 因此所有跨文件共享的常量/函数必须显式声明为全局，否则 no-undef 会大量误报。

const {
  defineConfig,
  globalIgnores,
} = require('eslint/config');

// 浏览器标准全局 API
const browserGlobals = {
  window: 'readonly', document: 'readonly', navigator: 'readonly', location: 'readonly',
  localStorage: 'readonly', sessionStorage: 'readonly', fetch: 'readonly', console: 'readonly',
  setTimeout: 'readonly', clearTimeout: 'readonly', setInterval: 'readonly', clearInterval: 'readonly',
  requestAnimationFrame: 'readonly', cancelAnimationFrame: 'readonly', Blob: 'readonly', URL: 'readonly',
  URLSearchParams: 'readonly', FileReader: 'readonly', Event: 'readonly', CustomEvent: 'readonly',
  MouseEvent: 'readonly', KeyboardEvent: 'readonly', AbortController: 'readonly',
  speechSynthesis: 'readonly', SpeechSynthesisUtterance: 'readonly', DOMParser: 'readonly',
  Node: 'readonly', NodeList: 'readonly', HTMLElement: 'readonly', HTMLInputElement: 'readonly',
  Element: 'readonly', Text: 'readonly', Image: 'readonly', alert: 'readonly', confirm: 'readonly',
  prompt: 'readonly', encodeURIComponent: 'readonly', decodeURIComponent: 'readonly',
  TextDecoder: 'readonly', TextEncoder: 'readonly', atob: 'readonly', btoa: 'readonly',
  structuredClone: 'readonly', crypto: 'readonly', performance: 'readonly',
};

// 项目跨文件常量（data.js 定义，其他文件使用）
const projectConstants = {
  DEFAULT_MODEL: 'readonly', MS_PER_DAY: 'readonly', COLOR_ERROR: 'readonly',
  COLOR_PRIMARY: 'readonly', SPEECH_LANG: 'readonly', HISTORY_GROUPS: 'readonly',
  PRESET_HISTORY: 'readonly', PROMPTS: 'readonly', TOAST_MS: 'readonly', THEME_KEY: 'readonly',
  MAX_ATTACHMENT_BYTES: 'readonly', CHARS_PER_TOKEN: 'readonly', CONTEXT_WINDOW_TOKENS: 'readonly',
  CONTEXT_WARN_RATIO: 'readonly', CHAMELEON_SVG: 'readonly',
};

// 项目跨文件函数与可变状态（utils.js / actions.js / app.js 定义并互相调用）
const projectFunctions = {
  ui: 'writable', appState: 'writable', abortController: 'writable',
  utils: 'readonly', escapeHtml: 'readonly', esc: 'readonly', formatTime: 'readonly',
  formatFullTime: 'readonly',
  renderMarkdown: 'readonly', scrollToBottom: 'readonly', copyText: 'readonly',
  speakText: 'readonly', logDebug: 'readonly', logInfo: 'readonly', logWarning: 'readonly',
  logError: 'readonly', injectChameleons: 'readonly', showToast: 'readonly',
  buildAssistantMessage: 'readonly', restoreAiMessage: 'readonly', updateContextMeter: 'readonly',
  renderOutline: 'readonly', saveCurrentChat: 'readonly', editUserMessage: 'readonly',
  stopGeneration: 'readonly', renameChat: 'readonly', bindMessageActions: 'readonly',
  extractMessages: 'readonly', createAiMessage: 'readonly', createSearchBadge: 'readonly',
  createSourcesPill: 'readonly', createThinkingPanel: 'readonly', deleteMessage: 'readonly',
  editAiMessage: 'readonly', regenerateFrom: 'readonly', setSearchBadgeCount: 'readonly',
  shareConversation: 'readonly', resetLocalUi: 'readonly', newChat: 'readonly',
  streamResponse: 'readonly', updateSendButton: 'readonly',
};

module.exports = defineConfig([
  globalIgnores(['node_modules/**', 'coverage/**']),
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'script',
      globals: { ...browserGlobals, ...projectConstants, ...projectFunctions },
    },
    rules: {
      // error：真实语法/逻辑风险
      'no-undef': 'error',
      'no-unreachable': 'error',
      'no-dupe-keys': 'error',
      'no-dupe-args': 'error',
      'no-duplicate-case': 'error',
      'no-cond-assign': 'error',
      'no-constant-condition': 'error',
      'no-unsafe-finally': 'error',
      'no-self-assign': 'error',
      'no-obj-calls': 'error',
      'no-sparse-arrays': 'error',
      'use-isnan': 'error',
      'valid-typeof': 'error',
      // warn：可维护性提示（跨文件常量在定义文件内显示未使用属正常，降级为 warn）
      'eqeqeq': ['warn', 'smart'],
      'no-var': 'warn',
      'no-unused-vars': ['warn', { args: 'none', varsIgnorePattern: '^_' }],
      'prefer-const': 'warn',
      'no-console': 'off',
    },
  },
  {
    // data.js / utils.js 是共享定义文件：其顶层常量与函数供其他 <script> 使用，
    // 在定义文件内单看确实"未被使用"，这是原生脚本架构的固有特性，关闭该规则避免假警告。
    files: ['data.js', 'utils.js', 'actions.js'],
    rules: {
      'no-unused-vars': 'off',
    },
  },
]);
