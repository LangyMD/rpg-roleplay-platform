// 插件 / MCP / Skill / API 能力页。从 platform-app.jsx 搬出。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import { Icon } from '../../game-icons.jsx';
import Modal from '../Modal.jsx';
import {
  PromptModal, SettingsToggle,
} from './shared.jsx';
import { copyText } from '../../lib/clipboard.js';
import { validateNewMcpServer, mcpLaunchable } from '../../lib/mcp-validate.js';
import { mcpDisplayName, mcpCommandLine, mcpStdioFields } from '../../lib/mcp-form.js';
import CSAlert from '@cloudscape-design/components/alert';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import i18n from '../../i18n/index.js';

/* ---------------------------- PLUGINS / MCP / SKILLS / API ----- */
// task 50：原本 decks 是 5 项 plugins / 5 项 mcp / 4 项 skills 全部硬编码示例
// （filesystem·本地 / 时间线可视化 / 角色一致性 等），整页零 API 调用，
// 「校验」按钮是 dead button。现在改为：
//   - kind="plugins"  → /api/tools → tools.plugins[]（用户可看可改但少 toggle，所有 enabled）
//   - kind="mcp"      → /api/tools → tools.mcp.servers[] + /api/mcp/runtime 拼运行状态
//   - kind="skills"   → /api/tools → tools.skills[]（来自本地 sandbox）
//   - kind="apis"     → /api/platform.commands（真后端 commands 列表）
function CapPage({ kind }) {
  const [addOpen, setAddOpen] = useStatePL(false);
  const [items, setItems] = useStatePL([]);
  const [loading, setLoading] = useStatePL(false);
  const [err, setErr] = useStatePL("");
  const [reloadTick, setReloadTick] = useStatePL(0);

  useEffectPL(() => {
    if (kind === "apis") return;
    let cancelled = false;
    setLoading(true); setErr("");
    (async () => {
      try {
        const r = await window.api.tools.list();
        if (cancelled) return;
        const t = (r && r.tools) || {};
        let list = [];
        if (kind === "plugins") {
          list = (t.plugins || []).map(p => ({
            id: p.id || p.name, name: p.name || p.id, desc: p.description || i18n.t('cap.builtin_plugin'),
            tag: p.kind || "plugin", on: p.enabled !== false, status: p.enabled === false ? i18n.t('cap.status_off') : i18n.t('cap.status_on'),
            _raw: p,
          }));
        } else if (kind === "mcp") {
          const servers = ((t.mcp || {}).servers) || [];
          // 拉运行状态以判断"已连接" vs "未连接"
          let running = [];
          try { const rt = await window.api.mcp.runtime(); running = (rt && (rt.running || [])) || []; } catch (_) {}
          const runSet = new Set(running.map(r => r.id || r.server_id || r.name));
          list = servers.map(s => {
            const isOn = !!s.enabled;
            const isRunning = isOn && (runSet.has(s.id) || runSet.has(s.server_id) || runSet.has(s.name));
            return {
              // 名字只在 display_name(后端不输出 name);按 name || id 取会把中文名服务器显示成 mcp-<哈希>。
              id: s.id || s.server_id || s.name, name: mcpDisplayName(s),
              desc: s.description || (s.transport === "http" ? `HTTP · ${s.url || s.endpoint || "—"}` : `stdio · ${s.command || "—"}`),
              tag: s.transport || (s.url || s.endpoint ? "http" : "stdio"),
              on: isOn,
              status: isRunning ? i18n.t('cap.status_connected') : (isOn ? i18n.t('cap.status_disconnected') : i18n.t('cap.status_off')),
              _raw: s,
            };
          });
        } else if (kind === "skills") {
          list = (t.skills || []).map(s => ({
            id: s.id || s.slug || s.name, name: s.name || s.id, desc: s.description || s.summary || "",
            tag: s.version || s.kind || "v1", on: s.enabled !== false, status: s.enabled !== false ? i18n.t('cap.status_deployed') : i18n.t('cap.status_off'),
            _raw: s,
          }));
        }
        if (cancelled) return;
        setItems(list);
      } catch (e) {
        if (!cancelled) setErr(e?.message || i18n.t('cap.fetch_failed'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [kind, reloadTick]);

  if (kind === "apis") return <ApiList />;

  // 校验：对 MCP 走 mcp.validate 逐条；其他类型只刷新 /api/tools 即可。
  const onValidateAll = async () => {
    setLoading(true);
    if (kind === "mcp") {
      const results = await Promise.all(
        items.filter(it => it.on).map(it =>
          window.api.mcp.validate({ id: it.id, server_id: it.id }).catch(() => null)
        )
      );
      // ok = 真能启动(ready_to_launch),不是「请求没报错」:命令在服务器上找不到也会回 200。
      const ok = results.filter(mcpLaunchable).length;
      const fail = results.length - ok;
      window.__apiToast?.(i18n.t('cap.validate_done', { ok, fail }), { kind: fail ? "warn" : "ok", duration: 2400 });
    }
    setReloadTick(t => t + 1);
  };

  const emptyMsg = kind === "mcp"
    ? i18n.t('cap.empty_mcp')
    : kind === "skills"
    ? i18n.t('cap.empty_skills')
    : i18n.t('cap.empty_plugins');

  return (
    <CSSpaceBetween size="l">
      {err && <CSAlert type="error" dismissible={false}>{i18n.t('cap.load_failed', { err })}</CSAlert>}
      <CSContainer header={
        <CSHeader
          variant="h2"
          counter={loading ? undefined : i18n.t('cap.counter', { total: items.length, on: items.filter(i => i.on).length })}
          actions={
            <CSSpaceBetween size="xs" direction="horizontal">
              <CSButton
                iconName="refresh"
                onClick={onValidateAll}
                loading={loading}
              >
                {i18n.t('cap.validate')}
              </CSButton>
              <CSButton
                variant="primary"
                iconName="add-plus"
                onClick={() => setAddOpen(true)}
              >
                {kind === "mcp" ? i18n.t('cap.add_server') : kind === "skills" ? i18n.t('cap.import_skill') : i18n.t('cap.add_plugin')}
              </CSButton>
            </CSSpaceBetween>
          }
        >
          {kind === "plugins" ? i18n.t('cap.plugins') : kind === "mcp" ? i18n.t('cap.mcp_servers') : i18n.t('cap.skill_packs')}
        </CSHeader>
      }>
        {loading && items.length === 0 ? (
          <CSBox textAlign="center" color="text-body-secondary" padding="l">{i18n.t('cap.loading')}</CSBox>
        ) : items.length === 0 ? (
          <CSBox textAlign="center" color="text-body-secondary" padding="l">{emptyMsg}</CSBox>
        ) : (
          <div className="pl-cap-grid">
            {items.map((it, i) => <CapCard key={it.id || i} {...it} kind={kind} onChanged={() => setReloadTick(t => t + 1)} />)}
          </div>
        )}
      </CSContainer>
      <PromptModal
        open={addOpen}
        eyebrow={kind === "mcp" ? i18n.t('cap.add_mcp_server') : kind === "skills" ? i18n.t('cap.import_skill') : i18n.t('cap.add_plugin')}
        title={kind === "mcp" ? i18n.t('cap.configure_mcp') : kind === "skills" ? i18n.t('cap.choose_skill') : i18n.t('cap.add_platform_plugin')}
        hint={kind === "mcp" ? "POST /api/v1/mcp/server" : kind === "skills" ? "POST /api/v1/skills/import" : "POST /api/v1/plugins"}
        fields={
          kind === "mcp" ? [
            { key: "name", label: i18n.t('cap.f_name'), required: true, placeholder: i18n.t('cap.ph_mcp_name') },
            { key: "transport", label: i18n.t('cap.f_transport'), type: "select", default: "stdio",
              options: [{ value: "stdio", label: i18n.t('cap.opt_stdio') }, { value: "http", label: i18n.t('cap.opt_http') }] },
            { key: "command", label: i18n.t('cap.f_command_url'), required: true, mono: true,
              placeholder: "stdio: npx @modelcontextprotocol/server-filesystem /data\nhttp: https://host:port" },
            { key: "env", label: i18n.t('cap.f_env_headers'), type: "textarea",
              placeholder: i18n.t('cap.ph_env'), rows: 3 },
          ] : kind === "skills" ? [
            { key: "repo_url", label: i18n.t('cap.f_github'), mono: true, placeholder: i18n.t('cap.ph_github') },
            { key: "file", label: i18n.t('cap.f_local_file'), type: "file", hint: i18n.t('cap.hint_local_file') },
          ] : [
            { key: "id", label: i18n.t('cap.f_plugin_id'), required: true, mono: true, placeholder: i18n.t('cap.ph_plugin_id') },
            { key: "name", label: i18n.t('cap.f_display_name'), required: true, placeholder: i18n.t('cap.ph_display_name') },
            { key: "desc", label: i18n.t('cap.f_desc'), type: "textarea", placeholder: i18n.t('cap.ph_desc') },
          ]
        }
        submitLabel={kind === "mcp" ? i18n.t('cap.submit_mcp') : kind === "skills" ? i18n.t('cap.submit_skill') : i18n.t('cap.submit_add')}
        onClose={() => setAddOpen(false)}
        onConfirm={async (vals) => {
          // task 50：原 onConfirm = () => setAddOpen(false)，纯关闭。
          // 现在按 kind 真打后端，失败把错误吐给用户。
          try {
            if (kind === "mcp") {
              // 解析 KEY=VALUE 行（env）
              const envObj = {};
              for (const line of String(vals.env || "").split("\n")) {
                const m = line.trim().match(/^([^=]+)=(.*)$/);
                if (m) envObj[m[1].trim()] = m[2];
              }
              const body = { name: vals.name, transport: vals.transport || "stdio", enabled: true };
              if (body.transport === "http") body.url = vals.command;
              else body.command = vals.command;
              if (Object.keys(envObj).length) body.env = envObj;
              const saved = await window.api.mcp.upsert(body);
              // 校验只认 id:用 upsert 回的 server_id(以前发 {name},后端读 id → 校验从没跑过)。
              const v = await validateNewMcpServer(window.api, saved?.server_id);
              window.__apiToast?.(v.message, { kind: v.ok ? "ok" : "warn", duration: v.ok ? 2000 : 5000 });
            } else if (kind === "skills") {
              const repo = String(vals.repo_url || "").trim();
              const f = vals.file;
              const isMd = f && /\.md$/i.test(f.name || "");
              if (!repo && !f) throw new Error(i18n.t('cap.need_repo_or_file'));
              if (repo || isMd) {
                // 人格 skill → 蒸馏成角色卡 + 人设图(纯数据,每用户隔离)
                const body = repo
                  ? { source: "github", repo_url: repo }
                  : { source: "upload", files: [{ name: f.name, content: await f.text() }] };
                const r = await window.api.personaSkills.import(body);
                if (!r || !r.ok) throw new Error((r && r.error) || i18n.t('cap.import_failed'));
                const nm = (r.card && r.card.name) || i18n.t('cap.card');
                const img = r.image_status === "queued" ? i18n.t('cap.persona_img_queued') : "";
                window.__apiToast?.(i18n.t('cap.card_generated', { name: nm, img }), { kind: "ok", duration: 2600 });
              } else {
                // .zip/.tar.gz 可执行 Skill 包(管理员)
                await window.api.skills.importPack(f);
                window.__apiToast?.(i18n.t('cap.skill_imported'), { kind: "ok", duration: 1800 });
              }
            } else {
              // plugins 没有专用 POST，只能在前端打 toast 解释
              window.__apiToast?.(i18n.t('cap.plugins_preset'), { kind: "warn", duration: 2400 });
            }
            setAddOpen(false);
            setReloadTick(t => t + 1);
          } catch (e) {
            window.__apiToast?.(i18n.t('cap.add_failed'), { kind: "danger", detail: e?.message || String(e) });
          }
        }}
      />
    </CSSpaceBetween>
  );
}

function CapCard({ id, name, desc, tag, on, status, kind, onChanged, _raw }) {
  const [v, setV] = useStatePL(!!on);
  const [editOpen, setEditOpen] = useStatePL(false);
  const [logOpen, setLogOpen] = useStatePL(false);
  const [logText, setLogText] = useStatePL("");
  const [logBusy, setLogBusy] = useStatePL(false);
  const [confirmDel, setConfirmDel] = useStatePL(false);
  const [delBusy, setDelBusy] = useStatePL(false);
  React.useEffect(() => { setV(!!on); }, [on]);
  // task 50：toggle 之前只改本地 state，没动后端 → 重新拉数据后状态被冲掉。
  // 现在 MCP/Skill 切换走真后端：MCP /api/mcp/server/enabled，Skill 暂没专用 toggle
  // 接口（后端默认全启用），只本地视觉切换并 toast 提示。
  const handleToggle = async (next) => {
    setV(next);
    if (kind === "mcp") {
      try {
        await window.api.mcp.enabled({ id, server_id: id, enabled: !!next });
        window.__apiToast?.(next ? i18n.t('cap.status_on') : i18n.t('cap.disabled_toast'), { kind: "ok", duration: 1500 });
        if (next) {
          try { await window.api.mcp.start({ id, server_id: id }); } catch (_) {}
        } else {
          try { await window.api.mcp.stop({ id, server_id: id }); } catch (_) {}
        }
        onChanged && onChanged();
      } catch (e) {
        setV(!next);
        window.__apiToast?.(i18n.t('cap.toggle_failed'), { kind: "danger", detail: e?.message });
      }
    } else if (kind === "skills") {
      // 后端目前无 skill enable toggle；不假装成功
      window.__apiToast?.(i18n.t('cap.skills_always_on'), { kind: "warn", duration: 2400 });
      setV(true);
    } else if (kind === "plugins") {
      window.__apiToast?.(i18n.t('cap.plugins_managed'), { kind: "warn", duration: 2400 });
      setV(true);
    }
  };
  // 删除 MCP 服务器
  const handleDelete = async () => {
    if (kind !== "mcp") {
      window.__apiToast?.(i18n.t('cap.delete_unsupported'), { kind: "warn", duration: 2000 });
      setConfirmDel(false);
      return;
    }
    setDelBusy(true);
    try {
      await window.api.mcp.remove({ id, server_id: id });
      window.__apiToast?.(i18n.t('cap.deleted_name', { name }), { kind: "ok", duration: 1500 });
      setConfirmDel(false);
      onChanged && onChanged();
    } catch (e) {
      window.__apiToast?.(i18n.t('cap.delete_failed'), { kind: "danger", detail: e?.message });
    }
    setDelBusy(false);
  };
  // task 50：查看日志 → 拉真后端运行时（admin 看到 stderr）。导出 → 下载文本。
  const loadLog = React.useCallback(async () => {
    setLogBusy(true);
    try {
      if (kind === "mcp") {
        const r = await window.api.mcp.runtime();
        const list = (r && r.running) || [];
        const me = list.find(x => x.id === id || x.server_id === id || x.name === name);
        if (me) {
          const stderr = me.stderr || me.last_stderr || "";
          const meta = `pid: ${me.pid || "-"} · status: ${me.status || (me.alive ? "alive" : "—")}\nlast_seen: ${me.last_seen_at || me.last_heartbeat_at || "—"}\n`;
          setLogText(meta + (stderr ? "\n--- stderr (recent) ---\n" + stderr : "\n" + i18n.t('cap.log_no_stderr')));
        } else {
          setLogText(i18n.t('cap.log_no_instance'));
        }
      } else {
        setLogText(i18n.t('cap.log_unsupported'));
      }
    } catch (e) {
      setLogText(i18n.t('cap.log_read_failed', { err: e?.message || String(e) }));
    }
    setLogBusy(false);
  }, [kind, id, name]);
  React.useEffect(() => { if (logOpen) loadLog(); }, [logOpen, loadLog]);
  const editFields = kind === "mcp" ? (() => {
    const rawTransport = (_raw || {}).transport || tag || "stdio";
    // 命令与参数分开落库(command + args),回填成一整行;只填 command 会让参数在保存时丢掉。
    const rawCommand = mcpCommandLine(_raw);
    const rawEnv = (() => { const e = (_raw || {}).env || {}; return Object.keys(e).length ? Object.entries(e).map(([k,v]) => `${k}=${v}`).join("\n") : ""; })();
    const rawUrl = (_raw || {}).url || "";
    const rawHeaders = (() => { const h = (_raw || {}).headers || {}; return Object.keys(h).length ? JSON.stringify(h, null, 2) : ""; })();
    return [
      { key: "name", label: i18n.t('cap.f_name'), required: true, default: name },
      { key: "transport", label: i18n.t('cap.f_transport'), type: "select", default: rawTransport,
        options: [{ value: "stdio", label: i18n.t('cap.opt_stdio') }, { value: "http", label: i18n.t('cap.opt_http') }] },
      { key: "url", label: "URL", mono: true, default: rawUrl, placeholder: "https://example.com/mcp" },
      { key: "command", label: i18n.t('cap.f_command'), mono: true, default: rawCommand, placeholder: "uvx my-mcp" },
      { key: "headers", label: "Headers (JSON)", type: "textarea", rows: 3, default: rawHeaders, placeholder: '{"Authorization":"Bearer xxx"}' },
      { key: "env", label: i18n.t('cap.f_env'), type: "textarea", placeholder: "KEY=VALUE", rows: 3, default: rawEnv },
    ];
  })() : kind === "skills" ? [
    { key: "name", label: i18n.t('cap.f_display_name'), required: true, default: name },
    { key: "version", label: i18n.t('cap.f_version'), default: tag },
    { key: "manifest", label: i18n.t('cap.f_manifest'), type: "textarea", rows: 4,
      placeholder: '{"hooks": ["before_turn", "after_state_write"]}' },
  ] : [
    { key: "id", label: i18n.t('cap.f_plugin_id'), required: true, mono: true, default: tag },
    { key: "name", label: i18n.t('cap.f_display_name'), required: true, default: name },
    { key: "desc", label: i18n.t('cap.f_desc'), type: "textarea", default: desc, rows: 3 },
  ];
  return (
    <div className="pl-cap">
      <div className="pl-cap-head">
        <div className="pl-cap-icon">
          <Icon name={kind === "mcp" ? "diamond" : kind === "skills" ? "spark" : "plug"} size={16} />
        </div>
        <div style={{minWidth: 0, flex: 1}}>
          <strong>{name}</strong>
          <div className="muted-2">{tag}</div>
        </div>
        <SettingsToggle on={v} set={handleToggle} />
      </div>
      <p className="pl-cap-desc">{desc}</p>
      <div className="pl-cap-foot">
        <span className={`pill ${v ? "ok" : ""}`}>
          <span className={`dot ${v ? "ok" : ""}`} /> {v ? status : i18n.t('cap.status_off')}
        </span>
        <div style={{display: "flex", gap: 4}}>
          <button className="iconbtn" data-tip={i18n.t('cap.edit')} onClick={() => setEditOpen(true)}><Icon name="edit" size={12} /></button>
          <button className="iconbtn" data-tip={i18n.t('cap.view_log')} onClick={() => setLogOpen(true)}><Icon name="debug" size={12} /></button>
          {kind === "mcp" && <button className="iconbtn" data-tip={i18n.t('cap.delete')} onClick={() => setConfirmDel(true)}><Icon name="trash" size={12} /></button>}
        </div>
      </div>
      <PromptModal
        open={editOpen}
        eyebrow={kind === "mcp" ? i18n.t('cap.edit_mcp') : kind === "skills" ? i18n.t('cap.edit_skill') : i18n.t('cap.edit_plugin')}
        title={name}
        hint={kind === "mcp" ? "POST /api/mcp/server" : kind === "skills" ? i18n.t('cap.no_edit_api') : i18n.t('cap.no_edit_api')}
        fields={editFields}
        submitLabel={i18n.t('cap.save')}
        onClose={() => setEditOpen(false)}
        onConfirm={async (vals) => {
          // task 50：之前是 () => setEditOpen(false) 纯关闭，没保存任何东西。
          // MCP 现在走真 /api/mcp/server upsert；其他类型说明不支持。
          if (kind === "mcp") {
            try {
              const envObj = {};
              for (const line of String(vals.env || "").split("\n")) {
                const m = line.trim().match(/^([^=]+)=(.*)$/);
                if (m) envObj[m[1].trim()] = m[2];
              }
              const body = { id, server_id: id, name: vals.name || name, transport: vals.transport || tag, enabled: v };
              if ((vals.transport || tag) === "http") {
                body.url = vals.url || "";
                body.command = "";
                try { body.headers = vals.headers ? JSON.parse(vals.headers) : {}; } catch (_) { body.headers = {}; }
              } else {
                Object.assign(body, mcpStdioFields(vals.command, _raw));
                body.url = "";
              }
              if (Object.keys(envObj).length) body.env = envObj;
              await window.api.mcp.upsert(body);
              window.__apiToast?.(i18n.t('cap.saved'), { kind: "ok", duration: 1500 });
              setEditOpen(false);
              onChanged && onChanged();
            } catch (e) {
              window.__apiToast?.(i18n.t('cap.save_failed'), { kind: "danger", detail: e?.message });
            }
          } else {
            window.__apiToast?.(i18n.t('cap.edit_unsupported'), { kind: "warn", duration: 2400 });
            setEditOpen(false);
          }
        }}
      />
      {logOpen && (
        <Modal
          open
          eyebrow={i18n.t('cap.log_eyebrow', { name })}
          title={i18n.t('cap.recent_50')}
          width={640}
          onClose={() => setLogOpen(false)}
          footer={<>
            <span className="muted-2" style={{fontSize: 11.5}}>
              <Icon name="info" size={11} /> {kind === "mcp" ? i18n.t('cap.log_hint_mcp') : i18n.t('cap.log_hint_none')}
            </span>
            <div style={{display: "flex", gap: 8}}>
              <button className="btn ghost" onClick={loadLog} disabled={logBusy}><Icon name="refresh" size={12} /> {i18n.t('common.refresh')}</button>
              <button className="btn ghost" onClick={() => setLogOpen(false)}>{i18n.t('cap.close')}</button>
              <button className="btn primary" disabled={!logText} onClick={() => {
                // task 50：之前是 dead button。下载日志文本为 .log 文件。
                try {
                  const blob = new Blob([logText || ""], { type: "text/plain;charset=utf-8" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  const safe = String(name || id || "log").replace(/[^\w.-]+/g, "_");
                  a.href = url; a.download = `${safe}.log`;
                  document.body.appendChild(a); a.click();
                  document.body.removeChild(a);
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                } catch (e) { window.__apiToast?.(i18n.t('cap.export_failed'), { kind: "danger", detail: e?.message }); }
              }}><Icon name="download" size={12} /> {i18n.t('cap.export')}</button>
            </div>
          </>}
        >
            <pre className="mono" style={{
              maxHeight: 320, overflow: "auto", margin: 0, padding: "12px 14px",
              background: "var(--bg-deep)", border: "1px solid var(--line-soft)",
              borderRadius: "var(--r-2)", fontSize: 11.5, lineHeight: 1.7, color: "var(--text-quiet)"
            }}>{logBusy ? i18n.t('common.loading') : logText || i18n.t('cap.log_empty')}</pre>
        </Modal>
      )}
      {confirmDel && (
        <Modal eyebrow={i18n.t('cap.confirm_delete_eyebrow')} title={i18n.t('cap.delete_mcp_title')} width={420}
          onClose={() => setConfirmDel(false)} closeDisabled={delBusy}
          footer={<>
            <span />
            <div style={{display: "flex", gap: 8}}>
              <button className="btn ghost" onClick={() => setConfirmDel(false)} disabled={delBusy}>{i18n.t('cap.cancel')}</button>
              <button className="btn danger" onClick={handleDelete} disabled={delBusy}>
                {delBusy ? i18n.t('cap.deleting') : <><Icon name="trash" size={12} /> {i18n.t('common.delete')}</>}
              </button>
            </div>
          </>}>
          <div style={{padding: "0 16px 16px", fontSize: 13.5, lineHeight: 1.7}}>
            {i18n.t('cap.confirm_delete_pre')}<strong>{name}</strong>{i18n.t('cap.confirm_delete_post')}
          </div>
        </Modal>
      )}
    </div>
  );
}
const apiRows = () => [
  { m: "GET",  p: "/",                              d: i18n.t('cap.api.d_home'),                       group: i18n.t('cap.api.g_home') },
  { m: "GET",  p: "/app",                           d: i18n.t('cap.api.d_app'),                   group: i18n.t('cap.api.g_home') },
  { m: "GET",  p: "/api/v1/state",                     d: i18n.t('cap.api.d_state'),                       group: i18n.t('cap.api.g_saves') },
  { m: "POST", p: "/api/v1/new",                       d: i18n.t('cap.api.d_new'),                   group: i18n.t('cap.api.g_saves') },
  { m: "POST", p: "/api/v1/chat",                      d: i18n.t('cap.api.d_chat'),                  group: i18n.t('cap.api.g_saves') },
  { m: "POST", p: "/api/v1/stop",                      d: i18n.t('cap.api.d_stop'),                               group: i18n.t('cap.api.g_saves') },
  { m: "POST", p: "/api/v1/save",                      d: i18n.t('cap.api.d_save'),                           group: i18n.t('cap.api.g_saves') },
  { m: "POST", p: "/api/v1/permissions",               d: i18n.t('cap.api.d_permissions'),                          group: i18n.t('cap.api.g_permissions') },
  { m: "POST", p: "/api/v1/memory/add",                d: i18n.t('cap.api.d_mem_add'),                           group: i18n.t('cap.api.g_memory') },
  { m: "POST", p: "/api/v1/memory/remove",             d: i18n.t('cap.api.d_mem_remove'),                           group: i18n.t('cap.api.g_memory') },
  { m: "GET",  p: "/api/v1/models",                    d: i18n.t('cap.api.d_models'),                        group: i18n.t('cap.api.g_models') },
  { m: "POST", p: "/api/v1/models/select",             d: i18n.t('cap.api.d_models_select'),                           group: i18n.t('cap.api.g_models') },
  { m: "GET",  p: "/api/v1/scripts",                   d: i18n.t('cap.api.d_scripts'),                                   group: i18n.t('cap.api.g_scripts') },
  { m: "POST", p: "/api/v1/scripts/import",            d: i18n.t('cap.api.d_scripts_import'),           group: i18n.t('cap.api.g_scripts') },
  { m: "GET",  p: "/api/v1/scripts/{id}/chapters",     d: i18n.t('cap.api.d_chapters'),                     group: i18n.t('cap.api.g_scripts') },
  { m: "GET",  p: "/api/v1/saves",                     d: i18n.t('cap.api.d_saves'),                               group: i18n.t('cap.api.g_platform') },
  { m: "POST", p: "/api/v1/saves",                     d: i18n.t('cap.api.d_saves_create'),                         group: i18n.t('cap.api.g_platform') },
  { m: "GET",  p: "/api/v1/branches/{save_id}",        d: i18n.t('cap.api.d_branches'),                                 group: i18n.t('cap.api.g_branches') },
  { m: "POST", p: "/api/v1/branches/continue",         d: i18n.t('cap.api.d_branches_continue'),                     group: i18n.t('cap.api.g_branches') },
  { m: "POST", p: "/api/v1/branches/delete",           d: i18n.t('cap.api.d_branches_delete'),                   group: i18n.t('cap.api.g_branches') },
  { m: "GET",  p: "/api/v1/library",                   d: i18n.t('cap.api.d_library'),                                 group: i18n.t('cap.api.g_library') },
  { m: "POST", p: "/api/v1/library/upload",            d: i18n.t('cap.api.d_upload'),                                   group: i18n.t('cap.api.g_library') },
  { m: "POST", p: "/api/v1/library/mkdir",             d: i18n.t('cap.api.d_mkdir'),                                 group: i18n.t('cap.api.g_library') },
  { m: "GET",  p: "/api/v1/library/asset/{id}/download", d: i18n.t('cap.api.d_download'),                                group: i18n.t('cap.api.g_library') },
  { m: "POST", p: "/api/v1/mcp/server",                d: i18n.t('cap.api.d_mcp'),                 group: i18n.t('cap.api.g_caps') },
  { m: "POST", p: "/api/v1/skills/import",             d: i18n.t('cap.api.d_skills'),                       group: i18n.t('cap.api.g_caps') },
];

function ApiList() {
  const [q, setQ] = useStatePL("");
  const filtered = apiRows().filter(r => !q || r.p.includes(q) || r.d.includes(q));
  const groups = {};
  filtered.forEach(r => { (groups[r.group] = groups[r.group] || []).push(r); });
  return (
    <div className="pl-stack">
      <section className="pl-sec">
        <div className="pl-sec-head">
          <h2>{i18n.t('cap.api.title')} <span className="muted-2">{i18n.t('cap.api.count', { n: filtered.length, g: Object.keys(groups).length })}</span></h2>
          <div className="pl-sec-tools" style={{flex: 1, maxWidth: 320}}>
            <input style={{height: 28, fontSize: 12}} placeholder={i18n.t('cap.api.search_ph')} aria-label={i18n.t('cap.api.search_aria')} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        {Object.entries(groups).map(([group, items]) => (
          <div key={group} style={{display: "grid", gap: 8}}>
            <div className="pl-stat-label" style={{padding: "8px 4px 0"}}>{group}</div>
            <div className="pl-api">
              <div className="pl-api-row head"><div>METHOD</div><div>{i18n.t('cap.api.col_path')}</div><div>{i18n.t('cap.api.col_desc')}</div><div></div></div>
              {items.map((r, i) => (
                <div key={i} className="pl-api-row">
                  <div><span className={`pl-api-method ${r.m}`}>{r.m}</span></div>
                  <div className="pl-api-path">{r.p}</div>
                  <div className="pl-api-desc">{r.d}</div>
                  <div className="pl-table-actions">
                    <button className="iconbtn" data-tip={i18n.t('cap.api.copy_path')} onClick={async () => {
                      // task 50：之前是 dead button
                      const ok = await copyText(r.p);
                      if (ok) window.__apiToast?.(i18n.t('cap.api.copied', { path: r.p }), { kind: "ok", duration: 1500 });
                      else window.__apiToast?.(i18n.t('cap.api.copy_failed'), { kind: "danger", detail: i18n.t('cap.api.clipboard_denied') });
                    }}><Icon name="link" size={12} /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

export { CapPage };
