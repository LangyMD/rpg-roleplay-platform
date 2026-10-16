/* toast.jsx — 全局瞬时 toast 收口(pl-toast-stack 版)。
 *
 * 此前 platform-app.jsx(__toastListeners/emitToast/window.toast/useToasts/ToastStack)
 * 与 game-app.jsx(IIFE 装 window.toast/__apiToast + window.__gameToastSubscribe + GameToastStack)
 * 各自手抄一份几乎相同的 pl-toast-stack pub/sub + 渲染。本模块把那段【逐字】提炼为一个工厂 ——
 * 行为零变化(关键:两宿主仍是各自独立总线,publish 侧契约逐字保留):
 *
 *   createToastChannel({ name, setWindowToast, guardWindowToast, setApiToast }) →
 *     { install, ToastStack, subscribe, fire }
 *
 *   · install()      幂等装一次(按 name 去重):
 *       - setWindowToast       → 装 window.toast(契约 {kind,icon,detail,duration,action} 不变)。
 *       - guardWindowToast     → 仅当 window.toast 未是函数时才装(承接 game-app「不覆盖 Platform」)。
 *       - setApiToast          → window.__apiToast = 本总线 fire(承接 game-app;Platform 侧不设,
 *                                以保持 __apiToast 在桌面外壳历来走 game 总线、不可见 的原行为)。
 *   · <ToastStack/>  pl-toast-stack 渲染(createPortal 到 body),订阅【本】总线;duration>0 自动消失。
 *
 * 为何不合一份总线:Platform 桌面外壳只挂自己的 <ToastStack/>。若把 __apiToast 也指向同一总线,
 * Platform 那 60 处历来不可见的 __apiToast 调用会在桌面突然可见 = 行为变化。故保持两条独立总线,
 * 只共用 pub/sub 机制 + 渲染组件。
 *
 * ⚠ 移动端 MobileRoot 的 fireToast(msg,kind,icon) 是另一套 UI 契约(单元素 .toast.show,定位参数,
 *    110+ nav.toast 调用方,独立 mobile.css),与本 pl-toast-stack 不同源,不并入。
 */
import React from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './game-icons.jsx';
import i18n from './i18n/index.js';

const __channels = (typeof window !== 'undefined')
  ? (window.__rpgToastChannels || (window.__rpgToastChannels = {}))
  : {};

export function createToastChannel(opts = {}) {
  const {
    name = 'default',
    setWindowToast = false,
    guardWindowToast = false,
    setApiToast = false,
  } = opts;

  // 同名总线跨入口/跨模块复用一份(幂等)。
  let chan = __channels[name];
  if (!chan) {
    const listeners = [];
    let nextId = 0;
    const fire = (message, o = {}) => {
      const t = {
        id: ++nextId,
        kind: o.kind || 'ok',        // ok | info | warn | danger
        icon: o.icon,
        message,
        detail: o.detail || null,
        duration: o.duration ?? 2400,
        action: o.action,
      };
      listeners.forEach((fn) => fn(t));
      return t.id;
    };
    const subscribe = (fn) => {
      listeners.push(fn);
      return () => {
        const i = listeners.indexOf(fn);
        if (i >= 0) listeners.splice(i, 1);
      };
    };
    chan = { listeners, fire, subscribe, installed: false };
    __channels[name] = chan;
  }

  function install() {
    if (typeof window === 'undefined' || chan.installed) return;
    chan.installed = true;
    if (setWindowToast) {
      if (guardWindowToast) {
        if (typeof window.toast !== 'function') window.toast = chan.fire;
      } else {
        window.toast = chan.fire;
      }
    }
    if (setApiToast) window.__apiToast = chan.fire;
  }

  function ToastStack() {
    const [items, setItems] = React.useState([]);
    React.useEffect(() => {
      const unsub = chan.subscribe((t) => {
        setItems((arr) => [...arr, t]);
        if (t.duration > 0) {
          setTimeout(() => dismissRef.current(t.id), t.duration);
        }
      });
      return unsub;
    }, []);
    // 两段式退场(动效审计:入场有 pl-toast-in,消失瞬间卸载):先标 _closing 播 .m-exit-down,
    // 100ms 后真正移除。dismissRef 供超时闭包引用最新实现。
    const dismiss = (id) => {
      setItems((arr) => arr.map((x) => x.id === id && !x._closing ? { ...x, _closing: true } : x));
      setTimeout(() => setItems((arr) => arr.filter((x) => x.id !== id)), 110);
    };
    const dismissRef = React.useRef(dismiss);
    dismissRef.current = dismiss;
    if (!items.length) return null;
    const node = (
      <div className="pl-toast-stack" aria-live="polite">
        {items.map((t) => (
          <div key={`toast-${t.id}`} className={`pl-toast pl-toast-${t.kind}${t._closing ? ' m-exit-down' : ''}`}>
            <span className={`pl-toast-icon dot ${t.kind === 'ok' ? 'ok' : t.kind === 'warn' ? 'warn' : t.kind === 'danger' ? 'danger' : 'info'}`} />
            <div className="pl-toast-body">
              <div className="pl-toast-msg">{t.message}</div>
              {t.detail && <div className="pl-toast-detail muted-2">{t.detail}</div>}
            </div>
            {t.action && (
              <button className="pl-toast-action" onClick={() => { try { t.action.onClick && t.action.onClick(); } catch (_) {} dismiss(t.id); }}>
                {t.action.label}
              </button>
            )}
            <button className="iconbtn pl-toast-close" onClick={() => dismiss(t.id)} data-tip={i18n.t('common.close')} aria-label={i18n.t('common.close')}>
              <Icon name="close" size={11} />
            </button>
          </div>
        ))}
      </div>
    );
    return createPortal(node, document.body);
  }

  return { install, ToastStack, subscribe: chan.subscribe, fire: chan.fire };
}

export default createToastChannel;
