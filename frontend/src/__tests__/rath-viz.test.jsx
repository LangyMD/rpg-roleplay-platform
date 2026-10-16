/* rath-viz.test.jsx — RATH 观测台 v3 可视化升级的纯函数回归测试。
 *
 * 覆盖两块确定性映射(与 pages/rath.jsx 顶部注释一致):
 *   · _groupEventsByWorldDay:events 按 world_clock_label 的"第N日"前缀分组,
 *     组内保持原始时序,非相邻的同日不合并。
 *   · _tensionSparkline:tension_hist(≤12 个 0-10 整数)映射成定长 12 格的
 *     柱状高度数据,不足 12 时前置占位柱,末尾真实值标 isLast。
 * 顺带覆盖 _truncateForTip(hover 提示 / 折叠摘要预览共用的截断helper)。
 */
import { describe, it, expect } from 'vitest';
import { _groupEventsByWorldDay, _parseWorldDayLabel, _tensionSparkline, _truncateForTip } from '../pages/rath.jsx';

describe('_parseWorldDayLabel', () => {
  it('提取"第N日"前缀', () => {
    expect(_parseWorldDayLabel('第14日 19:40')).toBe('第14日');
    expect(_parseWorldDayLabel('第1日')).toBe('第1日');
  });

  it('extracts the English "Day N" prefix (current backend format)', () => {
    expect(_parseWorldDayLabel('Day 14 19:40')).toBe('Day 14');
    expect(_parseWorldDayLabel('Day 1')).toBe('Day 1');
  });

  it('无法解析时返回空串', () => {
    expect(_parseWorldDayLabel('19:40')).toBe('');
    expect(_parseWorldDayLabel('')).toBe('');
    expect(_parseWorldDayLabel(null)).toBe('');
    expect(_parseWorldDayLabel(undefined)).toBe('');
  });
});

describe('_groupEventsByWorldDay', () => {
  it('空数组/非数组输入返回空分组', () => {
    expect(_groupEventsByWorldDay([])).toEqual([]);
    expect(_groupEventsByWorldDay(null)).toEqual([]);
    expect(_groupEventsByWorldDay(undefined)).toEqual([]);
  });

  it('连续同日事件合并进同一组,组内保持原始时序', () => {
    const events = [
      { id: 3, world_clock_label: '第14日 20:00' },
      { id: 2, world_clock_label: '第14日 19:40' },
      { id: 1, world_clock_label: '第14日 08:00' },
    ];
    const groups = _groupEventsByWorldDay(events);
    expect(groups).toHaveLength(1);
    expect(groups[0].day).toBe('第14日');
    expect(groups[0].events.map((e) => e.id)).toEqual([3, 2, 1]);
  });

  it('日期变化时切出新组,按外观顺序排列', () => {
    const events = [
      { id: 5, world_clock_label: '第15日 09:00' },
      { id: 4, world_clock_label: '第14日 22:00' },
      { id: 3, world_clock_label: '第14日 20:00' },
      { id: 2, world_clock_label: '第13日 23:00' },
    ];
    const groups = _groupEventsByWorldDay(events);
    expect(groups.map((g) => g.day)).toEqual(['第15日', '第14日', '第13日']);
    expect(groups[1].events.map((e) => e.id)).toEqual([4, 3]);
  });

  it('非相邻的同日不合并(先第14日,又出现第13日,再回到第14日 → 三组)', () => {
    const events = [
      { id: 3, world_clock_label: '第14日 10:00' },
      { id: 2, world_clock_label: '第13日 23:00' },
      { id: 1, world_clock_label: '第14日 09:00' },
    ];
    const groups = _groupEventsByWorldDay(events);
    expect(groups).toHaveLength(3);
    expect(groups.map((g) => g.day)).toEqual(['第14日', '第13日', '第14日']);
  });

  it('无法解析日期前缀的事件归入空 day 组,不与相邻真实日期误并', () => {
    const events = [
      { id: 2, world_clock_label: '第14日 10:00' },
      { id: 1, world_clock_label: '???' },
    ];
    const groups = _groupEventsByWorldDay(events);
    expect(groups.map((g) => g.day)).toEqual(['第14日', '']);
  });
});

describe('_tensionSparkline', () => {
  it('空/未定义 hist 返回 12 个占位柱,无 isLast', () => {
    const bars = _tensionSparkline(undefined);
    expect(bars).toHaveLength(12);
    expect(bars.every((b) => b.isPad)).toBe(true);
    expect(bars.some((b) => b.isLast)).toBe(false);
  });

  it('数据不足 12 时前置占位柱,真实值按 0-10 线性映射到 0-20 高度', () => {
    const bars = _tensionSparkline([0, 2, 5, 10]);
    expect(bars).toHaveLength(12);
    const pad = bars.slice(0, 8);
    const real = bars.slice(8);
    expect(pad.every((b) => b.isPad)).toBe(true);
    expect(real.map((b) => b.value)).toEqual([0, 2, 5, 10]);
    expect(real.map((b) => b.height)).toEqual([2, 4, 10, 20]); // minHeight=2 兜底 0 值
    expect(real.map((b) => b.isLast)).toEqual([false, false, false, true]);
  });

  it('超出 0-10 的值被夹紧,超过 12 个只取最近 12 个', () => {
    const bars = _tensionSparkline([-5, 15, ...Array(11).fill(3)]);
    expect(bars).toHaveLength(12);
    // 最近 12 个 = 去掉最前面的 -5,保留 15(夹紧到10) + 11 个 3
    expect(bars[0].value).toBe(10); // 15 clamped
    expect(bars.slice(1).every((b) => b.value === 3)).toBe(true);
    expect(bars[bars.length - 1].isLast).toBe(true);
  });
});

describe('_truncateForTip', () => {
  it('短文本原样返回', () => {
    expect(_truncateForTip('短文本')).toBe('短文本');
  });

  it('超过 maxLen 时截断并加省略号', () => {
    const long = '一'.repeat(80);
    const out = _truncateForTip(long, 60);
    expect(out.length).toBe(60);
    expect(out.endsWith('…')).toBe(true);
  });

  it('null/undefined 视为空串', () => {
    expect(_truncateForTip(null)).toBe('');
    expect(_truncateForTip(undefined)).toBe('');
  });
});
