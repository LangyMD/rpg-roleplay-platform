import React from 'react';
import { useTranslation } from 'react-i18next';
import { lsGet, lsSet } from '../lib/storage.js';

/* ImageSizePicker — 生图分辨率/比例选择器。
   · 预设几档常用比例(竖/方/横/长竖/宽屏),每档对应具体 WxH。
   · 默认值 = 按生图用途(kind)的「网站推荐比例」(见 RECOMMENDED_SIZE_BY_KIND)。
   · 用户改过一次后写 localStorage(按 kind/storeKey),下次该组件自动用上次选的——纯本地缓存,不经服务器。
   · 选中值通过 onChange(size:'1024x1024') 回传;父组件把它放进 api.images.generate 的 body.size。
   后端再把 WxH 透传给 provider(dashscope 会转成 W*H,doubao 直接吃,vertex 暂不支持忽略)。 */

export const SIZE_PRESETS = [
  { id: 'portrait',  label: 'Portrait 2:3',  value: '832x1216' },
  { id: 'square',    label: 'Square 1:1',  value: '1024x1024' },
  { id: 'landscape', label: 'Landscape 3:2',  value: '1216x832' },
  { id: 'tall',      label: 'Tall 9:16', value: '768x1344' },
  { id: 'wide',      label: 'Wide 16:9', value: '1344x768' },
];

// 各生图用途的推荐默认(对齐网站原始设计的展示比例):
//   卡头像/人设图(card/persona)= 竖版立绘;剧本封面(cover)= 宽屏;
//   账户头像(avatar)= 方形;聊天/游戏内(chat/game)= 方形。
export const RECOMMENDED_SIZE_BY_KIND = {
  card: '832x1216', persona: '832x1216', avatar: '1024x1024',
  cover: '1344x768', chat: '1024x1024', game: '1024x1024',
};

export function recommendedSize(kind) {
  return RECOMMENDED_SIZE_BY_KIND[kind] || '1024x1024';
}

export default function ImageSizePicker({ kind, value, onChange, storeKey }) {
  const { useEffect, useRef } = React;
  const { t } = useTranslation();
  const key = 'rpg.imgsize.' + (storeKey || kind || 'default');
  const inited = useRef(false);

  // 挂载时定初值:localStorage(上次选的) > 该 kind 推荐
  useEffect(() => {
    if (inited.current) return;
    inited.current = true;
    if (value) return;
    const saved = lsGet(key);
    onChange && onChange(saved || recommendedSize(kind));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pick = (v) => {
    lsSet(key, v);
    onChange && onChange(v);
  };

  return (
    <div className="isz" role="group" aria-label={t('image_size.aria_group')}>
      {SIZE_PRESETS.map((p) => (
        <button key={p.id} type="button"
          className={`isz__btn${value === p.value ? ' is-active' : ''}`}
          onClick={() => pick(p.value)} title={p.value}>
          {t(`image_size.preset_${p.id}`)}
        </button>
      ))}
    </div>
  );
}
