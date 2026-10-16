/* 个人中心 · 编辑资料(头像 / 基本资料 / 联系方式 / 本地化)。
   从 components/platform/me-pages.jsx 二次拆出,零行为变化。 */
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import { plNavigate } from '../../router.js';
import AvatarImg from '../AvatarImg.jsx';
import MediaStudio from '../MediaStudio.jsx';
import { _FORM_KEYS, ConfirmModal, publishUser, useReactiveUser, Field } from './shared.jsx';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSInput from '@cloudscape-design/components/input';
import CSSelect from '@cloudscape-design/components/select';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSTextarea from '@cloudscape-design/components/textarea';

function MeEditProfile() {
  const { t } = useTranslation();
  // task 45：改读 reactive user（publishUser 写到 __USER_STATE，登录后是真用户）
  const user = useReactiveUser();
  const [form, setForm] = useStatePL({
    display_name: user.display_name || "",
    username: user.username || "",
    email: user._raw?.email || "",
    phone: user._raw?.phone || "",
    real_name: user._raw?.real_name || "",
    gender: user._raw?.gender || "unspecified",
    birthday: user._raw?.birthday || "",
    location: user._raw?.location || "",
    website: user._raw?.website || "",
    bio: user.bio || "",
    pronouns: user._raw?.pronouns || "",
    language: user._raw?.language || "en",
    timezone: user._raw?.timezone || "UTC",
  });
  // task 57: 表单输入标记 dirty,保存/重置后清掉。
  const u = (k, v) => {
    setForm(f => ({ ...f, [k]: v }));
    try { window.__capMarkDirty && window.__capMarkDirty("settings.profile"); } catch (_) {}
  };
  const [uploadOpen, setUploadOpen] = useStatePL(false);
  const [resetAvatarOpen, setResetAvatarOpen] = useStatePL(false);
  const [saving, setSaving] = useStatePL(false);
  const avatarInputRef = React.useRef(null);
  const [mediaStudioOpen, setMediaStudioOpen] = useStatePL(false);
  const [avatarUrl, setAvatarUrl] = useStatePL(user.avatar_url || user._raw?.avatar_url || null);

  // 从 /api/me/profile 拉真实资料(后端合并了 profile_extras:邮箱/手机/真名/性别/
  // 生日/所在地/网站/代词/语言/时区)。只取表单已知字段,避免把 stats 等无关键污染进 form。
  // _FORM_KEYS 已提升到模块顶层
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await window.api.account.profile();
        if (cancelled) return;
        const src = (p && (p.profile || p.user)) || p || {};
        const picked = {};
        for (const k of _FORM_KEYS) if (src[k] != null) picked[k] = src[k];
        if (Object.keys(picked).length) setForm(f => ({ ...f, ...picked }));
      } catch (e) {
        if (!cancelled) window.__apiToast?.(t('platform.me.edit.load_failed'), { kind: "danger", detail: e?.message, duration: 3000 });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // [round-4-P2] reactive user 可能在 mount 之后才就绪;form 的 useStatePL 初值只取一次,
  //   会把 display_name/username/email/bio 锁成 mount 时的空值。这里在 user 就绪后【仅填空字段】,
  //   不覆盖用户已输入或上面 profile() 已合并的值(用 `f.x || user.x` 幂等回填)。
  useEffectPL(() => {
    setForm(f => ({
      ...f,
      display_name: f.display_name || user.display_name || "",
      username: f.username || user.username || "",
      email: f.email || user._raw?.email || "",
      bio: f.bio || user.bio || "",
    }));
    const _av = user.avatar_url || user._raw?.avatar_url;
    if (_av && !avatarUrl) setAvatarUrl(_av);
  }, [user.id, user.username, user.display_name]);

  const onSave = async () => {
    setSaving(true);
    try {
      await window.api.account.saveProfile(form);
      try { window.__capClearDirty && window.__capClearDirty("settings.profile"); } catch (_) {}
      // task 13: 拉一次权威源（/api/auth/me），用回包的 user 字段更新全局并广播事件，
      // 让 PlatformShell 左侧栏立即同步。失败也兜底先按本地 form 写一次（视觉上立即看到改动）。
      try {
        const me = await window.api?.auth?.me?.();
        if (me && me.user) {
          publishUser({
            id: me.user.id,
            username: me.user.username,
            display_name: me.user.display_name || form.display_name,
            role: me.user.role,
            bio: me.user.bio ?? form.bio,
          });
        } else {
          publishUser({ ...form });
        }
      } catch (_) {
        publishUser({ ...form });
      }
      window.__apiToast?.(t('platform.me.edit.saved', '已保存资料'), { kind: "ok", duration: 1600 });
    } catch (e) {
      window.__apiToast?.(t('platform.me.edit.save_failed', '保存失败'), { kind: "danger", detail: e?.message, duration: 3000 });
    } finally {
      setSaving(false);
    }
  };

  const onAvatarPick = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      window.__apiToast?.(t('platform.me.edit.file_too_large', '文件过大'), { kind: "danger", detail: t('platform.me.edit.max_size', '最大 2 MB') });
      return;
    }
    try {
      const res = await window.api.account.avatar(file);
      window.__apiToast?.(t('platform.me.edit.avatar_updated', '头像已更新'), { kind: "ok" });
      if (res && res.avatar_url) {
        // 更新本地 state（AvatarImg 响应式）
        setAvatarUrl(res.avatar_url + '?t=' + Date.now());
        // bust page-level avatar cache（保留兼容老代码）
        document.querySelectorAll(".pl-me-avatar.large, .pl-user-avatar").forEach(el => {
          el.style.backgroundImage = `url(${res.avatar_url}?t=${Date.now()})`;
        });
      }
      setUploadOpen(false);
    } catch (e) {
      window.__apiToast?.(t('platform.me.edit.upload_failed', '上传失败'), { kind: "danger", detail: e?.message });
    }
  };

  const onResetAvatar = async () => {
    try {
      await window.api.account.avatarReset();
      window.__apiToast?.(t('platform.me.edit.avatar_reset', '已恢复默认头像'), { kind: "ok" });
      setResetAvatarOpen(false);
    } catch (e) {
      window.__apiToast?.(t('platform.me.edit.op_failed', '操作失败'), { kind: "danger", detail: e?.message });
    }
  };

  return (
    <CSSpaceBetween size="l">
      {/* 头像 */}
      <CSContainer header={<CSHeader variant="h2">{t('platform.me.edit.section_avatar', '头像')}</CSHeader>}>
        <CSSpaceBetween size="m">
          {mediaStudioOpen && (
            <MediaStudio
              open={mediaStudioOpen}
              onClose={() => setMediaStudioOpen(false)}
              target={{ type: 'user_avatar' }}
              name={form.display_name || user.display_name || t('platform.me.edit.default_user', '用户')}
              defaultPrompt={form.display_name ? `${form.display_name} ${t('platform.me.edit.avatar_prompt_suffix', '的用户头像')}` : t('platform.me.edit.avatar_prompt_default', '用户头像')}
              onApplied={(url) => {
                setAvatarUrl(url + '?t=' + Date.now());
                setMediaStudioOpen(false);
              }}
            />
          )}
          <div className="pl-me-avatar-row">
            <AvatarImg
              src={avatarUrl}
              name={form.display_name || user.display_name || '?'}
              size={null}
              shape="circle"
              className="pl-me-avatar large"
            />
            <div className="pl-me-avatar-actions">
              <CSBox color="text-body-secondary" fontSize="body-s">{t('platform.me.edit.avatar_hint', '支持 PNG / JPG / WEBP，建议 512×512。最大 2 MB。')}</CSBox>
              <CSSpaceBetween direction="horizontal" size="xs">
                <CSButton iconName="gen-ai" onClick={() => setMediaStudioOpen(true)}>✦ {t('platform.me.edit.change_avatar', '更换头像')}</CSButton>
                <CSButton iconName="remove" onClick={() => setResetAvatarOpen(true)}>{t('platform.me.edit.use_default', '使用默认')}</CSButton>
              </CSSpaceBetween>
            </div>
          </div>
        </CSSpaceBetween>
      </CSContainer>

      {/* 基本资料 */}
      <CSContainer header={<CSHeader variant="h2">{t('platform.me.edit.section_basic', '基本资料')}</CSHeader>} data-cap-anchor="settings.profile">
        <CSSpaceBetween size="l">
          <div className="pl-form-grid-2">
            <Field label={t('platform.me.edit.field_display_name', '显示名')} hint={t('platform.me.edit.field_display_name_hint', '出现在游戏和评论里')}>
              <CSInput value={form.display_name} onChange={({ detail }) => u("display_name", detail.value)} />
            </Field>
            <Field label={t('platform.me.edit.field_pronouns', '代词')}>
              <CSSelect
                selectedOption={[{value:"她/她",label:t('platform.me.edit.pronoun_she')},{value:"他/他",label:t('platform.me.edit.pronoun_he')},{value:"TA/TA",label:"TA/TA"},{value:"不公开",label:t('platform.me.edit.pronouns_private','不公开')}].find(o => o.value === form.pronouns) || null}
                options={[{value:"她/她",label:t('platform.me.edit.pronoun_she')},{value:"他/他",label:t('platform.me.edit.pronoun_he')},{value:"TA/TA",label:"TA/TA"},{value:"不公开",label:t('platform.me.edit.pronouns_private','不公开')}]}
                onChange={({ detail }) => u("pronouns", detail.selectedOption.value)}
              />
            </Field>
            <Field label={t('platform.me.edit.field_username', '用户名')} hint={t('platform.me.edit.field_username_hint', '登录用，6 个月可改一次')} required>
              <CSInput value={form.username} onChange={({ detail }) => u("username", detail.value)} />
            </Field>
            <Field label={t('platform.me.edit.field_real_name', '真实姓名')} hint={t('platform.me.edit.field_real_name_hint', '仅自己可见')}>
              <CSInput value={form.real_name} onChange={({ detail }) => u("real_name", detail.value)} />
            </Field>
            <Field label={t('platform.me.edit.field_gender', '性别')}>
              <CSSpaceBetween direction="horizontal" size="xs">
                {[{v: "female", l: t('platform.me.edit.gender_female','女')}, {v: "male", l: t('platform.me.edit.gender_male','男')}, {v: "other", l: t('platform.me.edit.gender_other','其他')}, {v: "unspecified", l: t('platform.me.edit.gender_private','不公开')}].map(o => (
                  <CSButton key={o.v} variant={form.gender === o.v ? "primary" : "normal"} onClick={() => u("gender", o.v)}>{o.l}</CSButton>
                ))}
              </CSSpaceBetween>
            </Field>
            <Field label={t('platform.me.edit.field_birthday', '生日')}>
              <CSInput type="date" value={form.birthday} onChange={({ detail }) => u("birthday", detail.value)} />
            </Field>
            <Field label={t('platform.me.edit.field_location', '所在地')}>
              <CSInput value={form.location} onChange={({ detail }) => u("location", detail.value)} placeholder={t('platform.me.edit.field_location_ph', '例：上海')} />
            </Field>
            <Field label={t('platform.me.edit.field_website', '个人网站')}>
              <CSInput value={form.website} onChange={({ detail }) => u("website", detail.value)} placeholder="https://..." />
            </Field>
          </div>
          <Field label={t('platform.me.edit.field_bio', '简介')} hint={t('platform.me.edit.field_bio_hint', '280 字以内')}>
            <CSTextarea
              rows={3}
              value={form.bio}
              onChange={({ detail }) => u("bio", detail.value)}
            />
            <CSBox color="text-body-secondary" fontSize="body-s" textAlign="right">{form.bio.length} / 280</CSBox>
          </Field>
        </CSSpaceBetween>
      </CSContainer>

      {/* 联系方式 */}
      <CSContainer header={<CSHeader variant="h2">{t('platform.me.edit.section_contact', '联系方式')}</CSHeader>}>
        <div className="pl-form-grid-2">
          <Field label={t('platform.me.edit.field_email', '邮箱')} hint={t('platform.me.edit.field_email_hint', '用于通知与找回密码')}>
            <CSInput value={form.email} onChange={({ detail }) => u("email", detail.value)} placeholder="you@example.com" />
          </Field>
          <Field label={t('platform.me.edit.field_phone', '手机')} hint={t('platform.me.edit.field_phone_hint', '选填，仅自己可见')}>
            <CSInput value={form.phone} onChange={({ detail }) => u("phone", detail.value)} placeholder={t('platform.me.edit.field_optional', '选填')} />
          </Field>
        </div>
      </CSContainer>

      {/* 本地化 */}
      <CSContainer header={<CSHeader variant="h2">{t('platform.me.edit.section_locale', '本地化')}</CSHeader>}>
        <div className="pl-form-grid-2">
          <Field label={t('platform.me.edit.field_language', '界面语言')}>
            <CSSelect
              selectedOption={[{value:"zh-CN",label:"简体中文"},{value:"zh-TW",label:"繁體中文"},{value:"en",label:"English"},{value:"ja",label:"日本語"}].find(o => o.value === form.language) || null}
              options={[{value:"zh-CN",label:"简体中文"},{value:"zh-TW",label:"繁體中文"},{value:"en",label:"English"},{value:"ja",label:"日本語"}]}
              onChange={({ detail }) => u("language", detail.selectedOption.value)}
            />
          </Field>
          <Field label={t('platform.me.edit.field_timezone', '时区')}>
            <CSSelect
              selectedOption={[{value:"Asia/Shanghai",label:t('platform.me.edit.tz_shanghai')},{value:"Asia/Tokyo",label:t('platform.me.edit.tz_tokyo')},{value:"UTC",label:"UTC"},{value:"America/Los_Angeles",label:t('platform.me.edit.tz_la')}].find(o => o.value === form.timezone) || null}
              options={[{value:"Asia/Shanghai",label:t('platform.me.edit.tz_shanghai')},{value:"Asia/Tokyo",label:t('platform.me.edit.tz_tokyo')},{value:"UTC",label:"UTC"},{value:"America/Los_Angeles",label:t('platform.me.edit.tz_la')}]}
              onChange={({ detail }) => u("timezone", detail.selectedOption.value)}
            />
          </Field>
        </div>
      </CSContainer>

      {/* 保存按钮行 */}
      <CSSpaceBetween direction="horizontal" size="xs">
        <CSButton onClick={() => plNavigate('me')}>{t('common.cancel')}</CSButton>
        <CSButton variant="primary" onClick={onSave} loading={saving}>
          {saving ? t('platform.me.edit.saving', '保存中…') : t('platform.me.edit.save_btn', '保存资料')}
        </CSButton>
      </CSSpaceBetween>

      <input ref={avatarInputRef} type="file" accept="image/png,image/jpeg,image/webp"
        style={{display: "none"}} onChange={(e) => onAvatarPick(e.target.files?.[0])} />
      <ConfirmModal
        open={uploadOpen}
        title={t('platform.me.edit.upload_title', '上传新头像')}
        body={<>{t('platform.me.edit.avatar_hint', '支持 PNG / JPG / WEBP，建议 512×512。最大 2 MB。')}</>}
        confirmLabel={t('platform.me.edit.choose_file', '选择文件')}
        onClose={() => setUploadOpen(false)}
        onConfirm={() => { avatarInputRef.current?.click(); setUploadOpen(false); }}
      />
      <ConfirmModal
        open={resetAvatarOpen}
        title={t('platform.me.edit.reset_avatar_title', '恢复为默认头像？')}
        body={<>{t('platform.me.edit.reset_avatar_body', '将删除当前头像，使用由显示名首字生成的占位头像。')}</>}
        confirmLabel={t('platform.me.edit.reset_avatar_confirm', '恢复默认')}
        onClose={() => setResetAvatarOpen(false)} onConfirm={onResetAvatar}
      />
    </CSSpaceBetween>
  );
}

export { MeEditProfile };
