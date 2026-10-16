import React, { useEffect, useRef } from 'react';
import CSButton from '@cloudscape-design/components/button';
import i18n from '../i18n/index.js';

/* DetailDrawer — 右侧覆盖抽屉。
   替代 Cloudscape SplitPanel(那个自带「伸缩手柄」、单独用在 div 里会挤压主内容、外观诡异的组件)。
   特点:固定宽、position:fixed 覆盖在内容之上(不挤压表格)、点半透明遮罩或右上角 ✕ 关闭、无 resize。
   剧本编辑器的「世界书」「知识库人物」详情编辑共用,保证一致、不再各写一套。

   props:
     open       : 是否打开
     title      : 顶栏标题(string)
     onClose    : 关闭回调(点遮罩/✕ 都调它)
     width      : 抽屉宽度(px,默认 460;实际取 min(width, 94vw))
     closeLabel : ✕ 的 aria-label(默认「关闭」)
*/
export default function DetailDrawer({ open, title, onClose, width = 460, closeLabel: closeLabelProp, children }) {
  const closeLabel = closeLabelProp || i18n.t('common.close');
  const drawerRef = useRef(null);
  const prevFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    // Save currently focused element and move focus into the drawer.
    prevFocusRef.current = document.activeElement;
    // Try to focus the first focusable element in the drawer, else the drawer itself.
    const el = drawerRef.current;
    if (el) {
      const focusable = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusable) { focusable.focus(); } else { el.focus(); }
    }
    // Escape key handler.
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && onClose) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      // Restore focus when drawer closes.
      if (prevFocusRef.current && typeof prevFocusRef.current.focus === 'function') {
        prevFocusRef.current.focus();
      }
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, animation: 'm-fade-in var(--m-fast) ease-out both' }}
      />
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || closeLabel}
        tabIndex={-1}
        style={{
        position: 'fixed', top: 0, right: 0, height: '100vh', width: `min(${width}px, 94vw)`,
        background: 'var(--panel, #211f1d)', borderLeft: '1px solid var(--line, #36322d)',
        boxShadow: '-8px 0 28px rgba(0,0,0,.45)', zIndex: 1001,
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        animation: 'm-pop-in var(--m-base) var(--m-out) both',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px',
          borderBottom: '1px solid var(--line-soft, #2a2724)', flexShrink: 0,
        }}>
          <div style={{
            flex: 1, minWidth: 0, fontWeight: 600, fontSize: 15, color: 'var(--text, #ebe7df)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {title}
          </div>
          <CSButton variant="icon" iconName="close" ariaLabel={closeLabel} onClick={onClose} />
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>{children}</div>
      </div>
    </>
  );
}
