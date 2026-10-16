import { uiLocale } from '../../i18n/index.js';
/* Extracted from pages/MobileSaves.jsx — mechanical split, byte-for-byte. */

/* ── 工具函数 ─────────────────────────────────────────────── */
const API = () => window.__API_BASE || '';
const fmtDate = (v) => {
  if (!v) return '—';
  try { return new Date(v).toLocaleDateString(uiLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch (_) { return String(v); }
};
const normSave = (x) => (window.__normalizeSave ? window.__normalizeSave(x) : x);
const normScript = (x) => (window.__normalizeScript ? window.__normalizeScript(x) : x);

export { API, fmtDate, normSave, normScript };
