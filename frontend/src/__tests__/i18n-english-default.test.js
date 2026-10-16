/**
 * i18n-english-default.test.js — English is the default/fallback UI language.
 *   · DEFAULT_LANGUAGE / fallbackLng are 'en' (pref.ui_language in localStorage still wins at runtime);
 *   · en.json covers every zh-CN key and carries no CJK text;
 *   · HelpDrawer.embedUrl serves English docs for an English UI and the zh embed view for Chinese.
 */
import { describe, it, expect } from 'vitest';
import i18n, { DEFAULT_LANGUAGE } from '../i18n/index.js';
import en from '../i18n/locales/en.json';
import zh from '../i18n/locales/zh-CN.json';
import { embedUrl } from '../components/HelpDrawer.jsx';

function flat(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') flat(v, key, out);
    else out[key] = v;
  }
  return out;
}

describe('English default locale', () => {
  it('default and fallback language are English', () => {
    expect(DEFAULT_LANGUAGE).toBe('en');
    const fb = i18n.options.fallbackLng;
    expect(Array.isArray(fb) ? fb[0] : fb).toBe('en');
  });

  it('en.json has every zh-CN key', () => {
    const E = flat(en);
    const missing = Object.keys(flat(zh)).filter((k) => !(k in E));
    expect(missing).toEqual([]);
  });

  it('en.json contains no CJK text', () => {
    const bad = Object.entries(flat(en)).filter(([, v]) => /[一-鿿]/.test(String(v)));
    expect(bad).toEqual([]);
  });

  it('help drawer picks docs by UI language', () => {
    expect(embedUrl('scripts', true)).toMatch(/\/embed\/scripts\/$/);
    expect(embedUrl('scripts', false)).toMatch(/\/en\/scripts\/$/);
    expect(embedUrl('intro', false)).toMatch(/\/en\/getting-started\/$/);
  });
});
