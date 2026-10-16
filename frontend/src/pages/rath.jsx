/* RATH — Platform 内嵌子页(#rath,游玩 / Play 导航组下,与酒馆平级)。
 *
 * 设计:docs/design/rath_observation_deck_v0.md。后端 rpg/routes/rath.py。
 * 核心铁律(前端视角):这是「离线活世界」实验的**观测面板**,不写游戏 state ——
 * 所有操作(建实验/tick/加速/暂停/归档/引导)都只作用于 rath_experiments / rath_events,
 * 与玩家正在玩的存档 state 无关(存档只被只读地取材料)。
 *
 * 布局:
 *   顶部 — 实验选择/创建区(无实验→存档下拉+启动按钮+只读预检卡片;有实验→下拉切换)。
 *   实验面板(选中后 GET 详情,30s 轮询):
 *     · 状态行卡片:世界时间 + 加速档 SegmentedControl + 世界运行 Toggle(自动推进说明 + 暂停原因徽标)。
 *     · 操作条:推进一步 / 进入游戏(先暂停再走 window.__openContinue) / 归档(二次确认)。
 *     · 角色动态板:fluctlights 卡片网格(goal/stance/private_memories)。
 *     · 日志:顶部引导插入行(单行输入+按钮) + events 列表(新在上),互动事件可展开 transcript。
 *
 * 可见性门控(P0):document.hidden 时详情轮询整段跳过(不发请求,不续 last_viewed_at),
 * 回到前台立即补拉一次;可见时的请求带 ?active=1,与被动轮询区分「真的在看」。
 *
 * 403(flag 未开放)→ 整页空态提示,不渲染任何操作 UI。
 */
import React from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import CSHeader from '@cloudscape-design/components/header';
import CSContainer from '@cloudscape-design/components/container';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSButton from '@cloudscape-design/components/button';
import CSBox from '@cloudscape-design/components/box';
import CSBadge from '@cloudscape-design/components/badge';
import CSAlert from '@cloudscape-design/components/alert';
import CSSelect from '@cloudscape-design/components/select';
import CSSegmentedControl from '@cloudscape-design/components/segmented-control';
import CSInput from '@cloudscape-design/components/input';
import CSToggle from '@cloudscape-design/components/toggle';
import CSColumnLayout from '@cloudscape-design/components/column-layout';
import CSExpandableSection from '@cloudscape-design/components/expandable-section';

import { ConfirmModal } from '../tavern-app.jsx';

const POLL_MS = 30000;
const ACCEL_OPTIONS = [1, 60, 240];

/* ── 纯函数(v3 可视化:河道提示截断/张力 sparkline 映射/事件按世界日分组)──────
 * 均无副作用,供 vitest 直接单测(见 __tests__/rath-viz.test.jsx)。 */

/** 截断长文本用于 hover 提示 / 折叠行摘要预览,末尾加省略号。maxLen 默认 60(中文语境下的经验值)。 */
function _truncateForTip(text, maxLen = 60) {
  const s = String(text == null ? '' : text);
  if (s.length <= maxLen) return s;
  const cut = Math.max(1, maxLen - 1);
  return `${s.slice(0, cut).trimEnd()}…`;
}

/** 从 world_clock_label(如"第14日 19:40")解析出"第N日"前缀;解析不出时返回空串。 */
function _parseWorldDayLabel(label) {
  const m = /^(第\d+日|Day \d+)/.exec(String(label == null ? '' : label));
  return m ? m[1] : '';
}

/** 按世界日分组 events,组内保持原有时序;非相邻的同日不合并(与原始顺序一致地按"day 变化"切组)。 */
function _groupEventsByWorldDay(events) {
  const list = Array.isArray(events) ? events : [];
  const groups = [];
  for (const ev of list) {
    const day = _parseWorldDayLabel(ev && ev.world_clock_label);
    const last = groups[groups.length - 1];
    if (last && last.day === day) {
      last.events.push(ev);
    } else {
      groups.push({ day, events: [ev] });
    }
  }
  return groups;
}

/**
 * 把 tension_hist(≤12 个 0-10 整数)映射成定长 12 格的 sparkline 柱状数据。
 * 数据不足 12 时在前面补占位柱(isPad,极矮/无值),保证多条剧情线对齐;
 * 最后一根真实数据柱标 isLast,供高亮当前张力。
 */
function _tensionSparkline(hist, opts = {}) {
  const { max = 10, trackHeight = 20, minHeight = 2, count = 12 } = opts;
  const src = Array.isArray(hist) ? hist.slice(-count) : [];
  const padCount = Math.max(0, count - src.length);
  const padBars = Array.from({ length: padCount }, () => ({ value: null, height: minHeight, isLast: false, isPad: true }));
  const realBars = src.map((v, i) => {
    const n = Number(v);
    const value = Number.isFinite(n) ? Math.max(0, Math.min(max, n)) : 0;
    const height = Math.max(minHeight, Math.round((value / max) * trackHeight));
    return { value, height, isLast: i === src.length - 1, isPad: false };
  });
  return [...padBars, ...realBars];
}

/* ── 预检 tier 徽标 / 暂停原因徽标文案映射(纯函数,供 vitest 直接单测)──────
 * 均返回 {key, fallback} 或 null,组件里配合 t(key, {defaultValue: fallback}) 使用,
 * 未知取值时兜底成灰色徽标而非崩溃。 */

const PREFLIGHT_TIER_META = {
  full: { color: 'green', key: 'rath_page.preflight.tier_full', fallback: 'Fully stocked' },
  degraded: { color: 'blue', key: 'rath_page.preflight.tier_degraded', fallback: 'Partially degraded' },
  free: { color: 'grey', key: 'rath_page.preflight.tier_free', fallback: 'Free-form evolution' },
};
/** GET /api/rath/preflight 的 tier 字段 → 徽标颜色 + i18n key/兜底文案。未知 tier 兜底灰色徽标,显示原始值。 */
function _preflightTierMeta(tier) {
  return PREFLIGHT_TIER_META[tier] || { color: 'grey', key: null, fallback: String(tier == null ? '' : tier) };
}

const PAUSE_REASON_META = {
  user: { key: 'rath_page.pause_reason.user', fallback: 'Paused' },
  player_active: { key: 'rath_page.pause_reason.player_active', fallback: "You're playing — the world stepped aside" },
  unviewed: { key: 'rath_page.pause_reason.unviewed', fallback: 'Dormant after a long time unseen' },
  no_model: { key: 'rath_page.pause_reason.no_model', fallback: 'No model available' },
};
/** rath_experiments.pause_reason 枚举 → 徽标文案;未知/空值返回 null(不渲染徽标)。 */
function _pauseReasonMeta(reason) {
  return PAUSE_REASON_META[reason] || null;
}

/**
 * 可见性门控(P0):后台标签不应发详情轮询请求——document.hidden 为真时返回 false。
 * 纯函数,接收 document 对象(或等价 {hidden} 形状)方便单测,不直接读全局。
 * `doc` 缺失时保守地当作可见(SSR/无 document 环境不拦截)。
 */
function _shouldFetchOnPoll(doc) {
  return !(doc && doc.hidden);
}

/**
 * GET /api/rath/preflight 响应 → 规范化 preflight 对象;`ok!==true`(含 404/未部署/网络异常,
 * fetch 层已把这些统一 catch 成同一形状)一律返回 null,前端据此静默隐藏卡片、不阻断建实验。
 */
function _normalizePreflightResponse(r) {
  return (r && r.ok === true) ? r : null;
}

function StatCell({ label, value }) {
  return (
    <div>
      <CSBox variant="awsui-key-label">{label}</CSBox>
      <div>{value}</div>
    </div>
  );
}

/* ── 建实验前的只读预检卡片(纯展示组件,preflight=null 时不渲染)───────────────
 * tier 徽标(材料齐全/部分退化/自由演化)+ can_create=false 时的拒绝原因 + warnings 列表。 */
function PreflightCard({ preflight }) {
  const { t } = useTranslation();
  if (!preflight) return null;
  const meta = _preflightTierMeta(preflight.tier);
  return (
    <div className="rath-preflight-card" data-testid="rath-preflight-card">
      <CSSpaceBetween size="xs">
        <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
          <CSBadge color={meta.color}>{meta.key ? t(meta.key, { defaultValue: meta.fallback }) : meta.fallback}</CSBadge>
          <CSBox color="text-body-secondary" fontSize="body-s">
            {t('rath_page.preflight.summary', {
              defaultValue: `河道 ${preflight.river?.beats ?? 0} 拍 · 角色 ${preflight.cast?.count ?? 0} 人 · 世界书 ${preflight.worldbook?.count ?? 0} 条`,
              beats: preflight.river?.beats ?? 0,
              cast: preflight.cast?.count ?? 0,
              worldbook: preflight.worldbook?.count ?? 0,
            })}
          </CSBox>
        </CSSpaceBetween>
        {preflight.can_create === false && preflight.reason && (
          <CSAlert type="warning">{preflight.reason}</CSAlert>
        )}
        {Array.isArray(preflight.warnings) && preflight.warnings.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {preflight.warnings.map((w, i) => (
              <li key={i}><CSBox fontSize="body-s" color="text-body-secondary">{w}</CSBox></li>
            ))}
          </ul>
        )}
      </CSSpaceBetween>
    </div>
  );
}

/* ── 暂停原因徽标(纯展示组件,reason 未知/为空时不渲染)───────────────────── */
function PauseReasonBadge({ reason }) {
  const { t } = useTranslation();
  const meta = _pauseReasonMeta(reason);
  if (!meta) return null;
  return <CSBadge color="grey">{t(meta.key, { defaultValue: meta.fallback })}</CSBadge>;
}

/* ── 实验选择/创建条 ─────────────────────────────────────────────── */
function ExperimentPicker({ experiments, activeId, onSwitch, onCreated }) {
  const { t } = useTranslation();
  const [saves, setSaves] = useState(null);
  const [pickedSaveId, setPickedSaveId] = useState(null);
  const [creating, setCreating] = useState(false);
  // 选中存档后的只读预检(材料充足度)。404/异常一律静默隐藏,不阻断既有建实验流程。
  const [preflight, setPreflight] = useState(null);

  useEffect(() => {
    if (experiments.length > 0) return; // 已有实验时不必拉存档列表
    let alive = true;
    window.api.saves.list()
      .then((r) => {
        const list = Array.isArray(r) ? r : (r?.items || r?.saves || []);
        if (alive) setSaves(list);
      })
      .catch(() => { if (alive) setSaves([]); });
    return () => { alive = false; };
  }, [experiments.length]);

  useEffect(() => {
    setPreflight(null);
    if (!pickedSaveId) return;
    let alive = true;
    window.api.rath.preflight(pickedSaveId)
      .then((r) => { if (alive) setPreflight(_normalizePreflightResponse(r)); })
      .catch(() => { if (alive) setPreflight(null); });
    return () => { alive = false; };
  }, [pickedSaveId]);

  const saveOptions = (saves || []).map((s) => ({
    value: String(s.id),
    label: `${s.title || t('rath_page.picker.untitled_save', { defaultValue: '未命名存档' })} · #${s.id}`,
  }));

  const doCreate = async () => {
    if (!pickedSaveId || creating) return;
    setCreating(true);
    try {
      const r = await window.api.rath.create({ save_id: Number(pickedSaveId) });
      if (!r || r.ok === false) throw new Error(r?.error || t('rath_page.toast.create_failed', { defaultValue: '建立实验失败' }));
      window.__apiToast?.(t('rath_page.toast.created', { defaultValue: '实验已启动' }), { kind: 'ok', duration: 2000 });
      onCreated?.(r.experiment);
    } catch (e) {
      window.__apiToast?.(t('rath_page.toast.create_failed', { defaultValue: '建立实验失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      setCreating(false);
    }
  };

  if (experiments.length > 0) {
    const activeOpt = experiments.find((e) => String(e.id) === String(activeId));
    return (
      <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
        <CSSelect
          selectedOption={activeOpt ? { value: String(activeOpt.id), label: `#${activeOpt.id} · ${activeOpt.world_clock_label || ''}` } : null}
          options={experiments.map((e) => ({ value: String(e.id), label: `#${e.id} · ${e.world_clock_label || ''}${e.status === 'paused' ? t('rath_page.picker.paused_suffix', { defaultValue: '(已暂停)' }) : ''}` }))}
          onChange={({ detail }) => onSwitch(Number(detail.selectedOption.value))}
          placeholder={t('rath_page.picker.switch_placeholder', { defaultValue: '切换实验' })}
        />
      </CSSpaceBetween>
    );
  }

  return (
    <CSContainer>
      <CSSpaceBetween size="s">
        <div>
          <CSBox variant="h3">{t('rath_page.picker.intro_title', { defaultValue: '离线世界仍在继续' })}</CSBox>
          <CSBox color="text-body-secondary" fontSize="body-s">
            {t('rath_page.picker.intro_desc', { defaultValue: '给一个存档开一场有界实验:你离开之后,世界按真实时间继续运转,议程 NPC 会真的互相对话、留下痕迹——回来问问他们,他们记得。' })}
          </CSBox>
        </div>
        <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
          <CSSelect
            selectedOption={pickedSaveId ? saveOptions.find((o) => o.value === pickedSaveId) : null}
            options={saveOptions}
            onChange={({ detail }) => setPickedSaveId(detail.selectedOption.value)}
            placeholder={t('rath_page.picker.save_placeholder', { defaultValue: '选择一个存档' })}
            empty={t('rath_page.picker.no_saves', { defaultValue: '暂无存档' })}
            loadingText={t('common.loading')}
            statusType={saves == null ? 'loading' : 'finished'}
          />
          <CSButton
            variant="primary"
            disabled={!pickedSaveId || creating || preflight?.can_create === false}
            loading={creating}
            onClick={doCreate}
          >
            {t('rath_page.picker.launch_btn', { defaultValue: '启动实验' })}
          </CSButton>
        </CSSpaceBetween>

        <PreflightCard preflight={preflight} />
      </CSSpaceBetween>
    </CSContainer>
  );
}

/* ── 单条日志事件(事件 / 互动 / 引导,互动可展开 transcript,长纪要可展开查看全文)── */
function EventRow({ ev }) {
  const { t } = useTranslation();
  const isScene = ev.kind === 'scene';
  const isDirective = ev.kind === 'directive';
  const transcript = (ev.payload && Array.isArray(ev.payload.transcript)) ? ev.payload.transcript : [];
  const summary = ev.summary || '';
  const previewSummary = isScene ? _truncateForTip(summary, 60) : summary;
  const summaryTruncated = isScene && previewSummary !== summary;
  const badgeColor = isDirective ? 'blue' : (isScene ? 'green' : 'grey');
  const badgeText = isDirective
    ? t('rath_page.event.kind_directive', { defaultValue: '引导' })
    : (isScene ? t('rath_page.event.kind_scene', { defaultValue: '互动' }) : t('rath_page.event.kind_heartbeat', { defaultValue: '事件' }));
  const body = (
    <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
      <CSBadge color={badgeColor}>{badgeText}</CSBadge>
      <CSBox color="text-body-secondary" fontSize="body-s">{ev.world_clock_label}</CSBox>
      <CSBox>{previewSummary || t('rath_page.event.no_summary', { defaultValue: '(无摘要)' })}</CSBox>
    </CSSpaceBetween>
  );
  const expandable = isScene && (transcript.length > 0 || summaryTruncated);
  if (!expandable) {
    return <div className="rath-event-row">{body}</div>;
  }
  return (
    <div className="rath-event-row">
      <CSExpandableSection headerText={body} variant="footer">
        <CSSpaceBetween size="xs">
          {summaryTruncated && <CSBox fontSize="body-s">{summary}</CSBox>}
          {transcript.map((line, i) => (
            <div key={i} style={{ fontSize: 13 }}>
              <strong>{line.speaker || '?'}</strong>{': '}{line.line}
            </div>
          ))}
        </CSSpaceBetween>
      </CSExpandableSection>
    </div>
  );
}

/* ── 剧情线张力 sparkline(12 格 2px 竖条,当前值高亮)────────────────────── */
function ThreadSparkline({ hist }) {
  const bars = _tensionSparkline(hist);
  const barW = 2;
  const gap = 2;
  const trackH = 20;
  const w = bars.length * (barW + gap) - gap;
  return (
    <svg width={w} height={trackH} viewBox={`0 0 ${w} ${trackH}`} className="rath-spark" aria-hidden="true">
      {bars.map((b, i) => (
        <rect
          key={i}
          x={i * (barW + gap)}
          y={trackH - b.height}
          width={barW}
          height={b.height}
          rx={1}
          style={{
            fill: b.isPad
              ? 'var(--muted-3, #4d4842)'
              : (b.isLast ? 'var(--accent, #c96442)' : 'var(--muted-2, #6b655e)'),
            opacity: b.isPad ? 0.5 : 1,
          }}
        />
      ))}
    </svg>
  );
}

/* ── 选中实验的完整面板 ─────────────────────────────────────────────── */
function ExperimentPanel({ expId }) {
  const { t } = useTranslation();
  const [detail, setDetail] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [ticking, setTicking] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [accelBusy, setAccelBusy] = useState(false);
  const [archiveConfirm, setArchiveConfirm] = useState(false);
  const pollRef = useRef(null);

  // 可见性感知(P0):后台标签不发详情请求——既省掉整读 state_snapshot 的开销,也不再
  // 无条件续命 last_viewed_at(否则「标签开着不看」会让 72h 无人看自动暂停永远触发不了)。
  // 页面可见时才带 ?active=1(真正的「看」),回到前台立即补拉一次。
  const load = useCallback(async (silent) => {
    if (typeof document !== 'undefined' && !_shouldFetchOnPoll(document)) return; // 后台标签:静默跳过,不发请求
    try {
      const r = await window.api.rath.detail(expId, { active: true });
      if (!r || r.ok === false) throw new Error(r?.error || t('rath_page.toast.load_failed', { defaultValue: '加载实验失败' }));
      setDetail(r);
      setLoadErr(null);
    } catch (e) {
      if (!silent) setLoadErr(e?.message || String(e));
    }
  }, [expId, t]);

  useEffect(() => {
    setDetail(null); setLoadErr(null);
    load(false);
    pollRef.current = setInterval(() => load(true), POLL_MS);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [expId, load]);

  useEffect(() => {
    const onVisible = () => { if (typeof document !== 'undefined' && _shouldFetchOnPoll(document)) load(true); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [load]);

  const exp = detail?.experiment;
  const fluctlights = detail?.fluctlights || [];
  const events = detail?.events || [];
  const trace = detail?.trace || [];
  const threads = detail?.threads || [];
  const relations = detail?.relations || [];
  const canon = detail?.canon || null;
  const eventGroups = _groupEventsByWorldDay(events);
  // 推进后快轮询(实时看到运行日志):点击推进一步后 2 分钟内每 5s 拉一次
  const fastPollUntilRef = useRef(0);
  useEffect(() => {
    const iv = setInterval(() => {
      if (Date.now() < fastPollUntilRef.current) load(true);
    }, 5000);
    return () => clearInterval(iv);
  }, [load]);

  const doTick = async () => {
    if (ticking) return;
    setTicking(true);
    try {
      // 后端已异步化:立即返回 started,推进在后台完成(约1分钟),日志轮询自然刷出。
      const r = await window.api.rath.tick(expId);
      if (r && r.reason === 'no_model') {
        // 无可用模型(BYOK 缺失):后端已自动暂停实验(pause_reason='no_model'),
        // danger toast 引导去配置模型,而非笼统的"未执行"。
        window.__apiToast?.(
          t('rath_page.toast.no_model', { defaultValue: '无可用模型,实验已自动暂停——请到 设置→模型 配置凭据' }),
          { kind: 'danger', duration: 4200 },
        );
      } else if (!r || r.ok === false) {
        window.__apiToast?.(t('rath_page.toast.tick_declined', { defaultValue: '本次推进未执行' }), { kind: 'warn', detail: r?.error || r?.reason });
      } else {
        window.__apiToast?.(t('rath_page.toast.tick_started', { defaultValue: '已开始推进,运行日志实时可见(约1分钟完成)' }), { kind: 'ok', duration: 3600 });
        fastPollUntilRef.current = Date.now() + 120000;
      }
      await load(true);
    } catch (e) {
      window.__apiToast?.(t('rath_page.toast.tick_failed', { defaultValue: '推进请求失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      setTicking(false);
    }
  };

  const doPauseResume = async () => {
    if (statusBusy || !exp) return;
    setStatusBusy(true);
    const action = exp.status === 'running' ? 'pause' : 'resume';
    try {
      const r = await window.api.rath[action](expId);
      if (!r || r.ok === false) throw new Error(r?.error);
      setDetail((d) => (d ? { ...d, experiment: r.experiment } : d));
      window.__apiToast?.(
        action === 'pause' ? t('rath_page.toast.paused', { defaultValue: '已暂停' }) : t('rath_page.toast.resumed', { defaultValue: '已恢复' }),
        { kind: 'ok', duration: 1600 },
      );
    } catch (e) {
      window.__apiToast?.(t('rath_page.toast.action_failed', { defaultValue: '操作失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      setStatusBusy(false);
    }
  };

  const doArchive = async () => {
    setArchiveConfirm(false);
    try {
      const r = await window.api.rath.archive(expId);
      if (!r || r.ok === false) throw new Error(r?.error);
      window.__apiToast?.(t('rath_page.toast.archived', { defaultValue: '实验已归档' }), { kind: 'ok', duration: 1800 });
      window.dispatchEvent(new CustomEvent('rpg-rath-archived', { detail: { id: expId } }));
    } catch (e) {
      window.__apiToast?.(t('rath_page.toast.action_failed', { defaultValue: '操作失败' }), { kind: 'danger', detail: e?.message });
    }
  };

  // 进入游戏(P1):运行中时先暂停(等成功)再跳转,避免离线世界和玩家回合并发写同一存档;
  // 已暂停/已归档时直接跳转。跳转走全局 __openContinue 契约(platform-app.jsx),按
  // save_kind 分流酒馆/游戏台,与「继续」按钮全站同一入口。
  const [entering, setEntering] = useState(false);
  const doEnterGame = async () => {
    if (entering || !exp) return;
    setEntering(true);
    try {
      if (exp.status === 'running') {
        const r = await window.api.rath.pause(expId);
        if (!r || r.ok === false) throw new Error(r?.error || t('rath_page.toast.action_failed', { defaultValue: '操作失败' }));
        setDetail((d) => (d ? { ...d, experiment: r.experiment } : d));
      }
      window.__openContinue?.({ id: exp.save_id, save_kind: exp.save_kind });
    } catch (e) {
      window.__apiToast?.(
        t('rath_page.toast.enter_game_failed', { defaultValue: '暂停世界失败,未进入游戏' }),
        { kind: 'danger', detail: e?.message },
      );
    } finally {
      setEntering(false);
    }
  };

  const [directiveInput, setDirectiveInput] = useState('');
  const [directiveBusy, setDirectiveBusy] = useState(false);
  const doDirective = async () => {
    const text = directiveInput.trim();
    if (directiveBusy || !text) return;
    setDirectiveBusy(true);
    try {
      const r = await window.api.rath.directive(expId, text);
      if (r && r.ok === false) throw new Error(r.error || t('rath_page.directive.fail', { defaultValue: '插入失败' }));
      setDirectiveInput('');
      window.__apiToast?.(t('rath_page.directive.inserted', { defaultValue: '引导已插入,从当前时间点开始生效' }), { kind: 'ok' });
      await load(true);
    } catch (e) {
      window.__apiToast?.(t('rath_page.directive.fail', { defaultValue: '插入失败' }), { kind: 'danger', detail: String(e?.message || e) });
    } finally { setDirectiveBusy(false); }
  };

  const doAccel = async (accel) => {
    if (accelBusy || !exp || Number(exp.accel) === Number(accel)) return;
    setAccelBusy(true);
    try {
      const r = await window.api.rath.accel(expId, accel);
      if (!r || r.ok === false) throw new Error(r?.error);
      setDetail((d) => (d ? { ...d, experiment: r.experiment } : d));
    } catch (e) {
      window.__apiToast?.(t('rath_page.toast.action_failed', { defaultValue: '操作失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      setAccelBusy(false);
    }
  };

  if (loadErr && !exp) {
    return <CSAlert type="error" header={t('rath_page.load_error_header', { defaultValue: '加载失败' })}>{loadErr}</CSAlert>;
  }
  if (!exp) {
    return <CSBox color="text-body-secondary">{t('common.loading')}</CSBox>;
  }

  const budget = exp.budget || {};
  const running = exp.status === 'running';
  const accelMin = Math.round(Number(exp.accel) || 1);
  const tickIntervalMinutes = Math.round((Number(exp.tick_interval_sec) || 1800) / 60);

  return (
    <CSSpaceBetween size="l">
      {/* 状态行卡片 */}
      <CSContainer>
        <CSColumnLayout columns={2} variant="text-grid">
          <StatCell
            label={t('rath_page.stat.clock', { defaultValue: '世界时间' })}
            value={
              <>
                <CSBox fontSize="heading-xl" fontWeight="bold">{exp.world_clock_label || '—'}</CSBox>
                <CSBox color="text-body-secondary" fontSize="body-s" margin={{ top: 'xxs' }}>
                  {t('rath_page.stat.clock_hint', {
                    defaultValue: `时间流速 ${accelMin}× — 现实 1 分钟 ≈ 世界 ${accelMin} 分钟;推进一步 ≈ 世界 1 小时`,
                    accel: accelMin,
                  })}
                </CSBox>
              </>
            }
          />
          <StatCell
            label={t('rath_page.stat.accel', { defaultValue: '时间流速' })}
            value={
              <CSSegmentedControl
                selectedId={String(exp.accel)}
                options={ACCEL_OPTIONS.map((a) => ({ id: String(a), text: `${a}×` }))}
                onChange={({ detail }) => doAccel(Number(detail.selectedId))}
              />
            }
          />
        </CSColumnLayout>

        {canon && (
          <div className="rath-canon-row">
            <CSBox fontSize="body-s" color="text-body-secondary">
              {canon.current_chapter != null
                ? t('rath_page.canon.progress', {
                    defaultValue: `原著河道 第${canon.current_chapter}章 · ${canon.cursor}/${canon.total}`,
                    chapter: canon.current_chapter, cursor: canon.cursor, total: canon.total,
                  })
                : t('rath_page.canon.finished', {
                    defaultValue: `原著河道 已读完 · ${canon.cursor}/${canon.total}`,
                    cursor: canon.cursor, total: canon.total,
                  })}
            </CSBox>
            <div
              className="rath-canon-bar-wrap"
              {...(canon.next_text ? { 'data-tip': _truncateForTip(canon.next_text, 60) } : {})}
            >
              <div className="rath-canon-bar-track">
                <div
                  className="rath-canon-bar-fill"
                  style={{ width: `${canon.total > 0 ? Math.min(100, Math.max(0, (canon.cursor / canon.total) * 100)) : 0}%` }}
                />
              </div>
              {canon.stall >= 4 && (
                <span
                  className="rath-canon-bar-stall"
                  data-tip={t('rath_page.canon.stall_tip', { defaultValue: `滞留 ${canon.stall} 拍未推进`, stall: canon.stall })}
                />
              )}
            </div>
          </div>
        )}
      </CSContainer>

      {/* 世界运行开关 */}
      <CSContainer>
        <CSSpaceBetween size="xs">
          <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
            <CSToggle checked={running} disabled={statusBusy} onChange={doPauseResume}>
              {t('rath_page.run_toggle.label', { defaultValue: '世界运行' })}
            </CSToggle>
            {!running && <PauseReasonBadge reason={exp.pause_reason} />}
          </CSSpaceBetween>
          <CSBox color="text-body-secondary" fontSize="body-s">
            {t('rath_page.run_toggle.hint', {
              defaultValue: `开启时每 ${tickIntervalMinutes} 分钟自动推进一次 · 今日 ${exp.ticks_today ?? 0}/${budget.ticks_per_day ?? 48} 次`,
              minutes: tickIntervalMinutes,
              ticksToday: exp.ticks_today ?? 0,
              ticksPerDay: budget.ticks_per_day ?? 48,
            })}
          </CSBox>
        </CSSpaceBetween>
      </CSContainer>

      {/* 操作条 */}
      <CSSpaceBetween size="xs">
        <CSSpaceBetween direction="horizontal" size="xs">
          <CSButton variant="primary" loading={ticking} onClick={doTick}>
            {t('rath_page.action.tick', { defaultValue: '推进一步' })}
          </CSButton>
          <CSButton iconName="caret-right-filled" loading={entering} onClick={doEnterGame}>
            {t('rath_page.action.enter_game', { defaultValue: '进入游戏' })}
          </CSButton>
          <CSButton onClick={() => setArchiveConfirm(true)}>
            {t('rath_page.action.archive', { defaultValue: '归档' })}
          </CSButton>
        </CSSpaceBetween>
        <CSBox color="text-body-secondary" fontSize="body-s">
          {t('rath_page.action.enter_game_hint', { defaultValue: '暂停世界并进入该存档游玩;离开约2小时后世界自动继续' })}
        </CSBox>
      </CSSpaceBetween>

      {/* 日志:顶部插入引导 + events 列表 */}
      <CSContainer header={<CSHeader variant="h2">{t('rath_page.timeline.title', { defaultValue: '日志' })}</CSHeader>}>
        <CSSpaceBetween size="s">
          <CSSpaceBetween size="xs">
            <CSSpaceBetween direction="horizontal" size="xs" alignItems="center">
              <div style={{ flex: 1, minWidth: 240 }}>
                <CSInput
                  value={directiveInput}
                  onChange={({ detail }) => setDirectiveInput(detail.value)}
                  placeholder={t('rath_page.directive.placeholder', { defaultValue: '在此刻插入一条引导,影响之后的世界演化…' })}
                  onKeyDown={({ detail }) => { if (detail.key === 'Enter') doDirective(); }}
                />
              </div>
              <CSButton loading={directiveBusy} disabled={!directiveInput.trim()} onClick={doDirective}>
                {t('rath_page.directive.insert_btn', { defaultValue: '插入引导' })}
              </CSButton>
            </CSSpaceBetween>
            <CSBox color="text-body-secondary" fontSize="body-s">
              {t('rath_page.directive.hint', { defaultValue: '最新一条引导生效;历史引导保留在日志中。' })}
            </CSBox>
          </CSSpaceBetween>

          {events.length === 0 ? (
            <CSBox color="text-body-secondary" textAlign="center" padding={{ vertical: 'l' }}>
              {t('rath_page.timeline.empty', { defaultValue: '尚无日志——点「推进一步」触发第一次自动推进。' })}
            </CSBox>
          ) : (
            <CSSpaceBetween size="s">
              {eventGroups.map((g, gi) => (
                <div key={gi}>
                  {g.day && (
                    <div className="rath-day-header">{g.day}</div>
                  )}
                  <CSSpaceBetween size="xs">
                    {g.events.map((ev) => <EventRow key={ev.id} ev={ev} />)}
                  </CSSpaceBetween>
                </div>
              ))}
            </CSSpaceBetween>
          )}
        </CSSpaceBetween>
      </CSContainer>

      {/* 角色动态板 */}
      <CSContainer header={<CSHeader variant="h2">{t('rath_page.fluctlights.title', { defaultValue: '角色动态' })}</CSHeader>}>
        {threads.length > 0 && (
          <div className="rath-threads">
            {threads.map((th) => {
              const stage = th.stage || 'rising';
              const stageLabel = {
                seed: t('rath_page.threads.stage_seed', { defaultValue: '萌芽' }),
                rising: t('rath_page.threads.stage_rising', { defaultValue: '发展' }),
                climax: t('rath_page.threads.stage_climax', { defaultValue: '高潮' }),
                aftermath: t('rath_page.threads.stage_aftermath', { defaultValue: '余波' }),
              }[stage] || t('rath_page.threads.stage_rising', { defaultValue: '发展' });
              return (
                <div key={th.id} className="rath-thread-row">
                  <span className={`rath-stage-tag rath-stage-tag--${stage}`}>{stageLabel}</span>
                  <span className="rath-thread-desc">{th.desc}</span>
                  <ThreadSparkline hist={th.tension_hist} />
                </div>
              );
            })}
          </div>
        )}
        {fluctlights.length === 0 ? (
          <CSBox color="text-body-secondary" textAlign="center" padding={{ vertical: 'l' }}>
            {t('rath_page.fluctlights.empty', { defaultValue: '尚无角色动态——推进几步或进游戏玩几回合后,这里会出现各角色的目标、态度与私记。' })}
          </CSBox>
        ) : (
          <div className="rath-fluctlight-grid">
            {fluctlights.map((f) => (
              <div key={f.name} className="rath-fluctlight-card">
                <CSBox fontWeight="bold">{f.name}{f.kind === 'player' ? t('rath_page.fluctlights.player_tag', { defaultValue: '(玩家)' }) : ''}{f.status ? `·${f.status}` : ''}</CSBox>
                {(f.location || f.activity) && (
                  <CSBox fontSize="body-s" color="text-body-secondary">
                    {f.location}{f.location && f.activity ? ' · ' : ''}{f.activity}
                  </CSBox>
                )}
                {f.goal && <CSBox fontSize="body-s" margin={{ top: 'xxs' }}>{t('rath_page.fluctlights.goal_prefix', { defaultValue: '目标：' })}{f.goal}</CSBox>}
                {f.stance && <CSBox fontSize="body-s" color="text-body-secondary">{t('rath_page.fluctlights.stance_prefix', { defaultValue: '态度：' })}{f.stance}</CSBox>}
                {Array.isArray(f.private_memories) && f.private_memories.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {f.private_memories.map((m, i) => (
                      <div key={i} style={{ fontSize: 12, fontStyle: 'italic', color: 'var(--text-quiet, #a8a195)', marginTop: 2 }}>
                        {'“'}{m}{'”'}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="rath-relations">
          <CSBox variant="h3" margin={{ bottom: 'xs' }}>{t('rath_page.relations.title', { defaultValue: '人物关系' })}</CSBox>
          {relations.length === 0 ? (
            <CSBox color="text-body-secondary" fontSize="body-s">
              {t('rath_page.relations.empty', { defaultValue: '关系尚在形成' })}
            </CSBox>
          ) : (
            <CSSpaceBetween size="xs">
              {relations.map((r, i) => (
                <div key={`${r.a}-${r.b}-${i}`} className="rath-relation-row">
                  <CSBox fontSize="body-s">{r.a} — {r.b}{r.kind ? `: ${r.kind}` : ''}</CSBox>
                  {r.note && <CSBox fontSize="body-s" color="text-body-secondary">{r.note}</CSBox>}
                </div>
              ))}
            </CSSpaceBetween>
          )}
        </div>
      </CSContainer>

      {/* 运行日志(思考流/执行层) */}
      <CSExpandableSection variant="container" headerText={t('rath_page.trace.title', { defaultValue: '运行日志' })} headerDescription={t('rath_page.trace.desc', { defaultValue: '引擎每一步的决策与验收结果:材料装配、选角、模型产出与拒收原因。' })}>
        {trace.length === 0 ? (
          <CSBox color="text-body-secondary" fontSize="body-s">{t('rath_page.trace.empty', { defaultValue: '暂无运行记录——推进一步后这里会实时滚动。' })}</CSBox>
        ) : (
          <div style={{ maxHeight: 260, overflowY: 'auto', fontFamily: 'var(--font-family-monospace, monospace)', fontSize: 12, lineHeight: 1.7 }}>
            {trace.map((r) => (
              <div key={r.id} style={{ borderBottom: '1px solid var(--color-border-divider-default, #e9ebed)', padding: '2px 0' }}>
                <span style={{ opacity: 0.55, marginRight: 8 }}>{r.world_clock_label}</span>
                {r.summary}
              </div>
            ))}
          </div>
        )}
      </CSExpandableSection>

      <ConfirmModal
        open={archiveConfirm}
        title={t('rath_page.archive_confirm.title', { defaultValue: '归档这场实验？' })}
        body={t('rath_page.archive_confirm.body', { defaultValue: '归档后实验停止运行,已产生的观测记录仍会保留,但不能再恢复运行。' })}
        confirmLabel={t('rath_page.action.archive', { defaultValue: '归档' })}
        danger
        onClose={() => setArchiveConfirm(false)}
        onConfirm={doArchive}
      />
    </CSSpaceBetween>
  );
}

export default function RathPage() {
  const { t } = useTranslation();
  const [experiments, setExperiments] = useState(null);
  const [denied, setDenied] = useState(false);
  const [activeId, setActiveId] = useState(null);

  const reloadList = useCallback(async () => {
    try {
      const r = await window.api.rath.list();
      if (r && r.ok === false) {
        setDenied(true);
        setExperiments([]);
        return;
      }
      const list = Array.isArray(r?.experiments) ? r.experiments : [];
      setExperiments(list);
      setActiveId((cur) => {
        if (cur != null && list.some((e) => String(e.id) === String(cur))) return cur;
        return list.length ? list[0].id : null;
      });
    } catch (e) {
      if (e && e.status === 403) { setDenied(true); setExperiments([]); return; }
      window.__apiToast?.(t('rath_page.toast.load_failed', { defaultValue: '加载实验失败' }), { kind: 'danger', detail: e?.message });
      setExperiments([]);
    }
  }, [t]);

  useEffect(() => { reloadList(); }, [reloadList]);

  useEffect(() => {
    const onArchived = () => { setActiveId(null); reloadList(); };
    window.addEventListener('rpg-rath-archived', onArchived);
    return () => window.removeEventListener('rpg-rath-archived', onArchived);
  }, [reloadList]);

  if (denied) {
    return (
      <div className="pl-sec">
        <CSAlert type="info" header={t('rath_page.denied_header', { defaultValue: 'RATH 未对当前账号开放' })}>
          {t('rath_page.denied_body', { defaultValue: 'RATH 实验未对当前账号开放' })}
        </CSAlert>
      </div>
    );
  }

  return (
    <div className="pl-sec">
      <CSSpaceBetween size="l">
        <CSHeader variant="h1" description={t('rath_page.header.description', { defaultValue: '离线活世界实验:玩家不在时,世界仍按有界规则继续运转。' })}>
          {t('rath_page.header.title', { defaultValue: 'RATH' })}
        </CSHeader>

        {experiments == null ? (
          <CSBox color="text-body-secondary">{t('common.loading')}</CSBox>
        ) : (
          <ExperimentPicker
            experiments={experiments}
            activeId={activeId}
            onSwitch={setActiveId}
            onCreated={(exp) => { reloadList(); if (exp && exp.id != null) setActiveId(exp.id); }}
          />
        )}

        {activeId != null && <ExperimentPanel expId={activeId} />}
      </CSSpaceBetween>

      <style>{`
        .rath-fluctlight-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
          gap: 12px;
        }
        .rath-fluctlight-card {
          border: 1px solid var(--border, #3a352e);
          border-radius: 8px;
          padding: 12px 14px;
        }
        .rath-event-row {
          border-bottom: 1px solid var(--border, #3a352e);
          padding: 6px 0;
        }
        .rath-event-row:last-child { border-bottom: none; }

        /* 建实验前的只读预检卡片 */
        .rath-preflight-card {
          border: 1px solid var(--border, #3a352e);
          border-radius: 8px;
          padding: 10px 14px;
        }

        /* 原著河道进度条 */
        .rath-canon-row { margin-top: 12px; }
        .rath-canon-bar-wrap { position: relative; margin-top: 6px; padding-right: 4px; }
        .rath-canon-bar-track {
          height: 4px;
          background: rgba(255, 255, 255, 0.06);
          border-radius: 999px;
          overflow: hidden;
        }
        .rath-canon-bar-fill {
          height: 100%;
          background: var(--accent, #c96442);
          border-radius: 999px;
          transition: width var(--m-slow, 240ms) var(--m-out, cubic-bezier(0.16, 1, 0.3, 1));
        }
        .rath-canon-bar-stall {
          position: absolute;
          right: 0;
          top: 50%;
          width: 6px; height: 6px;
          border-radius: 50%;
          background: var(--warn, #d4b366);
          transform: translate(50%, -50%);
          box-shadow: 0 0 0 2px var(--panel-2, #282623);
        }

        /* 剧情线:阶段徽标 + 张力 sparkline */
        .rath-threads { margin-bottom: 12px; display: grid; gap: 2px; }
        .rath-thread-row {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 5px 0;
        }
        .rath-stage-tag {
          flex-shrink: 0;
          display: inline-block;
          font-size: 11px;
          line-height: 1.6;
          padding: 1px 8px;
          border-radius: 999px;
          border: 1px solid var(--border, #3a352e);
          color: var(--muted, #968f85);
          white-space: nowrap;
          transition: color var(--m-fast, 100ms) ease, border-color var(--m-fast, 100ms) ease, background-color var(--m-fast, 100ms) ease;
        }
        .rath-stage-tag--climax {
          color: var(--accent, #c96442);
          border-color: var(--accent-edge, rgba(201, 100, 66, 0.42));
          background: var(--accent-soft, rgba(201, 100, 66, 0.14));
        }
        .rath-stage-tag--aftermath {
          color: var(--muted-2, #6b655e);
          opacity: 0.9;
        }
        .rath-thread-desc {
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          font-size: 13px;
          color: var(--muted, #968f85);
        }
        .rath-spark { flex-shrink: 0; display: block; }

        /* 人物关系 */
        .rath-relations { margin-top: 16px; }
        .rath-relation-row {
          border-bottom: 1px solid var(--border, #3a352e);
          padding: 6px 0;
        }
        .rath-relation-row:last-child { border-bottom: none; }

        /* 事件按世界日分组的组头 */
        .rath-day-header {
          font-size: 12px;
          letter-spacing: 0.03em;
          color: var(--muted, #968f85);
          padding: 4px 0 6px;
          border-bottom: 1px dashed var(--border, #3a352e);
          margin-bottom: 4px;
        }
      `}</style>
    </div>
  );
}

export {
  _groupEventsByWorldDay, _parseWorldDayLabel, _tensionSparkline, _truncateForTip,
  _preflightTierMeta, _pauseReasonMeta, _shouldFetchOnPoll, _normalizePreflightResponse,
  ExperimentPanel, PreflightCard, PauseReasonBadge,
};
