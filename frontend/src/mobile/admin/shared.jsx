/* MobileAdmin 共享工具 + 行组件(fmtTime/fmtDate/LoadingRow/ErrRow/EmptyRow)。
   纯机械从 pages/MobileAdmin.jsx 拆出,JSX/props 路径零变化(逐字节等价)。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { fmtTimeFallback } from '../../data-loader.js';
import { uiLocale } from '../../i18n/index.js';

/* ── 工具 ─────────────────────────────────────────────── */
// 统一到 window.__fmt.time(data-loader.js;zh-CN 24h 制),保留本地别名免改调用点。
function fmtTime(iso) {
  if (window.__fmt && window.__fmt.time) return window.__fmt.time(iso);
  return fmtTimeFallback(iso);
}
function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString(uiLocale()); } catch (_) { return iso; }
}

function LoadingRow() {
  const { t } = useTranslation();
  return <div className="pl-row" style={{ justifyContent: 'center', color: 'var(--muted)', fontSize: 13 }}>{t('common.loading')}</div>;
}
function ErrRow({ msg, onRetry }) {
  const { t } = useTranslation();
  return (
    <div className="pl-row" style={{ flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
      <span className="pl-row-ic warn"><Icon name="warn" size={17} /></span>
      <span style={{ fontSize: 13, color: 'var(--danger)' }}>{msg}</span>
      {onRetry && <button className="pl-btn-ghost" style={{ fontSize: 12 }} onClick={onRetry}>{t('mobile.admin.retry')}</button>}
    </div>
  );
}
function EmptyRow({ text }) {
  const { t } = useTranslation();
  return <div className="pl-empty" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>{text ?? t('mobile.admin.no_data')}</div>;
}

export { fmtTime, fmtDate, LoadingRow, ErrRow, EmptyRow };
