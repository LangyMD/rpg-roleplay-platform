// 子模块模型区(ModuleModelsSection + FeatureToggle)。纯机械搬出,零行为变化。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import AgentModelPicker from '../AgentModelPicker.jsx';
import { useAutoSave } from '../../platform-app.jsx';
import { MODULES as AGENT_MODULES, MODULE_GROUPS, FEATURES as AGENT_FEATURES } from '../../agent-modules.js';
import { SetGroup, SetRow } from './shared.jsx';
import CSSelect from '@cloudscape-design/components/select';
import CSBox from '@cloudscape-design/components/box';
import CSToggle from '@cloudscape-design/components/toggle';

/* ModuleModelsSection — 给每个 LLM / RAG / 生图子模块单独选模型。

   ── 统一规范组件 ──────────────────────────────────────────────────────────
   每行的「选模型」一律用 <AgentModelPicker variant="bare"> —— 全站唯一实现,
   不再自造 CSSelect + 数据加载 + 自定义手填。各模块只声明 prefPrefix / persistShape /
   capabilityFilter / allowInherit,组件内部负责:仅展示已配 key 的 provider 的真实模型、
   按 capability 过滤、自定义手填兜底、双 flat key / dict 单 key 落库、「跟随主 GM」清空偏好。

   落库形态:
     · flat(默认)         : <prefPrefix>.api_id + <prefPrefix>.model_real_name
     · dict(sub_agent /    : persistShape="dict" + dictKey = { api_id, model }
        console)
   主 GM 不可继承(它是被继承者);embedder / image_gen allowInherit=false(必须自己选)。
   embedder 还传 platformVertexAllowed(admin/vip 才显示平台 vertex embedding 兜底)。 */
/* FeatureToggle — 引擎特性开关(每用户、默认开)。写 user_preferences["<key>.enabled"];
   后端 core.feature_flags.feature_enabled 读同一键(未设=跟随环境默认开)。键名前后端单一来源。
   initial 由父组件一次性 profile 读出下发,避免每个开关各拉一次 profile。 */
function FeatureToggle({ featureKey, label, desc, initial }) {
  const { t } = useTranslation();
  const [on, setOn] = useStatePL(initial !== false);
  const save = useAutoSave(label, featureKey);
  useEffectPL(() => { setOn(initial !== false); }, [initial]);
  return (
    <SetRow label={label} description={desc}>
      <CSToggle checked={on} onChange={({ detail }) => { setOn(detail.checked); save("enabled", detail.checked); }}>
        {on ? t('settings.features.on', { defaultValue: '已启用' }) : t('settings.features.off', { defaultValue: '已关闭' })}
      </CSToggle>
    </SetRow>
  );
}

function ModuleModelsSection() {
  const { t } = useTranslation();
  // 结构字段(prefPrefix / persistShape / dictKey / capabilityFilter / inherit / …)走单一来源
  // agent-modules.js(语义统一 #19);label / tip 文案为桌面端专属(比移动端详尽,且后续 i18n),
  // 故保留在本地按 id 取 → 显示零变化。
  const LABELS = {
    gm: t('settings.more.modules.label_gm'), sub_agent: t('settings.more.modules.label_sub_agent'), set_parser: t('settings.more.modules.label_set_parser'),
    console: t('settings.more.modules.label_console'), editor: t('settings.more.modules.label_editor'), extractor: t('settings.more.modules.label_extractor'), recorder: t('settings.more.modules.label_recorder'), card_gen: t('settings.more.modules.label_card_gen'),
    card_import: t('settings.more.modules.label_card_import'), critic: t('settings.more.modules.label_critic'), verifier: t('settings.more.modules.label_verifier'),
    phase_digest: t('settings.more.modules.label_phase_digest'), black_swan: t('settings.more.modules.label_black_swan'), agent: t('settings.more.modules.label_agent'),
    embedder: t('settings.more.modules.label_embedder'), image_gen: t('settings.more.modules.label_image_gen'),
  };
  const TIPS = {
    gm: t('settings.more.modules.tip_gm'),
    sub_agent: t('settings.more.modules.tip_sub_agent'),
    set_parser: t('settings.more.modules.tip_set_parser'),
    console: t('settings.more.modules.tip_console'),
    editor: t('settings.more.modules.tip_editor'),
    extractor: t('settings.more.modules.tip_extractor'),
    recorder: t('settings.more.modules.tip_recorder'),
    card_gen: t('settings.more.modules.tip_card_gen'),
    card_import: t('settings.more.modules.tip_card_import'),
    critic: t('settings.more.modules.tip_critic'),
    verifier: t('settings.more.modules.tip_verifier'),
    phase_digest: t('settings.more.modules.tip_phase_digest'),
    black_swan: t('settings.more.modules.tip_black_swan'),
    agent: t('settings.more.modules.tip_agent'),
    embedder: t('settings.more.modules.tip_embedder'),
    image_gen: t('settings.more.modules.tip_image_gen'),
  };
  const MODULES = AGENT_MODULES.map((m) => ({ ...m, label: LABELS[m.id], tip: TIPS[m.id] }));

  // 引擎特性 / 分组文案全部走 i18n:settings.features.<i18nKey>.* / settings.modules.group_desc.<id>。
  const _subHdr = { fontSize: 11, fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 };

  // task: embedder 兜底状态 — RAG 模型 section banner 文案 + 是否给 admin/vip 平台 vertex 兜底
  const [embedderStatus, setEmbedderStatus] = useStatePL(null);
  useEffectPL(() => {
    fetch('/api/me/embedder/status', { credentials: 'include' })
      .then(r => r.json()).then(es => setEmbedderStatus(es?.ok ? es : null)).catch(() => {});
  }, []);
  // 后端已按 _is_admin gate(admin/vip 才 true);非 vip/admin 不显示平台 vertex embedding。
  const platformVertexAllowed = !!(embedderStatus && embedderStatus.platform_fallback_available);

  // 一次性读取特性偏好(各开关初值),避免每个 FeatureToggle 各拉一次 profile。
  const [featPrefs, setFeatPrefs] = useStatePL({});
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await window.api.account.profile();
        if (!cancelled && profile && profile.preferences) setFeatPrefs(profile.preferences);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  const renderModelRow = (mod) => (
    <div key={mod.id}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>{mod.label}</strong>
        <span className="muted" style={{ fontSize: 11 }}>{mod.tip}</span>
      </div>
      <AgentModelPicker
        prefPrefix={mod.prefPrefix}
        persistShape={mod.persistShape || "flat"}
        dictKey={mod.dictKey || null}
        capabilityFilter={mod.capabilityFilter || null}
        allowInherit={!!mod.inherit}
        defaultModel={mod.defaultModel || null}
        preferProvider={mod.preferProvider || null}
        fallbackPrefix={mod.fallbackPrefix || null}
        platformVertexAllowed={mod.id === "embedder" ? platformVertexAllowed : false}
        variant="bare"
        configHash="apis"
      />
      {mod.id === 'embedder' && embedderStatus && (
        <div style={{ marginTop: 6 }}>
          {embedderStatus.fallback_active ? (
            <div style={{ fontSize: 11, color: "#0972d3" }}>{t('settings.more.modules.embedder_fallback_active')}</div>
          ) : embedderStatus.is_admin && embedderStatus.user_configured ? (
            <div style={{ fontSize: 11, color: "#1a7e3c" }}>{t('settings.more.modules.embedder_admin_configured')}</div>
          ) : embedderStatus.is_admin && !embedderStatus.user_configured ? (
            <div style={{ fontSize: 11, color: "#0972d3" }}>{t('settings.more.modules.embedder_admin_fallback')}</div>
          ) : !embedderStatus.user_configured ? (
            <div style={{ fontSize: 11, color: "#d18a00" }}>{t('settings.more.modules.embedder_user_no_key')}</div>
          ) : null}
        </div>
      )}
      {mod.id === "embedder" && (
        <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted)" }}>{t('settings.more.modules.embedder_note')}</div>
      )}
    </div>
  );

  return (
    <SetGroup
      title={t('settings.modules.title')}
      description={t('settings.modules.description')}
    >
      <CSBox>
        <span className="muted" style={{ fontSize: 12 }}>{t('settings.modules.hint')}</span>
      </CSBox>
      {/* 按功能分组卡片:每组先「功能开关」(每用户、默认开)再「模型分配」,强分隔、去杂乱。 */}
      <div style={{ display: "grid", gap: 16, marginTop: 10 }}>
        {MODULE_GROUPS.map(grp => {
          const items = MODULES.filter(m => (m.group || "misc") === grp.id);
          const feats = (AGENT_FEATURES || []).filter(f => f.group === grp.id);
          if (!items.length && !feats.length) return null;
          const groupLabel = t(`settings.more.modules.group_${grp.id}`, {
            defaultValue: { core: "对话核心（三贤者 + GM 管线）", script: "剧本与角色卡", world: "世界模拟与历史", gen: "检索与生成", misc: "通用兜底" }[grp.id] || grp.id,
          });
          const groupDesc = t(`settings.modules.group_desc.${grp.id}`, { defaultValue: "" });
          return (
            <div key={grp.id} style={{ border: "1px solid var(--pl-line, #e9e9ed)", borderRadius: 12, padding: "16px 18px 18px" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--pl-accent, #0972d3)" }}>{groupLabel}</div>
              {groupDesc && <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{groupDesc}</div>}

              {feats.length > 0 && (
                <div style={{ marginTop: 16, marginBottom: items.length ? 18 : 0 }}>
                  <div style={_subHdr}>{t('settings.modules.features_title', { defaultValue: '功能开关' })}</div>
                  <div style={{ display: "grid", gap: 2 }}>
                    {feats.map(f => (
                      <FeatureToggle
                        key={f.key}
                        featureKey={f.key}
                        label={t(`settings.features.${f.i18nKey}.label`, { defaultValue: f.key })}
                        desc={t(`settings.features.${f.i18nKey}.desc`, { defaultValue: "" })}
                        initial={featPrefs[`${f.key}.enabled`]}
                      />
                    ))}
                  </div>
                </div>
              )}

              {items.length > 0 && (
                <div style={{ marginTop: feats.length ? 0 : 16 }}>
                  <div style={_subHdr}>{t('settings.modules.models_title', { defaultValue: '模型分配' })}</div>
                  <div style={{ display: "grid", gap: 14 }}>
                    {items.map(renderModelRow)}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <CSBox>
        <span className="muted" style={{ fontSize: 11 }}>{t('settings.modules.footer')}</span>
      </CSBox>
    </SetGroup>
  );
}

export {
  ModuleModelsSection,
};
