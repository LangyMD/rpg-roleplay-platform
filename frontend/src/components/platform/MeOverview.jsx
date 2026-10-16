/* 个人中心 · 概览(Hero / 统计 / 成就墙 / 最近活动)。
   从 components/platform/me-pages.jsx 二次拆出,零行为变化。
   注意:flushAchievementToasts 是 achievements.jsx 的会话内去重单例,保持 import 关系不破坏其 dedup Set。 */
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../../game-icons.jsx';
import AvatarImg from '../AvatarImg.jsx';
import MediaStudio from '../MediaStudio.jsx';
import { usePlatformData, useReactiveUser } from './shared.jsx';
import { flushAchievementToasts, AchievementWall, AchvShareModal } from './achievements.jsx';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import { isZhUi, uiLocale } from '../../i18n/index.js';

/* ---------------------------- ME (personal home) ----------- */
// 匿名 designer preview 用的示例活动(登录态拉真实 /api/me/activity)。
const ME_ACTIVITY = [
  { ts: "Just now",       icon: "play",   type: "turn",   text: "Played turn 312 in Fog Harbor · main · Gu Chengyan", tag: "Turn" },
  { ts: "12 minutes ago", icon: "branch", type: "branch", text: "Created branch Inn line · Aheng POV from node #07", tag: "Branch" },
  { ts: "Today 14:08",    icon: "memory", text: "Pinned \"The pocket watch stopped at 3:42\" to memory", tag: "Memory" },
  { ts: "Today 12:30",    icon: "save",   type: "script", text: "Imported script Fog Harbor Tales · side volume", tag: "Script" },
  { ts: "Yesterday",      icon: "edit",   text: "Edited the tone of card · Shen Zhiwei", tag: "NPC card" },
  { ts: "Yesterday",      icon: "world",  text: "Set worldline variable Gu Chengyan.identity_exposure = 37%", tag: "Worldline" },
  { ts: "Last week",      icon: "upload", text: "Uploaded torn_page_scans.zip to the library", tag: "Library" },
  { ts: "Last week",      icon: "spark",  text: "Deployed Skill · Timeline projection v1.4", tag: "Skill" },
  { ts: "Last month",     icon: "user",   text: "Signed up · became the first administrator", tag: "Account" },
];
// 旧后端只给中文 tag 不给 type:兜底映射。
const _ACT_TAG_TYPE = { "回合": "turn", "分支": "branch", "剧本": "script" };
const activityType = (a) => (a && (a.type || _ACT_TAG_TYPE[a.tag])) || "";

function MeOverview() {
  const { t } = useTranslation();
  const { stats: platStats = {}, saves = [] } = usePlatformData();  // task 45：响应式 platform
  const user = useReactiveUser();  // task 13: MePage 切换 / 保存后即时更新
  const [filter, setFilter] = useStatePL("all");
  const [shareOpen, setShareOpen] = useStatePL(false);
  // task 48：原使用 ME_ACTIVITY / ME_ACHIEVEMENTS 硬编码示例（『在 雾港·主线·顾承砚
  // 进行了第 312 回合』『破雾之刻』『千言不渝』等）。后端暂无活动/成就接口，改成空态文案。
  // 匿名访客可见 mock 用作 designer offline preview。
  const IS_ANON = !(window.RPG_AUTH && window.RPG_AUTH.authed);
  // 最近活动:登录态拉真实 /api/me/activity(回合/分支/剧本),匿名用 mock 作 designer preview
  const [meActivity, setMeActivity] = useStatePL(null);
  useEffectPL(() => {
    if (IS_ANON) return;
    let cancelled = false;
    (async () => {
      try { const r = await window.api.account.activity(); if (!cancelled) setMeActivity((r && r.activity) || []); }
      catch (_) { if (!cancelled) setMeActivity([]); }
    })();
    return () => { cancelled = true; };
  }, [IS_ANON, saves.length]);
  const ACTIVITY = IS_ANON ? ME_ACTIVITY : (meActivity || []);
  // 成就在 meStats 拉到后派生(见下方 ACHIEVEMENTS)
  // task 49：之前 totalRounds = saves.reduce(* 7)、playHours = totalRounds*1.2/60 等
  // 全是凭空乘的伪派生；现在拉真后端 /api/me/stats。后端没真数据的字段（playMinutes）
  // 显式为 null，UI 显示 "—"。
  const [meStats, setMeStats] = useStatePL(null);
  useEffectPL(() => {
    if (IS_ANON) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await window.api.account.stats();
        if (!cancelled) setMeStats(r || null);
      } catch (_) {}
    })();
    return () => { cancelled = true; };
  }, [IS_ANON, saves.length]);
  const filteredActivity = filter === "all" ? ACTIVITY : ACTIVITY.filter(a => activityType(a) === filter);
  const fmtCN = (n) => {
    if (n == null) return "—";
    if (n >= 10000 && isZhUi()) return (n / 10000).toFixed(1).replace(/\.0$/, "") + " 万";
    return n.toLocaleString(uiLocale());
  };
  // fmtDate / fmtAgo 统一到 window.__fmt(data-loader.js)。fmtAgo 原本就在
  // window.__fmt.ago 存在时直接委派(运行时总成立),此处去掉死的本地兜底。
  const fmtDate = (iso) => {
    if (window.__fmt && window.__fmt.date) return window.__fmt.date(iso);
    if (!iso) return "—";
    try { return new Date(iso).toISOString().slice(0, 10); } catch { return "—"; }
  };
  const fmtAgo = (iso) => (window.__fmt && window.__fmt.ago) ? window.__fmt.ago(iso) : "—";
  const regAt = fmtDate(user.created_at);
  const lastLoginAgo = fmtAgo(meStats?.last_login_at);
  const totalRounds = meStats?.total_rounds;
  const branchesCount = meStats?.branches ?? platStats.branches;
  const maxDepth = meStats?.max_branch_depth;
  const importedScripts = meStats?.imported?.scripts ?? platStats.scripts;
  const importedWords = meStats?.imported?.words;
  const loginStreak = meStats?.login_streak;
  const longestStreak = meStats?.longest_login_streak;
  const playMinutesTotal = meStats?.play_minutes_total;
  const playMinutesWeek = meStats?.play_minutes_week;
  const playHoursLabel = (playMinutesTotal == null) ? "—" : (playMinutesTotal / 60).toFixed(1);

  // 成就:服务端权威(见 docs/design/I_achievements.md)。
  // 登录态拉 /api/me/achievements(含进度 + 解锁时间 + newly_unlocked);
  // 匿名态拉公开目录 /api/achievements 作全锁预览。客户端不再派生。
  const [achv, setAchv] = useStatePL(null);
  useEffectPL(() => {
    let cancelled = false;
    (async () => {
      try {
        if (IS_ANON) {
          const r = await window.api.account.achievementsCatalog();
          if (!cancelled) setAchv((r && r.items) || []);
          return;
        }
        const r = await window.api.account.achievements();
        if (cancelled) return;
        const items = (r && r.items) || [];
        setAchv(items);
        flushAchievementToasts(items);  // 弹未看过的解锁(会话内去重)
      } catch (_) { if (!cancelled) setAchv([]); }
    })();
    return () => { cancelled = true; };
  }, [IS_ANON, saves.length]);
  const ACHIEVEMENTS = achv || [];
  const unlockedCount = ACHIEVEMENTS.filter(a => a.unlocked).length;
  const [overviewAvatarStudioOpen, setOverviewAvatarStudioOpen] = useStatePL(false);
  const [overviewAvatarUrl, setOverviewAvatarUrl] = useStatePL(null);
  // 实际展示 URL:MediaStudio 更新后用 overviewAvatarUrl,否则回落 user.avatar_url(._raw 兜底防未来包装层)
  const displayAvatarUrl = overviewAvatarUrl || user.avatar_url || user._raw?.avatar_url || null;

  return (
    <CSSpaceBetween size="l">
      {/* Hero section */}
      <CSContainer>
        <CSSpaceBetween size="m">
          <CSSpaceBetween direction="horizontal" size="m">
            {overviewAvatarStudioOpen && (
              <MediaStudio
                open={overviewAvatarStudioOpen}
                onClose={() => setOverviewAvatarStudioOpen(false)}
                target={{ type: 'user_avatar' }}
                name={user.display_name || t('platform.me.user_fallback')}
                defaultPrompt={user.display_name ? t('platform.me.avatar_prompt_named', { name: user.display_name }) : t('platform.me.avatar_prompt')}
                onApplied={(url) => {
                  setOverviewAvatarUrl(url + '?t=' + Date.now());
                  setOverviewAvatarStudioOpen(false);
                }}
              />
            )}
            <div style={{ position: 'relative', display: 'inline-block' }}>
              <AvatarImg src={displayAvatarUrl} name={user.display_name || '?'} size={88} shape="circle" className="pl-me-avatar" zoomable />
              {!IS_ANON && (
                <button
                  onClick={() => setOverviewAvatarStudioOpen(true)}
                  title={t('platform.me.change_avatar', '更换头像')}
                  style={{
                    position: 'absolute', bottom: 0, right: 0,
                    background: 'var(--color-background-dropdown-item-default, #2a2927)',
                    border: '1px solid var(--color-border-divider-default, #444)',
                    borderRadius: '50%', width: 26, height: 26,
                    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 13, color: 'var(--color-text-interactive-default, #e8c97a)',
                    padding: 0,
                  }}
                >✦</button>
              )}
            </div>
            <div style={{flex: 1}}>
              <CSSpaceBetween size="xs">
                <CSBox variant="h2">
                  {user.display_name}
                  <span className="pill" style={{marginLeft: 8}}><span className="dot ok pulse" /> {t('platform.me.online', '在线')}</span>
                  <span className="pill accent" style={{marginLeft: 6}}>{user.role === "admin" ? t('platform.me.role_admin', '管理员') : user.role}</span>
                </CSBox>
                <CSBox color="text-body-secondary" fontSize="body-s">
                  <span><Icon name="user" size={11} /> @{user.username}</span>
                  <span className="mono" style={{marginLeft: 12}}>uid {user.uid}</span>
                  <span style={{marginLeft: 12}}><Icon name="history" size={11} /> {t('platform.me.registered_at', { date: regAt, defaultValue: `注册于 ${regAt}` })} · {t('platform.me.last_login', { ago: lastLoginAgo, defaultValue: `上次登录 ${lastLoginAgo}` })}</span>
                </CSBox>
                <CSBox>{user.bio || t('platform.me.no_bio', '暂无简介。')}</CSBox>
              </CSSpaceBetween>
            </div>
          </CSSpaceBetween>
        </CSSpaceBetween>
      </CSContainer>

      {/* Stat row */}
      <CSContainer>
        <CSColumnLayout columns={5} variant="text-grid">
          <div>
            <CSBox variant="awsui-key-label">{t('platform.me.stat_playtime', '游玩时长')}</CSBox>
            <CSBox fontSize="display-l" fontWeight="bold">
              {playHoursLabel}{playMinutesTotal != null && <span style={{fontSize: 14, color: "var(--muted)", marginLeft: 4}}>h</span>}
            </CSBox>
            <CSBox color="text-body-secondary" fontSize="body-s">{playMinutesWeek != null ? t('platform.me.stat_playtime_week', { h: (playMinutesWeek / 60).toFixed(1), defaultValue: `本周 +${(playMinutesWeek / 60).toFixed(1)}h` }) : t('platform.me.stat_no_data', '暂无统计')}</CSBox>
          </div>
          <div>
            <CSBox variant="awsui-key-label">{t('platform.me.stat_rounds', '回合数')}</CSBox>
            <CSBox fontSize="display-l" fontWeight="bold">{totalRounds != null ? totalRounds.toLocaleString() : "—"}</CSBox>
            <CSBox color="text-body-secondary" fontSize="body-s">{t('platform.me.stat_saves_count', { n: saves.length, defaultValue: `分布在 ${saves.length} 个存档` })}</CSBox>
          </div>
          <div>
            <CSBox variant="awsui-key-label">{t('platform.me.stat_branches', '创建分支')}</CSBox>
            <CSBox fontSize="display-l" fontWeight="bold">{branchesCount != null ? branchesCount : "—"}</CSBox>
            <CSBox color="text-body-secondary" fontSize="body-s">{maxDepth ? t('platform.me.stat_max_depth', { n: maxDepth, defaultValue: `最深 ${maxDepth} 层` }) : "—"}</CSBox>
          </div>
          <div>
            <CSBox variant="awsui-key-label">{t('platform.me.stat_scripts', '导入剧本')}</CSBox>
            <CSBox fontSize="display-l" fontWeight="bold">{importedScripts != null ? importedScripts : "—"}</CSBox>
            <CSBox color="text-body-secondary" fontSize="body-s">{importedWords ? t('platform.me.stat_words', { n: fmtCN(importedWords), defaultValue: `共 ${fmtCN(importedWords)}字` }) : "—"}</CSBox>
          </div>
          <div>
            <CSBox variant="awsui-key-label">{t('platform.me.stat_streak', '连续登录')}</CSBox>
            <CSBox fontSize="display-l" fontWeight="bold">
              {loginStreak != null ? loginStreak : "—"}<span style={{fontSize: 14, color: "var(--muted)", marginLeft: 4}}>{t('platform.me.stat_streak_unit', '天')}</span>
            </CSBox>
            <CSBox color="text-body-secondary" fontSize="body-s">{longestStreak ? t('platform.me.stat_streak_longest', { n: longestStreak, defaultValue: `最长 ${longestStreak} 天` }) : "—"}</CSBox>
          </div>
        </CSColumnLayout>
      </CSContainer>

      {/* 成就(服务端权威,按类目分组) */}
      <CSContainer header={<CSHeader variant="h2"
        actions={!IS_ANON && unlockedCount > 0 && <CSButton iconName="share" onClick={() => setShareOpen(true)}>{t('platform.achv.share_btn', '分享成就')}</CSButton>}
      >{t('platform.achv.heading', '成就')} <span className="muted-2">{unlockedCount} / {ACHIEVEMENTS.length} {t('platform.achv.unlocked_label', '已解锁')}</span></CSHeader>}>
        {ACHIEVEMENTS.length === 0 ? (
          <CSBox color="text-body-secondary" textAlign="center" padding="l">
            {achv === null ? t('common.loading', '加载中…') : t('platform.achv.empty', '暂无成就。')}
          </CSBox>
        ) : (
          <AchievementWall items={ACHIEVEMENTS} />
        )}
      </CSContainer>

      {shareOpen && (
        <AchvShareModal
          user={user}
          items={ACHIEVEMENTS}
          unlockedCount={unlockedCount}
          total={ACHIEVEMENTS.length}
          publicProfile={!!(meStats && meStats.public_profile)}
          onClose={() => setShareOpen(false)}
        />
      )}

      {/* 最近活动 */}
      <CSContainer header={
        <CSHeader variant="h2" actions={
          <CSSpaceBetween direction="horizontal" size="xs">
            <CSButton variant={filter === "all" ? "primary" : "normal"} onClick={() => setFilter("all")}>{t('common.all', '全部')}</CSButton>
            <CSButton variant={filter === "turn" ? "primary" : "normal"} onClick={() => setFilter("turn")}>{t('platform.me.activity_tag_round', '回合')}</CSButton>
            <CSButton variant={filter === "branch" ? "primary" : "normal"} onClick={() => setFilter("branch")}>{t('platform.me.activity_tag_branch', '分支')}</CSButton>
            <CSButton variant={filter === "script" ? "primary" : "normal"} onClick={() => setFilter("script")}>{t('platform.me.activity_tag_script', '剧本')}</CSButton>
          </CSSpaceBetween>
        }>{t('platform.me.recent_activity', '最近活动')}</CSHeader>
      }>
        <ol className="pl-activity">
          {filteredActivity.map((a, i) => (
            <li key={i}>
              <div className="pl-activity-rail">
                <span className="pl-activity-dot"><Icon name={a.icon} size={11} /></span>
                {i < filteredActivity.length - 1 && <span className="pl-activity-line" />}
              </div>
              <div className="pl-activity-body">
                <div className="pl-activity-text">{a.text}</div>
                {a.sub ? <div className="pl-activity-sub muted-2" style={{fontSize: 12, marginTop: 2}}>{a.sub}</div> : null}
                <div className="pl-activity-meta">
                  <span className="pill" style={{fontSize: 10.5}}>{({ turn: t('platform.me.activity_tag_round'), branch: t('platform.me.activity_tag_branch'), script: t('platform.me.activity_tag_script') })[activityType(a)] || a.tag}</span>
                  <span className="muted-2 mono" style={{fontSize: 11}}>{/^\d{4}-\d{2}-\d{2}T/.test(a.ts || "") ? fmtAgo(a.ts) : a.ts}</span>
                </div>
              </div>
            </li>
          ))}
          {filteredActivity.length === 0 && (
            <CSBox color="text-body-secondary" textAlign="center" padding="l">
              {meActivity === null && !IS_ANON
                ? t('platform.me.activity_loading', '正在加载活动…')
                : (ACTIVITY.length === 0
                    ? t('platform.me.activity_empty', '暂无活动。开始游戏、开辟分支或导入剧本后,这里会显示真实记录。')
                    : t('platform.me.activity_no_filter', '未找到此分类的活动'))}
            </CSBox>
          )}
        </ol>
      </CSContainer>
    </CSSpaceBetween>
  );
}

export { MeOverview };
