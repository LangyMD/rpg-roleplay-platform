/* MobileSaves — 移动端存档列表 + 详情 + 设置 + 分支树 (saves / saves-branches)
   覆盖桌面端 src/pages/saves.jsx 全部功能:
   - 存档列表 (搜索 / 排序 / 分页)
   - 存档详情 (overview KV / 重命名 / 继续游戏 / 激活 / 导出 Bundle / 删除)
   - 存档设置 (SaveSettingsForm 等价)
   - 分支节点列表 (SaveBranchList 等价)
   - 分支树页 (saves-branches: 选存档 + 真 branch tree + 激活节点 + 删除节点)
   - 新游戏入口 (新建存档 —— 跳转 scripts tab 或使用 NewGameWizard 最简版)
   - 导入存档 (.json / .zip)
   - 继续游戏 → nav.openGame(save)

   铁律:零 Cloudscape / 零桌面 UI 组件;仅用 window.api.*。
*/
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { fmtDate, normSave, normScript } from '../saves/helpers.js';
import { SaveDetail } from '../saves/SaveDetail.jsx';
import { BranchesPage } from '../saves/BranchesPage.jsx';
import { uiLocale } from '../../i18n/index.js';

/* ── 排序选项 ─────────────────────────────────────────────── */
const getSortOpts = (t) => [
  { value: 'played',  label: t('mobile.saves.sort.played') },
  { value: 'name',    label: t('mobile.saves.sort.name') },
  { value: 'created', label: t('mobile.saves.sort.created') },
];
const PAGE_SIZE = 50;

/* ══════════════════════════════════════════════════════════
   主组件 MobileSaves
   路由:saves(列表/详情) + saves-branches(分支树页)
   ══════════════════════════════════════════════════════════ */
export function MobileSaves({ nav }) {
  const { t } = useTranslation();

  /* ── 路由:saves-branches 分支树整页 ─────────────────────── */
  if (nav?.currentPage === 'saves-branches') {
    return (
      <div className="m-root">
        <div className="pl-root">
          <BranchesPage nav={nav} />
        </div>
      </div>
    );
  }

  /* ── 内部视图状态 ──────────────────────────────────────── */
  const [view, setView] = useState('list'); // list | detail
  const [selectedSave, setSelectedSave] = useState(null);

  const [saves, setSaves] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [loading, setLoading] = useState(true);

  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('played');
  const [page, setPage] = useState(1);
  const [sortOpen, setSortOpen] = useState(false);

  const importRef = useRef(null);

  /* ── Toast (inline) ─────────────────────────────────────── */
  const [toast, setToastState] = useState({ msg: '', kind: 'ok', show: false });
  const showToast = useCallback((msg, kind = 'ok') => {
    setToastState({ msg, kind, show: true });
    setTimeout(() => setToastState(p => ({ ...p, show: false })), 2600);
  }, []);

  /* ── 数据加载 ─────────────────────────────────────────── */
  const reload = useCallback(async () => {
    try {
      const r = await window.api.saves.list();
      // 存档 = 游戏模式专属;酒馆会话(save_kind='tavern')不进存档列表(它们在酒馆页)。
      const list = (Array.isArray(r) ? r : (r?.items || r?.saves || []))
        .filter(s => (s && (s.save_kind || 'game')) !== 'tavern')
        .map(normSave);
      setSaves(list);
      // rename/activate 后刷新 selectedSave 快照,避免详情面板显示旧数据。
      setSelectedSave(s => s ? (list.find(x => x.id === s.id) || s) : s);
    } catch (_) { setSaves([]); }
    try {
      const s = await window.api.scripts.list();
      const list = (Array.isArray(s) ? s : (s?.items || s?.scripts || [])).map(normScript);
      setScripts(list);
    } catch (_) { setScripts([]); }
    setLoading(false);
  }, []);

  useEffect(() => {
    reload();
    const refresh = () => reload();
    window.addEventListener('rpg-saves-updated', refresh);
    window.addEventListener('rpg-scripts-updated', refresh);
    return () => {
      window.removeEventListener('rpg-saves-updated', refresh);
      window.removeEventListener('rpg-scripts-updated', refresh);
    };
  }, [reload]);

  /* ── 搜索 + 排序 + 分页 ───────────────────────────────── */
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    let xs = saves;
    if (q) xs = saves.filter(s => {
      const sc = scripts.find(x => x.id === s.script_id);
      return (s.title || '').toLowerCase().includes(q) || (sc?.title || '').toLowerCase().includes(q);
    });
    const ts = v => (v ? new Date(v).getTime() || 0 : 0);
    const sorted = [...xs];
    if (sortBy === 'name') sorted.sort((a, b) => (a.title || '').localeCompare(b.title || '', uiLocale()));
    else if (sortBy === 'created') sorted.sort((a, b) => ts(b.created_ts) - ts(a.created_ts));
    else sorted.sort((a, b) => ts(b.last_played_ts) - ts(a.last_played_ts));
    return sorted;
  }, [saves, scripts, query, sortBy]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const paged = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  useEffect(() => { setPage(1); }, [query, sortBy]);

  const scriptTitle = s => scripts.find(x => x.id === s.script_id)?.title || t('mobile.saves.free_mode');

  /* ── 导入存档 ─────────────────────────────────────────── */
  const onImport = async (file) => {
    if (!file) return;
    if (!/\.(json|zip)$/i.test(file.name || '')) {
      showToast(t('mobile.saves.import.bad_format'), 'danger'); return;
    }
    if (file.size > 200 * 1024 * 1024) {
      showToast(t('mobile.saves.import.too_large'), 'danger'); return;
    }
    showToast(t('mobile.saves.import.importing'), 'ok');
    try {
      const r = await window.api.saves.importFile(file);
      if (r && r.ok === false) throw new Error(r.error || r.detail || t('mobile.saves.import.failed'));
      if (r?.warnings?.length) showToast(t('mobile.saves.import.done_with_warnings', { count: r.warnings.length }), 'ok');
      else showToast(t('mobile.saves.import.success'), 'ok');
      reload();
    } catch (e) { showToast(t('mobile.saves.import.failed_msg', { msg: e?.message || '' }), 'danger'); }
  };

  /* ── 详情视图 ─────────────────────────────────────────── */
  if (view === 'detail' && selectedSave) {
    return (
      <>
        <SaveDetail
          save={selectedSave}
          scripts={scripts}
          onBack={() => { setView('list'); setSelectedSave(null); }}
          onContinue={s => nav.openGame(s)}
          onToast={showToast}
          onReload={reload}
        />
        {/* Toast */}
        <div className={'toast ' + (toast.kind === 'ok' ? 'ok' : toast.kind === 'danger' ? 'danger' : '') + (toast.show ? ' show' : '')}>
          <Icon name={toast.kind === 'ok' ? 'check' : toast.kind === 'danger' ? 'warn' : 'info'} size={14} />
          {toast.msg}
        </div>
      </>
    );
  }

  /* ── 列表视图 ─────────────────────────────────────────── */
  return (
    <>
      {/* 头部 */}
      <div className="pl-head">
        <div className="pl-head-title">
          <strong style={{ fontSize: 17, fontFamily: 'var(--font-serif)' }}>{t('mobile.saves.list.title')}</strong>
          <span className="sub">{t('mobile.saves.list.count', { count: saves.length })}</span>
        </div>
        <div className="pl-head-actions">
          <button className="pl-headbtn" onClick={() => importRef.current?.click()}>
            <Icon name="upload" size={18} />
          </button>
          <button className="pl-headbtn accent" onClick={() => nav.go('saves-branches')}>
            <Icon name="branch" size={18} />
          </button>
          <button className="pl-headbtn accent" onClick={() => (nav.push ? nav.push('new-game') : nav.switchTab && nav.switchTab('scripts'))}>
            <Icon name="plus" size={20} />
          </button>
        </div>
        <input
          ref={importRef}
          type="file"
          accept=".json,.zip,application/json,application/zip"
          style={{ display: 'none' }}
          onChange={e => { onImport(e.target.files?.[0]); e.target.value = ''; }}
        />
      </div>

      {/* 搜索栏 + 排序 */}
      <div className="pl-toolbar">
        <div className="pl-search">
          <Icon name="search" size={16} />
          <input
            placeholder={t('mobile.saves.list.search_placeholder')}
            value={query}
            onChange={e => setQuery(e.target.value)}
            style={{ fontSize: 16 }}
          />
          {query && (
            <button onClick={() => setQuery('')}><Icon name="close" size={15} /></button>
          )}
        </div>
        <button
          style={{
            height: 40, padding: '0 12px', borderRadius: 11, border: '1px solid var(--line-soft)',
            background: 'var(--panel)', color: 'var(--text-quiet)', fontSize: 12.5, display: 'flex', alignItems: 'center', gap: 5, flexShrink: 0,
          }}
          onClick={() => setSortOpen(p => !p)}
        >
          <Icon name="filter" size={14} />
          {getSortOpts(t).find(o => o.value === sortBy)?.label}
        </button>
      </div>

      {/* 排序 Sheet */}
      {sortOpen && (
        <div className="sheet-wrap show" onClick={() => setSortOpen(false)}>
          <div className="sheet-scrim" />
          <div className="sheet" onClick={e => e.stopPropagation()}>
            <div className="sheet-grip" />
            <div className="sheet-title">{t('mobile.saves.list.sort_title')}</div>
            <div className="sheet-list" style={{ marginTop: 8 }}>
              {getSortOpts(t).map(o => (
                <button
                  key={o.value}
                  className={'sheet-item ' + (sortBy === o.value ? 'active' : '')}
                  onClick={() => { setSortBy(o.value); setSortOpen(false); }}
                >
                  <span className={'sheet-ico ' + (sortBy === o.value ? 'active' : '')}>
                    <Icon name={o.value === 'played' ? 'clock' : o.value === 'name' ? 'list' : 'history'} size={18} />
                  </span>
                  <span className="sheet-tx"><strong>{o.label}</strong></span>
                  {sortBy === o.value && <Icon name="check" size={17} className="sheet-check" style={{ color: 'var(--accent)' }} />}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 主体列表 */}
      <div className="pl-body tabbed">
        <div className="pl-pad" style={{ paddingTop: 8 }}>

          {loading && (
            <div className="pl-empty">
              <div className="ic"><Icon name="save" size={22} /></div>
              <p>{t('common.loading')}</p>
            </div>
          )}

          {!loading && saves.length === 0 && (
            <div className="pl-empty">
              <div className="ic"><Icon name="save" size={22} /></div>
              <h3>{t('mobile.saves.list.empty_title')}</h3>
              <p>{t('mobile.saves.list.empty_desc')}</p>
              <button className="pl-btn-primary" style={{ marginTop: 16, maxWidth: 220 }} onClick={() => (nav.push ? nav.push('new-game') : nav.switchTab && nav.switchTab('scripts'))}>
                <Icon name="book_open" size={17} />{t('mobile.saves.list.browse_scripts_btn')}
              </button>
            </div>
          )}

          {!loading && saves.length > 0 && visible.length === 0 && (
            <div className="pl-empty">
              <div className="ic"><Icon name="search" size={22} /></div>
              <h3>{t('mobile.saves.list.no_results_title')}</h3>
              <p>{t('mobile.saves.list.no_results_desc')}</p>
            </div>
          )}

          {paged.map(s => {
            const isCur = !!s.current;
            return (
              <button
                key={s.id}
                className={'pl-row ' + (isCur ? 'sel' : '')}
                onClick={() => { setSelectedSave(s); setView('detail'); }}
              >
                <span className={'pl-row-ic ' + (isCur ? 'accent' : '')}>
                  <Icon name={isCur ? 'play' : 'save'} size={18} />
                </span>
                <span className="pl-row-tx">
                  <strong className="serif">{s.title || t('mobile.saves.save_fallback', { id: s.id })}</strong>
                  <span>
                    {scriptTitle(s)}
                    <span className="mono">
                      {' '}· {t('mobile.saves.list.branch_count', { count: Number(s.branch_count) || 0 })}
                      {s.last_played_at ? ` · ${fmtDate(s.last_played_at)}` : ''}
                    </span>
                  </span>
                </span>
                <span className="pl-row-end" style={{ flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
                  {isCur && (
                    <span style={{ fontSize: 9.5, padding: '2px 7px', borderRadius: 99, background: 'var(--accent-soft)', color: 'var(--accent)', border: '1px solid var(--accent-edge)', fontWeight: 600, whiteSpace: 'nowrap' }}>{t('mobile.saves.detail.current_label')}</span>
                  )}
                  <button
                    style={{
                      display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5,
                      color: isCur ? 'var(--accent)' : 'var(--muted)',
                      padding: '5px 8px', borderRadius: 8,
                      border: '1px solid ' + (isCur ? 'var(--accent-edge)' : 'var(--line-soft)'),
                      background: isCur ? 'var(--accent-soft)' : 'var(--panel-2)',
                    }}
                    onClick={e => { e.stopPropagation(); nav.openGame(s); }}
                  >
                    <Icon name="play" size={13} />{t('mobile.saves.list.continue_btn')}
                  </button>
                </span>
              </button>
            );
          })}

          {/* 分页 */}
          {pageCount > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '16px 0 4px', fontSize: 13, color: 'var(--muted)' }}>
              <button
                style={{ width: 34, height: 34, borderRadius: 10, border: '1px solid var(--line-soft)', background: 'var(--panel)', color: 'var(--text-quiet)', display: 'grid', placeItems: 'center' }}
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
              >
                <Icon name="chevron_left" size={18} />
              </button>
              <span className="mono">{page} / {pageCount}</span>
              <button
                style={{ width: 34, height: 34, borderRadius: 10, border: '1px solid var(--line-soft)', background: 'var(--panel)', color: 'var(--text-quiet)', display: 'grid', placeItems: 'center' }}
                disabled={page >= pageCount}
                onClick={() => setPage(p => p + 1)}
              >
                <Icon name="chevron_right" size={18} />
              </button>
            </div>
          )}

          {/* 底部操作区 */}
          {!loading && (
            <div className="pl-sec" style={{ marginTop: 24 }}>
              <div className="pl-sec-head"><h2>{t('mobile.saves.list.actions_heading')}</h2></div>
              <div style={{ display: 'grid', gap: 8 }}>
                <button className="pl-row" onClick={() => importRef.current?.click()}>
                  <span className="pl-row-ic info"><Icon name="upload" size={18} /></span>
                  <span className="pl-row-tx">
                    <strong>{t('mobile.saves.import.action_title')}</strong>
                    <span>{t('mobile.saves.import.action_desc')}</span>
                  </span>
                  <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
                </button>
                <button className="pl-row" onClick={() => nav.go('saves-branches')}>
                  <span className="pl-row-ic"><Icon name="branch" size={18} /></span>
                  <span className="pl-row-tx">
                    <strong>{t('mobile.saves.branches_page.title')}</strong>
                    <span>{t('mobile.saves.branches_page.action_desc')}</span>
                  </span>
                  <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
                </button>
                <button className="pl-row" onClick={() => (nav.push ? nav.push('new-game') : nav.switchTab && nav.switchTab('scripts'))}>
                  <span className="pl-row-ic accent"><Icon name="plus" size={18} /></span>
                  <span className="pl-row-tx">
                    <strong>{t('mobile.saves.list.new_game_title')}</strong>
                    <span>{t('mobile.saves.list.new_game_desc')}</span>
                  </span>
                  <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Toast */}
      <div className={'toast ' + (toast.kind === 'ok' ? 'ok' : toast.kind === 'danger' ? 'danger' : '') + (toast.show ? ' show' : '')}>
        <Icon name={toast.kind === 'ok' ? 'check' : 'warn'} size={14} />
        {toast.msg}
      </div>
    </>
  );
}

export default MobileSaves;
