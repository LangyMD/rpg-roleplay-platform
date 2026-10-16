// SchemaField.jsx — mechanically split from login-app.jsx (JSX byte-for-byte).
import React from 'react';
import { useTranslation } from 'react-i18next';
import { isZhUi } from '../../i18n/index.js';

/// 渲染单个表单字段。`field` 形如:
///   { key, label, type, required, autocomplete, placeholder, min_length, max_length }
/// 当 type === 'boolean' 时渲染为 checkbox。
function SchemaField({ field, value, onChange }) {
  const { t } = useTranslation();
  if (field.type === 'boolean') {
    // 为 terms_accepted 字段注入带链接的 label;其余 boolean 字段用纯文本
    // 法律文档正本托管在 landing 站(play.stellatrix.icu/legal/),软件内不复制以避免双权威。
    // landing 的 legal/ 已发布 v1.2 双语 6 篇:privacy/terms/acceptable-use/cookie/dmca/adult-content-disclaimer
    const _legalBase = 'https://play.stellatrix.icu/legal';
    const _legalLang = isZhUi() ? 'zh-CN' : 'en';
    const labelNode = field.key === 'terms_accepted' ? (
      <span>
        {t('auth.terms_agree')}{' '}
        <a href={`${_legalBase}/terms-of-service.${_legalLang}.html`} target="_blank" rel="noopener noreferrer"
           style={{color: 'var(--accent)'}}>{t('auth.terms_of_service')}</a>
        {t('auth.app.legal_sep')}
        <a href={`${_legalBase}/privacy-policy.${_legalLang}.html`} target="_blank" rel="noopener noreferrer"
           style={{color: 'var(--accent)'}}>{t('auth.privacy_policy')}</a>
        {t('auth.app.legal_sep')}
        <a href={`${_legalBase}/acceptable-use-policy.${_legalLang}.html`} target="_blank" rel="noopener noreferrer"
           style={{color: 'var(--accent)'}}>{t('auth.acceptable_use')}</a>
        {' '}{t('auth.terms_and')}{' '}
        <a href={`${_legalBase}/adult-content-disclaimer.${_legalLang}.html`} target="_blank" rel="noopener noreferrer"
           style={{color: 'var(--accent)'}}>{t('auth.adult_disclaimer')}</a>
        {field.required && <span className="pl-field-req">*</span>}
      </span>
    ) : (
      <span>{field.label}{field.required && <span className="pl-field-req">*</span>}</span>
    );
    return (
      <div className="pl-field" style={{flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginTop: 6}}>
        <input
          id={field.key}
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(e.target.checked)}
          style={{marginTop: 3, flexShrink: 0, accentColor: 'var(--accent)'}}
        />
        <label htmlFor={field.key} style={{fontWeight: 'normal', cursor: 'pointer', fontSize: 13}}>
          {labelNode}
        </label>
      </div>
    );
  }
  return (
    <div className="pl-field">
      <label htmlFor={field.key}>
        {field.label}
        {field.required && <span className="pl-field-req">*</span>}
      </label>
      <input
        id={field.key}
        type={field.type || 'text'}
        autoComplete={field.autocomplete || undefined}
        placeholder={field.placeholder || undefined}
        minLength={field.min_length || undefined}
        maxLength={field.max_length || undefined}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export { SchemaField };
