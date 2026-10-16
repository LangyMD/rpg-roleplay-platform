import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import AgentModelPicker from '../../components/AgentModelPicker.jsx';
import { MODULES as AGENT_MODULES, MODULE_GROUPS, FEATURES as AGENT_FEATURES } from '../../agent-modules.js';
import { Toggle, usePrefSave } from './shared.jsx';

/* ────────────────────────────────────────────────────────────────── */
/* SECTION: 模块分配 (modules)                                         */
/* ────────────────────────────────────────────────────────────────── */
// 模块清单与桌面端同构。每行用统一规范组件 AgentModelPicker(不再自造 <select>)。
//   flat 模块走 prefPrefix(<prefPrefix>.api_id / .model_real_name);
//   dict 模块(sub_agent / console)走 persistShape="dict" + dictKey={api_id, model};
//   embedder / image_gen allowInherit=false(必须自己选);其它可「跟随主 GM」。
// 结构字段走单一来源 AGENT_MODULES;移动端 label/tip 文案精简(与桌面端不同),保留本地按 id 取。
const MODULES = AGENT_MODULES.map((m) => ({ ...m }));

/* FeatureToggleM — 移动端引擎特性开关(每用户、默认开)。写 user_preferences["<key>.enabled"],
   与桌面端、后端 core.feature_flags 同键。initial 由父组件一次性 profile 下发。 */
function FeatureToggleM({ featureKey, i18nKey, initial }) {
  const { t } = useTranslation();
  const [on, setOn] = useState(initial !== false);
  const save = usePrefSave(featureKey);
  useEffect(() => { setOn(initial !== false); }, [initial]);
  return (
    <div className="pl-card" style={{ marginBottom: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <div style={{ minWidth: 0 }}>
        <strong style={{ fontSize: 14 }}>{t(`settings.features.${i18nKey}.label`, { defaultValue: featureKey })}</strong>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2, lineHeight: 1.5 }}>{t(`settings.features.${i18nKey}.desc`, { defaultValue: '' })}</div>
      </div>
      <Toggle on={on} onChange={(v) => { setOn(v); save('enabled', v); }} />
    </div>
  );
}

function ModuleModelsSection({ nav }) {
  const { t } = useTranslation();
  // embedder 平台兜底状态:仅 admin/vip 显示平台 vertex embedding(后端已 _is_admin gate)。
  const [embedStatus, setEmbedStatus] = useState(null);
  useEffect(() => {
    fetch('/api/me/embedder/status', { credentials:'include' })
      .then(r => r.json()).then(es => setEmbedStatus(es?.ok ? es : null)).catch(() => {});
  }, []);
  const platformVertexAllowed = !!(embedStatus && embedStatus.platform_fallback_available);

  // 一次性读取特性偏好(各开关初值)。
  const [featPrefs, setFeatPrefs] = useState({});
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try { const r = await window.api.account.profile(); if (!cancelled && r && r.preferences) setFeatPrefs(r.preferences); } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <div className="pl-sec-note" style={{ marginBottom: 14 }}>
        {t('mobile.settings.modules.intro')}
      </div>
      {MODULE_GROUPS.map(grp => {
        const items = MODULES.filter(m => (m.group || 'misc') === grp.id);
        const feats = (AGENT_FEATURES || []).filter(f => f.group === grp.id);
        if (!items.length && !feats.length) return null;
        const groupLabel = t(`mobile.settings.modules.group.${grp.id}`, {
          defaultValue: { core: '对话核心（三贤者）', script: '剧本与角色卡', world: '世界模拟', gen: '检索与生成', misc: '通用兜底' }[grp.id] || grp.id,
        });
        return (
        <React.Fragment key={grp.id}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent, #0972d3)', margin: '14px 0 6px' }}>{groupLabel}</div>
          {feats.map(f => (
            <FeatureToggleM key={f.key} featureKey={f.key} i18nKey={f.i18nKey} initial={featPrefs[`${f.key}.enabled`]} />
          ))}
          {items.map(mod => (
        <div key={mod.id} className="pl-card" style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 10 }}>
            <strong style={{ fontSize: 14 }}>{t(`mobile.settings.modules.label.${mod.id}`)}</strong>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{t(`mobile.settings.modules.tip.${mod.id}`)}</div>
          </div>
          <AgentModelPicker
            prefPrefix={mod.prefPrefix}
            persistShape={mod.persistShape || 'flat'}
            dictKey={mod.dictKey || null}
            capabilityFilter={mod.capabilityFilter || null}
            allowInherit={!!mod.inherit}
            defaultModel={mod.defaultModel || null}
            preferProvider={mod.preferProvider || null}
            fallbackPrefix={mod.fallbackPrefix || null}
            platformVertexAllowed={mod.id === 'embedder' ? platformVertexAllowed : false}
            variant="bare"
            configHash="apis"
          />
          {mod.id==='embedder' && embedStatus && !embedStatus.user_configured && !platformVertexAllowed && (
            <div style={{ fontSize: 11, color: 'var(--warn)', marginTop: 8, lineHeight: 1.5 }}>
              {t('mobile.settings.modules.embedder_no_key')}
            </div>
          )}
        </div>
          ))}
        </React.Fragment>
        );
      })}
      <div style={{ fontSize: 11.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 8 }}>
        {t('mobile.settings.modules.embedder_switch_note')}
      </div>
    </>
  );
}

export { ModuleModelsSection };
