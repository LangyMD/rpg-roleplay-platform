// 偏好类设置区(Pref / Extractor / BlackSwan / Clarify)。纯机械从 pages/settings.jsx 搬出,零行为变化。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import AgentModelPicker from '../AgentModelPicker.jsx';
import { useAutoSave } from '../../platform-app.jsx';
import { SetGroup, SetRow, SetSelect } from './shared.jsx';
import CSToggle from '@cloudscape-design/components/toggle';
import i18n, { changeLanguage, DEFAULT_LANGUAGE } from '../../i18n/index.js';

function PrefSection() {
  // task 52：从 user_preferences 拉真实初值，改动直接 patch /api/me/preference。
  const { t } = useTranslation();
  const [interfaceLang, setInterfaceLang] = useStatePL(() => i18n.resolvedLanguage || i18n.language || DEFAULT_LANGUAGE);
  // 故事语言:GM / 酒馆叙事与后台微任务的输出语言。后端 core/language.py 读 user_preferences 的
  // 顶层 key `narration_language`(不带 pref. 前缀),缺省 en。
  const [storyLang, setStoryLang] = useStatePL(DEFAULT_LANGUAGE);
  const [serif, setSerif] = useStatePL(true);
  const [auto, setAuto] = useStatePL(true);
  const save = useAutoSave(t('settings.nav.preferences'), "pref");
  const saveTop = useAutoSave(t('settings.nav.preferences'), "");
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.profile();
        if (cancelled) return;
        const p = (r && r.preferences) || {};
        if (p.narration_language === 'zh-CN' || p.narration_language === 'en') setStoryLang(p.narration_language);
        if (p["pref.ui_language"]) setInterfaceLang(p["pref.ui_language"]);
        else if (p.ui_language) setInterfaceLang(p.ui_language);
        if (typeof p["pref.serif"] === "boolean") setSerif(p["pref.serif"]);
        else if (typeof p.serif === "boolean") setSerif(p.serif);
        if (typeof p["pref.autosave"] === "boolean") setAuto(p["pref.autosave"]);
        else if (typeof p.autosave === "boolean") setAuto(p.autosave);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);
  return (
    <SetGroup title={t('settings.preferences.title')}>
      <SetRow label={t('settings.preferences.interface_lang')} description={t('settings.preferences.interface_lang_desc')}>
        <SetSelect value={interfaceLang}
          options={[
            { value: 'zh-CN', label: '简体中文' },
            { value: 'zh-TW', label: '繁體中文' },
            { value: 'en', label: 'English' },
          ]}
          onChange={(v) => { setInterfaceLang(v); save("ui_language", v); changeLanguage(v); }} />
      </SetRow>
      <SetRow label={t('settings.preferences.story_lang')} description={t('settings.preferences.story_lang_desc')}>
        <SetSelect value={storyLang}
          options={[
            { value: 'en', label: 'English' },
            { value: 'zh-CN', label: '简体中文' },
          ]}
          onChange={(v) => { setStoryLang(v); saveTop("narration_language", v); }} />
      </SetRow>
      <SetRow label={t('settings.preferences.serif_font')} description={t('settings.preferences.serif_font_desc')}>
        <CSToggle checked={serif} onChange={({ detail }) => { setSerif(detail.checked); save("serif", detail.checked); }}>
          {serif ? t('settings.preferences.serif_on') : t('settings.preferences.serif_off')}
        </CSToggle>
      </SetRow>
      <SetRow label={t('settings.preferences.autosave')} description={t('settings.preferences.autosave_desc')}>
        <CSToggle checked={auto} onChange={({ detail }) => { setAuto(detail.checked); save("autosave", detail.checked); }}>
          {auto ? t('settings.preferences.autosave_on') : t('settings.preferences.autosave_off')}
        </CSToggle>
      </SetRow>
    </SetGroup>
  );
}

/* ExtractorSection — task 64：暴露后端 task 62/63 的 user_preferences.extractor.*。
   后端读 user_preferences.preferences["extractor.enabled"/"extractor.api_id"/"extractor.model_real_name"]。
   useAutoSave("叙事提取器", "extractor") 让 save("enabled", v) 写到 extractor.enabled，键正好对齐。 */
function ExtractorSection() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useStatePL(false);
  const save = useAutoSave(t('settings.extractor.title'), "extractor");
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await window.api.account.profile();
        if (cancelled) return;
        const p = (profile && profile.preferences) || {};
        if (typeof p["extractor.enabled"] === "boolean") setEnabled(p["extractor.enabled"]);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <SetGroup title={t('settings.extractor.title')}>
      <SetRow label={t('settings.extractor.enable')} description={t('settings.extractor.enable_desc')}>
        <CSToggle checked={enabled} onChange={({ detail }) => { setEnabled(detail.checked); save("enabled", detail.checked); }}>
          {enabled ? t('settings.extractor.enable_on') : t('settings.extractor.enable_off')}
        </CSToggle>
      </SetRow>
      {/* 统一共享组件:与「按模块分配模型」的提取器、scripts 导入流、cards 的 card_import
          同一实现(Provider+Model + 未配 key 警告 + 写 extractor.* prefs)。 */}
      <SetRow label={t('settings.extractor.api')} description={t('settings.extractor.model_desc')}>
        <AgentModelPicker
          prefPrefix="extractor"
          preferProvider="deepseek"
          defaultModel={null}
          variant="bare"
          configHash="settings-models"
        />
      </SetRow>
    </SetGroup>
  );
}

/* BlackSwanSection — 黑天鹅子代理开关：暴露 user_preferences["black_swan.enabled"]。
   后端 _is_black_swan_enabled(api_user) 读此偏好；未设置时退回 env-var(RPG_ENABLE_BLACK_SWAN)。
   useAutoSave("黑天鹅", "black_swan") 让 save("enabled", v) 写到 black_swan.enabled，键对齐。 */
function BlackSwanSection() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useStatePL(false);
  const save = useAutoSave(t('settings.black_swan.title'), "black_swan");
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await window.api.account.profile();
        if (cancelled) return;
        const p = (profile && profile.preferences) || {};
        if (typeof p["black_swan.enabled"] === "boolean") setEnabled(p["black_swan.enabled"]);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);
  return (
    <SetGroup title={t('settings.black_swan.title')}>
      <SetRow label={t('settings.black_swan.enable')} description={t('settings.black_swan.enable_desc')}>
        <CSToggle checked={enabled} onChange={({ detail }) => { setEnabled(detail.checked); save("enabled", detail.checked); }}>
          {enabled ? t('settings.black_swan.enable_on') : t('settings.black_swan.enable_off')}
        </CSToggle>
      </SetRow>
    </SetGroup>
  );
}

/* ClarifySection — task 85：暴露 user_preferences.curator.confidence_threshold。
   后端 _clarify_threshold(api_user) 读 preferences["curator.confidence_threshold"]，默认 0.5，
   clamp 到 [0.0, 1.0]。useAutoSave("Curator 反问", "curator") 让 save("confidence_threshold", v)
   写到 curator.confidence_threshold，键正好对齐。 */
function ClarifySection() {
  const { t } = useTranslation();
  const DEFAULT = 0.5;
  const [threshold, setThreshold] = useStatePL(DEFAULT);
  const save = useAutoSave("Curator", "curator");
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const profile = await window.api.account.profile();
        if (cancelled) return;
        const p = (profile && profile.preferences) || {};
        const raw = p["curator.confidence_threshold"];
        if (raw !== undefined && raw !== null) {
          const v = Number(raw);
          if (Number.isFinite(v)) {
            setThreshold(Math.max(0, Math.min(1, v)));
          }
        }
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  const commit = (v) => {
    let n = Number(v);
    if (!Number.isFinite(n)) n = DEFAULT;
    n = Math.max(0, Math.min(1, n));
    // 量化到 0.05 步进，避免 slider 浮点尾巴写库
    n = Math.round(n * 20) / 20;
    setThreshold(n);
    save("confidence_threshold", n);
  };

  return (
    <SetGroup title={t('settings.clarify.title')}>
      <SetRow label={t('settings.clarify.threshold')} description={t('settings.clarify.threshold_desc')}>
        <div style={{flexDirection: "row", alignItems: "center", display: "flex", gap: 8}}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(e) => { setThreshold(Number(e.target.value)); }}
            onMouseUp={(e) => commit(e.target.value)}
            onTouchEnd={(e) => commit(e.target.value)}
            onKeyUp={(e) => commit(e.target.value)}
            style={{flex: 1, minWidth: 120}}
          />
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(e) => { setThreshold(Number(e.target.value)); }}
            onBlur={(e) => commit(e.target.value)}
            style={{width: 72}}
          />
          <span className="muted" style={{fontSize: 12, minWidth: 90}}>
            {threshold.toFixed(2)}
          </span>
        </div>
      </SetRow>
    </SetGroup>
  );
}

export {
  PrefSection,
  ExtractorSection,
  BlackSwanSection,
  ClarifySection,
};
