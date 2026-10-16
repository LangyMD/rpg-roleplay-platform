/* Extracted from pages/MobileCaps.jsx — mechanical split, byte-for-byte. */
import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { MField, EmptyState } from './shared.jsx';
import { sha256hex } from '../../lib/crypto-safe.js';
import { feedbackDecisionLabel } from '../../lib/feedback.js';
import { fmtTimeFallback } from '../../data-loader.js';

const CONSENT_TEXT = '我已阅读 AUP §2.J,理解不得包含成人主题节选,同意(此操作记录我的同意)';
const AUP_LINK = 'https://play.stellatrix.icu/legal/aup#2J';
const MAX_FREE_TEXT = 10000;
const QQ_GROUP_NUMBER = '584876566';
const QQ_JOIN_URL = 'https://qm.qq.com/q/49Dqcr0aw0';

/* ──────────────────────────────────────────────────────────────────
   FEEDBACK
   ────────────────────────────────────────────────────────────────── */
const statusLabel = feedbackDecisionLabel;  // 语义统一 #26:用户侧决策标签(共享 lib/feedback.js)
function statusColor(d) {
  return !d ? 'info' : d === 'ok' ? 'ok' : d === 'spam' ? '' : 'danger';
}
// 统一到 window.__fmt.time(data-loader.js;zh-CN 24h 制),保留本地别名免改调用点。
function fmtTime(ts) {
  if (window.__fmt && window.__fmt.time) return window.__fmt.time(ts);
  return fmtTimeFallback(ts);
}

function FeedbackSection({ toast }) {
  const { t } = useTranslation();
  // Submit form state
  const [freeText, setFreeText] = useState('');
  const [includeRuntime, setIncludeRuntime] = useState(true);
  const [includeExcerpts, setIncludeExcerpts] = useState(false);
  const [recentTurns, setRecentTurns] = useState([]);
  const [selectedExcerpts, setSelectedExcerpts] = useState([]);
  const [consent, setConsent] = useState(false);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitDone, setSubmitDone] = useState(false);
  const [submitErr, setSubmitErr] = useState('');
  const [runtimePreview, setRuntimePreview] = useState(null);

  // History state
  const [history, setHistory] = useState([]);
  const [histLoading, setHistLoading] = useState(false);
  const [histErr, setHistErr] = useState('');
  const [filter, setFilter] = useState('all');

  // Section toggle: form vs history
  const [view, setView] = useState('form'); // 'form' | 'history'

  const loadHistory = useCallback(async () => {
    setHistLoading(true); setHistErr('');
    try {
      const res = await fetch('/api/me/feedback?limit=50', { credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!data || !data.ok) throw new Error(data?.error || t('mobile.caps.feedback.history.load_error'));
      setHistory(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      setHistErr(e?.message || t('mobile.caps.feedback.history.load_error'));
    } finally {
      setHistLoading(false);
    }
  }, []);

  useEffect(() => {
    try {
      const snap = window.__getRuntimeSnapshot && window.__getRuntimeSnapshot();
      setRuntimePreview(snap ? snap.__runtime__ : null);
    } catch (_) {}
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (!includeExcerpts) return;
    let cancelled = false;
    (async () => {
      try {
        let nodes = null;
        let saveId = '';
        try {
          const state = await window.api?.game?.state?.();
          nodes = state?.history || state?.branch_nodes || state?.turns || null;
          saveId = state?.save_id || state?._raw?.save_id || '';
        } catch (_) {}
        if (!Array.isArray(nodes) || nodes.length === 0) {
          if (window.MOCK_STATE && Array.isArray(window.MOCK_STATE.history)) nodes = window.MOCK_STATE.history;
        }
        const recent = (Array.isArray(nodes) ? nodes : [])
          .filter(n => n && (n.role === 'user' || n.role === 'assistant' || n.role === 'gm') && (n.content || n.text));
        const turns = recent.slice(-6).map((n, i) => ({
          idx: i, session_id: saveId, range: String(n.turn_index ?? n.turn ?? i),
          plaintext: ((n.content || n.text || '') + '').slice(0, 200),
          label: n.role === 'user' ? t('mobile.caps.feedback.turn_label.player') : 'GM',
        }));
        if (!cancelled) setRecentTurns(turns);
      } catch (_) { if (!cancelled) setRecentTurns([]); }
    })();
    return () => { cancelled = true; };
  }, [includeExcerpts]);

  const canSubmit = consent && freeText.trim().length > 0 && freeText.length <= MAX_FREE_TEXT && !submitBusy;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitBusy(true); setSubmitErr('');
    try {
      const token = await sha256hex(CONSENT_TEXT);
      const excerpts = includeExcerpts
        ? recentTurns.filter(t => selectedExcerpts.includes(t.idx)).map(({ session_id, range, plaintext }) => ({ session_id, range, plaintext }))
        : [];
      if (includeRuntime) {
        try {
          let freshHistory = null;
          try {
            const st = await window.api?.game?.state?.();
            if (st && Array.isArray(st.history)) freshHistory = st.history;
          } catch (_) {}
          const snap = window.__getRuntimeSnapshot && window.__getRuntimeSnapshot({ includeRecentDialog: true, recentDialog: freshHistory });
          if (snap && snap.__runtime__) excerpts.push(snap);
        } catch (_) {}
      }
      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ free_text: freeText, excerpts, consent_token: token, app_version: window.__APP_VERSION__ || '' }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      setSubmitDone(true);
      setFreeText(''); setConsent(false); setIncludeExcerpts(false); setSelectedExcerpts([]);
      toast(t('mobile.caps.feedback.toast.submitted'), 'ok');
      loadHistory();
    } catch (e) {
      setSubmitErr(e?.message || t('mobile.caps.feedback.submit_error'));
    } finally {
      setSubmitBusy(false);
    }
  };

  const handleWithdraw = async (id) => {
    if (!await window.__confirm({ message: t('mobile.caps.feedback.confirm.withdraw', { id }), danger: true })) return;
    try {
      const res = await fetch(`/api/feedback/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast(t('mobile.caps.feedback.toast.withdrawn'), 'ok');
      loadHistory();
    } catch (e) {
      toast(t('mobile.caps.feedback.toast.withdraw_failed'), 'danger');
    }
  };

  const counts = {
    total: history.length,
    pending: history.filter(it => !it.review_decision).length,
    ok: history.filter(it => it.review_decision === 'ok').length,
  };

  const filtered = history.filter(it => {
    if (filter === 'all') return true;
    if (filter === 'pending') return !it.review_decision;
    if (filter === 'ok') return it.review_decision === 'ok';
    return it.review_decision && it.review_decision !== 'ok';
  });

  return (
    <div className="pl-pad">
      {/* View toggle */}
      <div className="pl-seg2" style={{ marginBottom: 18 }}>
        <button className={view === 'form' ? 'active' : ''} onClick={() => setView('form')}>{t('mobile.caps.feedback.tab.submit')}</button>
        <button className={view === 'history' ? 'active accent' : ''} onClick={() => setView('history')}>
          {t('mobile.caps.feedback.tab.history')}{counts.total > 0 ? ` (${counts.total})` : ''}
        </button>
      </div>

      {view === 'form' && (
        <div style={{ display: 'grid', gap: 14 }}>
          {/* Warning */}
          <div style={{ padding: '11px 13px', borderRadius: 12, background: 'var(--warn-soft)', border: '1px solid rgba(212,179,102,0.3)', fontSize: 12.5, color: 'var(--text-quiet)', lineHeight: 1.6 }}>
            <strong style={{ color: 'var(--warn)' }}>{t('mobile.caps.feedback.warning.title')}</strong> {t('mobile.caps.feedback.warning.body')}
            {t('mobile.caps.feedback.warning.see')} <a href={AUP_LINK} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>AUP §2.J</a>
          </div>

          {submitDone && (
            <div style={{ padding: '11px 13px', borderRadius: 12, background: 'var(--ok-soft)', border: '1px solid rgba(126,184,142,0.3)', fontSize: 12.5, color: 'var(--ok)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="check" size={14} />
              {t('mobile.caps.feedback.submit_done')}
              <button onClick={() => setSubmitDone(false)} style={{ marginLeft: 'auto', color: 'var(--ok)', fontSize: 11 }}>{t('common.close')}</button>
            </div>
          )}
          {submitErr && (
            <div style={{ padding: '11px 13px', borderRadius: 12, background: 'var(--danger-soft)', border: '1px solid rgba(200,103,93,0.3)', fontSize: 12.5, color: 'var(--danger)' }}>
              {submitErr}
            </div>
          )}

          <MField label={t('mobile.caps.feedback.form.label')} desc={t('mobile.caps.feedback.form.max_chars', { max: MAX_FREE_TEXT })}>
            <textarea
              className="pl-input"
              placeholder={t('mobile.caps.feedback.form.placeholder')}
              value={freeText}
              onChange={e => setFreeText(e.target.value)}
              style={{ minHeight: 120, fontSize: 16, lineHeight: 1.6 }}
              disabled={submitBusy}
            />
            {freeText.length > MAX_FREE_TEXT && (
              <span style={{ fontSize: 11, color: 'var(--danger)' }}>{t('mobile.caps.feedback.form.over_limit', { max: MAX_FREE_TEXT })}</span>
            )}
          </MField>

          {/* Checkboxes */}
          <div style={{ display: 'grid', gap: 10 }}>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13, color: 'var(--text-quiet)', lineHeight: 1.5, cursor: 'pointer' }}>
              <input type="checkbox" checked={includeRuntime} onChange={e => setIncludeRuntime(e.target.checked)} disabled={submitBusy} style={{ marginTop: 2, accentColor: 'var(--accent)', width: 16, height: 16, flex: 'none' }} />
              {t('mobile.caps.feedback.form.include_runtime')}
            </label>
            {includeRuntime && runtimePreview && (
              <div className="mono" style={{ fontSize: 11, color: 'var(--muted)', padding: '8px 10px', borderRadius: 8, background: 'var(--bg-deep)', border: '1px solid var(--line-soft)', lineHeight: 1.7 }}>
                {t('mobile.caps.feedback.runtime_preview.page')} {runtimePreview.hash || runtimePreview.url || '—'} · {t('mobile.caps.feedback.runtime_preview.save')} {String(runtimePreview.active?.save_id ?? '—')}
                {'\n'}{t('mobile.caps.feedback.runtime_preview.errors')} {runtimePreview.errors?.length || 0} · {t('mobile.caps.feedback.runtime_preview.api_failures')} {runtimePreview.api_failures?.length || 0}
              </div>
            )}

            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13, color: 'var(--text-quiet)', lineHeight: 1.5, cursor: 'pointer' }}>
              <input type="checkbox" checked={includeExcerpts} onChange={e => setIncludeExcerpts(e.target.checked)} disabled={submitBusy} style={{ marginTop: 2, accentColor: 'var(--accent)', width: 16, height: 16, flex: 'none' }} />
              {t('mobile.caps.feedback.form.include_excerpts')}
            </label>
            {includeExcerpts && (
              recentTurns.length === 0
                ? <div style={{ fontSize: 12, color: 'var(--muted)', paddingLeft: 26 }}>{t('mobile.caps.feedback.form.no_excerpts')}</div>
                : <div style={{ paddingLeft: 26, display: 'grid', gap: 7 }}>
                    {recentTurns.map(turn => (
                      <label key={turn.idx} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12.5, color: 'var(--muted)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={selectedExcerpts.includes(turn.idx)} onChange={() => setSelectedExcerpts(p => p.includes(turn.idx) ? p.filter(i => i !== turn.idx) : [...p, turn.idx])} disabled={submitBusy} style={{ marginTop: 2, accentColor: 'var(--accent)', flex: 'none' }} />
                        <span><strong style={{ color: 'var(--text-quiet)' }}>{turn.label}</strong> {turn.plaintext.slice(0, 60)}{turn.plaintext.length > 60 ? '…' : ''}</span>
                      </label>
                    ))}
                  </div>
            )}
          </div>

          {/* Consent */}
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 12, color: 'var(--muted)', lineHeight: 1.55, cursor: 'pointer', padding: '11px 13px', borderRadius: 11, border: '1px solid var(--line-soft)', background: 'var(--panel)' }}>
            <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={submitBusy} style={{ marginTop: 2, accentColor: 'var(--accent)', width: 16, height: 16, flex: 'none' }} />
            {t('feedback_page.consent_text')}
          </label>

          <button
            className="pl-btn-primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{ opacity: !canSubmit ? 0.5 : 1 }}
          >
            {submitBusy ? <><span>{t('mobile.caps.feedback.form.submitting')}</span></> : <><Icon name="upload" size={17} />{t('mobile.caps.feedback.form.submit_btn')}</>}
          </button>

          {/* QQ group footer */}
          <div style={{ padding: '14px', borderRadius: 13, border: '1px solid var(--line-soft)', background: 'var(--panel)', marginTop: 4 }}>
            <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.14em', color: 'var(--muted-2)', marginBottom: 8 }}>{t('mobile.caps.feedback.qq.heading')}</div>
            <div style={{ fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6, marginBottom: 10 }}>
              {t('mobile.caps.feedback.qq.body', { group: QQ_GROUP_NUMBER })}
            </div>
            <a href={QQ_JOIN_URL} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 7, height: 38, padding: '0 16px', borderRadius: 10, background: 'var(--accent)', color: '#fff8f3', fontSize: 13.5, fontWeight: 500, textDecoration: 'none' }}>
              <Icon name="link" size={14} />{t('mobile.caps.feedback.qq.join_btn')}
            </a>
          </div>
        </div>
      )}

      {view === 'history' && (
        <div style={{ display: 'grid', gap: 14 }}>
          {/* KPI row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            {[
              { label: t('mobile.caps.feedback.kpi.total'), value: counts.total, color: '' },
              { label: t('mobile.caps.feedback.kpi.pending'), value: counts.pending, color: 'var(--info)' },
              { label: t('mobile.caps.feedback.kpi.accepted'), value: counts.ok, color: 'var(--ok)' },
            ].map(k => (
              <div key={k.label} style={{ border: '1px solid var(--line-soft)', borderRadius: 11, background: 'var(--panel)', padding: '11px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-serif)', color: k.color || 'var(--text)', lineHeight: 1.1 }}>{k.value}</div>
                <div style={{ fontSize: 10.5, color: 'var(--muted-2)', marginTop: 3 }}>{k.label}</div>
              </div>
            ))}
          </div>

          {/* Filter pills */}
          <div className="pl-seg-scroll" style={{ padding: '0 0 2px', gap: 7 }}>
            {[
              { id: 'all', label: `${t('common.all')} ${counts.total}` },
              { id: 'pending', label: `${t('mobile.caps.feedback.filter.pending')} ${counts.pending}` },
              { id: 'ok', label: `${t('mobile.caps.feedback.filter.accepted')} ${counts.ok}` },
              { id: 'other', label: t('mobile.caps.feedback.filter.other') },
            ].map(opt => (
              <button key={opt.id} className={'pl-pill' + (filter === opt.id ? ' active' : '')} onClick={() => setFilter(opt.id)}>
                {opt.label}
              </button>
            ))}
          </div>

          {/* Refresh */}
          <button className="pl-btn-ghost" style={{ height: 40 }} onClick={loadHistory} disabled={histLoading}>
            <Icon name="refresh" size={14} />{histLoading ? t('common.loading') : t('common.refresh')}
          </button>

          {/* List */}
          {histErr ? (
            <div style={{ padding: '12px 14px', borderRadius: 12, background: 'var(--danger-soft)', border: '1px solid rgba(200,103,93,0.3)', color: 'var(--danger)', fontSize: 13 }}>{histErr}</div>
          ) : history.length === 0 ? (
            <EmptyState icon="feedback" titleKey="mobile.caps.feedback.history.empty_title" descKey="mobile.caps.feedback.history.empty_desc" />
          ) : filtered.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--muted)', fontSize: 13, padding: '24px 0' }}>{t('mobile.caps.feedback.history.filter_empty')}</div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              {filtered.map(it => (
                <div key={it.id} style={{ border: '1px solid var(--line-soft)', borderRadius: 13, background: 'var(--panel)', padding: '13px 14px', display: 'grid', gap: 9 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <strong style={{ fontSize: 13.5, fontFamily: 'var(--font-mono)' }}>#{it.id}</strong>
                    <span className={`pill ${statusColor(it.review_decision)}`}>
                      <span className={`dot ${statusColor(it.review_decision)}`} />
                      {statusLabel(it.review_decision)}
                    </span>
                    {!it.review_decision && (
                      <button onClick={() => handleWithdraw(it.id)} style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--danger)', background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}>
                        {t('mobile.caps.feedback.history.withdraw_btn')}
                      </button>
                    )}
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
                    {fmtTime(it.created_at)}
                    {it.reviewed_at ? ` · ${t('mobile.caps.feedback.history.reviewed_at')} ${fmtTime(it.reviewed_at)}` : ''}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-quiet)', lineHeight: 1.6 }}>
                    {it.free_text_preview || t('mobile.caps.feedback.history.no_text')}
                  </div>
                  {it.admin_reply && (
                    <div style={{ padding: '10px 12px', borderRadius: 9, background: 'var(--accent-soft)', borderLeft: '3px solid var(--accent)', fontSize: 13, lineHeight: 1.65 }}>
                      <strong style={{ fontSize: 12, letterSpacing: '0.04em' }}>{t('mobile.caps.feedback.history.official_reply')}</strong>
                      {it.replied_at && <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 400 }}> · {fmtTime(it.replied_at)}</span>}
                      <div style={{ marginTop: 5, whiteSpace: 'pre-wrap', color: 'var(--text-quiet)' }}>{it.admin_reply}</div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export { FeedbackSection };
