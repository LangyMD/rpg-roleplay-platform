/* 新游戏向导 Step 4:初始身份(本体来源 + 身份卡 overlay + 是否知情)。
   从 components/saves/NewGame.jsx 二次拆出,JSX 逐字节不变。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSBox from '@cloudscape-design/components/box';
import CSBadge from '@cloudscape-design/components/badge';
import CSButton from '@cloudscape-design/components/button';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSFormField from '@cloudscape-design/components/form-field';
import CSInput from '@cloudscape-design/components/input';
import CSTextarea from '@cloudscape-design/components/textarea';
import CSAlert from '@cloudscape-design/components/alert';

/* ============================================================
   Step 4: 初始身份
   ============================================================ */
function IdentityStep({ scriptId, birthpoint, pickedCard, allRoleOptions, identity, setIdentity, playerOrigin, setPlayerOrigin, identityKnown, setIdentityKnown }) {
  const { t } = useTranslation();
  const [recs, setRecs] = React.useState([]);
  const [recsLoading, setRecsLoading] = React.useState(false);
  const [recsErr, setRecsErr] = React.useState("");
  const [customOpen, setCustomOpen] = React.useState(false);
  const [customName, setCustomName] = React.useState("");
  const [customRole, setCustomRole] = React.useState("");
  const [customBg, setCustomBg] = React.useState("");
  // 反馈#1:从原著 NPC 角色卡里选一个作为主角"失忆的真实身份"(与角色卡不冲突,只是开局不自知)。
  const [npcCards, setNpcCards] = React.useState([]);
  // 重做:身份来源统一成一个选择器(none / npc / ai / manual),驱动第二层只显示对应面板。
  const _srcOf = (id) => !id ? 'none' : (id._from === 'npc_card' ? 'npc' : id._from === 'ai' ? 'ai' : 'manual');
  const [identitySource, setIdentitySource] = React.useState(() => _srcOf(identity));

  const pickedRole = allRoleOptions ? allRoleOptions.find(o => o.key === pickedCard) : null;
  const pickedName = pickedRole?.name || t('saves.identity.no_card_selected');
  // 选「本剧本 NPC」开局 = 你就是这个 NPC 本人 → 出身强制锁「本世界人」(native):
  // 穿越类出身(灵魂/整体/双魂)与「我就是原著这个角色」语义矛盾,这里直接锁死,
  // 非 native 卡片不可点(实际 native 的强制由 NewGameModal 的 effect 落地)。
  const npcLocked = pickedRole?.kind === 'script_card';

  const fetchAiRecs = React.useCallback(async () => {
    if (!scriptId) {
      setRecsErr(t('saves.identity.no_script'));
      return;
    }
    setRecsLoading(true); setRecsErr(""); setRecs([]);
    const args = {
      birthpoint_phase: birthpoint ? birthpoint.phase_label : "",
      birthpoint_label: birthpoint ? birthpoint.story_time_label : "",
      character_card_id: pickedRole ? (pickedRole.id || null) : null,
      character_card_kind: pickedRole ? pickedRole.kind : null,
      player_origin: playerOrigin,  // 'isekai' | 'native' — 给 LLM prompt 决定身份类型
      n: 4,
    };
    try {
      const r = await fetch(
        `${window.__API_BASE || ""}/api/scripts/${parseInt(scriptId, 10)}/recommend-identity`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(args),
        }
      );
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        // 502 (LLM 失败) / 500 (工具失败) / 403 (无权) 一律显示后端真实错误
        const msg = (data && data.error) || t('saves.identity.ai_req_fail', { status: r.status });
        setRecsErr(msg);
        return;
      }
      if (data && data.ok === false && data.error) {
        setRecsErr(data.error);
        return;
      }
      if (data && Array.isArray(data.recommendations) && data.recommendations.length > 0) {
        setRecs(data.recommendations);
      } else {
        setRecsErr(t('saves.identity.ai_empty'));
      }
    } catch (e) {
      setRecsErr(t('saves.identity.ai_net_err', { err: e.message || String(e) }));
    } finally {
      setRecsLoading(false);
    }
  }, [scriptId, birthpoint, pickedRole, playerOrigin]);

  const pickRec = (rec) => {
    setIdentity({
      name: rec.name || "",
      role: rec.role || "",
      background: rec.background || "",
      source: "ai",
      _from: "ai",
      player_origin: playerOrigin,  // 'isekai' | 'native' — GM 由此判断玩家定位
    });
  };

  const applyCustom = () => {
    const role = customRole.trim();
    const bg = customBg.trim();
    if (!role && !bg) return;
    setIdentity({
      name: customName.trim(),
      role,
      background: bg,
      source: "custom",
      _from: "custom",
      player_origin: playerOrigin,
    });
  };

  const clearIdentity = () => {
    setIdentity(null);
  };

  // 反馈#1:拉取该剧本的原著 NPC 角色卡,供「失忆身份」选择。
  React.useEffect(() => {
    if (!scriptId) { setNpcCards([]); return; }
    let alive = true;
    (async () => {
      try {
        const r = await window.api.cards.scriptList(parseInt(scriptId, 10));
        const list = (r && (r.items || r.cards)) || (Array.isArray(r) ? r : []);
        if (alive) setNpcCards(Array.isArray(list) ? list : []);
      } catch (_) { if (alive) setNpcCards([]); }
    })();
    return () => { alive = false; };
  }, [scriptId]);

  // 选一张 NPC 卡当失忆身份:把卡的姓名/定位/背景填进 identity,标记来源 npc_card,
  // 并默认「不知道身份卡」(失忆)——何时想起由游戏内玩家选择决定。与原 NPC 卡共存,不删除。
  const pickNpcIdentity = (card) => {
    if (!card) return;
    const nm = card.name || card.title || "";
    const role = card.identity || card.role || card.archetype || card.title || "";
    const bg = card.background || card.persona || card.summary || card.description || card.bio || "";
    setIdentity({
      name: nm,
      role,
      background: bg,
      source: "npc_card",
      _from: "npc_card",
      npc_card_id: card.id || card.slug || null,
      player_origin: playerOrigin,
    });
    setIdentityKnown(false);
  };

  // 身份卡来源随出身条件化(消除矛盾组合):
  //  灵魂穿越=占据某原住民肉身→全开;整体穿越=彻底外来者无本地身份→仅不挂;
  //  双魂同体=须有共体的原住民本体→不能不挂;本世界人=你就是该角色→不能再选另一个原著人物。
  const ALLOWED_SOURCES = {
    soul: ['none', 'npc', 'ai', 'manual'],
    body: ['none'],
    dual: ['npc', 'ai', 'manual'],
    native: ['none', 'ai', 'manual'],
  };
  const allowedSources = ALLOWED_SOURCES[playerOrigin] || ['none', 'npc', 'ai', 'manual'];

  // 切出身:若当前身份来源与新出身不兼容,重置到首个允许来源(并清掉已选身份);否则只同步标记。
  React.useEffect(() => {
    if (!allowedSources.includes(identitySource)) {
      clearIdentity();
      setIdentitySource(allowedSources[0]);
    } else if (identity && identity.player_origin !== playerOrigin) {
      setIdentity({ ...identity, player_origin: playerOrigin });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerOrigin]);

  // identity 从外部到位时(草稿恢复 / 选中)同步来源 tab;identity 为 null 时不重置,
  // 以免把"刚点了某来源 tab 但还没选具体身份"的状态打回 none。
  React.useEffect(() => {
    if (identity) setIdentitySource(_srcOf(identity));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity ? `${identity._from || ''}:${identity.npc_card_id || ''}:${identity.name || ''}` : null]);

  const noIdentity = !identity;
  // 暖色面板样式(与角色档 CardSheet 一致)
  const panel = {
    background: 'var(--panel-2, #282623)', border: '1px solid var(--line-soft, #2a2724)',
    borderRadius: 12, padding: '14px 16px',
  };
  const labelEyebrow = { fontSize: 11, letterSpacing: '.06em', color: 'var(--accent, #c96442)', fontWeight: 600, textTransform: 'uppercase' };

  const chooseSource = (sid) => { setIdentitySource(sid); if (sid === 'none') clearIdentity(); };
  const idPreview = identity ? (
    <div style={{
      ...panel, borderColor: 'var(--accent, #c96442)', background: 'var(--accent-soft, rgba(201,100,66,.12))',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
    }}>
      <div style={{ display: 'grid', gap: 4, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <CSBadge color={identity._from === 'ai' ? 'blue' : (identity._from === 'npc_card' ? 'red' : 'grey')}>{identity._from === 'ai' ? t('saves.identity.badge_ai') : (identity._from === 'npc_card' ? t('saves.identity.badge_npc') : t('saves.identity.badge_manual'))}</CSBadge>
          {identity.name && <strong style={{ fontFamily: "'Noto Serif', 'Noto Serif SC', serif", fontSize: 15, color: 'var(--text, #ebe7df)' }}>{identity.name}</strong>}
          {identity.role && <span style={{ fontSize: 13, color: 'var(--text-quiet, #c8c2b7)' }}>{identity.role}</span>}
        </div>
        {identity.background && <span style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--muted, #968f85)' }}>{identity.background}</span>}
      </div>
      <CSButton iconName="close" variant="inline-link" onClick={() => chooseSource('none')}>{t('saves.identity.btn_clear')}</CSButton>
    </div>
  ) : null;

  const originCard = ({ value, icon, labelKey, essenceKey, mappingKey, hintKey, accentColor, accentBg, accentBorder }) => {
    const selected = playerOrigin === value;
    // 选了本剧本 NPC → 锁定 native;其余出身禁用(不可点、变灰)。
    const locked = npcLocked && value !== 'native';
    return (
      <button key={value} type="button" role="radio" aria-checked={selected} disabled={locked}
        onClick={() => { if (!locked) setPlayerOrigin(value); }}
        title={locked ? t('saves.identity.origin_locked_npc', { defaultValue: '已选择扮演本剧本 NPC,出身锁定为「本世界人」' }) : undefined}
        style={{ textAlign: 'left', padding: '11px 13px', cursor: locked ? 'not-allowed' : 'pointer',
          opacity: locked ? 0.4 : 1,
          border: selected ? `1px solid ${accentBorder}` : '1px solid var(--line-soft, #2a2724)',
          borderRadius: 10, background: selected ? accentBg : 'var(--panel, #211f1d)',
          display: 'grid', gap: 6, transition: 'border-color .12s, background .12s', outline: 'none' }}
        onFocus={(e) => { e.currentTarget.style.outlineOffset = '2px'; e.currentTarget.style.outline = `1px solid ${accentBorder}`; }}
        onBlur={(e) => { e.currentTarget.style.outline = 'none'; }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18, lineHeight: 1, flexShrink: 0, color: selected ? accentColor : 'var(--muted-2, #6b655e)', transition: 'color .12s', fontFamily: 'var(--font-serif)' }}>{icon}</span>
          <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, fontWeight: 700, color: selected ? accentColor : 'var(--text, #ebe7df)', transition: 'color .12s', lineHeight: 1.2 }}>{t(`saves.identity.${labelKey}`)}</span>
        </div>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: selected ? accentColor : 'var(--muted, #968f85)', lineHeight: 1.3, transition: 'color .12s' }}>{t(`saves.identity.${essenceKey}`)}</span>
        <span style={{ fontSize: 11, color: 'var(--muted-2, #6b655e)', lineHeight: 1.5, letterSpacing: '0.01em' }}>{t(`saves.identity.${mappingKey}`)}</span>
        {selected && (<span style={{ fontSize: 11.5, color: 'var(--muted, #968f85)', lineHeight: 1.5, borderTop: `1px solid ${accentBorder}`, paddingTop: 6, marginTop: 2 }}>{t(`saves.identity.${hintKey}`)}</span>)}
      </button>
    );
  };
  const ORIGINS = [
    { value: 'soul', icon: '◈', labelKey: 'origin_soul_label', essenceKey: 'origin_soul_essence', mappingKey: 'origin_soul_mapping', hintKey: 'origin_soul_hint', accentColor: '#8db4e8', accentBg: 'rgba(85,130,200,.14)', accentBorder: 'rgba(85,130,200,.38)' },
    { value: 'body', icon: '◉', labelKey: 'origin_body_label', essenceKey: 'origin_body_essence', mappingKey: 'origin_body_mapping', hintKey: 'origin_body_hint', accentColor: '#e8a87c', accentBg: 'rgba(220,140,80,.14)', accentBorder: 'rgba(220,140,80,.38)' },
    { value: 'dual', icon: '◑', labelKey: 'origin_dual_label', essenceKey: 'origin_dual_essence', mappingKey: 'origin_dual_mapping', hintKey: 'origin_dual_hint', accentColor: '#b8a0e8', accentBg: 'rgba(160,130,210,.14)', accentBorder: 'rgba(160,130,210,.38)' },
    { value: 'native', icon: '◎', labelKey: 'origin_native_label', essenceKey: 'origin_native_essence', mappingKey: 'origin_native_mapping', hintKey: 'origin_native_hint', accentColor: '#b8b0a5', accentBg: 'rgba(150,143,133,.14)', accentBorder: 'rgba(150,143,133,.32)' },
  ];
  const cardBtnStyle = (sel) => ({
    textAlign: 'left', padding: '11px 13px', cursor: 'pointer',
    border: sel ? '1px solid var(--accent, #c96442)' : '1px solid var(--line-soft, #2a2724)',
    borderRadius: 10, background: sel ? 'var(--accent-soft, rgba(201,100,66,.12))' : 'var(--panel, #211f1d)',
    display: 'grid', gap: 5, transition: 'border-color .12s, background .12s',
  });

  return (
    <CSSpaceBetween size="m">
      {/* 说明 */}
      <CSBox key="intro" color="text-body-secondary" fontSize="body-s">
        {t('saves.identity.intro')}
      </CSBox>

      {/* ── 第 1 步:本体来源(你如何进入这个世界)── */}
      <div key="origin-selector" style={{ ...panel, display: 'grid', gap: 12 }}>
        <div style={{ display: 'grid', gap: 4 }}>
          <span style={{ ...labelEyebrow }}>{t('saves.identity.step1')} · {t('saves.identity.origin_section_label')}</span>
          <span style={{ fontSize: 12, color: 'var(--muted, #968f85)', lineHeight: 1.55 }}>{t('saves.identity.origin_section_hint')}</span>
        </div>
        {npcLocked && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 11px', borderRadius: 8,
            background: 'rgba(150,143,133,.14)', border: '1px solid rgba(150,143,133,.32)',
            fontSize: 12, color: 'var(--text-quiet, #c8c2b7)', lineHeight: 1.5 }}>
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 15, color: '#b8b0a5', flexShrink: 0 }}>◎</span>
            <span>{t('saves.identity.origin_locked_banner', { name: pickedName, defaultValue: `已选择扮演本剧本 NPC「${pickedName}」—— 出身锁定为「本世界人」(你就是这个角色本人,GM 严格守世界观)。` })}</span>
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }} role="radiogroup" aria-label={t('saves.identity.origin_section_label')}>
          {ORIGINS.map(originCard)}
        </div>
      </div>

      {/* ── 第 2 步:角色身份(可选)— 统一选择器:不挂 / 从原著 / AI / 手动 ── */}
      <div key="id-source" style={{ ...panel, display: 'grid', gap: 12 }}>
        <div style={{ display: 'grid', gap: 4 }}>
          <span style={{ ...labelEyebrow }}>{t('saves.identity.step2')} · {t('saves.identity.id_section_label')}</span>
          <span style={{ fontSize: 12, color: 'var(--muted, #968f85)', lineHeight: 1.55 }}>{t(`saves.identity.id_section_hint_${playerOrigin}`, { name: pickedName, defaultValue: t('saves.identity.id_section_hint', { name: pickedName }) })}</span>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }} role="radiogroup" aria-label={t('saves.identity.id_section_label')}>
          {[['none', 'src_none'], ['npc', 'src_npc'], ['ai', 'src_ai'], ['manual', 'src_manual']].filter(([sid]) => allowedSources.includes(sid)).map(([sid, lk]) => {
            const sel = identitySource === sid;
            return (
              <button key={sid} type="button" role="radio" aria-checked={sel} onClick={() => chooseSource(sid)}
                style={{ padding: '7px 14px', cursor: 'pointer', borderRadius: 8, fontSize: 13, fontWeight: 600,
                  border: sel ? '1px solid var(--accent, #c96442)' : '1px solid var(--line-soft, #2a2724)',
                  background: sel ? 'var(--accent-soft, rgba(201,100,66,.12))' : 'var(--panel, #211f1d)',
                  color: sel ? 'var(--accent, #c96442)' : 'var(--text, #ebe7df)', transition: 'all .12s' }}>
                {t(`saves.identity.${lk}`)}
              </button>
            );
          })}
        </div>
        {idPreview}

        {/* 从原著角色选身份 */}
        {identitySource === 'npc' && (npcCards.length > 0 ? (
          <CSColumnLayout columns={2}>
            {npcCards.map((card, i) => {
              const cid = card.id || card.slug || i;
              const isSel = identity && identity._from === 'npc_card' && String(identity.npc_card_id) === String(card.id || card.slug);
              const nm = card.name || card.title || '';
              const role = card.identity || card.role || card.archetype || '';
              const bg = card.background || card.persona || card.summary || card.description || card.bio || '';
              return (
                <button key={cid} type="button" onClick={() => pickNpcIdentity(card)} style={cardBtnStyle(isSel)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {nm && <strong style={{ fontFamily: "'Noto Serif', 'Noto Serif SC', serif", fontSize: 14, color: 'var(--text, #ebe7df)' }}>{nm}</strong>}
                    {role && <span style={{ whiteSpace: 'nowrap' }}><CSBadge>{role}</CSBadge></span>}
                    {isSel && (<span style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}><CSBadge color="green">✓ {t('saves.identity.badge_selected')}</CSBadge></span>)}
                  </div>
                  {bg && <span style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--muted, #968f85)', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{bg}</span>}
                </button>
              );
            })}
          </CSColumnLayout>
        ) : (
          <CSBox fontSize="body-s" color="text-status-inactive">{t('saves.identity.npc_empty')}</CSBox>
        ))}

        {/* AI 生成身份候选 */}
        {identitySource === 'ai' && (
          <CSSpaceBetween size="s">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: 'var(--muted, #968f85)', lineHeight: 1.55, flex: '1 1 200px' }}>{t(`saves.identity.ai_desc_${playerOrigin}`, t('saves.identity.ai_desc'))}</span>
              <CSButton iconName={recs.length > 0 ? 'refresh' : 'gen-ai'} loading={recsLoading} disabled={recsLoading} onClick={fetchAiRecs}>
                {recs.length > 0 ? t('saves.identity.btn_regen') : t('saves.identity.btn_gen')}
              </CSButton>
            </div>
            {recsErr && <CSAlert type="error">{recsErr}</CSAlert>}
            {recs.length > 0 && (
              <CSColumnLayout columns={2}>
                {recs.map((rec, i) => {
                  const isSelected = identity && identity._from === 'ai' && identity.name === rec.name && identity.role === rec.role;
                  return (
                    <button key={i} type="button" onClick={() => pickRec(rec)} style={cardBtnStyle(isSelected)}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        {rec.name && <strong style={{ fontFamily: "'Noto Serif', 'Noto Serif SC', serif", fontSize: 14, color: 'var(--text, #ebe7df)' }}>{rec.name}</strong>}
                        {rec.role && <span style={{ whiteSpace: 'nowrap' }}><CSBadge>{rec.role}</CSBadge></span>}
                        {isSelected && (<span style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}><CSBadge color="green">✓ {t('saves.identity.badge_selected')}</CSBadge></span>)}
                      </div>
                      {rec.background && <span style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--muted, #968f85)' }}>{rec.background}</span>}
                    </button>
                  );
                })}
              </CSColumnLayout>
            )}
          </CSSpaceBetween>
        )}

        {/* 手动创建 */}
        {identitySource === 'manual' && (
          <CSSpaceBetween size="l">
            <CSColumnLayout columns={2}>
              <CSFormField label={t('saves.identity.field_alias')} description={t('saves.identity.field_alias_desc')}>
                <CSInput value={customName} onChange={({ detail }) => setCustomName(detail.value)} placeholder={t('saves.identity.field_alias_placeholder')} />
              </CSFormField>
              <CSFormField label={t('saves.identity.field_role')} constraintText={t('saves.identity.field_role_constraint')}>
                <CSInput value={customRole} onChange={({ detail }) => setCustomRole(detail.value)} placeholder={t('saves.identity.field_role_placeholder')} />
              </CSFormField>
              <div style={{ gridColumn: '1 / -1' }}>
                <CSFormField label={t('saves.identity.field_bg')}>
                  <CSTextarea rows={3} value={customBg} onChange={({ detail }) => setCustomBg(detail.value)} placeholder={t('saves.identity.field_bg_placeholder')} />
                </CSFormField>
              </div>
            </CSColumnLayout>
            <div style={{ textAlign: 'right' }}>
              <CSButton variant="primary" iconName="check" onClick={applyCustom} disabled={!customRole.trim() && !customBg.trim()}>{t('saves.identity.btn_apply')}</CSButton>
            </div>
          </CSSpaceBetween>
        )}
      </div>

      {/* ── 第 3 步:开局是否知道这个身份(仅当挂了身份 且 本体≠纯肉穿)── */}
      {identity && playerOrigin !== 'body' && (
        <div key="known" style={{ ...panel, display: 'grid', gap: 10 }}>
          <div style={{ display: 'grid', gap: 4 }}>
            <span style={{ ...labelEyebrow }}>{t('saves.identity.step3')} · {t('saves.identity.identity_known_label')}</span>
            <span style={{ fontSize: 12, color: 'var(--muted, #968f85)', lineHeight: 1.55 }}>{t('saves.identity.identity_known_hint')}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }} role="radiogroup" aria-label={t('saves.identity.identity_known_label')}>
            {[
              { val: true, labelKey: 'identity_known_true_label', descKey: 'identity_known_true_desc' },
              { val: false, labelKey: 'identity_known_false_label', descKey: 'identity_known_false_desc' },
            ].map(({ val, labelKey, descKey }) => {
              const sel = identityKnown === val;
              return (
                <button key={String(val)} type="button" role="radio" aria-checked={sel} onClick={() => setIdentityKnown(val)}
                  style={{ flex: '1 1 0', textAlign: 'left', padding: '9px 12px', cursor: 'pointer',
                    border: sel ? '1px solid var(--accent-edge, rgba(201,100,66,.42))' : '1px solid var(--line-soft, #2a2724)',
                    borderRadius: 8, background: sel ? 'var(--accent-soft, rgba(201,100,66,.12))' : 'var(--panel, #211f1d)',
                    display: 'grid', gap: 3, transition: 'border-color .12s, background .12s', outline: 'none' }}
                  onFocus={(e) => { e.currentTarget.style.outline = '1px solid var(--accent-edge)'; e.currentTarget.style.outlineOffset = '2px'; }}
                  onBlur={(e) => { e.currentTarget.style.outline = 'none'; }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: sel ? 'var(--accent, #c96442)' : 'var(--text, #ebe7df)', transition: 'color .12s' }}>{t(`saves.identity.${labelKey}`)}</span>
                  <span style={{ fontSize: 11.5, color: 'var(--muted, #968f85)', lineHeight: 1.5 }}>{t(`saves.identity.${descKey}`)}</span>
                </button>
              );
            })}
          </div>
          {identity._from === 'npc_card' && (
            <CSBox fontSize="body-s" color="text-body-secondary">{t('saves.identity.npc_known_hint')}</CSBox>
          )}
        </div>
      )}
      {identity && playerOrigin === 'body' && (
        <CSBox key="known-na" fontSize="body-s" color="text-status-inactive">{t('saves.identity.known_na_body')}</CSBox>
      )}
    </CSSpaceBetween>
  );
}

export { IdentityStep };
