/**
 * forced-set-section.test.jsx — 玩家强制设定 (/set) 管理面板回归测试。
 *
 * 群反馈(行者无疆):早期 /set 过的命令一直作为「硬约束」约束 GM(注入见
 * context_engine/layers.py),但前端无处删改。本组件把 worldline.user_variables
 * 列出来并提供逐条删除 + 清空全部,删除时一并清掉 /set 配对写入的固定记忆
 * 「玩家强制设定：…」(否则只删变量、pinned 仍注入 GM = 没真正解除)。
 *
 * 覆盖确定性行为:
 *   · 无 user_variables → 不渲染整段(返回 null)
 *   · 有变量 → 列出每条 value;删除按钮调 worldline.remove({key}) + 配对 pinned 删除
 *   · 单条时无「清空全部」;≥2 条才出现
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ForcedSetSection } from '../game-panels.jsx';

function installApiMocks() {
  const removeVar = vi.fn().mockResolvedValue({ ok: true });
  const memoryRemove = vi.fn().mockResolvedValue({ ok: true });
  window.api = { worldline: { remove: removeVar }, game: { memoryRemove } };
  window.__confirm = vi.fn().mockResolvedValue(true);
  window.__apiToast = vi.fn();
  return { removeVar, memoryRemove };
}

describe('ForcedSetSection — 玩家强制设定管理', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.api = undefined;
  });

  it('无 user_variables → 不渲染', () => {
    const { container } = render(<ForcedSetSection state={{ worldline: {}, memory: {} }} />);
    expect(container.firstChild).toBeNull();
  });

  it('列出每条强制设定的 value + 标题', () => {
    const state = {
      worldline: { user_variables: {
        set_2_1: { value: '巨大怪物在回归前不可被击杀', source: 'user:/set', turn: 2 },
        set_5_1: { value: '主角保留前世记忆', source: 'user:/set', turn: 5 },
      } },
      memory: { pinned: [] },
    };
    render(<ForcedSetSection state={state} />);
    expect(screen.getByText('玩家强制设定')).toBeTruthy();
    expect(screen.getByText('巨大怪物在回归前不可被击杀')).toBeTruthy();
    expect(screen.getByText('主角保留前世记忆')).toBeTruthy();
  });

  it('删除一条 → 调 worldline.remove({key}) 并删掉配对 pinned「玩家强制设定：…」', async () => {
    const { removeVar, memoryRemove } = installApiMocks();
    const state = {
      worldline: { user_variables: { set_2_1: { value: '巨大怪物在回归前不可被击杀', source: 'user:/set', turn: 2 } } },
      memory: { pinned: ['某无关固定记忆', '玩家强制设定：巨大怪物在回归前不可被击杀'] },
    };
    render(<ForcedSetSection state={state} />);
    fireEvent.click(screen.getByLabelText('删除这条强制设定'));
    await waitFor(() => expect(removeVar).toHaveBeenCalledWith({ key: 'set_2_1' }));
    // 配对 pinned 在 index 1 → memoryRemove({bucket:'pinned', index:1})
    await waitFor(() => expect(memoryRemove).toHaveBeenCalledWith({ bucket: 'pinned', index: 1 }));
  });

  it('also removes the paired pinned entry written with the English prefix', async () => {
    const { removeVar, memoryRemove } = installApiMocks();
    const state = {
      worldline: { user_variables: { set_2_1: { value: 'The giant cannot be killed yet', source: 'user:/set', turn: 2 } } },
      memory: { pinned: ['unrelated', 'other', 'Player forced setting: The giant cannot be killed yet'] },
    };
    render(<ForcedSetSection state={state} />);
    fireEvent.click(screen.getByLabelText('删除这条强制设定'));
    await waitFor(() => expect(removeVar).toHaveBeenCalledWith({ key: 'set_2_1' }));
    await waitFor(() => expect(memoryRemove).toHaveBeenCalledWith({ bucket: 'pinned', index: 2 }));
  });

  it('单条时无「清空全部」;≥2 条才出现', () => {
    const one = { worldline: { user_variables: { set_1_1: { value: 'A', turn: 1 } } }, memory: { pinned: [] } };
    const { rerender } = render(<ForcedSetSection state={one} />);
    expect(screen.queryByLabelText('清空全部')).toBeNull();
    const two = { worldline: { user_variables: { set_1_1: { value: 'A', turn: 1 }, set_2_1: { value: 'B', turn: 2 } } }, memory: { pinned: [] } };
    rerender(<ForcedSetSection state={two} />);
    expect(screen.getByLabelText('清空全部')).toBeTruthy();
  });

  it('清空全部 → 对每条都调 worldline.remove', async () => {
    const { removeVar } = installApiMocks();
    const state = {
      worldline: { user_variables: { set_1_1: { value: 'A', turn: 1 }, set_2_1: { value: 'B', turn: 2 } } },
      memory: { pinned: [] },
    };
    render(<ForcedSetSection state={state} />);
    fireEvent.click(screen.getByLabelText('清空全部'));
    await waitFor(() => expect(removeVar).toHaveBeenCalledTimes(2));
    expect(removeVar).toHaveBeenCalledWith({ key: 'set_1_1' });
    expect(removeVar).toHaveBeenCalledWith({ key: 'set_2_1' });
  });

  it('兼容旧形态:value 为裸字符串也能渲染', () => {
    const state = { worldline: { user_variables: { set_1_1: '裸字符串约束' } }, memory: { pinned: [] } };
    render(<ForcedSetSection state={state} />);
    expect(screen.getByText('裸字符串约束')).toBeTruthy();
  });
});
