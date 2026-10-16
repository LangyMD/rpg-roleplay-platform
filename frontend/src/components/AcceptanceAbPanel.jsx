// AcceptanceAbPanel — acceptance A/B 改写候选对比。
// 后端在 GM 首稿有验收点未覆盖、且节流放行时,额外生成一份「改写候选」并 yield `acceptance_alt` 事件。
// 首稿(玩家流式读到的)永远是权威版、不被静默替换;这里把两版并排给玩家选择,选择结果回传后端用于
// (a) 采集数据迭代 acceptance 算法,(b) 选改写才把该轮消息换成服务端存的改写稿。
import React from 'react';
import { useTranslation } from 'react-i18next';

const PANEL = {
  margin: '0 0 8px',
  border: '1px solid var(--accent-edge, var(--border))',
  borderRadius: 10,
  background: 'var(--panel)',
  boxShadow: '0 6px 20px rgba(0,0,0,0.28)',
  overflow: 'hidden',
};
const HEAD = {
  display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap',
  padding: '9px 12px',
  borderBottom: '1px solid var(--border)',
  background: 'var(--accent-soft, rgba(255,255,255,0.03))',
};
const COL_WRAP = {
  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1,
  background: 'var(--border)',
};
const COL = { display: 'flex', flexDirection: 'column', background: 'var(--panel)', minWidth: 0 };
const COL_HEAD = {
  padding: '6px 12px', fontSize: 11, letterSpacing: '.04em',
  color: 'var(--text-quiet, var(--muted))', textTransform: 'none',
  borderBottom: '1px solid var(--border)',
};
const PROSE = {
  padding: '10px 12px', maxHeight: 260, overflowY: 'auto',
  fontSize: 13.5, lineHeight: 1.72, color: 'var(--text)',
  whiteSpace: 'pre-wrap', wordBreak: 'break-word',
};
const ACT = { padding: '8px 12px', borderTop: '1px solid var(--border)' };
const BTN = {
  width: '100%', padding: '7px 10px', borderRadius: 6, cursor: 'pointer',
  fontSize: 12.5, border: '1px solid var(--border)',
  background: 'transparent', color: 'var(--text)',
};
const BTN_PRIMARY = {
  ...BTN,
  border: '1px solid var(--accent)',
  background: 'var(--accent)', color: 'var(--accent-contrast, #0b0b0b)',
  fontWeight: 600,
};

export function AcceptanceAbPanel({ alt, original, onChoose, onDismiss, busy }) {
  const { t } = useTranslation();
  if (!alt) return null;
  const unmet = Array.isArray(alt.unmet) ? alt.unmet : [];
  return (
    <div className="gc-ab-panel" style={PANEL} role="region" aria-label={t('acceptance_ab.aria')}>
      <div style={HEAD}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
          {t('acceptance_ab.title')}
        </span>
        <span style={{ flex: 1, fontSize: 12, color: 'var(--muted)' }}>
          {t('acceptance_ab.subtitle', { count: unmet.length })}
        </span>
        <button
          type="button"
          onClick={onDismiss}
          disabled={busy}
          style={{ ...BTN, width: 'auto', padding: '4px 10px', fontSize: 12, color: 'var(--muted)' }}
          title={t('acceptance_ab.keep_current_tip')}
        >{t('acceptance_ab.keep_current')}</button>
      </div>

      <div style={COL_WRAP}>
        <div style={COL}>
          <div style={COL_HEAD}>{t('acceptance_ab.current_version')}</div>
          <div style={PROSE}>{original || t('acceptance_ab.empty')}</div>
          <div style={ACT}>
            <button type="button" style={BTN} disabled={busy} onClick={() => onChoose('original')}>
              {t('acceptance_ab.keep_this')}
            </button>
          </div>
        </div>
        <div style={COL}>
          <div style={{ ...COL_HEAD, color: 'var(--accent)' }}>{t('acceptance_ab.rewrite_version')}</div>
          <div style={PROSE}>{alt.rewrite || t('acceptance_ab.empty')}</div>
          <div style={ACT}>
            <button type="button" style={BTN_PRIMARY} disabled={busy} onClick={() => onChoose('rewrite')}>
              {t('acceptance_ab.use_this')}
            </button>
          </div>
        </div>
      </div>

      {unmet.length > 0 && (
        <details style={{ padding: '6px 12px 9px', borderTop: '1px solid var(--border)' }}>
          <summary style={{ fontSize: 12, color: 'var(--muted)', cursor: 'pointer' }}>
            {t('acceptance_ab.why')}
          </summary>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12, color: 'var(--text-quiet, var(--muted))', lineHeight: 1.7 }}>
            {unmet.map((u, i) => (<li key={i}>{String(u)}</li>))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default AcceptanceAbPanel;
