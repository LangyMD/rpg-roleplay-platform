import React from 'react';
import i18n from '../i18n/index.js';

export class ErrorBoundary extends React.Component {
  state = { hasError: false, error: null, errorInfo: null };
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    // 也写到 window.console.error,后续可以接入 backend log endpoint
    console.error('[ErrorBoundary]', error, errorInfo);
    // 可选:fetch('/api/client-error', {method: 'POST', body: JSON.stringify({...})})
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{padding: 40, maxWidth: 600, margin: '40px auto', fontFamily: 'system-ui'}}>
          <h1 style={{color: 'var(--accent)'}}>{i18n.t('error_boundary.title')}</h1>
          <p>{i18n.t('error_boundary.desc')} <a href="mailto:security@stellatrix.icu">security@stellatrix.icu</a>{i18n.t('error_boundary.desc_end')}</p>
          <details style={{marginTop: 20, opacity: 0.6}}>
            <summary>{i18n.t('error_boundary.details')}</summary>
            <pre style={{whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12}}>
{String(this.state.error)}
{this.state.errorInfo?.componentStack}
            </pre>
          </details>
          <button onClick={() => location.reload()} style={{marginTop: 16, padding: '8px 16px'}}>{i18n.t('error_boundary.reload')}</button>
        </div>
      );
    }
    return this.props.children;
  }
}
