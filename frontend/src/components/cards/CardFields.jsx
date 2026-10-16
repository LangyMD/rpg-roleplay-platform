/* 共享角色档字段组(编辑)+ 只读档展示 + 人格 skill 折叠拉取 —— 从 pages/cards.jsx 拆出,逐字节不变。
   CardEditFields / CardSheet 被角色卡页、酒馆抽屉、新游戏向导、剧本编辑器复用。 */

import React from 'react';
import { useState as useStatePL, useCallback as useCallbackPL } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../../game-icons.jsx';
import AvatarImg from '../AvatarImg.jsx';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSBadge from '@cloudscape-design/components/badge';
import CSBox from '@cloudscape-design/components/box';
import CSKeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import CSFormField from '@cloudscape-design/components/form-field';
import CSInput from '@cloudscape-design/components/input';
import CSTextarea from '@cloudscape-design/components/textarea';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSToggle from '@cloudscape-design/components/toggle';
import CSExpandableSection from '@cloudscape-design/components/expandable-section';
import CSSelect from '@cloudscape-design/components/select';
import { _oneLine, clampLines } from './helpers.js';

// 共享字段组(EC2 区块)。kind: 'npc' | 'user' | 'persona'
function CardEditFields({ form, u, kind = 'user' }) {
  const { t } = useTranslation();
  const isNpc = kind === 'npc';
  // 图3:人格 skill 卡 —— 行为由整包 skill 原文驱动(扮演时逐字注入),通用档案字段对它基本无意义。
  // 这类卡的编辑器不再平铺一堆空字段,只留名称/标签,其余原始字段折叠收起。
  const isSkill = String(form.tags || '').split(/[,，]/).map((s) => s.trim()).includes('人格skill');
  const scopeOpts = isNpc
    ? [
        { value: 'script', label: t('cards.editor.scope_script') },
        { value: 'private', label: t('cards.editor.scope_private') },
        { value: 'public', label: t('cards.editor.scope_public') },
      ]
    : [
        { value: 'private', label: t('cards.editor.scope_private') },
        { value: 'public', label: t('cards.editor.scope_public') },
      ];
  return (
    <CSSpaceBetween size="l">
      {isSkill && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '14px 16px', borderRadius: 12,
                      background: 'color-mix(in srgb, var(--accent, #c96442) 12%, transparent)',
                      border: '1px solid color-mix(in srgb, var(--accent, #c96442) 35%, transparent)' }}>
          <Icon name="spark" size={20} style={{ color: 'var(--accent, #c96442)', flexShrink: 0, marginTop: 2 }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, color: 'var(--text, #ebe7df)', marginBottom: 4 }}>{t('cards_page.skill_card_title')}</div>
            <div style={{ fontSize: 12.5, color: 'var(--muted, #968f85)', lineHeight: 1.6 }}>
              {t('cards_page.skill_card_desc_prefix')}
              <b style={{ color: 'var(--text-quiet, #c8c2b7)' }}>{t('cards_page.skill_card_desc_highlight')}</b>{t('cards_page.skill_card_desc_mid')}
              <b style={{ color: 'var(--text-quiet, #c8c2b7)' }}>{t('cards_page.skill_card_desc_reimport')}</b>{t('cards_page.skill_card_desc_suffix')}
            </div>
          </div>
        </div>
      )}
      <CSExpandableSection variant="container" defaultExpanded
        headerText={t('cards.editor.section_basic')}
        headerDescription={t('cards.editor.section_basic_desc')}>
        <CSColumnLayout columns={2}>
          <CSFormField label={t('cards.editor.name')} constraintText={t('cards.editor.name_required')}>
            <CSInput value={form.name} onChange={({ detail }) => u('name', detail.value)} autoFocus />
          </CSFormField>
          <CSFormField label={t('cards.editor.full_name')} description={t('cards.editor.full_name_desc')}>
            <CSInput value={form.full_name} onChange={({ detail }) => u('full_name', detail.value)} />
          </CSFormField>
          <CSFormField label={t('cards.editor.identity')}>
            <CSInput value={form.identity} onChange={({ detail }) => u('identity', detail.value)} />
          </CSFormField>
          <CSFormField label={t('cards.editor.aliases')} description={t('cards.editor.aliases_desc')}>
            <CSInput value={form.aliases} onChange={({ detail }) => u('aliases', detail.value)} />
          </CSFormField>
          <div style={{ gridColumn: '1 / -1' }}>
            <CSFormField label={t('cards.editor.tags')} description={t('cards.editor.tags_desc')}>
              <CSInput value={form.tags} onChange={({ detail }) => u('tags', detail.value)} />
            </CSFormField>
          </div>
        </CSColumnLayout>
      </CSExpandableSection>

      <CSExpandableSection variant="container" defaultExpanded={!isSkill}
        headerText={isSkill ? (t('cards.editor.section_profile') + t('cards_page.raw_fields_suffix')) : t('cards.editor.section_profile')}
        headerDescription={t('cards.editor.section_profile_desc')}>
        <CSSpaceBetween size="l">
          <CSFormField label={t('cards.editor.background')} description={t('cards.editor.background_desc')}><CSTextarea rows={3} value={form.background} onChange={({ detail }) => u('background', detail.value)} /></CSFormField>
          <CSFormField label={t('cards.editor.appearance')}><CSTextarea rows={2} value={form.appearance} onChange={({ detail }) => u('appearance', detail.value)} /></CSFormField>
          <CSFormField label={t('cards.editor.personality')}><CSTextarea rows={3} value={form.personality} onChange={({ detail }) => u('personality', detail.value)} /></CSFormField>
          <CSFormField label={t('cards.editor.speech_style')}><CSTextarea rows={2} value={form.speech_style} onChange={({ detail }) => u('speech_style', detail.value)} /></CSFormField>
          <CSFormField label={t('cards.editor.current_status')} description={t('cards.editor.current_status_desc')}><CSTextarea rows={2} value={form.current_status} onChange={({ detail }) => u('current_status', detail.value)} /></CSFormField>
        </CSSpaceBetween>
      </CSExpandableSection>

      <CSExpandableSection variant="container" defaultExpanded={!isSkill}
        headerText={isSkill ? (t('cards.editor.section_story') + t('cards_page.raw_fields_suffix')) : t('cards.editor.section_story')}
        headerDescription={t('cards.editor.section_story_desc')}>
        <CSSpaceBetween size="l">
          <CSFormField label={t('cards.editor.secrets')} description={t('cards.editor.secrets_desc')}><CSTextarea rows={3} value={form.secrets} onChange={({ detail }) => u('secrets', detail.value)} /></CSFormField>
          <CSFormField label={t('cards.editor.sample_dialogue')} description={t('cards.editor.sample_dialogue_desc')}><CSTextarea rows={4} value={form.sample_dialogue} onChange={({ detail }) => u('sample_dialogue', detail.value)} /></CSFormField>
        </CSSpaceBetween>
      </CSExpandableSection>

      <CSExpandableSection variant="container" defaultExpanded={!isSkill}
        headerText={t('cards.editor.section_inject')}
        headerDescription={t('cards.editor.section_inject_desc')}>
        <CSColumnLayout columns={2}>
          <CSFormField label={t('cards.editor.importance')} description={t('cards.editor.importance_desc')}>
            <CSInput type="number" value={String(form.importance)} onChange={({ detail }) => u('importance', detail.value)} />
          </CSFormField>
          {isNpc && (
            <CSFormField label={t('cards.editor.first_revealed_chapter')} description={t('cards.editor.first_revealed_chapter_desc')}>
              <CSInput type="number" value={String(form.first_revealed_chapter)} onChange={({ detail }) => u('first_revealed_chapter', detail.value)} />
            </CSFormField>
          )}
          <CSFormField label={t('cards.editor.token_budget')} description={t('cards.editor.token_budget_desc')}>
            <CSInput type="number" value={String(form.token_budget)} onChange={({ detail }) => u('token_budget', detail.value)} />
          </CSFormField>
          <CSFormField label={t('cards.editor.priority')} description={t('cards.editor.priority_desc')}>
            <CSInput type="number" value={String(form.priority)} onChange={({ detail }) => u('priority', detail.value)} />
          </CSFormField>
          <CSFormField label={t('cards.editor.scope')}>
            <CSSelect selectedOption={scopeOpts.find((o) => o.value === form.scope) || scopeOpts[0]}
              options={scopeOpts} onChange={({ detail }) => u('scope', detail.selectedOption.value)} />
          </CSFormField>
          <CSFormField label={t('cards.editor.enabled')}>
            <CSToggle checked={!!form.enabled} onChange={({ detail }) => u('enabled', detail.checked)}>
              {form.enabled ? t('cards.editor.enabled_on') : t('cards.editor.enabled_off')}
            </CSToggle>
          </CSFormField>
        </CSColumnLayout>
      </CSExpandableSection>
    </CSSpaceBetween>
  );
}

/* 只读角色档展示(设定 tab / 详情用)。纯展示 DTO 结构化字段,不做任何文本解析。 */
// 人格 skill 完整定义:折叠 + 按需拉取(GET 单卡)+ 高度封顶滚动 + 渲染长度封顶。
// 关键:不把 30k 原文常驻 DOM(默认折叠)、不随 /api/state 下发(按需拉),避免长 skill 内存爆。
function SkillContentSection({ cardId, kind }) {
  const { t } = useTranslation();
  const [open, setOpen] = useStatePL(false);
  const [text, setText] = useStatePL('');
  const [loading, setLoading] = useStatePL(false);
  const [err, setErr] = useStatePL('');
  // 剧本 NPC 卡(kind='npc')的 user_id=NULL,不属于当前用户,不能走用户归属端点
  // /api/me/character-cards/{id}(会 404)。这类卡直接降级展示提示文案,不发请求。
  const npcUnsupported = kind === 'npc';
  const toggle = useCallbackPL(async () => {
    if (npcUnsupported) return;
    if (text) { setOpen((o) => !o); return; }
    if (loading || cardId == null) return;
    setLoading(true); setErr('');
    try {
      const r = await window.api.cards.myGet(cardId);
      const c = (r && (r.card || r)) || {};
      const sc = (c.metadata && c.metadata.skill_content) || c.background || '';
      setText(sc || t('cards_page.skill_empty')); setOpen(true);
    } catch (e) { setErr(e?.message || t('cards_page.skill_load_fail')); } finally { setLoading(false); }
  }, [cardId, text, loading, t, npcUnsupported]);
  const MAX = 60000;
  const shown = text.length > MAX ? (text.slice(0, MAX) + '\n' + t('cards_page.skill_truncated')) : text;
  return (
    <div style={{ background: 'var(--panel-2, #282623)', border: '1px solid var(--line-soft, #2a2724)', borderRadius: 10, padding: '12px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <div style={{ fontSize: 11, letterSpacing: '.08em', color: 'var(--accent, #c96442)', fontWeight: 600, textTransform: 'uppercase' }}>{t('cards_page.skill_section_label')}</div>
        {!npcUnsupported && (
          <button
            onClick={toggle}
            style={{ fontSize: 12, color: 'var(--accent, #c96442)', background: 'transparent', border: '1px solid var(--line, #3a352f)', borderRadius: 8, padding: '4px 12px', cursor: 'pointer' }}
          >
            {loading ? t('cards_page.skill_loading') : (open ? t('cards_page.skill_collapse') : t('cards_page.skill_view_full'))}
          </button>
        )}
      </div>
      {err && <div style={{ color: 'var(--danger, #c8675d)', fontSize: 12, marginTop: 6 }}>{err}</div>}
      {npcUnsupported ? (
        <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--muted-2, #8a847b)' }}>{t('cards_page.skill_npc_unsupported')}</div>
      ) : (
        <>
          {open && text && (
            <div style={{ marginTop: 10, maxHeight: 360, overflow: 'auto', whiteSpace: 'pre-wrap', lineHeight: 1.7, fontSize: 12.5, color: 'var(--text-quiet, #c8c2b7)', fontFamily: 'ui-monospace, monospace', wordBreak: 'break-word' }}>
              {shown}
            </div>
          )}
          {!open && <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--muted-2, #8a847b)' }}>{t('cards_page.skill_hint')}</div>}
        </>
      )}
    </div>
  );
}

function CardSheet({ card, kind = 'user', dense = false }) {
  const { t } = useTranslation();
  const raw = (card && card._raw) || card || {};
  const fullName = raw.full_name && raw.full_name !== raw.name ? raw.full_name : null;
  const aliases = Array.isArray(raw.aliases) ? raw.aliases : [];
  const tags = Array.isArray(raw.tags) ? raw.tags : [];
  const dialogues = Array.isArray(raw.sample_dialogue) ? raw.sample_dialogue : [];
  const chapterGate = (kind === 'npc' && raw.first_revealed_chapter > 1) ? raw.first_revealed_chapter : null;
  const initial = (raw.name || '?').trim().slice(0, 1);
  const hasBody = raw.background || raw.appearance || raw.personality || raw.speech_style || raw.current_status || raw.secrets || dialogues.length;

  const cardTypeLabel = {
    npc: t('cards.detail.type_npc'),
    pc: t('cards.detail.type_pc'),
    persona: t('cards.detail.type_persona'),
  };
  const scopeLabel = {
    script: t('cards.detail.scope_script'),
    private: t('cards.detail.scope_private'),
    public: t('cards.detail.scope_public'),
  };
  const sourceLabel = {
    extracted: t('cards.detail.source_extracted'),
    user: t('cards.detail.source_user'),
    persona: t('cards.detail.source_persona'),
    platform: t('cards.detail.source_platform'),
  };

  const block = (label, value) => value ? (
    <div style={{ background: 'var(--panel-2, #282623)', border: '1px solid var(--line-soft, #2a2724)', borderRadius: 10, padding: '12px 16px' }}>
      <div style={{ fontSize: 11, letterSpacing: '.08em', color: 'var(--accent, #c96442)', fontWeight: 600, marginBottom: 7, textTransform: 'uppercase' }}>{label}</div>
      <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.72, color: 'var(--text, #ebe7df)', fontSize: 13.5 }}>{value}</div>
    </div>
  ) : null;

  const attrs = [
    { label: t('cards.detail.type'), value: cardTypeLabel[raw.card_type] || (kind === 'npc' ? t('cards.detail.type_npc') : t('cards.detail.type_user')) },
    { label: t('cards.detail.source'), value: sourceLabel[raw.source] || t('cards.detail.source_generic') },
    { label: t('cards.detail.importance'), value: raw.importance != null ? String(raw.importance) : '—' },
    ...(chapterGate ? [{ label: t('cards.detail.first_revealed'), value: t('cards.detail.chapter_n', { n: chapterGate }) }] : []),
    { label: t('cards.detail.scope'), value: scopeLabel[raw.scope] || t('cards.detail.scope_private') },
    { label: t('cards.detail.status'), value: raw.enabled === false ? <CSStatusIndicator type="stopped">{t('cards.detail.status_disabled')}</CSStatusIndicator> : <CSStatusIndicator type="success">{t('cards.detail.status_enabled')}</CSStatusIndicator> },
    { label: t('cards.detail.token_budget'), value: String(raw.token_budget ?? 450) },
    { label: t('cards.detail.priority'), value: String(raw.priority ?? 100) },
  ];

  return (
    <CSSpaceBetween size="l">
      {/* 头部:头像首字 + 名 + 身份 + 别名/标签 */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
        <AvatarImg
          src={raw.avatar_path}
          name={raw.name || '?'}
          size={64}
          shape="rounded"
          zoomable
          className="pl-card-avatar serif"
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: "'Noto Serif', 'Noto Serif SC', serif", fontSize: 19, fontWeight: 600, color: 'var(--text, #ebe7df)' }}>
            {raw.name || t('cards.detail.unnamed')}
            {fullName && <span style={{ fontSize: 13, color: 'var(--muted, #968f85)', marginLeft: 8, fontStyle: 'italic' }}>{fullName}</span>}
          </div>
          {raw.identity && <div style={{ fontSize: 13.5, color: 'var(--text-quiet, #c8c2b7)', marginTop: 3, ...clampLines(2) }}>{_oneLine(raw.identity, 160)}</div>}
          {(aliases.length > 0 || tags.length > 0) && (
            <div style={{ marginTop: 9 }}>
              <CSSpaceBetween direction="horizontal" size="xxs">
                {aliases.map((a) => <CSBadge key={'a' + a}>{a}</CSBadge>)}
                {tags.map((tg) => <CSBadge key={'t' + tg} color="green">{tg}</CSBadge>)}
              </CSSpaceBetween>
            </div>
          )}
        </div>
      </div>

      {/* 属性条。dense(酒馆抽屉等窄容器):Cloudscape KVP 的响应式在 ~320px 会塌成单列,
          7 个短值竖排占半屏(用户实锤「特别空看着怪」)——改用自绘双列紧凑网格。 */}
      {dense ? (
        <div className="pl-cardsheet-attrs-dense"
          style={{ background: 'var(--panel, #211f1d)', border: '1px solid var(--line-soft, #2a2724)',
                   borderRadius: 10, padding: '10px 14px', display: 'grid',
                   gridTemplateColumns: '1fr 1fr', gap: '10px 16px' }}>
          {attrs.map((a) => (
            <div key={a.label} style={{ minWidth: 0 }}>
              <div style={{ fontSize: 11, letterSpacing: '.06em', color: 'var(--muted, #968f85)',
                            marginBottom: 2 }}>{a.label}</div>
              <div style={{ fontSize: 13, color: 'var(--text, #ebe7df)', overflow: 'hidden',
                            textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.value}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ background: 'var(--panel, #211f1d)', border: '1px solid var(--line-soft, #2a2724)', borderRadius: 10, padding: '12px 16px' }}>
          <CSKeyValuePairs columns={4} items={attrs} />
        </div>
      )}

      {/* 人格 skill 卡:不内联 30k 原文,改折叠按需拉(防内存爆);其余字段照常 */}
      {(raw.metadata && raw.metadata.persona_skill) || tags.includes('人格skill') ? (
        <CSSpaceBetween size="s">
          <SkillContentSection cardId={raw.id} kind={kind} />
          {block(t('cards.detail.appearance'), raw.appearance)}
          {block(t('cards.detail.personality'), raw.personality)}
          {block(t('cards.detail.speech_style'), raw.speech_style)}
        </CSSpaceBetween>
      ) : hasBody ? (
        <CSSpaceBetween size="s">
          {block(t('cards.detail.background'), raw.background)}
          {block(t('cards.detail.appearance'), raw.appearance)}
          {block(t('cards.detail.personality'), raw.personality)}
          {block(t('cards.detail.speech_style'), raw.speech_style)}
          {block(t('cards.detail.current_status'), raw.current_status)}
          {block(t('cards.detail.secrets'), raw.secrets)}
          {dialogues.length > 0 && (
            <div style={{ background: 'var(--panel-2, #282623)', border: '1px solid var(--line-soft, #2a2724)', borderRadius: 10, padding: '12px 16px' }}>
              <div style={{ fontSize: 11, letterSpacing: '.08em', color: 'var(--accent, #c96442)', fontWeight: 600, marginBottom: 8, textTransform: 'uppercase' }}>{t('cards.detail.sample_dialogue')}</div>
              <CSSpaceBetween size="xs">
                {dialogues.map((d, i) => (
                  <div key={i} style={{ borderLeft: '2px solid var(--accent-soft, rgba(201,100,66,.4))', paddingLeft: 10, color: 'var(--text-quiet, #c8c2b7)', fontSize: 13, lineHeight: 1.6 }}>
                    {typeof d === 'string' ? d : `${d.role ? d.role + ':' : ''}${d.content || ''}`}
                  </div>
                ))}
              </CSSpaceBetween>
            </div>
          )}
        </CSSpaceBetween>
      ) : (
        <CSBox color="text-status-inactive">{t('cards.empty.no_settings')}</CSBox>
      )}
    </CSSpaceBetween>
  );
}

export { CardEditFields, CardSheet };
