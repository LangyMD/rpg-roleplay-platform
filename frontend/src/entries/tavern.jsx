// Tavern 页面入口 — Vite ESM 版(镜像 entries/game-console.jsx)
import '../web-vitals-rum.js';
import '../fonts.js';
import React from 'react';
import * as ReactDOM from 'react-dom/client';

// 基础设施 side-effect 模块(与 game-console 一致)
import '../mock-data.js';
import '../api-client.js';
import '../runtime-telemetry.js';
import '../data-loader.js';
import '../state-event-bridge.js';
import '../worldbook-status-toast.js';
import '../ui-atlas.js';
import '../a11y-tooltip-labels.js';
import '../i18n/index.js';
import { lsGet, lsSet } from '../lib/storage.js';

// 反馈抽屉 / 复用的 CardSheet / CardEditFields 都用 Cloudscape 组件,
// 这里加载同一套暖色暗主题(与 game-console 完全一致)。
import '@cloudscape-design/global-styles/index.css';
import '../media.css';
import { installWarmTheme } from '../cloudscape-theme.js';
installWarmTheme();

import { ErrorBoundary } from '../components/ErrorBoundary.jsx';
import { FeedbackDrawerRoot } from '../components/FeedbackDrawer.jsx';
import GlobalTaskFloater from '../components/GlobalTaskFloater.jsx';
import TavernApp from '../tavern-app.jsx';

// density preset + narrative font init(等价 game-console 入口里的非 babel inline script)
(function () {
  const VALID_DENSITY = { compact: 1, default: 1, spacious: 1 };
  function _applyDensity(d) {
    if (!VALID_DENSITY[d]) d = 'default';
    document.documentElement.setAttribute('data-density', d);
    lsSet('rpg.density', d);
    window.dispatchEvent(new CustomEvent('rpg-density-change', { detail: d }));
  }
  const storedDensity = lsGet('rpg.density') || 'default';
  _applyDensity(storedDensity);
  window.RPG_setDensity = _applyDensity;

  const FONT_MAP = { serif: 'var(--font-serif)', sans: 'var(--font-sans)', mono: 'var(--font-mono)' };
  const storedFont = lsGet('rpg.narrativeFont') || 'serif';
  if (FONT_MAP[storedFont]) {
    document.documentElement.style.setProperty('--narrative-font', FONT_MAP[storedFont]);
  }
})();

const __mount = () => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <ErrorBoundary>
      <TavernApp />
      {/* 反馈抽屉根节点 — 监听 window.__openFeedback 全局事件 */}
      <FeedbackDrawerRoot />
      {/* 全局后台任务浮窗(导入 / 重建 / 生图,有活跃任务才显示) */}
      <GlobalTaskFloater />
    </ErrorBoundary>
  );
  // 通知 HTML splash 淡出 + 移除节点
  try {
    document.body.classList.add('rpg-mounted');
    setTimeout(() => {
      const sp = document.getElementById('rpg-game-splash');
      if (sp && sp.parentNode) sp.parentNode.removeChild(sp);
    }, 300);
  } catch (_) {}
};

const __gateThenMount = (info) => {
  const offline = new URLSearchParams(location.search).has('offline');
  if (info && info.online && !info.authed && !offline) {
    const next = encodeURIComponent(location.pathname + location.search + location.hash);
    location.replace('Login.html?next=' + next);
    return;
  }
  __mount();
};

if (window.RPG_DATA_READY) {
  window.RPG_DATA_READY.then(__gateThenMount);
} else {
  __mount();
}
