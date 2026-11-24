/**
 * 前端常量数据模块
 * 提示词库、预置会话等集中管理
 */

/** 预置历史对话(首次使用,无后端数据时展示) */
const PRESET_HISTORY = Object.freeze([
  { id: 'preset-1', title: '欢迎使用 HT182400', group: '今天' },
]);

/** 时间分组 */
const HISTORY_GROUPS = Object.freeze(['今天', '7 天内', '30 天内', '更早']);

/** 提示词库(增强功能) */
const PROMPTS = Object.freeze([
  { title: '专业邮件', cat: '写作', text: '请帮我写一封{场景}的邮件,语气{语气},包含以下要点:{要点}。要求简洁专业,控制在 200 字以内。' },
  { title: '代码审查', cat: '编程', text: '请审查以下代码,从正确性、性能、可读性、安全性四个维度给出改进建议,并提供优化后的版本:\n\n{代码}' },
  { title: 'Bug 排查', cat: '编程', text: '我遇到一个 Bug:{现象}。相关代码如下:{代码}。请帮我分析可能的原因并给出排查步骤。' },
  { title: '费曼讲解', cat: '学习', text: '请用费曼学习法,把「{概念}」讲给 10 岁小孩听,用生活中的类比。' },
  { title: '论文速读', cat: '学习', text: '请快速阅读这篇论文,用中文总结:研究问题、核心方法、主要结论、局限性各一句话。' },
  { title: '头脑风暴', cat: '创意', text: '帮我头脑风暴 5 个关于「{主题}」的创新点子,每个附一句话说明。' },
]);

/** Toast 显示时长(毫秒) */
const TOAST_MS = 2500;

/** 一天的毫秒数(会话时间分组用) */
const MS_PER_DAY = 86400000;

/** 验证失败提示色(红色) */
const COLOR_ERROR = '#e53e3e';

/** 主题主色(CSS 变量不可用时的 fallback) */
const COLOR_PRIMARY = '#4d6bfe';

/** 语音朗读语言 */
const SPEECH_LANG = 'zh-CN';

/** 主题持久化 localStorage 键名 */
const THEME_KEY = 'dsstudio-theme';

/** 单个文本附件大小上限(字节,2MB) */
const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;

/** 上下文用量估算:每 token 约等于的字符数(中文经验值) */
const CHARS_PER_TOKEN = 1.5;

/** 上下文窗口估算容量(tokens) */
const CONTEXT_WINDOW_TOKENS = 64000;

/** 上下文用量告警阈值(比例) */
const CONTEXT_WARN_RATIO = 0.8;

/** 默认模型(模型选择值为空时回退) */
const DEFAULT_MODEL = 'deepseek-flash';

/**
 * 精细变色龙 SVG(品牌图标)
 * 各部位带 class,由 styles.css 以不同相位做七色循环动画,形成"变色流动"效果
 * 面朝右、立于树枝,含螺旋卷尾/头冠/背脊锯齿/转动大眼/斑纹/四足
 */
const CHAMELEON_SVG = `<svg class="cham-logo" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-label="变色龙">
  <path class="cham-branch" d="M2 57 Q20 55 34 56.5 T62 56" fill="none" stroke-width="2.6" stroke-linecap="round"/>
  <path class="cham-tail" d="M19 40 C10 43 3 38 5 29 C6.5 22 15 22 16 29 C16.7 33 12.5 35.5 10.5 32" fill="none" stroke-width="3.6" stroke-linecap="round"/>
  <path class="cham-leg" d="M27 45 L25 55 M25 55 l-3.5 2 M25 55 l3.5 1.5" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path class="cham-leg2" d="M45 45 L47 55 M47 55 l-3.5 2 M47 55 l3.5 1.5" fill="none" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
  <path class="cham-body" d="M19 39 C17 27 27 19 39 20 C49 21 55 27 55 35 C55 43 47 47 37 47 C27 47 20 46 19 39 Z"/>
  <path class="cham-crest" d="M47 22 L51 11 L56 23 Z"/>
  <path class="cham-head" d="M48 23 C55 21 61 25 61 32 L59 38 C57 42 50 41 48 37 Z"/>
  <path class="cham-spine" d="M23 22 l2 -4.5 l3 3.5 l3 -4.5 l3 3.5 l3 -4 l3 3.5" fill="none" stroke-width="2" stroke-linejoin="round"/>
  <g class="cham-spots">
    <circle cx="28" cy="33" r="2.6"/><circle cx="35" cy="29" r="2.1"/><circle cx="32" cy="40" r="2"/><circle cx="41" cy="33" r="1.9"/><circle cx="38" cy="43" r="1.6"/>
  </g>
  <circle class="cham-eye" cx="54" cy="30" r="4.6"/>
  <circle cx="55" cy="30" r="2.2" fill="#fff"/>
  <circle cx="55.5" cy="30" r="1.1" fill="#111827"/>
  <path class="cham-mouth" d="M60 35 l-7 1.5" fill="none" stroke-width="1.4" stroke-linecap="round"/>
</svg>`;
