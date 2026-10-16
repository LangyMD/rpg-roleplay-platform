/* 角色卡编辑器 —— EC2 式单页多模块全屏表单(NPC / PC / persona 三态)—— 从 pages/cards.jsx 拆出,逐字节不变。 */

import React from 'react';
import { createPortal } from 'react-dom';
import { useState as useStatePL } from 'react';
import { useTranslation } from 'react-i18next';
import CharacterCardHero from '../CharacterCardHero.jsx';
import CSButton from '@cloudscape-design/components/button';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import CSFormField from '@cloudscape-design/components/form-field';
import CSSelect from '@cloudscape-design/components/select';
import CSKeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import CSBox from '@cloudscape-design/components/box';
import { cardFormInit, cardFormPayload } from './helpers.js';
import { CardEditFields } from './CardFields.jsx';

/* 角色卡编辑器 —— EC2 式单页多模块全屏表单(对齐新建存档)。
   覆盖 user_character_cards 全部角色相关列:name / identity / aliases / tags /
   appearance / personality / speech_style / current_status / secrets /
   sample_dialogue / token_budget / priority / enabled / scope。 */
function CardEditModal({ card, isNew, kind, onClose, onSave, onPromote, targetScriptOptions = [], targetScriptId = "", onTargetScriptChange }) {
  const { t } = useTranslation();
  const [form, setForm] = useStatePL(() => cardFormInit(card));
  const [submitting, setSubmitting] = useStatePL(false);
  const [promoting, setPromoting] = useStatePL(false);
  const [avatarUrl, setAvatarUrl] = useStatePL(card?._raw?.avatar_path || card?.avatar_path || null);
  const u = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const nameOk = !!form.name.trim();
  const editCardId = card?._raw?.id || card?.id || null;
  // scriptId 双载荷兼容:角色卡页传 {_raw: row} 包装,剧本详情页 NPC tab 直传裸 DTO
  // (script_id 在顶层)。只认 _raw 曾让后者恒 null → 头像上传落回 user 端点,NPC 卡
  // (user_id=NULL)被 403「角色卡不存在或无权访问」(群反馈:先知Kevin)。与 editCardId 同款回退。
  const editScriptId = kind === 'npc' ? (card?._raw?.script_id || card?.script_id || targetScriptId || null) : null;

  const doSave = async () => {
    if (!nameOk || submitting) return;
    setSubmitting(true);
    try {
      // payload 构造放进 try:个别卡字段类型异常时(理论上不应发生)别让整段静默吞掉。
      const payload = cardFormPayload(form, card);
      await onSave?.(payload);
    } catch (e) {
      // 关键:原来这里 catch(_){} 把**任何**错误(payload 构造抛错 / onSave 同步抛错)
      // 静默吞掉,用户表现为「保存按钮点了没反应」(群反馈)。改为显式 toast,暴露真因。
      // 父级 onSave 自己已 toast 的网络错走它那条;这里兜的是 payload/同步异常。
      try {
        window.__apiToast?.(t('cards.editor.save_fail', { defaultValue: '保存失败' }),
          { kind: 'danger', detail: (e && e.message) || String(e) });
      } catch (_) { /* toast 不可用也不该再抛 */ }
      // eslint-disable-next-line no-console
      console.error('[CardEditModal] save failed:', e);
    } finally { setSubmitting(false); }
  };

  const node = (
    <div style={{ position: 'fixed', top: 'var(--nav-h, 53px)', left: 0, right: 0, bottom: 0, zIndex: 1000, background: 'var(--bg, #1a1817)', overflow: 'auto' }}>
      {/* 顶部栏(位于平台顶栏下方,保留平台导航) */}
      <div style={{ position: 'sticky', top: 0, zIndex: 3, background: '#131211', borderBottom: '1px solid #36322d' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '13px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
          <div style={{ fontFamily: "'Noto Serif', 'Noto Serif SC', serif", fontSize: 18, fontWeight: 600, color: '#ebe7df' }}>
            {isNew ? t('cards.editor.modal_title_new') : t('cards.editor.modal_title_edit')}{kind === 'user' ? t('cards.editor.kind_user') : t('cards.editor.kind_npc')}
          </div>
          <CSButton iconName="close" variant="link" onClick={onClose}>{t('cards.editor.btn_cancel')}</CSButton>
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 24px 80px' }}>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
          {/* 左:共享字段组(NPC/PC/persona 三态统一) */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <CardEditFields form={form} u={u} kind={kind} />
          </div>

          {/* 右:概要 + 保存(sticky) */}
          <div style={{ width: 300, flexShrink: 0, position: 'sticky', top: 72 }}>
            <CSContainer header={<CSHeader variant="h2">{t('cards.editor.summary_title')}</CSHeader>}>
              <CSSpaceBetween size="m">
                {/* 当前头像预览 */}
                {/* 头像编辑(海报 + MediaStudio 生成/上传/图库 + 预览裁剪);新卡需先保存才有 id */}
                {!isNew && editCardId ? (
                  <div style={{ maxWidth: 260, margin: '0 auto 4px' }}>
                    <CharacterCardHero
                      card={{ id: editCardId, name: form.name, identity: form.identity, appearance: form.appearance, avatar_path: avatarUrl }}
                      editable scriptId={editScriptId}
                      onChanged={(uu) => { setAvatarUrl(uu); try { window.dispatchEvent(new CustomEvent('rpg-user-cards-updated')); } catch (_) {} }}
                    />
                  </div>
                ) : (isNew ? (
                  <CSBox color="text-body-secondary" fontSize="body-s" textAlign="center">{t('cards.editor.avatar_after_save', { defaultValue: '保存后可设置头像' })}</CSBox>
                ) : null)}
                <CSStatusIndicator type={nameOk ? 'success' : 'pending'}>{t('cards.editor.name_required_status')}</CSStatusIndicator>
                {kind === 'npc' && isNew && targetScriptOptions.length > 0 && (
                  <CSFormField label={t('cards.editor.target_script')} description={t('cards.editor.target_script_desc')}>
                    <CSSelect
                      selectedOption={targetScriptOptions.find((o) => o.value === String(targetScriptId)) || targetScriptOptions[0]}
                      options={targetScriptOptions}
                      disabled={targetScriptOptions.length <= 1}
                      onChange={({ detail }) => onTargetScriptChange?.(detail.selectedOption.value)}
                    />
                  </CSFormField>
                )}
                <CSKeyValuePairs columns={1} items={[
                  { label: t('cards.editor.name'), value: form.name.trim() || '—' },
                  { label: t('cards.editor.identity'), value: form.identity.trim() || '—' },
                  { label: t('cards.editor.scope'), value: form.scope === 'public' ? t('cards.detail.scope_public') : t('cards.detail.scope_private') },
                  { label: t('cards.editor.enabled'), value: form.enabled ? t('cards.editor.enabled_on') : t('cards.editor.enabled_off') },
                ]} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <CSButton variant="primary" disabled={!nameOk || submitting} loading={submitting} onClick={doSave}>
                    {isNew ? t('cards.editor.btn_create') : t('cards.editor.btn_save')}
                  </CSButton>
                  {/* NPC 卡:编辑页内直接「转为用户角色卡」(复制到自己名下,不改原剧本)。
                      仅已存在的 NPC 卡 + 调用方传了 onPromote 时显示。 */}
                  {kind === 'npc' && !isNew && onPromote && (
                    <CSButton iconName="add-plus" disabled={promoting} loading={promoting}
                      onClick={async () => { setPromoting(true); try { await onPromote(card); } finally { setPromoting(false); } }}>
                      {t('cards.editor.btn_promote_npc', { defaultValue: '转为用户角色卡' })}
                    </CSButton>
                  )}
                  <CSButton variant="link" onClick={onClose}>{t('cards.editor.btn_cancel')}</CSButton>
                </div>
              </CSSpaceBetween>
            </CSContainer>
          </div>
        </div>
      </div>
    </div>
  );
  return createPortal(node, document.body);
}

export { CardEditModal };
