// 账号 / 数据迁移 / 在线库 / 令牌 / 设备授权区。纯机械搬出,零行为变化。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL, useCallback as useCallbackPL } from 'react';
import { useTranslation } from 'react-i18next';
import { useReactiveUser, publishUser } from '../../platform-app.jsx';
import { SetGroup, SetRow } from './shared.jsx';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSInput from '@cloudscape-design/components/input';
import CSSelect from '@cloudscape-design/components/select';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSToggle from '@cloudscape-design/components/toggle';
import CSAlert from '@cloudscape-design/components/alert';
import CSBadge from '@cloudscape-design/components/badge';
import CSExpandableSection from '@cloudscape-design/components/expandable-section';

// ── 账号设置（Beta Co-builders opt-out）──────────────────────────────────────
function AccountSection() {
  const { t } = useTranslation();
  const user = useReactiveUser();
  const isCoBuilder = user?.is_co_builder === true;
  // true = 参加，false = 不参加（co_builder_opt_out=true 表示退出）
  const [checked, setChecked] = useStatePL(() => !user?.co_builder_opt_out);
  const [saving, setSaving] = useStatePL(false);

  // 用户数据就绪后同步初始值
  useEffectPL(() => {
    setChecked(!user?.co_builder_opt_out);
  }, [user?.co_builder_opt_out]);

  const handleToggle = async (newChecked) => {
    setChecked(newChecked);
    setSaving(true);
    try {
      await fetch('/api/me/profile', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ co_builder_opt_out: !newChecked }),
      });
      publishUser({ co_builder_opt_out: !newChecked });
      window.__apiToast?.(t('settings.account.co_builder_saved'), { kind: 'ok', duration: 1800 });
    } catch (e) {
      window.__apiToast?.(t('settings.account.co_builder_save_fail'), { kind: 'danger', detail: e?.message });
      // 回滚
      setChecked(!newChecked);
    }
    setSaving(false);
  };

  return (
    <CSSpaceBetween size="l">
      <SetGroup title={t('settings.account.title')}>
        {isCoBuilder ? (
          <SetRow
            label={t('settings.account.co_builder_label')}
            description={t('settings.account.co_builder_desc')}
          >
            <CSToggle
              checked={checked}
              onChange={({ detail }) => handleToggle(detail.checked)}
              disabled={saving}
            >
              {checked ? t('settings.account.co_builder_on') : t('settings.account.co_builder_off')}
            </CSToggle>
          </SetRow>
        ) : (
          <SetRow label={t('settings.account.co_builder_label')} description="">
            <span style={{ fontSize: 13, color: 'var(--text-quiet)' }}>{t('settings.account.co_builder_na')}</span>
          </SetRow>
        )}
      </SetGroup>
      <DataMigrationSection />
      <OnlineLibrarySection />
    </CSSpaceBetween>
  );
}

// 账号数据迁移:把个人数据(剧本/存档/角色卡/偏好)整体导出为 zip,在本地自部署实例导入。
function DataMigrationSection() {
  const { t } = useTranslation();
  const [est, setEst] = useStatePL(null);
  const [estErr, setEstErr] = useStatePL("");
  const [includeChunks, setIncludeChunks] = useStatePL(false);
  const [exporting, setExporting] = useStatePL(false);
  const [importing, setImporting] = useStatePL(false);
  const [importFile, setImportFile] = useStatePL(null);
  const [importResult, setImportResult] = useStatePL(null);
  const [importJob, setImportJob] = useStatePL(null);   // {stage, stage_progress, stage_total}
  const fileRef = React.useRef(null);
  const esRef = React.useRef(null);
  const pollRef = React.useRef(null);

  useEffectPL(() => {
    let alive = true;
    window.api?.account?.migrateEstimate?.()
      .then((r) => { if (alive) setEst(r); })
      .catch((e) => { if (alive) setEstErr(e?.message || String(e)); });
    return () => { alive = false; };
  }, []);

  const doExport = () => {
    setExporting(true);
    try {
      // 同源 GET + cookie → 直接触发浏览器下载 zip。
      const url = window.api.account.migrateExportUrl(includeChunks);
      const a = document.createElement('a');
      a.href = url;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.__apiToast?.(t('settings.migrate.export_started', { defaultValue: '已开始下载数据包…' }), { kind: 'ok', duration: 2200 });
    } catch (e) {
      window.__apiToast?.(t('settings.migrate.export_fail', { defaultValue: '导出失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      // 下载是浏览器接管,这里只复位按钮态
      setTimeout(() => setExporting(false), 800);
    }
  };

  const STAGE_LABELS = {
    scripts: t('settings.more.migrate.stage_scripts'),
    saves: t('settings.more.migrate.stage_saves'),
    cards: t('settings.more.migrate.stage_cards'),
    done: t('settings.more.migrate.stage_done'),
  };

  const finishJob = async (jobId) => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (esRef.current) { try { esRef.current.close?.(); } catch {} esRef.current = null; }
    try {
      const s = await window.api.scripts.jobStatus(jobId);
      const job = s?.job || {};
      const summary = (job.usage_actual && job.usage_actual.summary) || {};
      setImportResult({ scripts: summary.scripts ?? 0, saves: summary.saves ?? 0, cards: summary.cards ?? 0, warnings: job.warnings || [] });
      window.__apiToast?.(t('settings.migrate.import_done', { defaultValue: '导入完成' }), { kind: 'ok', duration: 2600,
        detail: t('settings.more.migrate.import_done_detail', { scripts: summary.scripts ?? 0, saves: summary.saves ?? 0, cards: summary.cards ?? 0 }) });
    } catch (e) {
      window.__apiToast?.(t('settings.migrate.import_fail', { defaultValue: '导入失败' }), { kind: 'danger', detail: e?.message });
    } finally {
      setImportJob(null); setImporting(false);
    }
  };

  const doImport = async () => {
    if (!importFile) return;
    setImporting(true); setImportResult(null); setImportJob({ stage: 'scripts', stage_progress: 0, stage_total: 0 });
    let jobId = null;
    try {
      const r = await window.api.account.migrateImport(importFile);
      jobId = r?.job_id;
      if (!jobId) throw new Error(r?.error || t('settings.more.migrate.no_job_id'));
    } catch (e) {
      setImporting(false); setImportJob(null);
      window.__apiToast?.(t('settings.migrate.import_fail', { defaultValue: '导入失败' }), { kind: 'danger', detail: e?.payload?.error || e?.message });
      return;
    }
    const isTerminal = (st) => ['done', 'done_with_errors', 'failed', 'cancelled'].includes(st);
    // SSE 主路 + 轮询兜底
    esRef.current = window.api.scripts.streamImport(jobId, {
      on_update: (jb) => { setImportJob(jb); if (isTerminal(jb.status)) finishJob(jobId); },
      on_done: () => finishJob(jobId),
      on_error: () => {
        if (pollRef.current) return;
        pollRef.current = setInterval(async () => {
          try {
            const s = await window.api.scripts.jobStatus(jobId);
            const job = s?.job; if (!job) return;
            setImportJob(job);
            if (isTerminal(job.status)) finishJob(jobId);
          } catch {}
        }, 2000);
      },
    });
  };

  useEffectPL(() => () => {
    if (esRef.current) { try { esRef.current.close?.(); } catch {} }
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  return (
    <SetGroup
      title={t('settings.migrate.title', { defaultValue: '数据迁移(导出 / 导入)' })}
      description={t('settings.migrate.desc', { defaultValue: '把你的全部个人数据打包,迁移到本地自部署实例;或从数据包恢复。不含 API 密钥。' })}
    >
      <CSAlert type="info">
        {t('settings.migrate.note_keys', { defaultValue: '出于安全,导出不含 API 密钥(在服务端加密存储,跨实例无法解密)。迁移到本地后请在「设置 → 模型」重新填写各 provider 的 API key。' })}
      </CSAlert>

      <SetRow
        label={t('settings.migrate.export_label', { defaultValue: '导出我的全部数据' })}
        description={est
          ? t('settings.migrate.export_counts', { defaultValue: '剧本 {{s}} · 存档 {{v}} · 角色卡 {{c}} · 模型条目 {{m}}', s: est.scripts ?? 0, v: est.saves ?? 0, c: est.cards ?? 0, m: est.model_entries ?? 0 })
          : (estErr ? t('settings.migrate.est_fail', { defaultValue: '统计失败:' }) + estErr : t('settings.migrate.estimating', { defaultValue: '正在统计…' }))}
      >
        <CSSpaceBetween size="xs">
          <CSToggle checked={includeChunks} onChange={({ detail }) => setIncludeChunks(detail.checked)}>
            {t('settings.migrate.include_chunks', { defaultValue: '包含原文切片(体积更大,用于本地继续做向量检索)' })}
          </CSToggle>
          <CSButton variant="primary" iconName="download" loading={exporting} onClick={doExport}>
            {t('settings.migrate.export_btn', { defaultValue: '导出数据包(.zip)' })}
          </CSButton>
        </CSSpaceBetween>
      </SetRow>

      <SetRow
        label={t('settings.migrate.import_label', { defaultValue: '导入数据包' })}
        description={t('settings.migrate.import_help', { defaultValue: '选择从在线服务导出的 account-*.zip。导入会在当前账号下新建剧本/存档/角色卡,不覆盖现有数据。' })}
      >
        <CSSpaceBetween size="xs">
          <input
            ref={fileRef}
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => { setImportFile(e.target.files?.[0] || null); setImportResult(null); }}
            style={{ fontSize: 13 }}
          />
          <CSButton iconName="upload" loading={importing} disabled={!importFile || importing} onClick={doImport}>
            {t('settings.migrate.import_btn', { defaultValue: '导入到当前账号' })}
          </CSButton>
        </CSSpaceBetween>
      </SetRow>

      {importJob && (
        <CSBox>
          <div style={{ fontSize: 13, marginBottom: 4 }}>
            {(STAGE_LABELS[importJob.stage] || importJob.stage || t('settings.more.migrate.stage_processing'))}
            {importJob.stage_total ? ` ${importJob.stage_progress || 0}/${importJob.stage_total}` : '…'}
          </div>
          <div style={{ height: 6, background: 'var(--line,#36322d)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${importJob.stage_total ? Math.round(100 * (importJob.stage_progress || 0) / importJob.stage_total) : 30}%`,
              background: 'var(--accent,#c96442)', transition: 'width .3s' }} />
          </div>
        </CSBox>
      )}

      {importResult && (
        <CSAlert type={(importResult.warnings || []).length ? 'warning' : 'success'} header={t('settings.migrate.import_result', { defaultValue: '导入结果' })}>
          <div>{t('settings.migrate.import_summary', { defaultValue: '剧本 {{s}} · 存档 {{v}} · 角色卡 {{c}}', s: importResult.scripts ?? 0, v: importResult.saves ?? 0, c: importResult.cards ?? 0 })}</div>
          {(importResult.warnings || []).length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
              {importResult.warnings.slice(0, 20).map((w, i) => <li key={i}>{w}</li>)}
              {importResult.warnings.length > 20 && <li>{t('settings.more.migrate.warnings_truncated', { count: importResult.warnings.length - 20 })}</li>}
            </ul>
          )}
        </CSAlert>
      )}
    </SetGroup>
  );
}

// 功能 B:本地↔在线剧本库联邦。集连接(PAT/设备码)+ 浏览/导入/发布 + 设备授权 + PAT 管理。
const DEFAULT_ONLINE_BASE = 'https://rpg-roleplay.stellatrix.icu';

function OnlineLibrarySection() {
  const { t } = useTranslation();
  const [conn, setConn] = useStatePL(null);            // {connected, base_url}
  const [isProvider, setIsProvider] = useStatePL(false); // 本实例是否为在线库提供方(server 模式)
  const reload = useCallbackPL(async () => {
    try { setConn(await window.api.federation.connectorGet()); } catch { setConn({ connected: false, base_url: DEFAULT_ONLINE_BASE }); }
  }, []);
  useEffectPL(() => { reload(); }, [reload]);
  useEffectPL(() => {
    window.api?.federation?.providerInfo?.().then((r) => setIsProvider(!!r?.provider_enabled)).catch(() => setIsProvider(false));
  }, []);

  // 角色分离:
  //  - 提供方(在线服务,server 模式)只显示「令牌管理」;设备授权在独立 /device 页完成,
  //    不在设置里放配对码填写窗口(避免在线服务器出现「连接到在线服务」这种自连客户端 UI)。
  //  - 客户端(本地自部署)只显示连接器(连接在线服务 / 浏览 / 导入 / 发布)。
  if (isProvider) {
    return (
      <SetGroup
        title={t('settings.more.online_lib.provider_title')}
        description={t('settings.more.online_lib.provider_desc')}
      >
        <PatManager />
      </SetGroup>
    );
  }
  return (
    <SetGroup
      title={t('settings.more.online_lib.client_title')}
      description={t('settings.more.online_lib.client_desc')}
    >
      <ConnectorConnect conn={conn} onChange={reload} />
      {conn?.connected && <OnlineBrowse />}
      {conn?.connected && <OnlinePublish />}
    </SetGroup>
  );
}

function ConnectorConnect({ conn, onChange }) {
  const { t } = useTranslation();
  const [base, setBase] = useStatePL(conn?.base_url || DEFAULT_ONLINE_BASE);
  const [token, setToken] = useStatePL('');
  const [busy, setBusy] = useStatePL(false);
  const [device, setDevice] = useStatePL(null);        // {user_code, verification_uri, device_code, base_url, interval}
  const pollRef = React.useRef(null);
  useEffectPL(() => { setBase(conn?.base_url || DEFAULT_ONLINE_BASE); }, [conn?.base_url]);
  useEffectPL(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const savePat = async () => {
    if (!token.trim()) { window.__apiToast?.(t('settings.more.online_lib.paste_token_warn'), { kind: 'warn' }); return; }
    setBusy(true);
    try {
      await window.api.federation.connectorSet(base.trim(), token.trim());
      window.__apiToast?.(t('settings.more.online_lib.connected_ok'), { kind: 'ok' });
      setToken(''); onChange?.();
    } catch (e) { window.__apiToast?.(t('settings.more.online_lib.connect_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); }
    finally { setBusy(false); }
  };

  const disconnect = async () => {
    setBusy(true);
    try { await window.api.federation.connectorSet(base.trim(), ''); window.__apiToast?.(t('settings.more.online_lib.disconnected'), { kind: 'ok' }); onChange?.(); }
    catch (e) { window.__apiToast?.(t('settings.more.online_lib.op_fail'), { kind: 'danger', detail: e?.message }); }
    finally { setBusy(false); }
  };

  const startDevice = async () => {
    setBusy(true);
    try {
      const d = await window.api.federation.deviceStart(base.trim(), ['library:read', 'library:publish']);
      setDevice(d);
      const iv = Math.max(2, (d.interval || 5)) * 1000;
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const r = await window.api.federation.devicePoll(d.base_url || base.trim(), d.device_code);
          if (r.connected) {
            clearInterval(pollRef.current); pollRef.current = null;
            setDevice(null); window.__apiToast?.(t('settings.more.online_lib.connected_ok'), { kind: 'ok' }); onChange?.();
          } else if (r.status && !['authorization_pending', 'pending'].includes(r.status)) {
            clearInterval(pollRef.current); pollRef.current = null;
            setDevice(null); window.__apiToast?.(t('settings.more.online_lib.auth_incomplete', { status: r.status }), { kind: 'warn' });
          }
        } catch { /* 继续轮询 */ }
      }, iv);
    } catch (e) { window.__apiToast?.(t('settings.more.online_lib.device_start_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); }
    finally { setBusy(false); }
  };

  if (conn?.connected) {
    return (
      <CSSpaceBetween size="s">
        <CSBox>{t('settings.more.online_lib.connected_to')}<strong>{conn.base_url}</strong></CSBox>
        <CSButton iconName="unlocked" loading={busy} onClick={disconnect}>{t('settings.more.online_lib.disconnect')}</CSButton>
      </CSSpaceBetween>
    );
  }

  return (
    <CSSpaceBetween size="m">
      <SetRow label={t('settings.more.online_lib.server_url')} description={t('settings.more.online_lib.server_url_desc')}>
        <CSInput value={base} onChange={({ detail }) => setBase(detail.value)} placeholder={DEFAULT_ONLINE_BASE} />
      </SetRow>

      <SetRow label={t('settings.more.online_lib.device_method')} description={t('settings.more.online_lib.device_method_desc')}>
        {device ? (
          <CSAlert type="info" header={t('settings.more.online_lib.device_auth_header')}>
            <div>{t('settings.more.online_lib.device_step1')} <a href={device.verification_uri_complete || device.verification_uri} target="_blank" rel="noopener noreferrer">{device.verification_uri_complete || device.verification_uri}</a></div>
            <div>{t('settings.more.online_lib.device_step2')} <strong style={{ fontSize: 18, letterSpacing: 2 }}>{device.user_code}</strong></div>
            <div style={{ marginTop: 6, color: 'var(--text-quiet)' }}>{t('settings.more.online_lib.device_waiting')}</div>
          </CSAlert>
        ) : (
          <CSButton variant="primary" iconName="external" loading={busy} onClick={startDevice}>{t('settings.more.online_lib.device_connect_btn')}</CSButton>
        )}
      </SetRow>

      <SetRow label={t('settings.more.online_lib.pat_method')} description={t('settings.more.online_lib.pat_method_desc')}>
        <CSSpaceBetween size="xs">
          <CSInput value={token} type="password" onChange={({ detail }) => setToken(detail.value)} placeholder="rpgpat_…" />
          <CSButton loading={busy} onClick={savePat}>{t('settings.more.online_lib.pat_save_btn')}</CSButton>
        </CSSpaceBetween>
      </SetRow>
    </CSSpaceBetween>
  );
}

function OnlineBrowse() {
  const { t } = useTranslation();
  const [q, setQ] = useStatePL('');
  const [items, setItems] = useStatePL(null);
  const [loading, setLoading] = useStatePL(false);
  const [importing, setImporting] = useStatePL({});
  const load = useCallbackPL(async (query) => {
    setLoading(true);
    try { const r = await window.api.federation.connectorScripts(query); setItems(r?.items || []); }
    catch (e) { window.__apiToast?.(t('settings.more.online_lib.browse_load_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); setItems([]); }
    finally { setLoading(false); }
  }, []);
  const doImport = async (it) => {
    setImporting((p) => ({ ...p, [it.id]: true }));
    try {
      const r = await window.api.federation.connectorImport(it.id);
      window.__apiToast?.(t('settings.more.online_lib.browse_import_ok'), { kind: 'ok', detail: t('settings.more.online_lib.browse_import_detail', { title: it.title, local: t('settings.more.online_lib.browse_import_local'), id: r.script_id }) });
    } catch (e) { window.__apiToast?.(t('settings.more.online_lib.browse_import_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); }
    finally { setImporting((p) => ({ ...p, [it.id]: false })); }
  };
  return (
    <CSExpandableSection headerText={t('settings.more.online_lib.browse_header')} defaultExpanded
      onChange={({ detail }) => { if (detail.expanded && items == null) load(''); }}>
      <CSSpaceBetween size="s">
        <div style={{ display: 'flex', gap: 8, maxWidth: 460 }}>
          <div style={{ flex: 1 }}>
            <CSInput value={q} type="search" placeholder={t('settings.more.online_lib.browse_search_placeholder')} onChange={({ detail }) => setQ(detail.value)}
              onKeyDown={(e) => { if (e.detail.key === 'Enter') load(q); }} />
          </div>
          <CSButton loading={loading} onClick={() => load(q)}>{t('settings.more.online_lib.browse_search_btn')}</CSButton>
        </div>
        {items && items.length === 0 && <CSBox color="text-body-secondary">{t('settings.more.online_lib.browse_empty')}</CSBox>}
        {(items || []).map((it) => (
          <div key={it.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '8px 10px', border: '1px solid var(--line,#36322d)', borderRadius: 8 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>{it.title || t('settings.more.online_lib.untitled')}</div>
              <div style={{ fontSize: 12, color: 'var(--text-quiet)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {it.owner_name ? `by ${it.owner_name} · ` : ''}♥ {it.clone_count || 0}{it.description ? ' · ' + String(it.description).slice(0, 50) : ''}
              </div>
            </div>
            <CSButton variant="primary" loading={!!importing[it.id]} onClick={() => doImport(it)}>{t('settings.more.online_lib.browse_import_btn')}</CSButton>
          </div>
        ))}
      </CSSpaceBetween>
    </CSExpandableSection>
  );
}

function OnlinePublish() {
  const { t } = useTranslation();
  const [scripts, setScripts] = useStatePL([]);
  const [sel, setSel] = useStatePL(null);
  const [busy, setBusy] = useStatePL(false);
  useEffectPL(() => {
    window.api.scripts.list().then((r) => {
      const list = Array.isArray(r) ? r : (r?.items || r?.scripts || []);
      setScripts(list.filter((s) => s.is_owner !== false).map((s) => ({ value: String(s.id), label: s.title || `${t('settings.more.online_lib.script_prefix')} #${s.id}` })));
    }).catch(() => {});
  }, []);
  const publish = async () => {
    if (!sel) return;
    setBusy(true);
    try {
      const r = await window.api.federation.connectorPublish(Number(sel.value));
      window.__apiToast?.(t('settings.more.online_lib.publish_ok'), { kind: 'ok', detail: `${t('settings.more.online_lib.online_script_prefix')} #${r.script_id}` });
    } catch (e) { window.__apiToast?.(t('settings.more.online_lib.publish_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); }
    finally { setBusy(false); }
  };
  return (
    <SetRow label={t('settings.more.online_lib.publish_label')} description={t('settings.more.online_lib.publish_desc')}>
      <div style={{ display: 'flex', gap: 8, maxWidth: 460 }}>
        <div style={{ flex: 1 }}>
          <CSSelect selectedOption={sel} options={scripts} placeholder={t('settings.more.online_lib.publish_select_placeholder')}
            onChange={({ detail }) => setSel(detail.selectedOption)} />
        </div>
        <CSButton iconName="upload" loading={busy} disabled={!sel} onClick={publish}>{t('settings.more.online_lib.publish_btn')}</CSButton>
      </div>
    </SetRow>
  );
}

function PatManager() {
  const { t } = useTranslation();
  const [items, setItems] = useStatePL([]);
  const [name, setName] = useStatePL('');
  const [scopes, setScopes] = useStatePL({ read: true, publish: false });
  const [created, setCreated] = useStatePL(null);
  const [busy, setBusy] = useStatePL(false);
  const reload = useCallbackPL(async () => {
    try { const r = await window.api.federation.patList(); setItems(r?.items || []); } catch { setItems([]); }
  }, []);
  useEffectPL(() => { reload(); }, [reload]);
  const create = async () => {
    const sc = [scopes.read && 'library:read', scopes.publish && 'library:publish'].filter(Boolean);
    if (!sc.length) { window.__apiToast?.(t('settings.more.online_lib.pat_scope_warn'), { kind: 'warn' }); return; }
    setBusy(true);
    try {
      const r = await window.api.federation.patCreate({ name: name.trim(), scopes: sc });
      setCreated(r.token); setName(''); reload();
    } catch (e) { window.__apiToast?.(t('settings.more.online_lib.pat_create_fail'), { kind: 'danger', detail: e?.payload?.error || e?.message }); }
    finally { setBusy(false); }
  };
  const revoke = async (id) => {
    try { await window.api.federation.patRevoke(id); reload(); window.__apiToast?.(t('settings.more.online_lib.pat_revoked'), { kind: 'ok' }); }
    catch (e) { window.__apiToast?.(t('settings.more.online_lib.op_fail'), { kind: 'danger', detail: e?.message }); }
  };
  return (
    <CSSpaceBetween size="s">
      {created && (
        <CSAlert type="success" header={t('settings.more.online_lib.pat_created_header')} dismissible onDismiss={() => setCreated(null)}>
          <code style={{ wordBreak: 'break-all' }}>{created}</code>
        </CSAlert>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ width: 180 }}>
          <CSInput value={name} placeholder={t('settings.more.online_lib.pat_name_placeholder')} onChange={({ detail }) => setName(detail.value)} />
        </div>
        <CSToggle checked={scopes.read} onChange={({ detail }) => setScopes((s) => ({ ...s, read: detail.checked }))}>{t('settings.more.online_lib.pat_scope_read')}</CSToggle>
        <CSToggle checked={scopes.publish} onChange={({ detail }) => setScopes((s) => ({ ...s, publish: detail.checked }))}>{t('settings.more.online_lib.pat_scope_publish')}</CSToggle>
        <CSButton loading={busy} onClick={create}>{t('settings.more.online_lib.pat_create_btn')}</CSButton>
      </div>
      {items.length === 0 && <CSBox color="text-body-secondary" fontSize="body-s">{t('settings.more.online_lib.pat_empty')}</CSBox>}
      {items.map((p) => (
        <div key={p.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, fontSize: 13 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <CSBadge color={p.source === 'device' ? 'green' : 'grey'}>{p.source === 'device' ? t('settings.more.online_lib.pat_source_device') : t('settings.more.online_lib.pat_source_manual')}</CSBadge>
            <strong>{p.name || t('settings.more.online_lib.untitled')}</strong>
            <span style={{ color: 'var(--text-quiet)' }}>{(p.scopes || []).join(', ')}</span>
            <span style={{ color: 'var(--text-quiet)', fontSize: 12 }}>
              {p.last_used_at ? `· ${t('settings.more.online_lib.pat_last_used')} ` + (window.__fmt?.ago(p.last_used_at) || p.last_used_at) : `· ${t('settings.more.online_lib.pat_never_used')}`}
              {p.revoked_at ? ` · ${t('settings.more.online_lib.pat_revoked_badge')}` : ''}
            </span>
          </span>
          {!p.revoked_at && <CSButton variant="inline-link" onClick={() => revoke(p.id)}>{t('settings.more.online_lib.pat_revoke_btn')}</CSButton>}
        </div>
      ))}
    </CSSpaceBetween>
  );
}

export {
  AccountSection,
};
