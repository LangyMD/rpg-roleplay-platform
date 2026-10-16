// md-continue.js — Cursor 风「AI 续写/改写正文」引擎(CodeMirror 6)。
// 设计:LLM 只产正文文本(流式),前端确定性决定插哪(选中→改写替换 / 光标→续写插入),
// 插入内容高亮为「待定区」,Tab 接受 / Esc 放弃 —— 即 VSCode/Cursor 的 Cmd+K 应用到小说正文。
// 复用后端 POST /api/console_assistant/continue(SSE: token/done/error)。
import { StateField, StateEffect, Prec } from '@codemirror/state';
import { EditorView, Decoration, keymap, showPanel } from '@codemirror/view';
import { setPanelVisible } from './md-panel.js';
import { consumeSSE } from './sse-consume.js';
import i18n from '../i18n/index.js';

// ── 待定区状态(高亮 + 范围 + 改写时的原文,用于放弃还原)──────────────────
const setPending = StateEffect.define();   // {from,to,original,busy} | null

export const pendingField = StateField.define({
  create: () => null,
  update(val, tr) {
    let v = val;
    if (v && tr.docChanged) {
      // 流式插入会改文档,映射范围;from 用 -1(不随插入右移)、to 用 1(随插入扩张)。
      v = { ...v, from: tr.changes.mapPos(v.from, -1), to: tr.changes.mapPos(v.to, 1) };
    }
    for (const e of tr.effects) if (e.is(setPending)) v = e.value;
    return v;
  },
  provide: (f) => EditorView.decorations.from(f, (v) =>
    (v && v.to > v.from)
      ? Decoration.set([Decoration.mark({ class: 'mde-ai-pending' }).range(v.from, v.to)])
      : Decoration.none),
});

function pendingState(view) { return view.state.field(pendingField, false) || null; }

export function acceptPending(view) {
  const p = pendingState(view);
  if (!p) return false;
  // 接受前先抓住这段被接受的正文,清空待定区后回调(用于「续写后同步设定到知识库」桥接)。
  const text = view.state.doc.sliceString(p.from, p.to);
  view.dispatch({ effects: setPending.of(null) });
  view.focus();
  if (text && text.trim() && typeof p.onAccept === 'function') {
    try { p.onAccept(text, { rewrite: !!p.rewrite }); } catch (_) {}
  }
  return true;
}

export function rejectPending(view) {
  const p = pendingState(view);
  if (!p) return false;
  // 删掉插入的待定文本;改写模式还原原文。
  view.dispatch({
    changes: { from: p.from, to: p.to, insert: p.original || '' },
    effects: setPending.of(null),
  });
  view.focus();
  return true;
}

// ── 顶部提示条(待定时显示 Tab 接受 / Esc 放弃)──────────────────────────
function pendingPanel(view) {
  const dom = document.createElement('div');
  dom.className = 'mde-ai-panel';
  dom.style.display = 'none';
  const sync = (v) => {
    const p = v.state.field(pendingField, false);
    setPanelVisible(dom, !!p);
    if (p) dom.textContent = p.busy ? i18n.t('md_ai.busy') : i18n.t('md_ai.done');
  };
  sync(view);
  return { dom, update: (u) => sync(u.view) };
}

// ── 待定期间的快捷键(高优先级:Tab 接受 / Esc 放弃)────────────────────
const pendingKeymap = Prec.highest(keymap.of([
  { key: 'Tab', run: (view) => acceptPending(view) },
  { key: 'Mod-Enter', run: (view) => acceptPending(view) },
  { key: 'Escape', run: (view) => rejectPending(view) },
]));

export function aiContinueExtension() {
  return [pendingField, showPanel.of(pendingPanel), pendingKeymap];
}

const BEFORE_CAP = 4000, AFTER_CAP = 1500;

// ── 主入口:对一个 EditorView 跑一次续写/改写 ────────────────────────────
// opts: { scriptId, instruction, onState?(s) }  s ∈ 'busy'|'done'|'error'|'cancel'
export async function runContinue(view, opts = {}) {
  if (!view) return;
  if (pendingState(view)) rejectPending(view);   // 已有待定 → 先清掉再来

  const doc = view.state.doc;
  const sel = view.state.selection.main;
  const rewrite = !sel.empty;
  const selectionText = rewrite ? doc.sliceString(sel.from, sel.to) : '';
  const anchor = rewrite ? sel.from : sel.head;
  const before = doc.sliceString(Math.max(0, anchor - BEFORE_CAP), anchor);
  const afterStart = rewrite ? sel.to : sel.head;
  const after = doc.sliceString(afterStart, Math.min(doc.length, afterStart + AFTER_CAP));

  // 改写:先删选中,插入点 = 选中起点(原文存进待定区,放弃时还原)。
  let insertAt = anchor;
  if (rewrite) {
    view.dispatch({ changes: { from: sel.from, to: sel.to, insert: '' } });
    insertAt = sel.from;
  }
  // 建空待定区(busy)。onAccept/rewrite 随待定区一路携带,接受时回调用于「同步到知识库」桥接。
  view.dispatch({ effects: setPending.of({ from: insertAt, to: insertAt, original: selectionText, busy: true, onAccept: opts.onAccept, rewrite }) });
  view.focus();

  const ctrl = new AbortController();
  let got = false;
  opts.onState?.('busy');

  const insertToken = (text) => {
    if (!text) return;
    const p = pendingState(view);
    if (!p) { ctrl.abort(); return; }   // 用户中途取消
    // 插入点取「待定区末尾」p.to —— pendingField 已随并发编辑重映射;不用裸闭包整数 pos,
    // 否则流式期间用户在待定区前手输使文档左移、旧 pos 失效 → token 插错位、高亮与实文发散(harness 审计 P2)。
    const at = p.to;
    view.dispatch({
      changes: { from: at, insert: text },
      effects: setPending.of({ from: p.from, to: at + text.length, original: p.original, busy: true, onAccept: p.onAccept, rewrite: p.rewrite }),
      scrollIntoView: true,
    });
    got = true;
  };

  try {
    const res = await fetch('/api/console_assistant/continue', {
      method: 'POST', credentials: 'include', signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        before, after, selection: selectionText,
        instruction: opts.instruction || '',
        mode: rewrite ? 'rewrite' : 'continue',
        script_id: opts.scriptId,
        chapter_index: (opts.chapterIndex != null ? opts.chapterIndex : null),  // 后端据此装配相关设定+防剧透
      }),
    });
    let errMsg = '';
    await consumeSSE(res, (ev, data) => {
      if (ev === 'token') insertToken(data.text || '');
      else if (ev === 'error') errMsg = data.message || i18n.t('md_ai.gen_failed');
    }, { signal: ctrl.signal });

    const p = pendingState(view);
    if (!p) { opts.onState?.('cancel'); return; }
    if (!got) {
      // SSE 正常结束却一个 token 都没产出(模型返空/拒答/上下文不适合补全),或带 error —— 别留个
      // 空的「续写完成」让用户以为写了却「啥也没看到」(群反馈 耀月余辉)。撤回空待定区 + 明确提示。
      rejectPending(view);
      opts.onState?.('error', errMsg || 'empty');
      try {
        window.__apiToast?.(
          errMsg ? i18n.t('md_ai.failed') : i18n.t('md_ai.empty'),
          { kind: errMsg ? 'danger' : 'warn',
            detail: errMsg || i18n.t('md_ai.empty_detail') },
        );
      } catch (_) {}
      return;
    }
    // 完成:留高亮 + 提示条,等用户 Tab 接受 / Esc 放弃。
    view.dispatch({ effects: setPending.of({ from: p.from, to: p.to, original: p.original, busy: false, onAccept: p.onAccept, rewrite: p.rewrite }) });
    opts.onState?.('done');
  } catch (e) {
    if (pendingState(view) && !got) rejectPending(view);
    opts.onState?.('error', e?.message);
    try { window.__apiToast?.(i18n.t('md_ai.error'), { kind: 'danger', detail: e?.message }); } catch (_) {}
  }
}

// ── Cmd+K 行内指令:复用全局 __prompt 取指令 → runContinue ────────────────
// getOnAccept:可选,返回「接受续写后同步知识库」回调,与侧栏「续写到正文」共用同一桥接。
export function cmdKKeymap(getScriptId, getOnAccept, getChapterIndex) {
  return keymap.of([{
    key: 'Mod-k',
    run: (view) => {
      (async () => {
        const sel = view.state.selection.main;
        const title = sel.empty ? i18n.t('md_ai.cmdk_continue') : i18n.t('md_ai.cmdk_rewrite');
        let instr = '';
        try {
          instr = await (window.__prompt
            ? window.__prompt({ title, label: i18n.t('md_ai.cmdk_label'), default: '' })
            : Promise.resolve(prompt(title)));
        } catch (_) { instr = null; }
        if (instr === null) return;   // 取消
        runContinue(view, { scriptId: getScriptId?.(), instruction: instr, onAccept: getOnAccept?.(), chapterIndex: getChapterIndex?.() });
      })();
      return true;
    },
  }]);
}
