/* MobileMe · VIEW 个人主页 Overview —— 从 pages/MobileMe.jsx 拆出,逐字节不变。 */
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../icons.jsx';
import { usePlatformData } from '../../platform-app.jsx';
import AvatarImg from '../../components/AvatarImg.jsx';
import { fmtN, fmtWan, fmtDate, fmtAgo, TIER_RANK, TIER_COLOR } from './helpers.js';
import { PageHead } from './shared.jsx';

/* ═══════════════════════════════════════════════════════════════════
   VIEW: 个人主页 Overview
   ═══════════════════════════════════════════════════════════════════ */
function ViewOverview({ nav, user }) {
  const { t } = useTranslation();
  const { saves = [] } = usePlatformData();
  const [meStats, setMeStats] = useState(null);
  const [activity, setActivity] = useState(null);
  const [achv, setAchv] = useState(null);
  const [actFilter, setActFilter] = useState('all');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.stats();
        if (!cancelled) setMeStats(r || null);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.activity();
        if (!cancelled) setActivity((r && r.activity) || []);
      } catch (_) { if (!cancelled) setActivity([]); }
    })();
    return () => { cancelled = true; };
  }, [saves.length]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.achievements();
        if (!cancelled) setAchv((r && r.items) || []);
      } catch (_) { if (!cancelled) setAchv([]); }
    })();
    return () => { cancelled = true; };
  }, [saves.length]);

  const regAt = fmtDate(user.created_at);
  const totalRounds = meStats?.total_rounds;
  const branches = meStats?.branches;
  const importedScripts = meStats?.imported?.scripts;
  const importedWords = meStats?.imported?.words;
  const loginStreak = meStats?.login_streak;
  const longestStreak = meStats?.longest_login_streak;
  const playMinutes = meStats?.play_minutes_total;
  const playHours = playMinutes != null ? (playMinutes / 60).toFixed(1) : null;
  const playMinutesWeek = meStats?.play_minutes_week;
  const maxDepth = meStats?.max_branch_depth;

  const unlockedCount = (achv || []).filter(a => a.unlocked).length;
  const topAchv = (achv || []).filter(a => a.unlocked).sort((a, b) => (TIER_RANK[b.tier] || 0) - (TIER_RANK[a.tier] || 0)).slice(0, 6);

  // 以后端 type(turn/branch/script)过滤;旧后端只给中文 tag 时兜底映射(与桌面 MeOverview 孪生)。
  const _actType = (a) => (a && (a.type || ({ '回合': 'turn', '分支': 'branch', '剧本': 'script', Turn: 'turn', Branch: 'branch', Script: 'script' })[a.tag])) || '';
  const filteredAct = actFilter === 'all' ? (activity || []) : (activity || []).filter(a => _actType(a) === actFilter);

  return (
    <>
      <PageHead
        title={t('mobile.me.overview.title')}
        actions={
          <button className="pl-headbtn" onClick={() => nav.go('me-edit')} aria-label={t('mobile.me.edit.title')}>
            <Icon name="edit" size={18} />
          </button>
        }
      />
      <div className="pl-body tabbed">
        <div className="pl-pad">

          {/* Hero */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 14,
            padding: '16px 16px 14px',
            background: 'var(--panel)', border: '1px solid var(--line-soft)',
            borderRadius: 14, marginBottom: 16,
          }}>
            <AvatarImg
              src={user.avatar_url || user._raw?.avatar_url}
              name={user.display_name || user.username}
              size={56}
              shape="rounded"
              className="mc-me-avatar"
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 17, fontWeight: 700, fontFamily: 'var(--font-serif)', color: 'var(--text)' }}>
                {user.display_name || '—'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                @{user.username || '—'}
                {user.role && <span style={{ marginLeft: 8, padding: '1px 7px', borderRadius: 999, fontSize: 10.5, background: 'var(--accent-soft)', color: 'var(--accent)', border: '1px solid var(--accent-edge)' }}>{user.role}</span>}
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--text-quiet)', marginTop: 5, lineHeight: 1.5 }}>
                {user.bio || <span style={{ color: 'var(--muted-2)' }}>{t('mobile.me.overview.no_bio')}</span>}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 5, fontFamily: 'var(--font-mono)' }}>
                {t('mobile.me.overview.registered_at', { date: regAt })}
              </div>
            </div>
          </div>

          {/* 统计 */}
          <div className="pl-stats" style={{ marginBottom: 16 }}>
            <div className="pl-stat">
              <span className="n accent">{playHours != null ? playHours : '—'}</span>
              <div className="l">{t('mobile.me.stats.play_hours')}{playMinutesWeek != null ? <span style={{ display: 'block', fontSize: 9 }}>+{(playMinutesWeek/60).toFixed(1)}h/{t('mobile.me.stats.per_week')}</span> : ''}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{totalRounds != null ? fmtN(totalRounds) : '—'}</span>
              <div className="l">{t('mobile.me.stats.total_rounds')}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{branches != null ? fmtN(branches) : '—'}</span>
              <div className="l">{t('mobile.me.stats.branches')}{maxDepth ? <span style={{ display: 'block', fontSize: 9 }}>{t('mobile.me.stats.max_depth', { n: maxDepth })}</span> : ''}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{loginStreak != null ? loginStreak : '—'}</span>
              <div className="l">{t('mobile.me.stats.streak_days')}{longestStreak ? <span style={{ display: 'block', fontSize: 9 }}>{t('mobile.me.stats.longest_streak', { n: longestStreak })}</span> : ''}</div>
            </div>
          </div>
          <div className="pl-stats" style={{ marginBottom: 16 }}>
            <div className="pl-stat">
              <span className="n">{importedScripts != null ? importedScripts : '—'}</span>
              <div className="l">{t('mobile.me.stats.imported_scripts')}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{importedWords != null ? fmtWan(importedWords) : '—'}</span>
              <div className="l">{t('mobile.me.stats.imported_words')}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{unlockedCount}</span>
              <div className="l">{t('mobile.me.stats.achievements_unlocked')}</div>
            </div>
            <div className="pl-stat">
              <span className="n">{saves.length}</span>
              <div className="l">{t('mobile.me.stats.saves')}</div>
            </div>
          </div>

          {/* 成就摘要 */}
          <div className="pl-sec">
            <div className="pl-sec-head">
              <h2>{t('mobile.me.overview.achievements')}</h2>
              <button className="act" onClick={() => nav.go('wall')}>{t('common.all')} <Icon name="chevron_right" size={13} /></button>
            </div>
            {achv === null ? (
              <div className="pl-empty">{t('common.loading')}</div>
            ) : achv.length === 0 ? (
              <div className="pl-empty">{t('mobile.me.overview.no_achievements')}</div>
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingBottom: 4 }}>
                {topAchv.map(a => (
                  <div key={a.id} title={a.name + (a.desc ? ': ' + a.desc : '')} style={{
                    display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                    padding: '8px 10px', borderRadius: 10, minWidth: 60, maxWidth: 80,
                    background: 'var(--panel)', border: '1px solid ' + (TIER_COLOR[a.tier] ? TIER_COLOR[a.tier] + '55' : 'var(--line-soft)'),
                  }}>
                    <span style={{ fontSize: 20 }}>{a.icon || '🏆'}</span>
                    <span style={{ fontSize: 10, color: 'var(--muted)', textAlign: 'center', lineHeight: 1.3, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name}</span>
                  </div>
                ))}
                {(achv || []).filter(a => a.unlocked).length > 6 && (
                  <button onClick={() => nav.go('wall')} style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    width: 60, height: 70, borderRadius: 10, flexDirection: 'column', gap: 4,
                    background: 'var(--panel)', border: '1px solid var(--line-soft)', color: 'var(--muted)', fontSize: 12,
                  }}>
                    <Icon name="more" size={16} />
                    <span style={{ fontSize: 10 }}>{t('mobile.me.overview.more')}</span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* 最近活动 */}
          <div className="pl-sec">
            <div className="pl-sec-head">
              <h2>{t('mobile.me.overview.recent_activity')}</h2>
            </div>
            {/* 活动筛选标签 */}
            <div style={{ display: 'flex', gap: 7, marginBottom: 10, overflowX: 'auto', paddingBottom: 2 }} className="scroll">
              {[
                { v: 'all', l: t('common.all') },
                { v: 'turn', l: t('mobile.me.overview.filter_rounds') },
                { v: 'branch', l: t('mobile.me.overview.filter_branches') },
                { v: 'script', l: t('mobile.me.overview.filter_scripts') },
              ].map(f => (
                <button key={f.v} onClick={() => setActFilter(f.v)} style={{
                  flexShrink: 0, height: 28, padding: '0 12px', borderRadius: 999,
                  fontSize: 12, fontWeight: 500,
                  background: actFilter === f.v ? 'var(--accent-soft)' : 'var(--panel-2)',
                  color: actFilter === f.v ? 'var(--accent)' : 'var(--muted)',
                  border: '1px solid ' + (actFilter === f.v ? 'var(--accent-edge)' : 'var(--line-soft)'),
                }}>
                  {f.l}
                </button>
              ))}
            </div>
            {activity === null ? (
              <div className="pl-empty">{t('common.loading')}</div>
            ) : filteredAct.length === 0 ? (
              <div className="pl-empty" style={{ fontSize: 12.5 }}>
                {activity.length === 0 ? t('mobile.me.overview.no_activity') : t('mobile.me.overview.no_activity_in_filter')}
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 1 }}>
                {filteredAct.slice(0, 12).map((a, i) => (
                  <div key={i} className="pl-row" style={{ margin: 0, pointerEvents: 'none' }}>
                    <span className="pl-row-ic info"><Icon name={a.icon || 'clock'} size={16} /></span>
                    <span className="pl-row-tx">
                      <strong style={{ fontSize: 13 }}>{a.text}</strong>
                      <span className="mono" style={{ fontSize: 11 }}>
                        {a.tag && <span style={{ marginRight: 6, padding: '1px 6px', borderRadius: 999, background: 'var(--panel-2)', border: '1px solid var(--line-soft)' }}>{({ turn: t('mobile.me.overview.filter_rounds'), branch: t('mobile.me.overview.filter_branches'), script: t('mobile.me.overview.filter_scripts') })[_actType(a)] || a.tag}</span>}
                        {a.ts ? fmtAgo(a.ts) : ''}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 快捷跳转 */}
          <div className="pl-sec">
            <div className="pl-sec-head"><h2>{t('mobile.me.overview.account_mgmt')}</h2></div>
            <button className="pl-row" onClick={() => nav.go('me-edit')}>
              <span className="pl-row-ic"><Icon name="edit" size={17} /></span>
              <span className="pl-row-tx"><strong>{t('mobile.me.edit.title')}</strong><span>{t('mobile.me.overview.edit_desc')}</span></span>
              <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
            </button>
            <button className="pl-row" onClick={() => nav.go('me-settings')}>
              <span className="pl-row-ic"><Icon name="settings" size={17} /></span>
              <span className="pl-row-tx"><strong>{t('mobile.me.settings.title')}</strong><span>{t('mobile.me.overview.settings_desc')}</span></span>
              <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
            </button>
            <button className="pl-row" onClick={() => nav.go('usage')}>
              <span className="pl-row-ic info"><Icon name="usage" size={17} /></span>
              <span className="pl-row-tx"><strong>{t('mobile.me.usage.title')}</strong><span>{t('mobile.me.overview.usage_desc')}</span></span>
              <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
            </button>
            <button className="pl-row" onClick={() => nav.go('wall')}>
              <span className="pl-row-ic ok"><Icon name="trophy" size={17} /></span>
              <span className="pl-row-tx"><strong>{t('mobile.me.wall.title')}</strong><span>{t('mobile.me.overview.wall_desc', { count: unlockedCount })}</span></span>
              <span className="pl-row-chev"><Icon name="chevron_right" size={17} /></span>
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

export { ViewOverview };
