/* feedback — 反馈共享内核 + 法务/渠道常量 + 决策文案(语义统一 #22 / #26)
 *
 * 此前各反馈入口(FeedbackQuickModal / FeedbackDrawer / pages/feedback / mobile/MobileCaps)
 * 各抄一份:同意文案常量、AUP / QQ 群常量、运行环境快照 + POST /api/feedback 的提交内核、
 * 以及「处理决策 → 中文标签」映射。抽到此处单一来源,各端 UI 仍各自保留。
 */
import { sha256hex } from './crypto-safe.js';
import i18n from '../i18n/index.js';

// ── 法务 / 渠道常量(各端逐字一致 → 共享) ──────────────────────────────
export const AUP_LINK = 'https://play.stellatrix.icu/legal/aup#2J';
export const MAX_FREE_TEXT = 10000;
export const QQ_GROUP_NUMBER = '584876566';
export const QQ_JOIN_URL = 'https://qm.qq.com/q/49Dqcr0aw0';
export const QQ_QR_SRC = '/qq-group.jpg';

// 同意文案规范版(FeedbackQuickModal / pages/feedback / MobileCaps 用此 ASCII 标点版)。
// 注:FeedbackDrawer 历史上用全角标点版,显示文案不同 → 不强行统一(见该文件),
// 提交时各端把自己的文案作为 consentText 传入(后端只校验 64-hex,不校验等于某文案的 SHA256)。
export const CONSENT_TEXT = '我已阅读 AUP §2.J,理解不得包含成人主题节选,同意(此操作记录我的同意)';

/**
 * 处理决策 → 用户侧中文标签(语义统一 #26)。
 * 受众=反馈提交者(已采纳 / 未采纳),≠ MobileAdmin 的管理员侧 decisionLabel(OK/封号/垃圾)。
 *   null/'' → 待处理 · ok → 已采纳 · spam → 未采纳 · nsfw_terminate → 违规处理 · 其它原样。
 * @param {string | null | undefined} decision
 * @returns {string}
 */
export function feedbackDecisionLabel(decision) {
  if (!decision) return i18n.t('feedback.decision.pending');
  if (decision === 'ok') return i18n.t('feedback.decision.ok');
  if (decision === 'spam') return i18n.t('feedback.decision.spam');
  if (decision === 'nsfw_terminate') return i18n.t('feedback.decision.nsfw_terminate');
  return decision;
}

/**
 * 反馈提交内核:算 consent_token、(可选)追加运行环境快照到 excerpts、POST /api/feedback、解析回执。
 * 成功返回响应 data;失败抛 Error(message 取后端 detail/error 或 HTTP 状态)。
 * 各端 UI(表单状态 / toast / 历史刷新)仍各自处理。
 *
 * @param {Object}   opts
 * @param {string}   opts.freeText             反馈正文
 * @param {Array}    [opts.excerpts=[]]        已选对话节选(调用方预先构造好的数组,会被原地 push 运行快照)
 * @param {string}   [opts.consentText]        同意文案(默认规范版;FeedbackDrawer 传自己的全角版)
 * @param {boolean}  [opts.includeRuntime=false] 是否追加运行环境快照
 * @param {boolean}  [opts.includeRecentDialog=true] 运行快照是否带最近对话(现拉 /api/state 喂最新 history)
 * @returns {Promise<any>} 后端响应 data
 */
export async function submitFeedback({
  freeText,
  excerpts = [],
  consentText = CONSENT_TEXT,
  includeRuntime = false,
  includeRecentDialog = true,
  contactEmail = '',
} = {}) {
  const token = await sha256hex(consentText);
  if (includeRuntime) {
    try {
      // 现拉一次 /api/state 拿权威最新对话,避免 MOCK_STATE 陈旧(各端原内核一致)。
      let freshHistory = null;
      try {
        const st = await window.api?.game?.state?.();
        if (st && Array.isArray(st.history)) freshHistory = st.history;
      } catch (_) {}
      const snap = window.__getRuntimeSnapshot
        && window.__getRuntimeSnapshot({ includeRecentDialog, recentDialog: freshHistory });
      if (snap && snap.__runtime__) excerpts.push(snap);
    } catch (_) {}
  }
  const res = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      free_text: freeText,
      excerpts,
      consent_token: token,
      app_version: window.__APP_VERSION__ || '',
      ...(contactEmail ? { contact_email: contactEmail } : {}),
    }),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) {
    throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  }
  return data;
}

if (typeof window !== 'undefined') {
  window.feedbackDecisionLabel = feedbackDecisionLabel;
}
