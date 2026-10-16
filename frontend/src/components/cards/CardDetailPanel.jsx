/* 角色卡详情面板(信息 / 设定 / 编辑 / 人设图 Tabs)+ 人设图画廊 / 缩略条 —— 从 pages/cards.jsx 拆出,逐字节不变。 */

import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL, useCallback as useCallbackPL } from 'react';
import { useTranslation } from 'react-i18next';
import AvatarImg from '../AvatarImg.jsx';
import CharacterCardHero from '../CharacterCardHero.jsx';
import ImageLightbox from '../ImageLightbox.jsx';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSButton from '@cloudscape-design/components/button';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSBox from '@cloudscape-design/components/box';
import CSTabs from '@cloudscape-design/components/tabs';
import CSKeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import CSExpandableSection from '@cloudscape-design/components/expandable-section';
import CSToggle from '@cloudscape-design/components/toggle';
import { cardFormInit, cardFormPayload, _oneLine, clampLines } from './helpers.js';
import { CardSheet, CardEditFields } from './CardFields.jsx';
import { uiLocale } from '../../i18n/index.js';

/* 人设图历史画廊 — 仅 persona/pc 卡显示 */
function PersonaImageGallery({ cardId, onAvatarRefresh }) {
  const { t } = useTranslation();
  const [images, setImages] = useStatePL(null);   // null=未加载, []=空
  const [loading, setLoading] = useStatePL(false);
  const [setting, setSetting] = useStatePL(null); // 正在 set-current 的 image_id

  const load = useCallbackPL(async () => {
    setLoading(true);
    try {
      const r = await window.api.cards.personaImages(cardId);
      setImages(Array.isArray(r) ? r : (r?.images || r?.items || []));
    } catch (e) {
      window.__apiToast?.(t('cards.page.persona.gallery_load_fail'), { kind: 'danger', detail: e?.message });
      setImages([]);
    } finally { setLoading(false); }
  }, [cardId, t]);

  // 挂载时自动加载
  useEffectPL(() => { load(); }, [load]);
  // 生图完成(SSE rpg-image-updated,kind=persona)→ 自动刷新缩略图,无需手动刷新
  useEffectPL(() => {
    const h = (ev) => { const d = (ev && ev.detail) || {}; if (d.op === 'ready' && (d.payload?.kind || '') === 'persona') load(); };
    window.addEventListener('rpg-image-updated', h);
    return () => window.removeEventListener('rpg-image-updated', h);
  }, [load]);

  const doSetCurrent = async (img) => {
    if (img.is_current || setting) return;
    setSetting(img.id);
    try {
      await window.api.cards.personaSetCurrent(cardId, img.id);
      window.__apiToast?.(t('cards.page.persona.set_current_ok'), { kind: 'ok', duration: 2000 });
      // 刷新列表
      await load();
      // 通知父组件更新头像显示
      if (onAvatarRefresh) onAvatarRefresh(img.image_url);
    } catch (e) {
      window.__apiToast?.(t('cards.page.persona.set_current_fail'), { kind: 'danger', detail: e?.message });
    } finally { setSetting(null); }
  };

  const fmtDate = (s) => {
    if (!s) return '—';
    try {
      const d = new Date(s);
      return d.toLocaleDateString(uiLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (_) { return s; }
  };
  const sourceLabel = {
    auto_sync: t('cards.page.persona.source_auto'),
    manual: t('cards.page.persona.source_manual'),
    import: t('cards.page.persona.source_import'),
  };

  if (loading && images === null) {
    return <CSBox color="text-body-secondary" padding="s">{t('cards.page.persona.gallery_loading')}</CSBox>;
  }
  if (!images || images.length === 0) {
    return (
      <CSBox color="text-body-secondary" padding="s">
        {t('cards.page.persona.gallery_empty')}
      </CSBox>
    );
  }

  return (
    <CSSpaceBetween size="m">
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <CSButton iconName="refresh" variant="inline-link" loading={loading} onClick={load}>{t('common.refresh')}</CSButton>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {images.map((img) => {
          const isCurrent = !!img.is_current;
          const isSettingThis = setting === img.id;
          return (
            <div
              key={img.id}
              onClick={() => doSetCurrent(img)}
              style={{
                width: 110,
                cursor: isCurrent ? 'default' : 'pointer',
                borderRadius: 8,
                border: isCurrent
                  ? '2px solid var(--accent, #c96442)'
                  : '2px solid var(--line, #36322d)',
                overflow: 'hidden',
                background: 'var(--panel, #211f1d)',
                opacity: isSettingThis ? 0.6 : 1,
                transition: 'border-color .15s, opacity .15s',
                flexShrink: 0,
              }}
            >
              <div style={{ width: 110, height: 110, overflow: 'hidden', position: 'relative' }}>
                <AvatarImg
                  src={img.image_url}
                  name="?"
                  size={110}
                  shape="square"
                  style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                />
                {isCurrent && (
                  <div style={{
                    position: 'absolute', bottom: 0, left: 0, right: 0,
                    background: 'rgba(201,100,66,.85)', color: '#fff',
                    fontSize: 10, textAlign: 'center', padding: '2px 0', fontWeight: 600, letterSpacing: '.04em',
                  }}>{t('cards.page.persona.badge_current')}</div>
                )}
              </div>
              <div style={{ padding: '5px 7px', fontSize: 10.5, color: 'var(--text-quiet, #9a948c)', lineHeight: 1.5 }}>
                <div>{sourceLabel[img.source] || img.source || '—'}</div>
                <div style={{ color: 'var(--muted, #b8b2a8)' }}>{fmtDate(img.created_at)}</div>
                {!isCurrent && (
                  <div style={{ marginTop: 3, color: 'var(--accent-soft, rgba(201,100,66,.8))', fontSize: 10 }}>
                    {isSettingThis ? t('cards.page.persona.setting_in_progress') : t('cards.page.persona.click_to_set_current')}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </CSSpaceBetween>
  );
}

/* 人设图缩略条 — 内联在卡详情左侧媒体列(海报下方)的精简画廊。
   点缩略图 → ImageLightbox 预览 + 裁剪(裁剪后存为新的当前人设图);hover 显「设为当前」。
   空(无人设图)时不渲染,不占位;完整管理仍在「人设图」tab。 */
function PersonaThumbStrip({ cardId, onAvatarRefresh }) {
  const { t } = useTranslation();
  const [images, setImages] = useStatePL(null);
  const [preview, setPreview] = useStatePL(null);

  const load = useCallbackPL(async () => {
    try {
      const r = await window.api.cards.personaImages(cardId);
      setImages(Array.isArray(r) ? r : (r?.images || r?.items || []));
    } catch (_) { setImages([]); }
  }, [cardId]);
  useEffectPL(() => { load(); }, [load]);
  // 生图完成(SSE rpg-image-updated,kind=persona)→ 自动刷新缩略图,无需手动刷新
  useEffectPL(() => {
    const h = (ev) => { const d = (ev && ev.detail) || {}; if (d.op === 'ready' && (d.payload?.kind || '') === 'persona') load(); };
    window.addEventListener('rpg-image-updated', h);
    return () => window.removeEventListener('rpg-image-updated', h);
  }, [load]);

  const setCurrent = async (img) => {
    if (img.is_current) return;
    try {
      await window.api.cards.personaSetCurrent(cardId, img.id);
      await load();
      onAvatarRefresh && onAvatarRefresh(img.image_url);
      window.__apiToast?.(t('cards.page.persona.set_current_ok'), { kind: 'ok', duration: 1500 });
    } catch (e) { window.__apiToast?.(t('common.error'), { kind: 'danger', detail: e?.message }); }
  };

  const onCrop = async (blob) => {
    const ext = (blob.type && blob.type.split('/')[1]) || 'jpg';
    const r = await window.api.cards.uploadPersonaImage(cardId, new File([blob], 'crop.' + ext, { type: blob.type || 'image/jpeg' }));
    const url = r && (r.url || r.image_url);
    await load();
    if (url && onAvatarRefresh) onAvatarRefresh(url);
    window.__apiToast?.(t('cards.page.persona.crop_saved'), { kind: 'ok', duration: 2000 });
    setPreview(null);
  };

  if (!images || images.length === 0) return null;

  return (
    <div className="pstrip">
      <div className="pstrip__head">{t('cards.page.persona.strip_title')} <span className="pstrip__count">{images.length}</span></div>
      <div className="pstrip__row">
        {images.map((img) => (
          <div key={img.id} className={`pstrip__cell${img.is_current ? ' is-current' : ''}`}>
            <img src={img.image_url} alt="" loading="lazy" onClick={() => setPreview(img.image_url)} title={t('cards.page.persona.thumb_title')} />
            {img.is_current
              ? <span className="pstrip__badge">{t('cards.page.persona.badge_current')}</span>
              : <button className="pstrip__set" onClick={() => setCurrent(img)}>{t('cards.page.persona.btn_set_current')}</button>}
          </div>
        ))}
      </div>
      <ImageLightbox open={!!preview} src={preview} onClose={() => setPreview(null)}
        onCrop={onCrop} cropHint={t('cards.page.persona.crop_hint')} />
    </div>
  );
}

/* 角色卡详情面板 —— 选中后在列表下方展开(对齐剧本/存档)。
   Tabs:角色信息(KeyValuePairs)/ 设定(只读展示)/ 角色设置(内联编辑表单)。 */
function CardDetailPanel({ card, kind, onSave, onDuplicate, onDelete }) {
  const { t } = useTranslation();
  const raw = card._raw || card;
  // 是否为 persona/pc 卡(显示人设图功能)
  const cardType = raw.card_type || (kind === 'npc' ? 'npc' : kind === 'user' ? 'persona' : kind);
  const isPersonaOrPc = cardType === 'persona' || cardType === 'pc';
  const [tab, setTab] = useStatePL('info');
  const [form, setForm] = useStatePL(null);
  const [saving, setSaving] = useStatePL(false);
  const [avatarUrl, setAvatarUrl] = useStatePL(raw.avatar_path || null);
  // Phase 4: 人设图状态
  const [autoSync, setAutoSync] = useStatePL(!!raw.auto_image_sync);
  const [autoSyncBusy, setAutoSyncBusy] = useStatePL(false);
  const [genPersonaBusy, setGenPersonaBusy] = useStatePL(false);
  // W3-C1: 手动上传状态(人设图;头像上传统一走 CharacterCardHero 内置入口)
  const [uploadPersonaBusy, setUploadPersonaBusy] = useStatePL(false);
  // 图2:分享到在线角色卡库(发布/取消公开)
  const [isPub, setIsPub] = useStatePL(raw.is_public === true || raw.scope === 'public');
  const [pubBusy, setPubBusy] = useStatePL(false);
  const personaInputRef = React.useRef(null);
  useEffectPL(() => {
    setTab('info');
    setForm(cardFormInit(raw));
    setSaving(false);  // 切卡时重置:防上一张卡的保存挂起态残留 → 新卡保存键卡死 loading
    setAvatarUrl(raw.avatar_path || null);
    setAutoSync(!!raw.auto_image_sync);
    setIsPub(raw.is_public === true || raw.scope === 'public');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.id]);
  const u = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const doSave = async () => {
    if (!form?.name?.trim()) { window.__apiToast?.(t('cards.toast.name_required'), { kind: 'warn' }); return; }
    setSaving(true);
    try { await onSave(cardFormPayload(form, card)); }
    finally { setSaving(false); }
  };

  // 图2:分享/取消分享到在线角色卡库(api.cards.setPublic → POST /me/character-cards/{id}/visibility {public})
  const doShare = async () => {
    const next = !isPub;
    setPubBusy(true);
    try {
      await window.api.cards.setPublic(raw.id ?? card.id, next);
      setIsPub(next);
      window.__apiToast?.(next
        ? t('cards.toast.published', { defaultValue: '已分享到在线角色卡库' })
        : t('cards.toast.unpublished', { defaultValue: '已取消公开' }), { kind: 'ok', duration: 1800 });
    } catch (e) {
      window.__apiToast?.(t('cards.toast.publish_fail', { defaultValue: '操作失败' }), { kind: 'danger', detail: e?.message || String(e) });
    } finally { setPubBusy(false); }
  };

  const doToggleAutoSync = async (checked) => {
    setAutoSync(checked);
    setAutoSyncBusy(true);
    try {
      await window.api.cards.personaAutoSync(raw.id ?? card.id, checked);
      window.__apiToast?.(checked ? t('cards.page.persona.auto_sync_on') : t('cards.page.persona.auto_sync_off'), { kind: 'ok', duration: 1800 });
    } catch (e) {
      setAutoSync(!checked); // 回滚
      window.__apiToast?.(t('common.error'), { kind: 'danger', detail: e?.message });
    } finally { setAutoSyncBusy(false); }
  };

  const doGenPersonaImage = async () => {
    setGenPersonaBusy(true);
    try {
      await window.api.cards.personaGenerate(raw.id ?? card.id);
      window.__apiToast?.(t('cards.page.persona.gen_queued'), { kind: 'ok', duration: 2800 });
    } catch (e) {
      window.__apiToast?.(t('cards.page.persona.gen_fail'), { kind: 'danger', detail: e?.message });
    } finally { setGenPersonaBusy(false); }
  };

  // W3-C1: 上传人设图
  const doUploadPersonaImage = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    e.target.value = '';
    setUploadPersonaBusy(true);
    window.__apiToast?.(t('cards.page.persona.uploading_persona'), { kind: 'info', duration: 2000 });
    try {
      const res = await window.api.cards.uploadPersonaImage(raw.id ?? card.id, file);
      if (res && res.url) setAvatarUrl(res.url);
      window.__apiToast?.(t('cards.page.persona.persona_uploaded'), { kind: 'ok', duration: 2200 });
    } catch (e2) {
      window.__apiToast?.(t('cards.page.persona.upload_fail'), { kind: 'danger', detail: e2?.message });
    } finally { setUploadPersonaBusy(false); }
  };

  const fullName = raw.full_name && raw.full_name !== raw.name ? raw.full_name : null;
  const chapterGate = (kind === 'npc' && raw.first_revealed_chapter > 1) ? raw.first_revealed_chapter : null;

  const cardTypeLabel = { npc: t('cards.detail.type_npc'), pc: t('cards.detail.type_pc'), persona: t('cards.detail.type_persona') };
  const sourceLabel = { extracted: t('cards.detail.source_extracted'), user: t('cards.detail.source_user'), persona: t('cards.detail.source_persona'), platform: t('cards.detail.source_platform') };
  const scopeLabel = { script: t('cards.detail.scope_script'), private: t('cards.detail.scope_private'), public: t('cards.detail.scope_public') };

  return (
    <>
    {/* 头像的生成/上传/图库统一入口 = 下方 CharacterCardHero(内置 MediaStudio);
        旧 W3-C1 的独立头像 input + GenerateImageModal 无触发器已摘除(横扫确认死代码,
        且其直调 user 端点的写法对 NPC 卡是 403 陷阱,防复活)。 */}
    {/* W3-C1: 隐藏 file input — 人设图上传 */}
    <input
      ref={personaInputRef}
      type="file"
      accept="image/png,image/jpeg,image/webp"
      style={{ display: 'none' }}
      onChange={doUploadPersonaImage}
    />
    <CSContainer header={
      <CSHeader variant="h2"
        actions={
          <CSSpaceBetween direction="horizontal" size="xs">
            {isPersonaOrPc && (
              <CSButton iconName="gen-ai" loading={genPersonaBusy} onClick={doGenPersonaImage}>{t('cards.page.persona.btn_gen_persona')}</CSButton>
            )}
            <CSButton variant="primary" iconName="check" loading={saving} onClick={doSave}>{t('cards.detail.btn_save')}</CSButton>
            {kind === 'user' && (
              <CSButton iconName={isPub ? 'lock-private' : 'share'} loading={pubBusy} onClick={doShare}>
                {isPub ? t('cards.detail.btn_unpublish', { defaultValue: '取消公开' }) : t('cards.detail.btn_publish', { defaultValue: '分享到在线库' })}
              </CSButton>
            )}
            <CSButton iconName="copy" onClick={onDuplicate}>{t('cards.detail.btn_duplicate')}</CSButton>
            {kind === 'user' && <CSButton href={window.api.cards.exportTavern(card.id)} target="_blank" iconName="download">{t('cards.detail.btn_export')}</CSButton>}
            <CSButton iconName="remove" onClick={onDelete}>{t('cards.detail.btn_delete')}</CSButton>
          </CSSpaceBetween>
        }
      >{card.name}{fullName && <CSBox display="inline" color="text-status-inactive" fontSize="body-s" padding={{ left: 's' }}>{fullName}</CSBox>}</CSHeader>
    }>
      {/* 图片优先的角色海报 — 宽屏左右分栏(图列左 sticky + 信息列右),窄屏堆叠 */}
      <div className="msplit">
        <div className="msplit__media">
          <CharacterCardHero
            card={{ id: raw.id, name: raw.name, identity: raw.identity || raw.role, appearance: raw.appearance, avatar_path: avatarUrl }}
            editable
            scriptId={kind === 'npc' ? (raw.script_id || card?._raw?.script_id || null) : null}
            onChanged={(u) => setAvatarUrl(u)}
          />
          {/* 海报下方内联人设图缩略条(仅 persona/pc;无图时不渲染)——点开预览支持裁剪 */}
          {isPersonaOrPc && <PersonaThumbStrip cardId={raw.id ?? card.id} onAvatarRefresh={(u) => setAvatarUrl(u)} />}
        </div>
        <div className="msplit__body">
      <CSTabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: 'info', label: t('cards.detail.tab_info'), content: (
          <CSKeyValuePairs columns={4} items={[
            { label: t('cards.detail.identity'), value: (raw.identity || raw.role)
                ? <div style={{ ...clampLines(2) }}>{_oneLine(raw.identity || raw.role, 140)}</div>
                : '—' },
            ...(fullName ? [{ label: t('cards.detail.full_name'), value: fullName }] : []),
            { label: t('cards.detail.type'), value: cardTypeLabel[raw.card_type] || (kind === 'npc' ? t('cards.detail.type_npc') : t('cards.detail.type_user')) },
            { label: t('cards.detail.source'), value: sourceLabel[raw.source] || card.origin || t('cards.detail.source_generic') },
            { label: t('cards.detail.importance'), value: raw.importance != null ? String(raw.importance) : '—' },
            ...(chapterGate ? [{ label: t('cards.detail.chapter_gate'), value: <CSStatusIndicator type="info">📖 {t('cards.detail.chapter_n', { n: chapterGate })}</CSStatusIndicator> }] : []),
            { label: t('cards.detail.scope'), value: scopeLabel[raw.scope] || '—' },
            { label: t('cards.detail.status'), value: raw.enabled === false ? <CSStatusIndicator type="stopped">{t('cards.detail.status_disabled')}</CSStatusIndicator> : <CSStatusIndicator type="success">{t('cards.detail.status_enabled')}</CSStatusIndicator> },
            { label: t('cards.detail.tags_label'), value: (Array.isArray(raw.tags) && raw.tags.length) ? raw.tags.join(' · ') : '—' },
            { label: t('cards.detail.updated'), value: card.updated || '—' },
            { label: t('cards.detail.card_id'), value: <span className="mono">{card.id}</span> },
          ]} />
        ) },
        { id: 'setting', label: t('cards.detail.tab_setting'), content: <CardSheet card={card} kind={kind} /> },
        { id: 'edit', label: t('cards.detail.tab_edit'), content: form && (
          <CSSpaceBetween size="l">
            <CardEditFields form={form} u={u} kind={kind} />
            <CSBox><CSButton variant="primary" iconName="check" loading={saving} onClick={doSave}>{t('cards.detail.btn_save')}</CSButton></CSBox>
          </CSSpaceBetween>
        ) },
        // Phase 4: 人设图标签页 — 仅 persona/pc 卡显示
        ...(isPersonaOrPc ? [{
          id: 'persona_images',
          label: t('cards.page.persona.tab_label'),
          content: (
            <CSSpaceBetween size="l">
              {/* 自动维护开关 */}
              <CSContainer header={<CSHeader variant="h3">{t('cards.page.persona.auto_section_title')}</CSHeader>}>
                <CSSpaceBetween size="s">
                  <CSToggle
                    checked={autoSync}
                    disabled={autoSyncBusy}
                    onChange={({ detail }) => doToggleAutoSync(detail.checked)}
                  >
                    {t('cards.page.persona.auto_sync_label')}
                  </CSToggle>
                  <CSBox color="text-body-secondary" fontSize="body-s">
                    {t('cards.page.persona.auto_sync_desc')}
                  </CSBox>
                </CSSpaceBetween>
              </CSContainer>

              {/* 手动生成 */}
              <CSContainer header={<CSHeader variant="h3" actions={
                <CSSpaceBetween direction="horizontal" size="xs">
                  <CSButton iconName="gen-ai" loading={genPersonaBusy} onClick={doGenPersonaImage}>{t('cards.page.persona.btn_gen_now')}</CSButton>
                  <CSButton iconName="upload" loading={uploadPersonaBusy} disabled={uploadPersonaBusy}
                    onClick={() => personaInputRef.current && personaInputRef.current.click()}>{t('cards.page.persona.btn_upload_persona')}</CSButton>
                </CSSpaceBetween>
              }>{t('cards.page.persona.manual_section_title')}</CSHeader>}>
                <CSBox color="text-body-secondary" fontSize="body-s">
                  {t('cards.page.persona.manual_section_desc')}
                </CSBox>
              </CSContainer>

              {/* 历史画廊 */}
              <CSExpandableSection
                variant="container"
                headerText={t('cards.page.persona.history_title')}
                headerDescription={t('cards.page.persona.history_desc')}
                defaultExpanded
              >
                {tab === 'persona_images' && (
                  <PersonaImageGallery
                    cardId={raw.id ?? card.id}
                    onAvatarRefresh={(url) => setAvatarUrl(url)}
                  />
                )}
              </CSExpandableSection>
            </CSSpaceBetween>
          ),
        }] : []),
      ]} />
        </div>
      </div>
    </CSContainer>
    </>
  );
}

export { CardDetailPanel };
