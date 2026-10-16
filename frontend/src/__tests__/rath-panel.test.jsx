/* rath-panel.test.jsx — RATH v4 前端接线回归测试。
 *
 * 覆盖本轮四块行为(与 pages/rath.jsx 顶部注释一致):
 *   · 可见性门控纯函数 _shouldFetchOnPoll + ExperimentPanel 实际行为(后台标签不发详情
 *     请求,回前台立即补拉一次,可见时的请求带 {active:true})。
 *   · preflight 预检卡片渲染分支(纯函数 _preflightTierMeta/_normalizePreflightResponse +
 *     展示组件 PreflightCard:tier 徽标、can_create=false 拒绝原因、warnings 列表、null 隐藏)。
 *   · pause_reason 徽标映射(纯函数 _pauseReasonMeta + 展示组件 PauseReasonBadge)。
 *   · 「进入游戏」按钮先暂停(等成功)后跳转的调用顺序(window.api.rath.pause →
 *     window.__openContinue),已暂停时跳过 pause 直接跳转。
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  _shouldFetchOnPoll, _pauseReasonMeta, _preflightTierMeta, _normalizePreflightResponse,
  ExperimentPanel, PreflightCard, PauseReasonBadge,
} from '../pages/rath.jsx';

function setDocumentHidden(hidden) {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
}

afterEach(() => {
  setDocumentHidden(false);
  window.api = undefined;
  delete window.__apiToast;
  delete window.__openContinue;
});

describe('_shouldFetchOnPoll — 可见性门控纯函数', () => {
  it('document.hidden=false → 应发请求', () => {
    expect(_shouldFetchOnPoll({ hidden: false })).toBe(true);
  });
  it('document.hidden=true → 不应发请求', () => {
    expect(_shouldFetchOnPoll({ hidden: true })).toBe(false);
  });
  it('缺失 document(SSR)→ 保守当作可见', () => {
    expect(_shouldFetchOnPoll(null)).toBe(true);
    expect(_shouldFetchOnPoll(undefined)).toBe(true);
  });
});

describe('_pauseReasonMeta / PauseReasonBadge — 暂停原因徽标映射', () => {
  it('四个枚举值都有对应文案', () => {
    expect(_pauseReasonMeta('user').fallback).toBe('Paused');
    expect(_pauseReasonMeta('player_active').fallback).toBe("You're playing — the world stepped aside");
    expect(_pauseReasonMeta('unviewed').fallback).toBe('Dormant after a long time unseen');
    expect(_pauseReasonMeta('no_model').fallback).toBe('No model available');
  });
  it('未知/空值返回 null', () => {
    expect(_pauseReasonMeta('bogus')).toBeNull();
    expect(_pauseReasonMeta(null)).toBeNull();
    expect(_pauseReasonMeta(undefined)).toBeNull();
  });
  it('渲染徽标文案', () => {
    render(<PauseReasonBadge reason="player_active" />);
    expect(screen.getByText('你在游玩，世界让路')).toBeTruthy();
  });
  it('reason 为空/未知时不渲染任何内容', () => {
    const { container } = render(<PauseReasonBadge reason={null} />);
    expect(container.firstChild).toBeNull();
  });
});

describe('_preflightTierMeta / _normalizePreflightResponse — 预检纯函数', () => {
  it('三档 tier 都有颜色 + 文案', () => {
    expect(_preflightTierMeta('full')).toMatchObject({ color: 'green', fallback: 'Fully stocked' });
    expect(_preflightTierMeta('degraded')).toMatchObject({ color: 'blue', fallback: 'Partially degraded' });
    expect(_preflightTierMeta('free')).toMatchObject({ color: 'grey', fallback: 'Free-form evolution' });
  });
  it('未知 tier 兜底灰色徽标 + 原始值', () => {
    expect(_preflightTierMeta('weird')).toMatchObject({ color: 'grey', key: null, fallback: 'weird' });
  });
  it('ok!==true(404/异常统一形态)一律规范化为 null', () => {
    expect(_normalizePreflightResponse(null)).toBeNull();
    expect(_normalizePreflightResponse(undefined)).toBeNull();
    expect(_normalizePreflightResponse({ ok: false })).toBeNull();
  });
  it('ok===true 原样透传', () => {
    const r = { ok: true, tier: 'full', can_create: true };
    expect(_normalizePreflightResponse(r)).toBe(r);
  });
});

describe('PreflightCard — 预检卡片渲染分支', () => {
  it('preflight=null → 不渲染', () => {
    const { container } = render(<PreflightCard preflight={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('tier=full → 绿色徽标「材料齐全」+ 摘要行,无警告', () => {
    render(<PreflightCard preflight={{ tier: 'full', can_create: true, river: { beats: 12 }, cast: { count: 4 }, worldbook: { count: 20 } }} />);
    expect(screen.getByText('材料齐全')).toBeTruthy();
    expect(screen.getByText('河道 12 拍 · 角色 4 人 · 世界书 20 条')).toBeTruthy();
  });

  it('can_create=false → 显示拒绝原因,禁止创建', () => {
    render(<PreflightCard preflight={{ tier: 'free', can_create: false, reason: '酒馆存档暂不支持', river: {}, cast: {}, worldbook: {} }} />);
    expect(screen.getByText('自由演化')).toBeTruthy();
    expect(screen.getByText('酒馆存档暂不支持')).toBeTruthy();
  });

  it('warnings 数组逐条渲染', () => {
    render(<PreflightCard preflight={{ tier: 'degraded', can_create: true, warnings: ['角色卡质量薄弱', '世界书条目过少'], river: {}, cast: {}, worldbook: {} }} />);
    expect(screen.getByText('角色卡质量薄弱')).toBeTruthy();
    expect(screen.getByText('世界书条目过少')).toBeTruthy();
  });
});

/* ── ExperimentPanel 集成测试(mock window.api / window.__openContinue / window.__apiToast)── */

function baseExperiment(overrides = {}) {
  return {
    id: 7,
    save_id: 42,
    save_kind: 'game',
    status: 'running',
    accel: 60,
    tick_interval_sec: 1800,
    ticks_today: 3,
    budget: { ticks_per_day: 48 },
    world_clock_label: '第1日 08:00',
    pause_reason: null,
    ...overrides,
  };
}

function detailResponse(expOverrides = {}) {
  return {
    ok: true,
    experiment: baseExperiment(expOverrides),
    fluctlights: [], events: [], trace: [], threads: [], relations: [], canon: null,
  };
}

function installApiMocks({ detail, pause, tick } = {}) {
  const api = {
    rath: {
      detail: detail || vi.fn().mockResolvedValue(detailResponse()),
      pause: pause || vi.fn().mockResolvedValue({ ok: true, experiment: baseExperiment({ status: 'paused', pause_reason: 'user' }) }),
      resume: vi.fn().mockResolvedValue({ ok: true, experiment: baseExperiment() }),
      tick: tick || vi.fn().mockResolvedValue({ ok: true, started: true }),
      archive: vi.fn().mockResolvedValue({ ok: true }),
      directive: vi.fn().mockResolvedValue({ ok: true }),
      accel: vi.fn().mockResolvedValue({ ok: true, experiment: baseExperiment() }),
    },
  };
  window.api = api;
  window.__apiToast = vi.fn();
  return api;
}

describe('ExperimentPanel — 可见性门控实际行为', () => {
  it('后台标签(document.hidden=true)挂载时不发详情请求', async () => {
    setDocumentHidden(true);
    const api = installApiMocks();
    render(<ExperimentPanel expId={7} />);
    // 给潜在的微任务一点时间;不应发起请求。
    await new Promise((r) => setTimeout(r, 10));
    expect(api.rath.detail).not.toHaveBeenCalled();
  });

  it('回到前台(visibilitychange)立即补拉一次,请求带 {active:true}', async () => {
    setDocumentHidden(true);
    const api = installApiMocks();
    render(<ExperimentPanel expId={7} />);
    await new Promise((r) => setTimeout(r, 10));
    expect(api.rath.detail).not.toHaveBeenCalled();

    setDocumentHidden(false);
    document.dispatchEvent(new Event('visibilitychange'));
    await waitFor(() => expect(api.rath.detail).toHaveBeenCalledWith(7, { active: true }));
  });

  it('可见时挂载 → 立即发一次详情请求(带 active:true)', async () => {
    const api = installApiMocks();
    render(<ExperimentPanel expId={7} />);
    await waitFor(() => expect(api.rath.detail).toHaveBeenCalledWith(7, { active: true }));
  });
});

describe('ExperimentPanel — 进入游戏按钮', () => {
  it('运行中:先暂停(等成功)再调 window.__openContinue,顺序不可颠倒', async () => {
    const calls = [];
    const pause = vi.fn(async () => { calls.push('pause'); return { ok: true, experiment: baseExperiment({ status: 'paused', pause_reason: 'user' }) }; });
    installApiMocks({ pause });
    window.__openContinue = vi.fn(async () => { calls.push('openContinue'); });

    render(<ExperimentPanel expId={7} />);
    const btn = await screen.findByText('进入游戏');
    fireEvent.click(btn);

    await waitFor(() => expect(window.__openContinue).toHaveBeenCalled());
    expect(pause).toHaveBeenCalledWith(7);
    expect(calls).toEqual(['pause', 'openContinue']);
    expect(window.__openContinue).toHaveBeenCalledWith({ id: 42, save_kind: 'game' });
  });

  it('已暂停:跳过 pause,直接调 window.__openContinue', async () => {
    const pause = vi.fn();
    installApiMocks({
      pause,
      detail: vi.fn().mockResolvedValue(detailResponse({ status: 'paused', pause_reason: 'user' })),
    });
    window.__openContinue = vi.fn();

    render(<ExperimentPanel expId={7} />);
    const btn = await screen.findByText('进入游戏');
    fireEvent.click(btn);

    await waitFor(() => expect(window.__openContinue).toHaveBeenCalledWith({ id: 42, save_kind: 'game' }));
    expect(pause).not.toHaveBeenCalled();
  });

  it('暂停原因徽标随 exp.pause_reason 渲染(已暂停 · no_model)', async () => {
    installApiMocks({
      detail: vi.fn().mockResolvedValue(detailResponse({ status: 'paused', pause_reason: 'no_model' })),
    });
    render(<ExperimentPanel expId={7} />);
    expect(await screen.findByText('无可用模型')).toBeTruthy();
  });
});

describe('ExperimentPanel — no_model tick 降级 toast', () => {
  it('tick 返回 reason=no_model → danger toast 引导去配置模型,而非笼统的"未执行"', async () => {
    const tick = vi.fn().mockResolvedValue({ ok: false, reason: 'no_model' });
    installApiMocks({ tick });

    render(<ExperimentPanel expId={7} />);
    const btn = await screen.findByText('推进一步');
    fireEvent.click(btn);

    await waitFor(() => expect(window.__apiToast).toHaveBeenCalledWith(
      expect.stringContaining('无可用模型'),
      expect.objectContaining({ kind: 'danger' }),
    ));
  });
});
