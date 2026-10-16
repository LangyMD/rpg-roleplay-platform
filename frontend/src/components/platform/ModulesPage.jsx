// 5E 兼容冒险模组页。纯机械从 platform-app.jsx 搬出,零行为变化。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import CSAlert from '@cloudscape-design/components/alert';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import CSTable from '@cloudscape-design/components/table';
import i18n from '../../i18n/index.js';

/* ---------------------------- MODULES (5E compatible) -------- */
// 内部 ruleset id "dnd5e"，对外文案统一 "5E compatible / 五版规则兼容"。
// 不引入官方 D&D 商标、Forgotten Realms 等非 SRD IP。
function ModulesPage() {
  const [modules, setModules] = useStatePL([]);
  const [loaded, setLoaded] = useStatePL(false);
  const [busyId, setBusyId] = useStatePL(null);
  const [errorMsg, setErrorMsg] = useStatePL("");

  useEffectPL(() => {
    if (!window.api?.rules) {
      setErrorMsg(i18n.t('modules_page.api_missing'));
      setLoaded(true);
      return;
    }
    window.api.rules.modules()
      .then(d => {
        if (d && d.ok) setModules(d.modules || []);
        else setErrorMsg(d?.detail || d?.error || i18n.t('modules_page.load_failed'));
      })
      .catch(e => setErrorMsg(String(e?.message || e)))
      .finally(() => setLoaded(true));
  }, []);

  const startModule = async (m) => {
    setBusyId(m.id);
    setErrorMsg("");
    try {
      // Bug 2：用 /api/rules/module/launch 一步建立独立 save + 激活 + 加载模组。
      // 之前的「先 newGame 再 startModule」两步流程在前端层面看是新存档，但实际
      // newGame 走的 /api/new 并不真的建一个独立 game_save（只是 reset 当前 runtime），
      // 接着 startModule mutate 当前激活 save → 污染了用户的小说存档。
      // launch 端点是后端原子流程，保证模组 save_id 是新的。
      const moduleName = m.name_cn || m.name || m.id;
      const data = await window.api.rules.launchModule(m.id, { title: moduleName });
      if (!data || !data.ok) throw new Error(data?.detail || data?.error || i18n.t('modules_page.launch_failed'));
      window.__apiToast?.(i18n.t('modules_page.started', { name: moduleName, id: data.save_id }), { kind: "ok" });
      try { window.dispatchEvent(new CustomEvent("rpg-saves-updated")); } catch (_) {}
      window.location.href = "Game Console.html#rules";
    } catch (e) {
      setErrorMsg(String(e?.message || e));
      window.__apiToast?.(i18n.t('modules_page.start_failed'), { kind: "danger", detail: String(e?.message || e) });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <CSSpaceBetween size="l">
      {errorMsg && (
        <CSAlert type="error" dismissible={false}>{errorMsg}</CSAlert>
      )}
      <CSContainer header={
        <CSHeader
          variant="h2"
          counter={loaded ? `(${modules.length})` : undefined}
          description={i18n.t('modules_page.desc')}
        >
          {i18n.t('modules_page.title')}
        </CSHeader>
      }>
        {!loaded ? (
          <CSBox color="text-body-secondary" textAlign="center" padding="l">{i18n.t('modules_page.loading')}</CSBox>
        ) : (
          <CSTable
            columnDefinitions={[
              {
                id: "module",
                header: i18n.t('modules_page.col_module'),
                cell: m => (
                  <div className="pl-title-cell">
                    <strong>{m.name_cn || m.name}</strong>
                    <span className="muted-2 mono">{m.id}</span>
                    {m.tagline ? <span className="muted-2" style={{fontStyle:"italic",marginTop:3}}>{m.tagline}</span> : null}
                  </div>
                ),
              },
              {
                id: "ruleset",
                header: i18n.t('modules_page.col_ruleset'),
                cell: m => {
                  const ruleset = m.ruleset || {};
                  return <CSStatusIndicator type="success">{ruleset.public_label || "5E compatible"}</CSStatusIndicator>;
                },
              },
              {
                id: "level",
                header: i18n.t('modules_page.col_level'),
                cell: m => <span className="mono">{(m.level_range || []).join("-") || "—"}</span>,
              },
              {
                id: "duration",
                header: i18n.t('modules_page.col_duration'),
                cell: m => <span className="muted">{m.estimated_minutes ? i18n.t('modules_page.minutes', { n: m.estimated_minutes }) : "—"}</span>,
              },
              {
                id: "action",
                header: "",
                cell: m => (
                  <CSButton
                    variant="primary"
                    loading={busyId === m.id}
                    onClick={() => startModule(m)}
                  >
                    {busyId === m.id ? i18n.t('modules_page.starting') : i18n.t('modules_page.start')}
                  </CSButton>
                ),
              },
            ]}
            items={modules}
            trackBy="id"
            empty={
              <CSBox textAlign="center" color="text-body-secondary" padding="l">
                {i18n.t('modules_page.empty_pre')}<code>rpg/modules/</code>{i18n.t('modules_page.empty_post')}
              </CSBox>
            }
          />
        )}
      </CSContainer>
      <CSContainer>
        <CSBox color="text-body-secondary" fontSize="body-s">
          {i18n.t('modules_page.disclaimer')}
        </CSBox>
      </CSContainer>
    </CSSpaceBetween>
  );
}

export { ModulesPage };
