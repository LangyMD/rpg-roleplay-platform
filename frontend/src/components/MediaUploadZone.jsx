import React from 'react';
import i18n from '../i18n/index.js';

/* MediaUploadZone — 统一上传原语：拖拽 / 粘贴 / 点击。
   把选到的 File 交给 onFile(file)。本组件不负责后端上传，只负责"拿到图片文件"。

   props:
     onFile(file)   : 选到图片文件时回调
     accept         : input accept（默认 image/png,image/jpeg,image/webp）
     disabled       : 禁用
     children       : 自定义内容（不传则渲默认拖放区 UI）
     className      : 外层 class（默认 .mh-drop）
     enablePaste    : 是否监听全局粘贴（默认 true）
*/
export default function MediaUploadZone({
  onFile,
  accept = 'image/png,image/jpeg,image/webp',
  disabled = false,
  children,
  className = 'mh-drop',
  enablePaste = true,
}) {
  const { useRef, useState, useEffect, useCallback } = React;
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);

  const take = useCallback((file) => {
    if (!file || disabled) return;
    if (!/^image\//.test(file.type)) return;
    onFile && onFile(file);
  }, [onFile, disabled]);

  // 全局粘贴图片
  useEffect(() => {
    if (!enablePaste || disabled) return;
    const onPaste = (e) => {
      const items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (const it of items) {
        if (it.type && it.type.startsWith('image/')) {
          const f = it.getAsFile();
          if (f) { take(f); e.preventDefault(); break; }
        }
      }
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [enablePaste, disabled, take]);

  const onDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    setDrag(false);
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) take(f);
  };

  return (
    <div
      className={`${className}${drag ? ' is-drag' : ''}`}
      data-drop-label={i18n.t('media.drop_overlay')}
      onClick={() => !disabled && inputRef.current && inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDrag(true); }}
      onDragLeave={(e) => { e.preventDefault(); setDrag(false); }}
      onDrop={onDrop}
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
    >
      {children || (
        <>
          <div className="mh-drop__icon">⬆</div>
          <div className="mh-drop__title">{i18n.t('media.drop_title')}</div>
          <div className="mh-drop__hint">PNG / JPG / WebP</div>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files && e.target.files[0]; if (f) take(f); e.target.value = ''; }}
      />
    </div>
  );
}
