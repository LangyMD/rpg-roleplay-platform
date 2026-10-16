/* 分支管理页 (VSCode Git Graph 风格) + 继续游戏选择器 (存档 / 分支两步)。
   从 pages/saves.jsx 拆出,JSX / props 流逐字节不变。
   守卫测试 (test_branch_graph_vscode_style / test_continue_picker_uses_commit_activate /
   test_state_repository_single_source) read_text 本文件断言 BranchesPage / ContinuePicker 结构。 */

import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../../game-icons.jsx';
import Modal from '../Modal.jsx';
import { plNavigate } from '../../router.js';
import { ConfirmModal } from '../../platform-app.jsx';
import { BranchGraph } from '../../branch-graph.jsx';
import { NewGameModal } from './NewGame.jsx';

/* ---------------------------- BRANCHES ------------------------- */
const BRANCH_DATA = {
  nodes: [
    { id: 1, x: 80, y: 280, summary: "Opening · the night before the crossing", role: "root", current: false, branch: 0 },
    { id: 2, x: 240, y: 280, summary: "Ask the boatman after boarding", role: "round", branch: 0 },
    { id: 3, x: 400, y: 240, summary: "Land in the late afternoon · fog lingers", role: "round", branch: 0 },
    { id: 4, x: 400, y: 360, summary: "Stay at the fishermen's inn", role: "round", branch: 1 },
    { id: 5, x: 560, y: 240, summary: "Hear of three bodies at the docks", role: "round", branch: 0 },
    { id: 6, x: 560, y: 360, summary: "Meet Shen Zhiwei at the inn", role: "round", branch: 1 },
    { id: 7, x: 720, y: 200, summary: "Hide your identity from the tax collector", role: "round", branch: 0, current: true, lastExit: true },
    { id: 8, x: 720, y: 320, summary: "Torn page exposed · questioned by the inspector", role: "round", branch: 2, deleted: true },
    { id: 9, x: 720, y: 420, summary: "Hurry to the lighthouse before dark", role: "round", branch: 1 },
    { id: 10, x: 880, y: 200, summary: "Wait for Shen Zhiwei below the lighthouse", role: "round", branch: 0 },
    { id: 11, x: 880, y: 420, summary: "Find the keeper's daughter Aheng", role: "round", branch: 1 },
  ],
  edges: [
    { from: 1, to: 2, branch: 0 }, { from: 2, to: 3, branch: 0 }, { from: 2, to: 4, branch: 1 },
    { from: 3, to: 5, branch: 0 }, { from: 4, to: 6, branch: 1 },
    { from: 5, to: 7, branch: 0 }, { from: 5, to: 8, branch: 2, deleted: true },
    { from: 6, to: 9, branch: 1 },
    { from: 7, to: 10, branch: 0 }, { from: 9, to: 11, branch: 1 },
  ],
};

const BRANCH_LABELS = {
  0: { name: "Main line", desc: "Hide your identity from the tax collector; meeting at the lighthouse" },
  1: { name: "Inn line", desc: "Stay with the fishermen; meet Aheng earliest" },
  2: { name: "Exposure line", desc: "The inspector finds the torn page (deleted)", deleted: true },
};

function BranchesPage() {
  const { t } = useTranslation();
  // 用户要求"git ui 在 vscode 底部终端里的那个" — 改用 BranchGraph 组件 (VSCode Git Graph 风格)。
  // 旧版是自由拖拽 SVG (140×40 矩形 + 贝塞尔曲线),信息密度低、交互复杂、不像 git tool。
  // 新版用 swimlane 算法:每行一个 commit,左侧固定 column 分支线,右侧 message + ref pills + 操作。
  //
  // 后端不变(branch_commits + branch_refs);组件抽到 frontend/src/branch-graph.jsx,
  // 游戏内右侧 BranchTreeRail 和这里共用,只换 variant prop (compact / full)。

  const [saves, setSaves] = useStatePL([]);
  const [selectedSave, setSelectedSave] = useStatePL(undefined);
  const [savesLoaded, setSavesLoaded] = useStatePL(false);
  const [treePayload, setTreePayload] = useStatePL(null);  // {nodes, refs, active_commit_id}
  const [treeLoading, setTreeLoading] = useStatePL(false);
  const [treeError, setTreeError] = useStatePL("");
  const [selectedNodeId, setSelectedNodeId] = useStatePL(null);
  const [deleteTarget, setDeleteTarget] = useStatePL(null);

  // 1) 拉用户的 saves 列表
  useEffectPL(() => {
    (async () => {
      try {
        const r = await window.api.saves.list();
        const list = Array.isArray(r) ? r : (r?.items || r?.saves || []);
        const normalized = list.map(window.__normalizeSave || ((x) => x));
        setSaves(normalized);
        if (normalized.length) {
          setSelectedSave(prev => (
            prev && normalized.some(s => s.id === prev) ? prev : normalized[0].id
          ));
        } else {
          setSelectedSave(undefined);
        }
      } catch (_) {
        setSaves([]);
        setSelectedSave(undefined);
      } finally {
        setSavesLoaded(true);
      }
    })();
  }, []);

  // 2) selectedSave 变 → 拉该存档的 branch tree
  const reloadTree = async () => {
    if (!selectedSave) { setTreePayload(null); return; }
    setTreeLoading(true); setTreeError("");
    try {
      const r = await window.api.branches.list(selectedSave);
      setTreePayload(r ? {
        nodes: r.nodes || r.commits || [],
        refs: r.refs || [],
        active_commit_id: r.active_commit_id || r.active_branch_node_id || null,
      } : null);
    } catch (e) {
      setTreeError(e?.message || t('saves.branches.load_fail', { err: '' }));
      setTreePayload(null);
    } finally {
      setTreeLoading(false);
    }
  };
  useEffectPL(() => { reloadTree(); }, [selectedSave]);

  const onActivate = async (commitId) => {
    try {
      await window.api.branches.activate({ save_id: selectedSave, commit_id: commitId, node_id: commitId });
      window.__apiToast?.(t('saves.branches.toast_activated'), { kind: "ok" });
      reloadTree();
    } catch (e) {
      window.__apiToast?.(t('saves.branches.toast_activate_fail'), { kind: "danger", detail: e?.message });
    }
  };

  const onContinue = (commitId) => {
    window.__openContinue?.(saves.find(s => s.id === selectedSave), commitId);
  };

  const onDeleteRequest = (commitId) => {
    const node = (treePayload?.nodes || []).find(n => (n.commit_id ?? n.id) === commitId);
    if (node) setDeleteTarget(node);
  };

  const onDeleteConfirmed = async () => {
    if (!deleteTarget) return;
    const cid = deleteTarget.commit_id ?? deleteTarget.id;
    try {
      await window.api.branches.delete({ save_id: selectedSave, node_id: cid, commit_id: cid });
      window.__apiToast?.(t('saves.branches.toast_deleted'), { kind: "ok" });
      setDeleteTarget(null);
      reloadTree();
    } catch (e) {
      window.__apiToast?.(t('saves.branches.toast_delete_fail'), { kind: "danger", detail: e?.message });
    }
  };

  // 空态:用户没有任何存档
  if (savesLoaded && saves.length === 0) {
    return (
      <div className="pl-stack">
        <section className="pl-sec" data-cap-anchor="saves.branches">
          <div className="pl-sec-head">
            <h2>{t('saves.branches.page_title')} <span className="muted-2">{t('saves.branches.no_saves_title')}</span></h2>
          </div>
          <div className="pl-empty" style={{padding: "32px 24px", textAlign: "center", color: "var(--muted)"}}>
            <div style={{marginBottom: 12, fontFamily: "var(--font-serif)", fontSize: 15, color: "var(--text)"}}>
              {t('saves.branches.no_saves_body')}
            </div>
            <div style={{marginBottom: 16, fontSize: 13}}>
              {t('saves.branches.no_saves_hint')}
            </div>
            <div style={{display: "inline-flex", gap: 8}}>
              <button className="btn primary" onClick={() => plNavigate("scripts")}>
                <Icon name="bookmark" size={12} /> {t('saves.branches.no_saves_btn_scripts')}
              </button>
              <button className="btn ghost" onClick={() => plNavigate("saves")}>
                <Icon name="list" size={12} /> {t('saves.branches.no_saves_btn_list')}
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const nodeCount = (treePayload?.nodes || []).length;
  const refCount = (treePayload?.refs || []).length;

  return (
    <div className="pl-stack">
      <section className="pl-sec" data-cap-anchor="saves.branches">
        <div className="pl-sec-head">
          <h2>
            {t('saves.branches.page_title')}{" "}
            <span className="muted-2">
              {t('saves.branches.page_subtitle', { commits: nodeCount, refs: refCount })}
            </span>
          </h2>
          <div className="pl-sec-tools">
            <select value={selectedSave || ""} onChange={(e) => setSelectedSave(Number(e.target.value))}
              style={{height: 28, fontSize: 12, padding: "0 10px"}}>
              {saves.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}
            </select>
            <button className="btn ghost" onClick={reloadTree}><Icon name="refresh" size={12} /> {t('saves.branches.btn_refresh')}</button>
            <button className="btn primary"
              disabled={!selectedSave}
              onClick={() => window.__openContinue?.(saves.find(s => s.id === selectedSave))}>
              <Icon name="play" size={12} /> {t('saves.branches.btn_enter')}
            </button>
          </div>
        </div>
        <div style={{padding: "8px 0"}}>
          {treeLoading && (
            <div className="muted-2" style={{padding: "16px", fontSize: 12.5}}>{t('saves.branches.loading_tree')}</div>
          )}
          {!treeLoading && treeError && (
            <div className="muted-2" style={{padding: "16px", fontSize: 12.5, color: "var(--danger)"}}>{t('saves.branches.load_fail', { err: treeError })}</div>
          )}
          {!treeLoading && !treeError && treePayload && (
            <BranchGraph
              data={treePayload}
              variant="full"
              selectedId={selectedNodeId}
              onSelect={setSelectedNodeId}
              onActivate={onActivate}
              onContinue={onContinue}
              onDelete={onDeleteRequest}
            />
          )}
        </div>
        <div className="muted-2" style={{padding: "6px 4px 0", fontSize: 11, fontFamily: "var(--font-mono)"}}>
          {t('saves.branches.legend')}
        </div>
      </section>
      <ConfirmModal
        open={!!deleteTarget}
        title={t('saves.branches.delete_title', { id: deleteTarget?.commit_id ?? deleteTarget?.id })}
        body={
          <>
            {t('saves.branches.delete_body_suffix')} <strong>{deleteTarget?.summary || deleteTarget?.message || t('saves.branches.delete_body_node', { id: deleteTarget?.commit_id ?? deleteTarget?.id })}</strong>
            {" "}
            {t('saves.branches.delete_body_irrev')}
            <div style={{marginTop: 8, fontSize: 12, color: "var(--muted)"}}>POST /api/branches/delete</div>
          </>
        }
        danger confirmLabel={t('saves.branches.delete_confirm_label')}
        onClose={() => setDeleteTarget(null)}
        onConfirm={onDeleteConfirmed}
      />
    </div>
  );
}

/* ---------------------------- CONTINUE PICKER ------------------ */
function ContinuePicker({ open, save, focusedNodeId, onClose }) {
  const { t } = useTranslation();
  // task 45：原来 allSaves = window.MOCK_PLATFORM.saves —— 登录用户看不到自己的真存档
  // （只看到 mock 的 4 条假 save id=11/12/13/14）。改用 /api/saves 实时拉真存档。
  // 匿名访客（designer preview）才回退到 MOCK_PLATFORM。
  const [allSaves, setAllSaves] = useStatePL([]);
  const [savesLoading, setSavesLoading] = useStatePL(false);
  const [branchTree, setBranchTree] = useStatePL(null);  // task 45：真实分支树 / null=未加载
  const [branchLoading, setBranchLoading] = useStatePL(false);
  const [step, setStep] = useStatePL("save"); // save | branch | new
  const [pickedSave, setPickedSave] = useStatePL(null);
  const [newOpen, setNewOpen] = useStatePL(false);

  // 拉真实 saves
  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSavesLoading(true);
    (async () => {
      let list = [];
      try {
        const r = await window.api.saves.list();
        list = Array.isArray(r) ? r : (r?.items || r?.saves || []);
      } catch (_) {
        // 匿名访客 / 401：回退到 mock 保留 designer offline preview
        list = (window.RPG_AUTH && window.RPG_AUTH.authed) ? [] : (window.MOCK_PLATFORM?.saves || []);
      }
      if (cancelled) return;
      setAllSaves(list);
      setSavesLoading(false);
      if (save) { setPickedSave(save); setStep("branch"); }
      else if (list.length) { setPickedSave(list[0]); setStep("save"); }
      else { setPickedSave(null); setStep("save"); }
    })();
    return () => { cancelled = true; };
  }, [open, save]);

  // 拉真实 branch tree
  React.useEffect(() => {
    if (!open || !pickedSave?.id) { setBranchTree(null); return; }
    let cancelled = false;
    setBranchLoading(true);
    (async () => {
      let tree = null;
      try {
        const r = await window.api.branches.list(pickedSave.id);
        // 后端真相源是 user_runtime.active_commit_id (改后的 tree() 已经透传)
        const activeId = r?.active_commit_id || r?.active_branch_node_id;
        const nodes = (r?.nodes || r?.commits || []).map((n, i) => {
          // ref_names 是后端 tree() 给的真实分支指针名 ["refs/heads/main", "refs/runtime/user-6"]
          const refNames = Array.isArray(n.ref_names) ? n.ref_names : [];
          // 截短显示 (refs/heads/main → main)
          const shortRefs = refNames.map(rn => {
            const s = String(rn);
            return s.startsWith("refs/") ? s.split("/").slice(2).join("/") : s;
          });
          // 主分支判定:有 main / master ref 算主线;否则用 ref 名
          const isMain = shortRefs.includes("main") || shortRefs.includes("master");
          const branchLabel = shortRefs.length
            ? (isMain ? "main" : shortRefs[0])
            : t('saves.page.no_ref');
          return {
            id: n.id,
            summary: n.summary || n.message || n.content_preview || t('saves.page.node_fallback', { id: n.id }),
            turn_index: n.turn_index ?? i,
            kind: n.kind || "round",
            ref_names: refNames,    // 完整 ref 名(用于 hover tooltip)
            short_refs: shortRefs,  // 截短的 ref 名 list
            branch_label: branchLabel,  // 显示的主标签
            current: n.id === activeId,
            lastExit: n.id === activeId,
          };
        });
        tree = { nodes, edges: [] };
      } catch (_) { tree = { nodes: [], edges: [] }; }
      if (cancelled) return;
      setBranchTree(tree);
      setBranchLoading(false);
    })();
    return () => { cancelled = true; };
  }, [open, pickedSave?.id]);

  // task 45：BRANCH_DATA 已退役 —— 真实树为空就显示空态（"新账号还没存档/还没存任何分支节点"），
  // 不再回退到 mock 11 节点
  const nodes = branchTree?.nodes || [];
  const edges = branchTree?.edges || [];
  const lastExit = nodes.find(n => n.lastExit) || nodes[0];
  const childCount = (nodeId) => edges.filter(e => e.from === nodeId).length;
  const initialPick = focusedNodeId || lastExit?.id;
  const [pickedNode, setPickedNode] = useStatePL(initialPick);
  React.useEffect(() => { if (open) setPickedNode(initialPick); }, [open, initialPick]);

  if (!open) return null;

  const picked = nodes.find(n => n.id === pickedNode);
  const isFork = picked && childCount(picked.id) > 0;
  // task 30 + 关键 bug 修复:进入 Game Console 之前必须把 runtime 切到正确的
  // **commit**(不只是 save)。
  //
  // 旧版只调 saves.activate(targetId) — 这只切 save 级 active,后端会按
  // game_saves.active_commit_id 加载该 save 当前活跃的 commit,**完全忽略用户
  // 选的 pickedNode**。结果:
  //   · 用户在第 2 步选了 #13"扎兹巴鲁姆..."节点 (柏林剧情中段),
  //   · saves.activate 把 save 级切到"当前自动存档",但 active_commit_id 还是
  //     #15 末尾(或别的 commit),
  //   · 进 Game Console 看到的是末尾 commit 的 state — 可能是混乱的旧 runtime
  //     (如 ash_mine 内容)而非用户选的 #13 柏林剧情。
  //
  // 修复:如果用户在树里选了具体节点,改调 branches.activate({node_id}) —
  // 这会同时:
  //   1. _set_save_active 写 game_saves.active_commit_id = pickedNode
  //   2. _write_checkout 写 runtime_checkouts
  //   3. runtime.activate_state_snapshot 把 user_runtime 切到 pickedNode +
  //      该 commit 的 state_snapshot
  // 这才是 git "checkout commit_id" 的语义。
  // 没选具体节点(只切了 save 没选 commit)→ fallback 到 saves.activate。
  const confirm = async () => {
    const targetSaveId = pickedSave?.id;
    if (!targetSaveId) {
      // 完全没存档信息,不要带着旧 runtime 进 Game Console
      window.__apiToast?.(t('saves.toast.no_target_save'), { kind: "danger", duration: 2400 });
      return;
    }
    try {
      if (pickedNode != null && pickedNode !== "") {
        // 用户选了具体 commit:走 commit 级 activate,把 runtime 切到该节点 state
        const r = await window.api.branches.activate({
          node_id: pickedNode,
          commit_id: pickedNode,
        });
        if (r && r.ok === false) {
          throw new Error(r.error || r.detail || t('saves.page.err_commit_activate_fail'));
        }
      } else {
        // 只选了 save 没选节点:fallback save 级 activate (切到该 save 的当前 active commit)
        await window.api.saves.activate(targetSaveId);
      }
    } catch (e) {
      window.__apiToast?.(t('saves.toast.branch_activate_fail'), { kind: "danger", detail: e?.message, duration: 3000 });
      return;  // 不要带着旧 runtime 进去
    }
    location.href = "Game Console.html";
  };

  // STEP 1: Save selection
  if (step === "save") {
    return (
      <Modal
        open
        eyebrow={t('saves.continue.step1_eyebrow')}
        title={t('saves.continue.step1_title')}
        width={620}
        onClose={onClose}
        footer={<>
          <span className="muted-2" style={{fontSize: 11.5}}>
            <Icon name="info" size={11} /> {t('saves.continue.hint_dblclick')}
          </span>
          <div style={{display: "flex", gap: 8}}>
            <button className="btn ghost" onClick={onClose}>{t('saves.continue.btn_cancel')}</button>
            <button className="btn primary" onClick={() => setStep("branch")} disabled={!pickedSave}>
              {t('saves.continue.btn_next')} <Icon name="arrow_right" size={12} />
            </button>
          </div>
        </>}
      >
          <div className="pl-save-picker">
            {savesLoading && (
              <div className="muted-2" style={{padding: "20px 12px", textAlign: "center", fontSize: 13}}>
                {t('saves.continue.loading_saves')}
              </div>
            )}
            {!savesLoading && allSaves.length === 0 && (
              <div className="muted-2" style={{padding: "20px 12px", textAlign: "center", fontSize: 13, lineHeight: 1.7}}>
                {t('saves.continue.no_saves')}
              </div>
            )}
            {allSaves.map(s => (
              <button key={s.id}
                className={`pl-save-pick-row ${pickedSave?.id === s.id ? "active" : ""}`}
                onClick={() => setPickedSave(s)}
                onDoubleClick={() => { setPickedSave(s); setStep("branch"); }}>
                <div className={`pl-radio ${pickedSave?.id === s.id ? "on" : ""}`} />
                <div className="pl-save-pick-body">
                  <div className="pl-save-pick-title">
                    {s.title}
                    {s.current && <span className="pill accent" style={{marginLeft: 8, fontSize: 10.5}}><span className="dot accent pulse" /> {t('saves.continue.playing_pill')}</span>}
                  </div>
                  <div className="pl-save-pick-meta muted-2 mono">
                    {t('saves.continue.node_meta', { n: s.branch_count, date: s.updated_at })}
                  </div>
                </div>
              </button>
            ))}
            <button className="pl-save-pick-row pl-save-pick-new"
              onClick={() => setNewOpen(true)}>
              <div className="pl-save-pick-mark"><Icon name="plus" size={14} /></div>
              <div className="pl-save-pick-body">
                <div className="pl-save-pick-title">{t('saves.continue.new_game_title')}</div>
                <div className="pl-save-pick-meta muted-2">{t('saves.continue.new_game_desc')}</div>
              </div>
              <Icon name="chevron_right" size={14} style={{color: "var(--muted-2)"}} />
            </button>
          </div>
          <NewGameModal
            open={newOpen}
            onClose={() => setNewOpen(false)}
            // Codex P0-1 修复:之前 onConfirm 把 payload 丢了 → 用户填的剧本 / 角色卡
            // 信息没生效,关闭 modal 后直接 confirm() 激活旧 save,看着像"开始新游戏"
            // 实际是继续当前存档。现在走统一原子流:saves.create → activate → 进游戏。
            onConfirm={async (payload) => {
              await window.__createAndEnterSave(payload);
              // 成功会跳页 (location.href),不会执行到下面
            }}
          />
      </Modal>
    );
  }

  // STEP 2: Branch / node selection
  return (
    <Modal
      open
      width={640}
      onClose={onClose}
      eyebrow={
        <button className="pl-back-btn" onClick={() => setStep("save")} data-tip={t('saves.continue.step2_back_tip')}>
          <Icon name="chevron_left" size={11} /> {t('saves.continue.step2_back')}
        </button>
      }
      title={pickedSave?.title || t('saves.continue.step2_fallback_title')}
      footer={<>
        <span className="muted-2" style={{fontSize: 11.5}}>
          <Icon name="info" size={11} />{" "}
          {isFork
            ? t('saves.continue.info_fork', { id: String(picked.id).padStart(2, "0") })
            : t('saves.continue.info_continue', { id: String(picked?.id || 0).padStart(2, "0") })}
        </span>
        <div style={{display: "flex", gap: 8}}>
          <button className="btn ghost" onClick={() => setStep("save")}>{t('saves.continue.btn_prev')}</button>
          <button className="btn primary" onClick={confirm} disabled={pickedNode == null}>
            <Icon name="play" size={12} /> {isFork ? t('saves.continue.btn_fork') : t('saves.continue.btn_continue')}
          </button>
        </div>
      </>}
    >

        {/* task 45：真分支树。loading 时显示加载提示；空时显示空态（新账号还没存档的常见情况） */}
        {branchLoading && (
          <div className="muted-2" style={{padding: "20px 24px", textAlign: "center", fontSize: 13}}>
            {t('saves.continue.loading_branches')}
          </div>
        )}
        {!branchLoading && nodes.length === 0 && (
          <div className="muted-2" style={{padding: "32px 24px", textAlign: "center", fontSize: 13, lineHeight: 1.7}}>
            {t('saves.continue.no_branch_nodes')}<br />
            <span className="muted">{t('saves.continue.no_branch_hint')}</span>
          </div>
        )}
        {!branchLoading && lastExit && (
          <button className={`pl-modal-hero ${pickedNode === lastExit.id ? "active" : ""}`}
                  onClick={() => setPickedNode(lastExit.id)} style={{textAlign: "left"}}>
            <div className="pl-modal-hero-mark">
              <span className="dot accent pulse" />
              <span className="mono">{t('saves.continue.last_exit_label')}</span>
            </div>
            <div className="pl-modal-hero-body">
              <div className="pl-modal-hero-title">{t('saves.continue.branch_label', { branch: lastExit.branch })} · {BRANCH_LABELS[lastExit.branch]?.name || t('saves.continue.branch_default')}</div>
              <div className="pl-modal-hero-summary serif">#{String(lastExit.id).padStart(2,"00")} · {lastExit.summary}</div>
              <div className="pl-modal-hero-meta muted-2 mono">turn {lastExit.turn_index ?? "?"} · {lastExit.kind || "round"}</div>
            </div>
            <div className="pl-modal-hero-radio">
              <div className={`pl-radio ${pickedNode === lastExit.id ? "on" : ""}`} />
            </div>
          </button>
        )}

        {!branchLoading && nodes.length > 1 && (
          <div className="pl-modal-section-label">{t('saves.continue.more_nodes_label')} <span className="muted-2" style={{marginLeft: 6, fontSize: 11, textTransform: "none", letterSpacing: 0}}>{t('saves.continue.more_nodes_hint')}</span></div>
        )}

        <div className="pl-modal-branches">
          {nodes.filter(n => n.id !== lastExit?.id && !n.deleted).map(n => {
            const hasChildren = childCount(n.id) > 0;
            return (
              <button key={n.id}
                className={`pl-modal-branch ${pickedNode === n.id ? "active" : ""}`}
                onClick={() => setPickedNode(n.id)}>
                <div className={`pl-radio ${pickedNode === n.id ? "on" : ""}`} />
                <div className="pl-modal-branch-body">
                  <div className="pl-modal-branch-title">
                    #{String(n.id).padStart(2, "0")} · {n.summary}
                    {hasChildren && (
                      <span className="pill" data-tip={t('saves.continue.fork_tip')} style={{marginLeft: 8, fontSize: 10.5, color: "var(--warn)", borderColor: "rgba(212, 179, 102, 0.32)", background: "var(--warn-soft)"}}>
                        <Icon name="fork" size={9} /> {t('saves.continue.fork_pill')}
                      </span>
                    )}
                  </div>
                  <div className="pl-modal-branch-desc">
                    {n.short_refs && n.short_refs.length > 0 ? (
                      <>
                        {n.short_refs.map((rn, i) => (
                          <span key={i} className="pill" style={{
                            marginRight: 6, fontSize: 10.5,
                            color: rn === "main" || rn === "master" ? "var(--accent)" : "var(--info)",
                            borderColor: "var(--line)",
                          }} title={n.ref_names?.[i] || rn}>
                            {n.current ? "HEAD → " : ""}{rn}
                          </span>
                        ))}
                        {n.turn_index != null && (
                          <span className="muted-2 mono" style={{fontSize: 10.5}}>turn {n.turn_index}</span>
                        )}
                      </>
                    ) : (
                      <span className="muted-2 mono" style={{fontSize: 10.5}}>
                        {n.kind === "root" ? t('saves.continue.save_root') : `turn ${n.turn_index}`}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })}
        </div>

    </Modal>
  );
}

export { BranchesPage, ContinuePicker };
