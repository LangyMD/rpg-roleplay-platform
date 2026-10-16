// 部署设置区(DeploySection)。纯机械搬出,零行为变化。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import { SetGroup, SetRow, SetSelect } from './shared.jsx';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSInput from '@cloudscape-design/components/input';
import CSButton from '@cloudscape-design/components/button';
import CSToggle from '@cloudscape-design/components/toggle';
import CSAlert from '@cloudscape-design/components/alert';

function DeploySection() {
  const { t } = useTranslation();
  // 部署配置通过 POST /api/admin/deployment-config 存 app_config 表。
  // 监听地址 / CORS 等网络级配置需要重启才能生效，UI 有明确提示。
  const timerRef = React.useRef(null);
  const pendingRef = React.useRef({});
  const saveDeployConfig = React.useCallback((patch) => {
    Object.assign(pendingRef.current, patch);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      const batch = pendingRef.current;
      pendingRef.current = {};
      try {
        await window.api.admin.saveDeploymentConfig(batch);
        window.toast?.(t('settings.deploy.save_ok'), { kind: "ok", duration: 2000 });
      } catch (e) {
        window.toast?.(t('settings.deploy.save_fail'), { kind: "danger", detail: e?.message || "", duration: 3000 });
      }
    }, 300);
  }, []);

  const [listenAddr, setListenAddr] = useStatePL("127.0.0.1:7860");
  const [corsOrigins, setCorsOrigins] = useStatePL("http://127.0.0.1:5173,http://localhost:3000");
  const [uploadLimit, setUploadLimit] = useStatePL("12 MB");
  const [uploadLimitError, setUploadLimitError] = useStatePL("");
  const [smtpEnabled, setSmtpEnabled] = useStatePL(false);
  const [smtpHost, setSmtpHost] = useStatePL("smtp.example.com");
  const [smtpPort, setSmtpPort] = useStatePL("587");
  const [smtpTls, setSmtpTls] = useStatePL("starttls");
  const [smtpUser, setSmtpUser] = useStatePL("noreply@example.com");
  const [smtpPass, setSmtpPass] = useStatePL("");
  const [smtpFromName, setSmtpFromName] = useStatePL("RPG Roleplay");
  const [smtpFromEmail, setSmtpFromEmail] = useStatePL("noreply@rpgroleplay.app");
  const [smtpTesting, setSmtpTesting] = useStatePL(false);
  // task 49：原"最近测试：12 分钟前"是硬编码。改成本地状态：只有用户实际
  // 点过"发送测试邮件"按钮后才记录时间戳并显示，否则显示"尚未测试"。
  const [smtpLastTestAt, setSmtpLastTestAt] = useStatePL(null);
  const [smtpLastTestOk, setSmtpLastTestOk] = useStatePL(null);
  const [captchaProvider, setCaptchaProvider] = useStatePL("off");
  // task 56：之前 6 个 captcha 子选项是 dead button（recaptcha 版本 3 个 +
  // turnstile widget 模式 3 个，没 onClick），UI 看着能切实际只是装饰。
  const [recaptchaVer, setRecaptchaVer] = useStatePL("v3");
  const [recaptchaSiteKey, setRecaptchaSiteKey] = useStatePL("");
  const [recaptchaSecretKey, setRecaptchaSecretKey] = useStatePL("");
  const [recaptchaScore, setRecaptchaScore] = useStatePL(0.5);
  const [turnstileMode, setTurnstileMode] = useStatePL("non_interactive");
  const [turnstileSiteKey, setTurnstileSiteKey] = useStatePL("");
  const [turnstileSecretKey, setTurnstileSecretKey] = useStatePL("");
  const [hcaptchaSiteKey, setHcaptchaSiteKey] = useStatePL("");
  const [hcaptchaSecretKey, setHcaptchaSecretKey] = useStatePL("");
  // S2: CAPTCHA 触发位置多选，默认注册/找回密码/登录重试已选中
  const [captchaTriggers, setCaptchaTriggers] = useStatePL(["register", "password_reset", "login_retry"]);

  // 从 backend 拉取已保存的部署配置
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.admin.deploymentConfig();
        if (cancelled) return;
        const c = (r && r.config) || {};
        if (c.listen_address) setListenAddr(c.listen_address);
        if (c.cors_origins) setCorsOrigins(c.cors_origins);
        if (c.upload_limit) setUploadLimit(c.upload_limit);
        if (c.smtp_enabled !== undefined) setSmtpEnabled(!!c.smtp_enabled);
        if (c.smtp_host) setSmtpHost(c.smtp_host);
        if (c.smtp_port) setSmtpPort(String(c.smtp_port));
        if (c.smtp_tls) setSmtpTls(c.smtp_tls);
        if (c.smtp_user) setSmtpUser(c.smtp_user);
        // smtp_pass not pre-filled for security
        if (c.smtp_from_name) setSmtpFromName(c.smtp_from_name);
        if (c.smtp_from_email) setSmtpFromEmail(c.smtp_from_email);
        if (c.captcha_provider) setCaptchaProvider(c.captcha_provider);
        if (c.recaptcha_ver) setRecaptchaVer(c.recaptcha_ver);
        if (c.recaptcha_site_key) setRecaptchaSiteKey(c.recaptcha_site_key);
        if (c.recaptcha_score !== undefined) setRecaptchaScore(Number(c.recaptcha_score));
        if (c.turnstile_mode) setTurnstileMode(c.turnstile_mode);
        if (c.turnstile_site_key) setTurnstileSiteKey(c.turnstile_site_key);
        if (c.hcaptcha_site_key) setHcaptchaSiteKey(c.hcaptcha_site_key);
        if (Array.isArray(c.captcha_triggers)) setCaptchaTriggers(c.captcha_triggers);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <SetGroup title={t('settings.deploy.title')}>
      <CSAlert type="warning">
        <strong>{t('settings.deploy.warning')}</strong>
      </CSAlert>
      <SetRow label={t('settings.deploy.listen_addr')} description={t('settings.deploy.listen_addr_desc')}>
        <CSInput value={listenAddr} onChange={({ detail }) => { setListenAddr(detail.value); saveDeployConfig({ listen_address: detail.value }); }} />
      </SetRow>
      <SetRow label={t('settings.deploy.cors')} description={t('settings.deploy.cors_desc')}>
        <CSInput value={corsOrigins} onChange={({ detail }) => { setCorsOrigins(detail.value); saveDeployConfig({ cors_origins: detail.value }); }} />
      </SetRow>
      <SetRow label={t('settings.deploy.upload_limit')} description={t('settings.deploy.upload_limit_desc')}>
        <div>
          <CSInput
            value={uploadLimit}
            invalid={!!uploadLimitError}
            onChange={({ detail }) => {
              const v = detail.value.trim();
              setUploadLimit(detail.value);
              if (!v || /^\d+\s*(MB|GB|KB|B)?$/i.test(v)) {
                setUploadLimitError("");
                if (v) saveDeployConfig({ upload_limit: v });
              } else {
                setUploadLimitError(t('settings.deploy.upload_limit_error'));
              }
            }}
            placeholder="12MB"
          />
          {uploadLimitError && (
            <div style={{color: "var(--danger)", fontSize: 11.5, marginTop: 4}}>{uploadLimitError}</div>
          )}
        </div>
      </SetRow>

      <SetRow label={t('settings.deploy.smtp')} description={t('settings.deploy.smtp_desc')}>
        <CSToggle checked={smtpEnabled} onChange={({ detail }) => { setSmtpEnabled(detail.checked); saveDeployConfig({ smtp_enabled: detail.checked }); }}>
          {smtpEnabled ? t('settings.deploy.smtp_on') : t('settings.deploy.smtp_off')}
        </CSToggle>
      </SetRow>
      {smtpEnabled && (
        <>
          <SetRow label={t('settings.deploy.smtp_preset')} description={t('settings.deploy.smtp_preset_desc')}>
            <SetSelect
              value="custom"
              options={[
                { value: "custom",   label: t('settings.deploy.smtp_custom') },
                { value: "gmail",    label: "Gmail (smtp.gmail.com:587 · STARTTLS)" },
                { value: "qq",       label: t('settings.more.deploy.smtp_qq') },
                { value: "163",      label: t('settings.more.deploy.smtp_163') },
                { value: "aws",      label: "AWS SES (email-smtp.us-east-1.amazonaws.com:587)" },
                { value: "resend",   label: "Resend (smtp.resend.com:587)" },
                { value: "sendgrid", label: "SendGrid (smtp.sendgrid.net:587)" },
              ]}
              onChange={(val) => {
                const PRESETS = {
                  gmail:    { smtp_host: "smtp.gmail.com",                          smtp_port: "587", smtp_tls: "starttls" },
                  qq:       { smtp_host: "smtp.qq.com",                             smtp_port: "465", smtp_tls: "ssl" },
                  "163":    { smtp_host: "smtp.163.com",                            smtp_port: "465", smtp_tls: "ssl" },
                  aws:      { smtp_host: "email-smtp.us-east-1.amazonaws.com",      smtp_port: "587", smtp_tls: "starttls" },
                  resend:   { smtp_host: "smtp.resend.com",                         smtp_port: "587", smtp_tls: "starttls" },
                  sendgrid: { smtp_host: "smtp.sendgrid.net",                       smtp_port: "587", smtp_tls: "starttls" },
                };
                const p = PRESETS[val];
                if (p) { setSmtpHost(p.smtp_host); setSmtpPort(p.smtp_port); setSmtpTls(p.smtp_tls); saveDeployConfig(p); }
              }}
            />
          </SetRow>
          <SetRow label={t('settings.deploy.smtp_host_port')} description={t('settings.deploy.smtp_host_port_desc')}>
            <div style={{display: "grid", gridTemplateColumns: "1fr 90px 110px", gap: 6}}>
              <CSInput value={smtpHost} placeholder={t('settings.deploy.smtp_host_placeholder')} onChange={({ detail }) => { setSmtpHost(detail.value); saveDeployConfig({ smtp_host: detail.value }); }} />
              <CSInput value={smtpPort} placeholder={t('settings.deploy.smtp_port_placeholder')} onChange={({ detail }) => { setSmtpPort(detail.value); saveDeployConfig({ smtp_port: detail.value }); }} />
              <SetSelect
                value={smtpTls}
                options={[
                  { value: "none",     label: t('settings.deploy.smtp_tls_none') },
                  { value: "starttls", label: "STARTTLS" },
                  { value: "ssl",      label: "SSL / TLS" },
                ]}
                onChange={(val) => { setSmtpTls(val); saveDeployConfig({ smtp_tls: val }); }}
              />
            </div>
          </SetRow>
          <SetRow label={t('settings.deploy.smtp_auth')} description={t('settings.deploy.smtp_auth_desc')}>
            <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6}}>
              <CSInput value={smtpUser} placeholder={t('settings.deploy.smtp_user_placeholder')} onChange={({ detail }) => { setSmtpUser(detail.value); saveDeployConfig({ smtp_user: detail.value }); }} />
              <CSInput type="password" value={smtpPass} placeholder={t('settings.deploy.smtp_pass_placeholder')} onChange={({ detail }) => { setSmtpPass(detail.value); saveDeployConfig({ smtp_pass: detail.value }); }} />
            </div>
          </SetRow>
          <SetRow label={t('settings.deploy.smtp_from')} description={t('settings.deploy.smtp_from_desc')}>
            <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6}}>
              <CSInput value={smtpFromName} placeholder={t('settings.deploy.smtp_from_name_placeholder')} onChange={({ detail }) => { setSmtpFromName(detail.value); saveDeployConfig({ smtp_from_name: detail.value }); }} />
              <CSInput value={smtpFromEmail} placeholder={t('settings.deploy.smtp_from_email_placeholder')} onChange={({ detail }) => { setSmtpFromEmail(detail.value); saveDeployConfig({ smtp_from_email: detail.value }); }} />
            </div>
          </SetRow>
          <SetRow label={t('settings.deploy.smtp_test')} description={t('settings.deploy.smtp_test_desc')}>
            <CSSpaceBetween direction="horizontal" size="s">
              <CSButton variant="normal" disabled={smtpTesting} onClick={async () => {
                setSmtpTesting(true);
                window.toast?.(t('settings.deploy.smtp_testing_toast'), { kind: "info", duration: 1200 });
                let ok = false;
                try {
                  const r = await window.api.admin.saveDeploymentConfig({});
                  void r;
                  const smtpTestResp = await window.api.raw?.POST("/api/v1/admin/smtp/test", {});
                  ok = !!(smtpTestResp && smtpTestResp.ok !== false);
                } catch (_) { ok = false; }
                setSmtpTesting(false);
                setSmtpLastTestAt(new Date().toISOString());
                setSmtpLastTestOk(ok);
                window.toast?.(ok ? t('settings.deploy.smtp_test_ok') : t('settings.deploy.smtp_test_fail'), { kind: ok ? "ok" : "danger", duration: 3000 });
              }}>
                {smtpTesting ? t('settings.deploy.smtp_testing') : t('settings.deploy.smtp_test_btn')}
              </CSButton>
              <span className="muted-2" style={{fontSize: 11}}>
                {smtpLastTestAt
                  ? (smtpLastTestOk ? t('settings.deploy.smtp_last_ok', { time: window.__fmt?.ago(smtpLastTestAt) || smtpLastTestAt }) : t('settings.deploy.smtp_last_fail', { time: window.__fmt?.ago(smtpLastTestAt) || smtpLastTestAt }))
                  : t('settings.deploy.smtp_not_tested')}
              </span>
            </CSSpaceBetween>
          </SetRow>
        </>
      )}

      <SetRow label={t('settings.deploy.captcha')} description={t('settings.deploy.captcha_desc')}>
        <CSSpaceBetween direction="horizontal" size="xs">
          <CSButton variant={captchaProvider === "off" ? "primary" : "normal"} onClick={() => { setCaptchaProvider("off"); saveDeployConfig({ captcha_provider: "off" }); }}>{t('settings.deploy.captcha_off')}</CSButton>
          <CSButton variant={captchaProvider === "recaptcha" ? "primary" : "normal"} onClick={() => { setCaptchaProvider("recaptcha"); saveDeployConfig({ captcha_provider: "recaptcha" }); }}>Google reCAPTCHA</CSButton>
          <CSButton variant={captchaProvider === "turnstile" ? "primary" : "normal"} onClick={() => { setCaptchaProvider("turnstile"); saveDeployConfig({ captcha_provider: "turnstile" }); }}>Cloudflare Turnstile</CSButton>
          <CSButton variant={captchaProvider === "hcaptcha" ? "primary" : "normal"} onClick={() => { setCaptchaProvider("hcaptcha"); saveDeployConfig({ captcha_provider: "hcaptcha" }); }}>hCaptcha</CSButton>
        </CSSpaceBetween>
      </SetRow>
      {captchaProvider === "recaptcha" && (
        <>
          <SetRow label={t('settings.deploy.captcha_recaptcha_ver')} description={t('settings.deploy.captcha_recaptcha_ver_desc')}>
            <CSSpaceBetween direction="horizontal" size="xs">
              <CSButton variant={recaptchaVer === "v3" ? "primary" : "normal"} onClick={() => { setRecaptchaVer("v3"); saveDeployConfig({ recaptcha_ver: "v3" }); }}>{t('settings.deploy.captcha_recaptcha_v3')}</CSButton>
              <CSButton variant={recaptchaVer === "v2c" ? "primary" : "normal"} onClick={() => { setRecaptchaVer("v2c"); saveDeployConfig({ recaptcha_ver: "v2c" }); }}>{t('settings.deploy.captcha_recaptcha_v2c')}</CSButton>
              <CSButton variant={recaptchaVer === "v2i" ? "primary" : "normal"} onClick={() => { setRecaptchaVer("v2i"); saveDeployConfig({ recaptcha_ver: "v2i" }); }}>{t('settings.deploy.captcha_recaptcha_v2i')}</CSButton>
            </CSSpaceBetween>
          </SetRow>
          <SetRow label="Site Key" description={t('settings.deploy.captcha_site_key_desc')}>
            <CSInput value={recaptchaSiteKey} placeholder="6L···Y9" onChange={({ detail }) => { setRecaptchaSiteKey(detail.value); saveDeployConfig({ recaptcha_site_key: detail.value }); }} />
          </SetRow>
          <SetRow label="Secret Key" description={t('settings.deploy.captcha_secret_key_desc')}>
            <CSInput type="password" value={recaptchaSecretKey} placeholder="6L···Z3" onChange={({ detail }) => { setRecaptchaSecretKey(detail.value); saveDeployConfig({ recaptcha_secret_key: detail.value }); }} />
          </SetRow>
          <SetRow label={t('settings.deploy.captcha_score')} description={t('settings.deploy.captcha_score_desc')}>
            <CSInput type="number" value={String(recaptchaScore)}
              onChange={({ detail }) => { setRecaptchaScore(Number(detail.value)); saveDeployConfig({ recaptcha_score: Number(detail.value) }); }} />
          </SetRow>
        </>
      )}
      {captchaProvider === "turnstile" && (
        <>
          <SetRow label="Site Key" description={t('settings.deploy.captcha_turnstile_site_desc')}>
            <CSInput value={turnstileSiteKey} placeholder="0x4A···AAAA" onChange={({ detail }) => { setTurnstileSiteKey(detail.value); saveDeployConfig({ turnstile_site_key: detail.value }); }} />
          </SetRow>
          <SetRow label="Secret Key" description={t('settings.deploy.captcha_turnstile_secret_desc')}>
            <CSInput type="password" value={turnstileSecretKey} placeholder="0x4A···AAAA" onChange={({ detail }) => { setTurnstileSecretKey(detail.value); saveDeployConfig({ turnstile_secret_key: detail.value }); }} />
          </SetRow>
          <SetRow label={t('settings.deploy.captcha_widget_mode')} description={t('settings.deploy.captcha_widget_desc')}>
            <CSSpaceBetween direction="horizontal" size="xs">
              <CSButton variant={turnstileMode === "non_interactive" ? "primary" : "normal"} onClick={() => { setTurnstileMode("non_interactive"); saveDeployConfig({ turnstile_mode: "non_interactive" }); }}>{t('settings.deploy.captcha_non_interactive')}</CSButton>
              <CSButton variant={turnstileMode === "interactive" ? "primary" : "normal"} onClick={() => { setTurnstileMode("interactive"); saveDeployConfig({ turnstile_mode: "interactive" }); }}>{t('settings.deploy.captcha_interactive')}</CSButton>
              <CSButton variant={turnstileMode === "invisible" ? "primary" : "normal"} onClick={() => { setTurnstileMode("invisible"); saveDeployConfig({ turnstile_mode: "invisible" }); }}>{t('settings.deploy.captcha_invisible')}</CSButton>
            </CSSpaceBetween>
          </SetRow>
        </>
      )}
      {captchaProvider === "hcaptcha" && (
        <>
          <SetRow label="Site Key">
            <CSInput value={hcaptchaSiteKey} placeholder="xxxxxxxx-xxxx-xxxx" onChange={({ detail }) => { setHcaptchaSiteKey(detail.value); saveDeployConfig({ hcaptcha_site_key: detail.value }); }} />
          </SetRow>
          <SetRow label="Secret Key">
            <CSInput type="password" value={hcaptchaSecretKey} placeholder="0x···" onChange={({ detail }) => { setHcaptchaSecretKey(detail.value); saveDeployConfig({ hcaptcha_secret_key: detail.value }); }} />
          </SetRow>
        </>
      )}
      {captchaProvider !== "off" && (
        <SetRow label={t('settings.deploy.captcha_triggers')} description={t('settings.deploy.captcha_triggers_desc')}>
          <CSSpaceBetween direction="horizontal" size="xs">
            {[
              { key: "register",       label: t('settings.deploy.trigger_register') },
              { key: "password_reset", label: t('settings.deploy.trigger_password_reset') },
              { key: "login_retry",    label: t('settings.deploy.trigger_login_retry') },
              { key: "every_login",    label: t('settings.deploy.trigger_every_login') },
              { key: "api_key_create", label: t('settings.deploy.trigger_api_key_create') },
            ].map(({ key, label }) => {
              const active = captchaTriggers.includes(key);
              return (
                <CSButton key={key} variant={active ? "primary" : "normal"} onClick={() => {
                  const next = active
                    ? captchaTriggers.filter(t => t !== key)
                    : [...captchaTriggers, key];
                  setCaptchaTriggers(next);
                  saveDeployConfig({ captcha_triggers: next });
                }}>{label}</CSButton>
              );
            })}
          </CSSpaceBetween>
        </SetRow>
      )}
    </SetGroup>
  );
}

export {
  DeploySection,
};
