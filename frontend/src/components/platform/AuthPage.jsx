// 内联登录 / 注册页 AuthPage。纯机械从 platform-app.jsx 搬出,零行为变化。
import React from 'react';
import { useState as useStatePL } from 'react';
import { Icon } from '../../game-icons.jsx';
import i18n from '../../i18n/index.js';

/* ---------------------------- AUTH ----------------------------- */
function AuthPage() {
  const [mode, setMode] = useStatePL("login");
  const [username, setUsername] = useStatePL("");
  const [password, setPassword] = useStatePL("");
  const [displayName, setDisplayName] = useStatePL("");
  const [busy, setBusy] = useStatePL(false);
  const [err, setErr] = useStatePL("");
  // Login/AuthPage 上没有 PlatformShell 注入的 window.__apiToast，需要内联反馈
  // 字段来承接「忘记密码」等次要交互的提示，不能依赖可能不存在的全局 toast。
  const [notice, setNotice] = useStatePL("");

  // 登录后跳哪里：优先 ?next=...（来自 Platform/Game Console 的鉴权 gate），
  // 严格只允许同源相对路径，防止开放重定向（?next=https://evil.com）。
  const __nextOrDefault = () => {
    try {
      const raw = new URLSearchParams(location.search).get("next") || "";
      if (!raw) return "Platform.html";
      // 拒绝包含控制字符的输入
      if (/[\r\n\0]/.test(raw)) return "Platform.html";
      // 严格验证：解析后必须同源，才允许跳转
      const u = new URL(raw, location.href);
      if (u.origin !== location.origin) return "Platform.html";
      return u.pathname + u.search + u.hash;
    } catch (_) { return "Platform.html"; }
  };

  // If already logged in → 跳目标页（next 或 Platform）
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await window.api?.auth.me();
        if (!cancelled && me && me.user) {
          location.replace(__nextOrDefault());
        }
      } catch (_) { /* not logged in, stay */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setErr("");
    if (!username.trim() || !password.trim()) {
      setErr(i18n.t('auth_page.need_credentials'));
      return;
    }
    setBusy(true);
    try {
      if (mode === "register") {
        await window.api.auth.register({
          username: username.trim(),
          password,
          display_name: displayName.trim() || undefined,
        });
      } else {
        await window.api.auth.login({ username: username.trim(), password });
      }
      window.__apiToast?.(mode === "register" ? i18n.t('auth_page.register_ok') : i18n.t('auth_page.login_ok'), { kind: "ok", duration: 1400 });
      location.replace(__nextOrDefault());
    } catch (e) {
      setErr(e?.message || i18n.t('auth_page.request_failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pl-auth-wrap">
      <div className="pl-auth">
        <div style={{display: "flex", alignItems: "center", gap: 12}}>
          <div className="pl-auth-mark"><Icon name="logo" size={16} /></div>
          <div>
            <h1>RPG Roleplay</h1>
            <div className="pl-auth-sub">{i18n.t('auth_page.subtitle')}</div>
          </div>
        </div>
        <div className="pl-auth-tabs">
          <button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>{i18n.t('auth_page.login')}</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>{i18n.t('auth_page.register')}</button>
        </div>
        <form className="pl-auth-form" onSubmit={submit}>
          <div className="pl-field">
            <label>{i18n.t('auth_page.username')}</label>
            <input autoComplete="username" placeholder={i18n.t('auth_page.username_ph')}
              value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="pl-field">
            <label>{i18n.t('auth_page.password')}</label>
            <input type="password" autoComplete={mode === "register" ? "new-password" : "current-password"}
              placeholder={i18n.t('auth_page.password_ph')}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {mode === "register" && (
            <div className="pl-field">
              <label>{i18n.t('auth_page.display_name')}</label>
              <input placeholder={i18n.t('auth_page.display_name_ph')}
                value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
          )}
          {err && (
            <div className="pl-auth-error" style={{color: "var(--danger,#c0392b)", fontSize: 12.5, padding: "4px 0"}}>
              {err}
            </div>
          )}
          {notice && (
            <div className="pl-auth-notice" role="status" aria-live="polite"
              style={{color: "var(--muted, #6b7280)", fontSize: 12.5, padding: "4px 0",
                      borderLeft: "2px solid var(--accent, #b65b41)", paddingLeft: 8}}>
              {notice}
            </div>
          )}
          <button type="submit" className="btn primary" disabled={busy}
            style={{justifyContent: "center", height: 34, opacity: busy ? 0.7 : 1}}>
            {busy ? i18n.t('auth_page.submitting') : (mode === "login" ? i18n.t('auth_page.login') : i18n.t('auth_page.create_account'))}
          </button>
          <div className="pl-auth-foot">
            <span>{i18n.t('auth_page.first_admin')}</span>
            <a href="#"
              onClick={(e) => {
                e.preventDefault();
                // 主反馈：内联 notice（Login 页没有 PlatformShell 注入的 toast，
                // 之前直接 optional-chain 全局 toast，匿名用户点了完全没反应）
                setNotice(i18n.t('auth_page.forgot_notice'));
                // 次要：如果恰好在 PlatformShell 里也跑了一遍 AuthPage，全局 toast 也带上
                window.__apiToast?.(i18n.t('auth_page.forgot_toast'), { kind: "info", duration: 2400 });
              }}
              style={{borderBottom: 0}}>{i18n.t('auth_page.forgot')}</a>
          </div>
        </form>
      </div>
    </div>
  );
}

export { AuthPage };
