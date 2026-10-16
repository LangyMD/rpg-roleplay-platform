/* Admin — AdminFeedbackPage — 反馈审查队列。从 pages/admin.jsx 纯机械拆出,JSX / props / fetch 路径零变化。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSTable from '@cloudscape-design/components/table';
import CSButton from '@cloudscape-design/components/button';
import CSBox from '@cloudscape-design/components/box';
import CSBadge from '@cloudscape-design/components/badge';
import CSAlert from '@cloudscape-design/components/alert';
import CSSelect from '@cloudscape-design/components/select';
import CSModal from '@cloudscape-design/components/modal';
import CSFormField from '@cloudscape-design/components/form-field';
import CSTextarea from '@cloudscape-design/components/textarea';
import { fmtTime } from './shared.jsx';

/* ─────────────────────────────────────────────────────────────────
   AdminFeedbackPage — 反馈审查队列 (FB-03)
   ───────────────────────────────────────────────────────────────── */
export function AdminFeedbackPage() {
  const { t } = useTranslation();
  const [items, setItems]           = React.useState([]);
  const [loading, setLoading]       = React.useState(true);
  const [err, setErr]               = React.useState(null);
  const [statusFilter, setStatusFilter] = React.useState({ value: 'unreviewed', label: t('admin_page.feedback.status_unreviewed') });
  const [detailModal, setDetailModal]   = React.useState(null); // feedback item
  const [actionBusy, setActionBusy]     = React.useState(false);
  const [actionErr, setActionErr]       = React.useState(null);
  const [terminateReason, setTerminateReason] = React.useState('');
  const [replyText, setReplyText] = React.useState('');

  const statusOptions = [
    { value: 'unreviewed', label: t('admin_page.feedback.status_unreviewed') },
    { value: 'reviewed',   label: t('admin_page.feedback.status_reviewed') },
    { value: 'all',        label: t('admin_page.feedback.status_all') },
  ];

  const load = React.useCallback(async (filter) => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/admin/feedback?status=${encodeURIComponent(filter)}&limit=50`,
        { credentials: 'include' },
      );
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      setItems(data.items || []);
    } catch (e) {
      setErr(e?.message || t('admin_page.common.load_fail'));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(statusFilter.value); }, [statusFilter.value]);

  async function doDecision(feedbackId, decision, notes) {
    setActionBusy(true);
    setActionErr(null);
    try {
      const res = await fetch(`/api/admin/feedback/${feedbackId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ decision, notes: notes || '' }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      window.toast?.(t('admin_page.feedback.op_ok'), { kind: 'ok' });
      setDetailModal(null);
      setTerminateReason('');
      load(statusFilter.value);
    } catch (e) {
      setActionErr(e?.message || t('admin_page.feedback.op_fail'));
    } finally {
      setActionBusy(false);
    }
  }

  async function doReply(feedbackId, reply) {
    setActionBusy(true);
    setActionErr(null);
    try {
      const res = await fetch(`/api/admin/feedback/${feedbackId}/reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ reply }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      window.toast?.(reply ? t('admin_page.more.reply_sent') : t('admin_page.more.reply_withdrawn'), { kind: 'ok' });
      setDetailModal((m) => (m ? { ...m, admin_reply: reply || null } : m));
      load(statusFilter.value);
    } catch (e) {
      setActionErr(e?.message || t('admin_page.more.reply_fail'));
    } finally {
      setActionBusy(false);
    }
  }

  const decisionBadge = (d) => {
    if (!d) return <CSBadge color="grey">{t('admin_page.feedback.badge_pending')}</CSBadge>;
    if (d === 'ok') return <CSBadge color="green">OK</CSBadge>;
    if (d === 'nsfw_terminate') return <CSBadge color="red">{t('admin_page.feedback.badge_terminate')}</CSBadge>;
    if (d === 'spam') return <CSBadge color="severity-medium">{t('admin_page.feedback.badge_spam')}</CSBadge>;
    return <CSBadge color="grey">{d}</CSBadge>;
  };

  return (
    <CSSpaceBetween size="l">
      {err && <CSAlert type="error" header={t('admin_page.common.load_fail')}>{err}</CSAlert>}

      <CSContainer
        header={
          <CSHeader
            variant="h2"
            description={t('admin_page.feedback.description')}
            actions={
              <CSSpaceBetween direction="horizontal" size="xs">
                <CSSelect
                  selectedOption={statusFilter}
                  options={statusOptions}
                  onChange={({ detail }) => setStatusFilter(detail.selectedOption)}
                />
                <CSButton iconName="refresh" onClick={() => load(statusFilter.value)} loading={loading}>
                  {t('admin_page.common.refresh')}
                </CSButton>
              </CSSpaceBetween>
            }
          >
            {t('admin_page.feedback.title')}
          </CSHeader>
        }
      >
        <CSTable
          loading={loading}
          loadingText={t('admin_page.common.loading')}
          trackBy="id"
          items={items}
          empty={
            <CSBox textAlign="center" color="inherit">
              <CSBox padding={{ bottom: 's' }} variant="p" color="inherit">{t('admin_page.feedback.empty')}</CSBox>
            </CSBox>
          }
          columnDefinitions={[
            { id: 'id',      header: t('admin_page.feedback.col_id'),      cell: (f) => f.id },
            { id: 'user',    header: t('admin_page.feedback.col_user'),     cell: (f) => f.username || '—' },
            { id: 'ts',      header: t('admin_page.feedback.col_ts'),       cell: (f) => fmtTime(f.created_at) },
            { id: 'status',  header: t('admin_page.feedback.col_status'),   cell: (f) => decisionBadge(f.review_decision) },
            {
              id: 'preview', header: t('admin_page.feedback.col_preview'),
              cell: (f) => (
                <span style={{ maxWidth: 300, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {(f.free_text || '').slice(0, 80) || t('admin_page.feedback.detail_empty')}
                </span>
              ),
            },
            {
              id: 'actions', header: t('admin_page.feedback.col_actions'),
              cell: (f) => (
                <CSButton variant="inline-link" onClick={() => { setDetailModal(f); setActionErr(null); setTerminateReason(''); setReplyText(f.admin_reply || ''); }}>
                  {t('admin_page.feedback.btn_view')}
                </CSButton>
              ),
            },
          ]}
        />
      </CSContainer>

      {/* detail + action modal */}
      {detailModal && (
        <CSModal
          visible
          size="large"
          onDismiss={() => !actionBusy && setDetailModal(null)}
          header={t('admin_page.feedback.detail_modal_title', { id: detailModal.id, user: detailModal.username })}
          footer={
            !detailModal.review_decision ? (
              <CSBox float="right">
                <CSSpaceBetween direction="horizontal" size="xs">
                  <CSButton variant="link" disabled={actionBusy} onClick={() => setDetailModal(null)}>{t('admin_page.feedback.btn_cancel')}</CSButton>
                  <CSButton variant="normal" loading={actionBusy} onClick={() => doDecision(detailModal.id, 'spam')}>
                    {t('admin_page.feedback.btn_spam')}
                  </CSButton>
                  <CSButton variant="primary" loading={actionBusy} onClick={() => doDecision(detailModal.id, 'ok')}>
                    {t('admin_page.feedback.btn_ok')}
                  </CSButton>
                  <CSButton
                    variant="primary"
                    iconName="status-warning"
                    loading={actionBusy}
                    disabled={!terminateReason.trim()}
                    onClick={() => doDecision(detailModal.id, 'nsfw_terminate', terminateReason)}
                  >
                    {t('admin_page.feedback.btn_terminate_nsfw')}
                  </CSButton>
                </CSSpaceBetween>
              </CSBox>
            ) : (
              <CSBox float="right">
                <CSButton variant="link" onClick={() => setDetailModal(null)}>{t('admin_page.feedback.btn_close')}</CSButton>
              </CSBox>
            )
          }
        >
          <CSSpaceBetween size="m">
            {actionErr && <CSAlert type="error">{actionErr}</CSAlert>}

            <CSBox>
              <strong>{t('admin_page.feedback.detail_submit_time')}</strong>{fmtTime(detailModal.created_at)}
              {t('common.space_sep')}
              <strong>{t('admin_page.feedback.detail_status_label')}</strong>{decisionBadge(detailModal.review_decision)}
              {detailModal.reviewed_at && (
                <span>{t('common.space_sep')}<strong>{t('admin_page.feedback.detail_review_time')}</strong>{fmtTime(detailModal.reviewed_at)}</span>
              )}
            </CSBox>

            <CSBox>
              <strong>{t('admin_page.feedback.detail_free_text')}</strong>
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--color-background-container-content)', padding: 8, borderRadius: 4 }}>
                {detailModal.free_text || t('admin_page.feedback.detail_empty')}
              </pre>
            </CSBox>

            {/* 反馈回复: 写一条对用户可见的回复(展示在 ta 的「我的反馈历史」),与审核决定互不影响 */}
            <CSBox>
              <strong>{t('admin_page.more.reply_user_label')}</strong> <span style={{ color: 'var(--color-text-body-secondary)' }}>{t('admin_page.more.reply_user_hint')}</span>
              <textarea
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                rows={3}
                placeholder={t('admin_page.more.reply_placeholder')}
                style={{ width: '100%', marginTop: 4, padding: 8, borderRadius: 4, fontSize: 13, boxSizing: 'border-box', fontFamily: 'inherit', resize: 'vertical', border: '1px solid var(--color-border-input-default, #888)', background: 'var(--color-background-container-content)', color: 'inherit' }}
              />
              <CSBox padding={{ top: 'xs' }}>
                <CSButton variant="primary" loading={actionBusy} onClick={() => doReply(detailModal.id, replyText.trim())}>
                  {detailModal.admin_reply ? t('admin_page.more.reply_update') : t('admin_page.more.reply_send')}
                </CSButton>
              </CSBox>
            </CSBox>

            {Array.isArray(detailModal.excerpts) && detailModal.excerpts.length > 0 && (() => {
              // 三种 entry:
              //  - __runtime__: 客户端运行环境快照(bug 排查切片)— 新结构,显式渲染
              //  - __moderation__: NSFW 审核结果 — 后端自动追加
              //  - 普通对话节选 {session_id, range, plaintext}
              const runtimeEntry = detailModal.excerpts.find(e => e && e.__runtime__);
              const modEntry = detailModal.excerpts.find(e => e && e.__moderation__);
              const dialogEntries = detailModal.excerpts.filter(e => e && !e.__runtime__ && !e.__moderation__);
              return (
                <>
                  {runtimeEntry && (() => {
                    const r = runtimeEntry.__runtime__ || {};
                    return (
                      <CSBox>
                        <strong>{t('admin_page.more.runtime_slice_label')}</strong>
                        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 4, background: 'var(--color-background-container-content)', padding: 8, borderRadius: 4, fontSize: 12 }}>
{`URL/Hash:  ${r.url || ''}${r.hash || ''}
App ver:   ${r.app_version || '—'}
Viewport:  ${r.viewport || '—'} · ${r.locale || ''} · ${r.tz || ''}
User:      uid=${r.user?.uid || '—'} role=${r.user?.role || '—'} authed=${String(r.user?.authed)}
Active:    script=${r.active?.script_id ?? '—'} save=${r.active?.save_id ?? '—'} turn=${r.active?.turn ?? '—'}

Errors (${(r.errors || []).length}):
${(r.errors || []).map((e, i) => `  ${i + 1}. [${e.kind}] ${e.msg}${e.stack ? '\n     stack: ' + e.stack.slice(0, 200) : ''}`).join('\n') || '  (none)'}

API failures (${(r.api_failures || []).length}):
${(r.api_failures || []).map((e, i) => `  ${i + 1}. ${e.status} ${e.code} ${e.msg}${e.url ? ' @ ' + e.url : ''}`).join('\n') || '  (none)'}

Recent dialog (${(r.recent_dialog || []).length}):
${(r.recent_dialog || []).map((m, i) => `  ${i + 1}. [${m.role}@turn ${m.turn ?? '?'}] ${m.text}`).join('\n') || '  (not included)'}`}
                        </pre>
                      </CSBox>
                    );
                  })()}
                  {modEntry && (
                    <CSBox>
                      <strong>{t('admin_page.more.nsfw_result_label')}</strong>
                      <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 4, background: 'var(--color-background-container-content)', padding: 8, borderRadius: 4, fontSize: 12 }}>
{JSON.stringify(modEntry.__moderation__, null, 2)}
                      </pre>
                    </CSBox>
                  )}
                  {dialogEntries.length > 0 && (
                    <CSBox>
                      <strong>{t('admin_page.feedback.detail_excerpts', { count: dialogEntries.length })}</strong>
                      {dialogEntries.map((ex, i) => (
                        <CSBox key={i} padding={{ top: 'xs' }}>
                          <CSBadge color="grey">session: {ex.session_id}</CSBadge>
                          {' '}range: {ex.range}
                          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: 4, background: 'var(--color-background-container-content)', padding: 8, borderRadius: 4 }}>
                            {ex.plaintext}
                          </pre>
                        </CSBox>
                      ))}
                    </CSBox>
                  )}
                </>
              );
            })()}

            {!detailModal.review_decision && (
              <CSFormField
                label={t('admin_page.feedback.terminate_reason_label')}
                description={t('admin_page.feedback.terminate_reason_desc')}
              >
                <CSTextarea
                  value={terminateReason}
                  onChange={({ detail }) => setTerminateReason(detail.value)}
                  placeholder={t('admin_page.feedback.terminate_reason_placeholder')}
                  rows={3}
                  disabled={actionBusy}
                />
              </CSFormField>
            )}
          </CSSpaceBetween>
        </CSModal>
      )}
    </CSSpaceBetween>
  );
}
