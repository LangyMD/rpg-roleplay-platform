// Login 页入口 — Vite ESM 版
import '../web-vitals-rum.js';
import '../fonts.js';
import * as React from 'react';
import * as ReactDOM from 'react-dom/client';

import '../api-client.js';
import '../a11y-tooltip-labels.js';   // data-tip → aria-label 镜像(屏幕阅读器)
import '../i18n/index.js';
import { LoginApp } from '../login-app.jsx';
import { ErrorBoundary } from '../components/ErrorBoundary.jsx';

const __mount = () => {
  const root = document.getElementById('root');
  if (!root) return;
  // 登录页是全站网关:组件崩溃必须降级到错误 UI(可刷新),否则白屏 = 用户被锁在门外。
  // 与 platform/game-console 入口一致。
  ReactDOM.createRoot(root).render(
    <ErrorBoundary>
      <LoginApp />
    </ErrorBoundary>
  );
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', __mount, { once: true });
} else {
  __mount();
}
