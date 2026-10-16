/**
 * AdultSplash.jsx — AGE-02 首次访问 / 版本升级后强制 18+ 确认弹窗
 *
 * Props:
 *   splashVersion  string   当前 splash 版本常量，需与后端 SPLASH_CURRENT_VERSION 一致
 *   onAcked        () => void  ack 成功后的回调，父组件撤销覆盖层
 */
import React, { useState, useEffect, useRef, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { isZhUi } from '../i18n/index.js';

const LEGAL_BASE = 'https://play.stellatrix.icu/legal/adult-content-disclaimer';

function getLang() {
  return isZhUi() ? 'zh-CN' : 'en';
}

export default function AdultSplash({ splashVersion, onAcked }) {
  const { t } = useTranslation();
  const lang = getLang();
  const legalUrl = `${LEGAL_BASE}.${lang}.html`;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const confirmBtnRef = useRef(null);
  const titleId = useId();

  // Move focus to primary action on mount.
  useEffect(() => {
    if (confirmBtnRef.current) confirmBtnRef.current.focus();
  }, []);

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/api/me/splash/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ splash_version: splashVersion }),
        credentials: 'same-origin',
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${resp.status}`);
      }
      onAcked && onAcked();
    } catch (e) {
      setError(e.message || t('adult_splash.network_error'));
      setLoading(false);
    }
  };

  const handleLeave = () => {
    try { window.location.replace('about:blank'); } catch (_) { window.close(); }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(10, 8, 6, 0.92)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
      }}
    >
      <div
        style={{
          width: 'min(480px, 94vw)',
          background: 'var(--panel, #211f1d)',
          border: '1px solid var(--line, #3a3330)',
          borderRadius: '10px',
          padding: '32px 28px 28px',
          boxShadow: '0 8px 40px rgba(0,0,0,0.7)',
          color: 'var(--text, #e6ddd5)',
        }}
      >
        {/* Title */}
        <h2
          id={titleId}
          style={{
            fontFamily: 'var(--font-serif, Georgia, serif)',
            fontSize: 17,
            fontWeight: 600,
            marginBottom: 16,
            lineHeight: 1.4,
            letterSpacing: '0.02em',
          }}
        >
          {t('adult_splash.title')}
        </h2>

        {/* Body */}
        <p style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--text-quiet, #b0a89e)', marginBottom: 16 }}>
          {t('adult_splash.body')}
        </p>

        {/* Legal link */}
        <p style={{ marginBottom: 24 }}>
          <a
            href={legalUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13, color: 'var(--accent, #d4a45e)', textDecoration: 'underline' }}
          >
            {t('adult_splash.legal_link')}
          </a>
        </p>

        {/* Error */}
        {error && (
          <p style={{ fontSize: 12, color: 'var(--danger, #e07070)', marginBottom: 12 }}>
            {error}
          </p>
        )}

        {/* Buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <button
            ref={confirmBtnRef}
            onClick={handleConfirm}
            disabled={loading}
            style={{
              padding: '11px 20px',
              borderRadius: 6,
              border: '1px solid var(--accent, #d4a45e)',
              background: 'var(--accent, #d4a45e)',
              color: '#1a1510',
              fontSize: 14,
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
              transition: 'opacity 0.15s',
            }}
          >
            {loading ? t('adult_splash.loading') : t('adult_splash.confirm')}
          </button>
          <button
            onClick={handleLeave}
            disabled={loading}
            style={{
              padding: '10px 20px',
              borderRadius: 6,
              border: '1px solid var(--line, #3a3330)',
              background: 'transparent',
              color: 'var(--muted, #888)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            {t('adult_splash.leave')}
          </button>
        </div>
      </div>
    </div>
  );
}
