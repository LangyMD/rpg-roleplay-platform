import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { SetGroup, MSlider, Toggle, usePrefSave } from './shared.jsx';
import i18n, { changeLanguage, DEFAULT_LANGUAGE } from '../../i18n/index.js';

/* ────────────────────────────────────────────────────────────────── */
/* SECTION: 偏好 (preferences)                                        */
/* ────────────────────────────────────────────────────────────────── */
function PrefSection({ nav }) {
  const { t } = useTranslation();
  const save = usePrefSave('pref');
  const saveTop = usePrefSave('');
  const [lang, setLang] = useState(() => i18n.resolvedLanguage || i18n.language || DEFAULT_LANGUAGE);
  // 故事语言(narration_language,顶层 key,后端 core/language.py 读;缺省 en)—— 与桌面 PrefSection 孪生
  const [storyLang, setStoryLang] = useState(DEFAULT_LANGUAGE);
  const [serif, setSerif] = useState(true);
  const [auto, setAuto] = useState(true);
  const [blackSwan, setBlackSwan] = useState(false);
  const [threshold, setThreshold] = useState(0.5);
  const saveCurator = usePrefSave('curator');
  const saveBS = usePrefSave('black_swan');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.profile();
        if (cancelled) return;
        const p = (r && r.preferences) || {};
        if (p['pref.ui_language']) setLang(p['pref.ui_language']);
        if (p.narration_language === 'zh-CN' || p.narration_language === 'en') setStoryLang(p.narration_language);
        if (typeof p['pref.serif'] === 'boolean') setSerif(p['pref.serif']);
        if (typeof p['pref.autosave'] === 'boolean') setAuto(p['pref.autosave']);
        if (typeof p['black_swan.enabled'] === 'boolean') setBlackSwan(p['black_swan.enabled']);
        const raw = p['curator.confidence_threshold'];
        if (raw !== undefined && raw !== null) {
          const v = Number(raw);
          if (Number.isFinite(v)) setThreshold(Math.max(0, Math.min(1, v)));
        }
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  const commitThreshold = (v) => {
    const n = Math.max(0, Math.min(1, Math.round(Number(v) * 20) / 20));
    setThreshold(n);
    saveCurator('confidence_threshold', n);
  };

  return (
    <>
      {/* 界面偏好 */}
      <SetGroup title={t('mobile.settings.pref.ui_prefs')}>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('mobile.settings.pref.ui_language')}</strong>
            <span>{t('mobile.settings.pref.ui_language_desc')}</span>
          </div>
          <div className="pl-seg2" style={{ marginLeft: 'auto', flexShrink: 0, width: 170 }}>
            {[['en','EN'],['zh-CN','简体'],['zh-TW','繁體']].map(([id, l]) => (
              <button key={id} className={lang===id?'active accent':''} onClick={() => {
                setLang(id); save('ui_language', id);
                Promise.resolve(changeLanguage(id)).catch(() => {});
              }}>{l}</button>
            ))}
          </div>
        </div>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('settings.preferences.story_lang')}</strong>
            <span>{t('settings.preferences.story_lang_desc')}</span>
          </div>
          <div className="pl-seg2" style={{ marginLeft: 'auto', flexShrink: 0, width: 130 }}>
            {[['en','EN'],['zh-CN','中文']].map(([id, l]) => (
              <button key={id} className={storyLang===id?'active accent':''} onClick={() => {
                setStoryLang(id); saveTop('narration_language', id);
              }}>{l}</button>
            ))}
          </div>
        </div>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('mobile.settings.pref.serif_font')}</strong>
            <span>{t('mobile.settings.pref.serif_font_desc')}</span>
          </div>
          <Toggle on={serif} onChange={(v) => { setSerif(v); save('serif', v); }} />
        </div>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('mobile.settings.pref.autosave')}</strong>
            <span>{t('mobile.settings.pref.autosave_desc')}</span>
          </div>
          <Toggle on={auto} onChange={(v) => { setAuto(v); save('autosave', v); }} />
        </div>
      </SetGroup>

      {/* GM 叙事风格 */}
      <div className="pl-sec" style={{ marginTop: 18 }}>
        <div className="pl-sec-head"><h2>{t('mobile.settings.pref.gm_style')}</h2></div>
        <button className="pl-row" onClick={() => nav.toast(t('mobile.settings.pref.gm_style_desktop_only'), 'warn', 'sparkle')}>
          <span className="pl-row-ic accent"><Icon name="sparkle" size={18} /></span>
          <span className="pl-row-tx"><strong>{t('mobile.settings.pref.gm_style_custom')}</strong><span>{t('mobile.settings.pref.gm_style_custom_desc')}</span></span>
          <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
        </button>
      </div>

      {/* 黑天鹅事件 */}
      <SetGroup title={t('mobile.settings.pref.black_swan_agent')}>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('mobile.settings.pref.black_swan_enable')}</strong>
            <span>{t('mobile.settings.pref.black_swan_enable_desc')}</span>
          </div>
          <Toggle on={blackSwan} onChange={(v) => { setBlackSwan(v); saveBS('enabled', v); }} />
        </div>
      </SetGroup>

      {/* 叙事提取器 */}
      <SetGroup title={t('mobile.settings.pref.extractor')}>
        <div className="pl-setrow">
          <div className="pl-setrow-tx">
            <strong>{t('mobile.settings.pref.extractor_model')}</strong>
            <span>{t('mobile.settings.pref.extractor_model_desc')}</span>
          </div>
          <button
            style={{ fontSize: 11.5, color: 'var(--accent)', background: 'none', border: 'none' }}
            onClick={() => nav.go('settings-modules')}
          >
            {t('mobile.settings.pref.extractor_configure')} <Icon name="chevron_right" size={13} />
          </button>
        </div>
      </SetGroup>

      {/* Curator 反问阈值 */}
      <div className="pl-sec" style={{ marginTop: 18 }}>
        <div className="pl-sec-head"><h2>{t('mobile.settings.pref.curator_threshold')}</h2></div>
        <div className="pl-card" style={{ border: '1px solid var(--line-soft)', borderRadius: 14, background: 'var(--panel)', padding: 14 }}>
          <MSlider
            label={t('mobile.settings.pref.confidence_threshold')}
            desc={t('mobile.settings.pref.confidence_threshold_desc')}
            value={threshold}
            min={0} max={1} step={0.05}
            onChange={(v) => setThreshold(v)}
          />
          <div style={{ textAlign: 'right', marginTop: 4 }}>
            <button
              className="pl-btn-ghost"
              style={{ height: 36, fontSize: 13, width: 'auto', paddingInline: 16 }}
              onTouchEnd={() => commitThreshold(threshold)}
              onClick={() => commitThreshold(threshold)}
            >
              <Icon name="save" size={14} /> {t('common.save')}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

export { PrefSection };
