/* script-modules-panel.jsx — Rebuild Panel 编排层 (phase_rebuild_panel).
   职责:把 ModuleStatusCard / ModuleMatrixOverview / RebuildJobBanner / RebuildEstimateModal 串成一个
   可在 ScriptDetailPanel 内消费的 React hook + view 组件.

   核心 useScriptRebuild(scriptId) 返回:
     - statusPayload     当前 /modules-status 快照
     - statusLoading     是否在 reload 状态
     - activeJob         { job_id, kind, module, before_count, after_count, overall_progress, ... }
     - openEstimate({ module, options? })  打开 estimate modal
     - bannerProps       传给 <RebuildJobBanner>
     - matrixProps       传给 <ModuleMatrixOverview>
     - modalProps        传给 <RebuildEstimateModal>
     - cardProps(module) 传给单卡 <ModuleStatusCard module={...} {...cardProps('canon')} />

   后端契约假设(任务说明里硬约束 3):
     GET    /api/scripts/{sid}/modules-status                   → { ok, modules: {...}, active_job? }
     POST   /api/scripts/{sid}/rebuild/{module}/estimate        → { ok, tokens_est, cost_est, model, affects[], prereqs[], note }
     POST   /api/scripts/{sid}/rebuild/{module}                 → { ok, job_id }
     POST   /api/scripts/{sid}/rebuild/embeddings  body:{include:[]} → { ok, job_id }
     SSE    /api/scripts/import-jobs/{job_id}/stream            (复用现有 streamImport)
*/

import React from 'react';
import { useTranslation } from 'react-i18next';
import CSSpaceBetween from '@cloudscape-design/components/space-between';

import { ModuleStatusCard } from '../components/ModuleStatusCard.jsx';
import { ModuleMatrixOverview } from '../components/ModuleMatrixOverview.jsx';
import { RebuildJobBanner } from '../components/RebuildJobBanner.jsx';
import { RebuildEstimateModal } from '../components/RebuildEstimateModal.jsx';

// 收敛处置④:「知识库中心」新增三张模块卡(后端并行注册,契约:
// POST /api/scripts/{id}/rebuild/{module}[/estimate] 与既有 7 模块完全同构,
// useScriptRebuild 的 cardProps(module) 天然适配,零改动即可接入)。
const EXTRA_MODULE_CARDS = [
  {
    id: 'facts_refine',
    titleKey: 'modules.facts_refine.title',
    titleDefault: 'LLM chapter summary refinement',
    descKey: 'modules.facts_refine.desc',
    descDefault: 'Upgrade rule-based fragment summaries to real LLM summaries plus in-story time',
  },
  {
    id: 'worldbook_enrich',
    titleKey: 'modules.worldbook_enrich.title',
    titleDefault: 'Worldbook core entry enrichment',
    descKey: 'modules.worldbook_enrich.desc',
    descDefault: 'Flesh out power systems and core setting entries at the mechanics level',
  },
  {
    id: 'world_key',
    titleKey: 'modules.world_key.title',
    titleDefault: 'World split backfill',
    descKey: 'modules.world_key.desc',
    descDefault: 'Split multi-world books (infinite-flow / transmigration) by world, with the LLM confirming boundaries',
  },
];

export function useScriptRebuild(scriptId) {
  const { t } = useTranslation();
  const [statusPayload, setStatusPayload] = React.useState(null);
  const [statusLoading, setStatusLoading] = React.useState(false);
  const [activeJob, setActiveJob] = React.useState(null);

  // estimate modal state
  const [pendingModule, setPendingModule] = React.useState(null); // string|null
  const [pendingOptions, setPendingOptions] = React.useState(null);
  const [estimate, setEstimate] = React.useState(null);
  const [estimateLoading, setEstimateLoading] = React.useState(false);

  const reload = React.useCallback(async () => {
    if (!scriptId) return;
    setStatusLoading(true);
    setActiveJob(null);
    try {
      const r = await window.api?.scripts?.getModulesStatus?.(scriptId);
      if (r && r.ok !== false) {
        // 后端返 modules: [{module: 'chunks', done_count, total_count, status, ...}, ...]
        // 前端组件 (ModuleMatrixOverview / cardProps) 期望 dict: { chunks: {...}, chapter_facts: {...} }
        // 同时把后端的 'chapter-facts' (dash) 归一化成 'chapter_facts' (underscore) 跟 MODULE_META 对齐
        let modulesDict = r.modules;
        if (Array.isArray(r.modules)) {
          modulesDict = {};
          for (const m of r.modules) {
            if (!m || typeof m !== 'object') continue;
            const key = String(m.module || '').replace(/-/g, '_');
            if (!key) continue;
            modulesDict[key] = m;
          }
        }
        setStatusPayload({ ...r, modules: modulesDict || {} });
        if (r.active_job && (r.active_job.job_id || r.active_job.id)) {
          setActiveJob(r.active_job);
        }
      }
    } catch (_) {
      // backend not deployed yet — leave payload null, cards render in 'unknown'
      setStatusPayload({ modules: {} });
    } finally {
      setStatusLoading(false);
    }
    // P1-5: modules-status 现在不返 active_job,所以单独拉 /active-job 看有没有 full_pipeline / llm_extract / knowledge_sync 在跑
    try {
      if (window.api?.scripts?.activeJob) {
        const aj = await window.api.scripts.activeJob(scriptId);
        if (aj && aj.ok !== false && aj.active && aj.job) {
          const j = aj.job;
          const jid = j.job_id || j.id;
          if (jid) {
            setActiveJob((prev) => {
              // 不覆盖 confirmRebuild 刚设的 rebuild_* job(那个 jid 已正确)
              if (prev && (prev.job_id || prev.id) === jid) return prev;
              return {
                job_id: jid,
                kind: j.kind,
                module: j.module || (j.kind && !String(j.kind).startsWith('rebuild_') ? null : String(j.kind || '').replace(/^rebuild_/, '')),
                status: j.status || 'running',
                overall_progress: j.overall_progress || 0,
                overall_total: j.overall_total || 100,
                stage_label: j.stage_label,
              };
            });
          }
        } else if (aj && aj.ok !== false) {
          setActiveJob(null);
        }
      }
    } catch (_) {}
  }, [scriptId]);

  React.useEffect(() => { reload(); }, [reload]);

  // 兜底轮询:RebuildJobBanner 的 SSE 在 on_error 里什么都不做,部署重启 / 网络抖动断流后
  // 永远收不到 on_done → activeJob 一直卡「运行中」、其他「重做」按钮被禁用
  // (用户反馈:所有子项重做都用不了)。activeJob 存在时每 5s 直接查该 job 真实状态,
  // 终态(done/failed/cancelled)或查不到即本地清理 + reload 刷新真实计数。瞬时错误不误清。
  React.useEffect(() => {
    const jid = activeJob && (activeJob.job_id || activeJob.id);
    if (!jid || !scriptId) return undefined;
    let alive = true;
    const iv = setInterval(async () => {
      try {
        const r = await window.api?.scripts?.jobStatus?.(jid);
        if (!alive) return;
        const st = r && (r.status || (r.job && r.job.status));
        const terminal = st && ['done', 'done_with_errors', 'failed', 'cancelled'].includes(st);
        if ((r && r.ok === false) || terminal) {
          setActiveJob(null);
          reload();
        }
      } catch (_) { /* 瞬时错误:保持轮询,不误清「运行中」*/ }
    }, 5000);
    return () => { alive = false; clearInterval(iv); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJob && (activeJob.job_id || activeJob.id), scriptId, reload]);

  const runEstimate = React.useCallback(async (module, options) => {
    setEstimate(null);
    setEstimateLoading(true);
    try {
      const r = await window.api?.scripts?.rebuildEstimate?.(scriptId, module, options || {});
      setEstimate(r || { ok: false, error: 'no_response' });
    } catch (e) {
      const payload = (e && e.payload) || {};
      setEstimate({ ok: false, error: payload.error || e?.message || 'estimate_failed' });
    } finally {
      setEstimateLoading(false);
    }
  }, [scriptId]);

  const openEstimate = React.useCallback(async ({ module, options }) => {
    if (!module || !scriptId) return;
    setPendingModule(module);
    setPendingOptions(options || null);
    await runEstimate(module, options);
  }, [scriptId, runEstimate]);

  // 进度感知角色卡:cards 重建面板里改「重建到第 N 章」/「LLM 丰富」时,带新 options 重估并记下,
  // 让 confirmRebuild 用最新 options 派发(chapter_max / mode)。
  const updateOptions = React.useCallback(async (nextOptions) => {
    if (!pendingModule || !scriptId) return;
    setPendingOptions(nextOptions || null);
    await runEstimate(pendingModule, nextOptions || {});
  }, [pendingModule, scriptId, runEstimate]);

  const closeEstimate = React.useCallback(() => {
    setPendingModule(null);
    setPendingOptions(null);
    setEstimate(null);
  }, []);

  const confirmRebuild = React.useCallback(async () => {
    if (!pendingModule || !scriptId) return;
    try {
      let r;
      if (pendingModule === 'embeddings') {
        r = await window.api?.scripts?.rebuildEmbeddings?.(scriptId, pendingOptions || {});
      } else {
        r = await window.api?.scripts?.rebuild?.(scriptId, pendingModule, pendingOptions || {});
      }
      const jid = r && (r.job_id || r.id);
      if (jid) {
        setActiveJob({ job_id: jid, kind: `rebuild_${pendingModule}`, module: pendingModule, status: 'running', overall_progress: 0, overall_total: 100 });
        window.__apiToast?.(t('modules.toast.dispatched', { defaultValue: '重做任务已派发' }), { kind: 'ok', duration: 2400 });
      } else {
        window.__apiToast?.(t('modules.toast.dispatch_fail', { defaultValue: '派发失败' }), { kind: 'danger', detail: (r && r.error) || '' });
      }
    } catch (e) {
      const p = (e && e.payload) || {};
      if (p.job_id) {
        // 409 conflict — 复用已在跑的 job
        setActiveJob({ job_id: p.job_id, kind: `rebuild_${pendingModule}`, module: pendingModule, status: 'running', overall_progress: 0, overall_total: 100 });
      } else {
        window.__apiToast?.(t('modules.toast.dispatch_fail', { defaultValue: '派发失败' }), { kind: 'danger', detail: p.error || e?.message || '' });
      }
    } finally {
      closeEstimate();
    }
  }, [pendingModule, pendingOptions, scriptId, closeEstimate, t]);

  const onBannerDone = React.useCallback((finalJob) => {
    setActiveJob(null);
    // reload status → 让所有卡片刷新计数
    reload();
    try { window.dispatchEvent(new CustomEvent('rpg-scripts-updated')); } catch (_) {}
    window.__apiToast?.(t('modules.toast.rebuild_done', { defaultValue: '重做完成' }), { kind: 'ok', duration: 2800 });
  }, [reload, t]);

  const cardProps = React.useCallback((module) => {
    const m = (statusPayload && statusPayload.modules && statusPayload.modules[module]) || {};
    return {
      module,
      scriptId,
      status: m.status || 'unknown',
      doneCount: m.done_count,
      totalCount: m.total_count,
      lastJobId: m.last_job_id,
      lastRebuiltAt: m.last_rebuilt_at,
      source: m.source,
      activeJobId: activeJob ? (activeJob.job_id || activeJob.id) : null,
      onRebuild: openEstimate,
    };
  }, [statusPayload, scriptId, activeJob, openEstimate]);

  const bannerProps = {
    scriptId,
    activeJob,
    onChange: (j) => setActiveJob(j),
    onDone: onBannerDone,
  };
  const matrixProps = {
    scriptId,
    status: statusPayload,
    loading: statusLoading,
    activeJobId: activeJob ? (activeJob.job_id || activeJob.id) : null,
    onRebuild: openEstimate,
  };
  const modalProps = {
    open: !!pendingModule,
    module: pendingModule,
    scriptId,
    estimate,
    loading: estimateLoading,
    options: pendingOptions,
    onOptionsChange: updateOptions,  // 进度感知角色卡:cards 改 chapter_max/mode 时重估
    onClose: closeEstimate,
    onConfirm: confirmRebuild,
  };

  return {
    statusPayload,
    statusLoading,
    activeJob,
    reload,
    openEstimate,
    cardProps,
    bannerProps,
    matrixProps,
    modalProps,
  };
}

/* ModuleRebuildPanel — 「知识库中心」tab 用,把 matrix + banner + modal 合成一个 view.
   ScriptDetailPanel 在 "modules"(知识库中心)tab 直接 <ModuleRebuildPanel scriptId={s.id} /> */
export function ModuleRebuildPanel({ scriptId }) {
  const { t } = useTranslation();
  const rb = useScriptRebuild(scriptId);
  return (
    <CSSpaceBetween size="l">
      <RebuildJobBanner {...rb.bannerProps} />
      <ModuleMatrixOverview {...rb.matrixProps} />
      {/* 收敛处置④:三张新模块卡——与既有 7 模块走同一套 rb.cardProps/openEstimate 机制,
          端点 POST /api/scripts/{id}/rebuild/{module}[/estimate] 自动成立(后端并行注册)。 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {EXTRA_MODULE_CARDS.map((m) => (
          <ModuleStatusCard
            key={m.id}
            {...rb.cardProps(m.id)}
            title={t(m.titleKey, { defaultValue: m.titleDefault })}
            description={t(m.descKey, { defaultValue: m.descDefault })}
          />
        ))}
      </div>
      <RebuildEstimateModal {...rb.modalProps} />
    </CSSpaceBetween>
  );
}

export default ModuleRebuildPanel;
