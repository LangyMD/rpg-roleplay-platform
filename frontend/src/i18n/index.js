/* i18n 初始化 — i18next + react-i18next
   语言优先级: localStorage["pref.ui_language"] > en(默认/回落)
   浏览器语言不参与探测:私有本地部署默认英文,想要中文在设置里切换即可。
   changeLanguage(lng) 供 settings.jsx 的 interfaceLang onChange 调用。 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import zhCN from './locales/zh-CN.json';
import en from './locales/en.json';
import { lsGet, lsSet } from '../lib/storage.js';

const STORAGE_KEY = 'pref.ui_language';
export const DEFAULT_LANGUAGE = 'en';

// 读 prefs 里存的语言(settings.jsx 的 save("ui_language", v) 写的 key)
// 缺失返回 undefined(非 null),让 i18next 回落到 LanguageDetector / fallbackLng。
function getStoredLang() {
  return lsGet(STORAGE_KEY) || undefined;
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': { translation: zhCN },
      'zh-TW': { translation: zhCN }, // 暂时复用简体;后续补繁体 locale
      'en':    { translation: en },
    },
    lng: getStoredLang(),           // prefs 优先;未设则走 detector(仅 localStorage)→ en
    fallbackLng: DEFAULT_LANGUAGE,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage'],
      lookupLocalStorage: STORAGE_KEY,
      caches: [],  // 不让 detector 自己写 localStorage;由 settings 的 save() 管
    },
  });

function currentLng() {
  return i18n.resolvedLanguage || i18n.language || DEFAULT_LANGUAGE;
}

/** UI 当前是否中文(决定外链文档 / 法务页等走哪个语言版本)。 */
export function isZhUi() {
  return /^zh/i.test(currentLng());
}

/** 当前 UI 语言对应的 BCP-47 locale(给 toLocaleString / localeCompare / Intl 用)。 */
export function uiLocale() {
  return isZhUi() ? currentLng() : 'en-US';
}

function syncHtmlLang() {
  try {
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.lang = isZhUi() ? currentLng() : 'en';
    }
  } catch (_) { /* noop */ }
}
syncHtmlLang();
// 给非模块脚本(api-client.js 是 IIFE)取文案用。
try { if (typeof window !== 'undefined') window.__i18n = i18n; } catch (_) { /* noop */ }
i18n.on('languageChanged', syncHtmlLang);

/** 切换语言并同步写 localStorage(prefs save 也会写后端,这里只保证本地立即生效) */
export function changeLanguage(lng) {
  lsSet(STORAGE_KEY, lng);
  return i18n.changeLanguage(lng);
}

export default i18n;
