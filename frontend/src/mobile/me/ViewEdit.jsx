/* MobileMe · VIEW 编辑资料 Edit —— 从 pages/MobileMe.jsx 拆出,逐字节不变。 */
import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { publishUser } from '../../platform-app.jsx';
import AvatarImg from '../../components/AvatarImg.jsx';
import { PageHead, ActionBtn, Input, Select } from './shared.jsx';

/* ═══════════════════════════════════════════════════════════════════
   VIEW: 编辑资料 Edit
   ═══════════════════════════════════════════════════════════════════ */
function ViewEdit({ nav, user }) {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    display_name: user.display_name || '',
    username: user.username || '',
    email: user._raw?.email || '',
    phone: user._raw?.phone || '',
    real_name: user._raw?.real_name || '',
    gender: user._raw?.gender || 'unspecified',
    birthday: user._raw?.birthday || '',
    location: user._raw?.location || '',
    website: user._raw?.website || '',
    bio: user.bio || '',
    pronouns: user._raw?.pronouns || '',
    language: user._raw?.language || 'en',
    timezone: user._raw?.timezone || 'UTC',
  });
  const [saving, setSaving] = useState(false);
  // 头像预览 URL：先用当前 user，上传成功后刷新
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || user._raw?.avatar_url || null);
  const avatarRef = useRef(null);
  const u = (k, v) => setForm(f => ({ ...f, [k]: v }));

  // 从后端拉真实资料
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await window.api.account.profile();
        if (cancelled) return;
        const src = (p && (p.profile || p.user)) || p || {};
        const keys = ['display_name', 'username', 'email', 'phone', 'real_name', 'gender', 'birthday', 'location', 'website', 'bio', 'pronouns', 'language', 'timezone'];
        const picked = {};
        for (const k of keys) if (src[k] != null) picked[k] = src[k];
        if (Object.keys(picked).length) setForm(f => ({ ...f, ...picked }));
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  const onSave = async () => {
    setSaving(true);
    try {
      await window.api.account.saveProfile(form);
      try {
        const me = await window.api?.auth?.me?.();
        if (me && me.user) {
          publishUser({ id: me.user.id, username: me.user.username, display_name: me.user.display_name || form.display_name, role: me.user.role, bio: me.user.bio ?? form.bio });
        } else {
          publishUser({ ...form });
        }
      } catch (_) { publishUser({ ...form }); }
      nav.toast(t('mobile.me.edit.save_success'), 'ok', 'check');
      nav.go('me');
    } catch (e) {
      nav.toast(t('mobile.me.edit.save_error', { msg: e?.message || '' }), 'danger', 'warn');
    } finally { setSaving(false); }
  };

  const onAvatarFile = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { nav.toast(t('mobile.me.edit.avatar_too_large'), 'danger', 'warn'); return; }
    try {
      // 乐观预览：用 object URL 即时显示选中的图片
      const previewUrl = URL.createObjectURL(file);
      setAvatarUrl(previewUrl);
      const r = await window.api.account.avatar(file);
      // 上传完成后用后端返回的正式 URL 替换（若有）
      const serverUrl = r?.avatar_url || r?.url || null;
      if (serverUrl) setAvatarUrl(serverUrl);
      nav.toast(t('mobile.me.edit.avatar_updated'), 'ok', 'check');
    } catch (e) {
      // 上传失败：还原到原始头像
      setAvatarUrl(user.avatar_url || user._raw?.avatar_url || null);
      nav.toast(t('mobile.me.edit.upload_failed'), 'danger', 'warn');
    }
  };

  const onResetAvatar = async () => {
    try {
      await window.api.account.avatarReset();
      setAvatarUrl(null);
      nav.toast(t('mobile.me.edit.avatar_reset'), 'ok', 'check');
    } catch (e) { nav.toast(t('mobile.me.op_failed'), 'danger', 'warn'); }
  };

  return (
    <>
      <PageHead title={t('mobile.me.edit.title')} onBack={() => nav.go('me')} />
      <div className="pl-body tabbed">
        <div className="pl-pad">

          {/* 头像 */}
          <div className="pl-sec">
            <div className="pl-sec-head"><h2>{t('mobile.me.edit.avatar_section')}</h2></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '8px 0 12px' }}>
              <AvatarImg
                src={avatarUrl}
                name={form.display_name || user.display_name || user.username}
                size={64}
                shape="rounded"
                className="mc-me-avatar-edit"
              />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <ActionBtn label={t('mobile.me.edit.upload_avatar')} icon="upload" onClick={() => avatarRef.current?.click()} />
                <ActionBtn label={t('mobile.me.edit.reset_avatar')} icon="user" onClick={onResetAvatar} />
                <div style={{ fontSize: 11, color: 'var(--muted)' }}>{t('mobile.me.edit.avatar_hint')}</div>
              </div>
            </div>
            <input ref={avatarRef} type="file" accept="image/png,image/jpeg,image/webp"
              style={{ display: 'none' }} onChange={e => onAvatarFile(e.target.files?.[0])} />
          </div>

          {/* 基本资料 */}
          <div className="pl-sec">
            <div className="pl-sec-head"><h2>{t('mobile.me.edit.basic_section')}</h2></div>
            <Input label={t('mobile.me.edit.field_display_name')} hint={t('mobile.me.edit.field_display_name_hint')} value={form.display_name} onChange={v => u('display_name', v)} />
            <Input label={t('mobile.me.edit.field_username')} hint={t('mobile.me.edit.field_username_hint')} value={form.username} onChange={v => u('username', v)} />
            <Input label={t('mobile.me.edit.field_real_name')} hint={t('mobile.me.edit.field_real_name_hint')} value={form.real_name} onChange={v => u('real_name', v)} />
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>{t('mobile.me.edit.field_gender')}</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {[{ v: 'female', l: t('mobile.me.edit.gender_female') }, { v: 'male', l: t('mobile.me.edit.gender_male') }, { v: 'other', l: t('mobile.me.edit.gender_other') }, { v: 'unspecified', l: t('mobile.me.edit.gender_unspecified') }].map(o => (
                  <button key={o.v} onClick={() => u('gender', o.v)} style={{
                    height: 34, padding: '0 16px', borderRadius: 999, fontSize: 13,
                    background: form.gender === o.v ? 'var(--accent)' : 'var(--panel)',
                    color: form.gender === o.v ? '#fff8f3' : 'var(--text-quiet)',
                    border: '1px solid ' + (form.gender === o.v ? 'var(--accent-2)' : 'var(--line-soft)'),
                  }}>{o.l}</button>
                ))}
              </div>
            </div>
            <Select label={t('mobile.me.edit.field_pronouns')} value={form.pronouns || t('mobile.me.edit.gender_unspecified')}
              onChange={v => u('pronouns', v)}
              options={[{ value: '她/她', label: t('mobile.me.edit.pronoun_she') }, { value: '他/他', label: t('mobile.me.edit.pronoun_he') }, { value: 'TA/TA', label: 'TA/TA' }, { value: '不公开', label: t('mobile.me.edit.gender_unspecified') }]} />
            <Input label={t('mobile.me.edit.field_birthday')} type="date" value={form.birthday} onChange={v => u('birthday', v)} />
            <Input label={t('mobile.me.edit.field_location')} placeholder={t('mobile.me.edit.field_location_placeholder')} value={form.location} onChange={v => u('location', v)} />
            <Input label={t('mobile.me.edit.field_website')} placeholder="https://..." value={form.website} onChange={v => u('website', v)} />
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 5 }}>{t('mobile.me.edit.field_bio')} <span style={{ float: 'right', color: 'var(--muted-2)' }}>{form.bio.length}/280</span></div>
              <textarea
                value={form.bio} onChange={e => u('bio', e.target.value)} rows={4}
                placeholder={t('mobile.me.edit.field_bio_placeholder')}
                style={{
                  width: '100%', background: 'var(--panel)', border: '1px solid var(--line)',
                  borderRadius: 10, color: 'var(--text)', fontSize: 16, padding: '10px 12px',
                  outline: 'none', fontFamily: 'var(--font-sans)', resize: 'vertical', boxSizing: 'border-box',
                }}
              />
            </div>
          </div>

          {/* 联系方式 */}
          <div className="pl-sec">
            <div className="pl-sec-head"><h2>{t('mobile.me.edit.contact_section')}</h2></div>
            <Input label={t('mobile.me.edit.field_email')} hint={t('mobile.me.edit.field_email_hint')} type="email" value={form.email} onChange={v => u('email', v)} placeholder="you@example.com" />
            <Input label={t('mobile.me.edit.field_phone')} hint={t('mobile.me.edit.field_phone_hint')} type="tel" value={form.phone} onChange={v => u('phone', v)} placeholder={t('mobile.me.edit.optional')} />
          </div>

          {/* 本地化 */}
          <div className="pl-sec">
            <div className="pl-sec-head"><h2>{t('mobile.me.edit.locale_section')}</h2></div>
            <Select label={t('mobile.me.edit.field_language')} value={form.language} onChange={v => u('language', v)}
              options={[{ value: 'zh-CN', label: '简体中文' }, { value: 'zh-TW', label: '繁體中文' }, { value: 'en', label: 'English' }, { value: 'ja', label: '日本語' }]} />
            <Select label={t('mobile.me.edit.field_timezone')} value={form.timezone} onChange={v => u('timezone', v)}
              options={[{ value: 'Asia/Shanghai', label: 'UTC+8 · Shanghai' }, { value: 'Asia/Tokyo', label: 'UTC+9 · Tokyo' }, { value: 'UTC', label: 'UTC' }, { value: 'America/Los_Angeles', label: 'UTC-8 · Los Angeles' }]} />
          </div>

          {/* 保存 */}
          <div style={{ display: 'flex', gap: 10, padding: '8px 0 32px' }}>
            <button onClick={() => nav.go('me')} style={{ flex: 1, height: 46, borderRadius: 12, fontSize: 14, background: 'var(--panel-2)', border: '1px solid var(--line)', color: 'var(--text-quiet)' }}>{t('common.cancel')}</button>
            <button onClick={onSave} disabled={saving} style={{ flex: 2, height: 46, borderRadius: 12, fontSize: 14, fontWeight: 600, background: 'var(--accent)', border: 'none', color: '#fff8f3', opacity: saving ? 0.7 : 1 }}>
              {saving ? t('mobile.me.edit.saving') : t('mobile.me.edit.save_btn')}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

export { ViewEdit };
