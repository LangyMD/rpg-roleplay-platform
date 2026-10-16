/* 玩家强制设定 section(记忆 tab 内)—— 纯机械从 game-panels.jsx 搬出,零行为变化。 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Icon } from '../../game-icons.jsx';

// 玩家强制设定 (/set) 管理 —— 列出 worldline.user_variables(每回合作为「硬约束」注入 GM,
// 见 context_engine/layers.py),提供逐条删除 + 清空全部。早期 /set 过的命令一直约束 GM 却
// 无处删改(群反馈:行者无疆),这里给出唯一的「删改入口」。删除时一并清掉 /set 配对写入的
// 固定记忆「玩家强制设定：…」,否则只删变量、pinned 仍注入 GM = 没真正解除。
function ForcedSetSection({ state }) {
  const { t } = useTranslation();
  const uvars = (state && state.worldline && state.worldline.user_variables) || {};
  const entries = Object.entries(uvars)
    .map(([key, info]) => ({
      key,
      value: (info && typeof info === "object") ? (info.value || "") : String(info || ""),
      turn: (info && typeof info === "object") ? info.turn : undefined,
    }))
    .filter((e) => e.value);
  if (!entries.length) return null;

  const removeOne = async ({ key, value }) => {
    await window.api.worldline.remove({ key });   // 硬约束变量(server 端按当前存档解析 save_id)
    try {
      const pins = (state && state.memory && state.memory.pinned) || [];
      const idx = pins.findIndex(
        (p) => typeof p === "string" && (p.indexOf("Player forced setting") === 0 || p.indexOf("玩家强制设定") === 0)
          && (value ? p.indexOf(value) >= 0 : true),
      );
      if (idx >= 0) await window.api.game.memoryRemove({ bucket: "pinned", index: idx });
    } catch (_) {}
  };
  const refresh = () => { try { window.dispatchEvent(new CustomEvent("game-state-refresh")); } catch (_) {} };

  return (
    <div className="gp-section">
      <div className="section-head">
        <h3>{t("game.memory.forced_set")}
          <span className="muted-2" style={{ marginLeft: 8, fontSize: 11, textTransform: "none" }}>{t("game.memory.forced_set_subtitle")}</span>
        </h3>
        {entries.length >= 2 ? (
          <button className="iconbtn" data-tip={t("game.memory.forced_set_clear_all")} aria-label={t("game.memory.forced_set_clear_all")}
            onClick={async () => {
              if (!await window.__confirm({ message: t("game.memory.forced_set_clear_all_confirm", { count: entries.length }), danger: true })) return;
              try {
                for (const e of entries) { await removeOne(e); }
                refresh();
                window.__apiToast?.(t("game.memory.deleted_ok"), { kind: "ok" });
              } catch (err) { window.__apiToast?.(t("game.memory.action_failed"), { kind: "danger", detail: err?.message }); }
            }}>
            <Icon name="trash" size={14} />
          </button>
        ) : null}
      </div>
      <ul className="gp-flat-list">
        {entries.map((e) => (
          <li key={e.key} style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
            <span style={{ flex: 1 }}>
              <span className="serif">{e.value}</span>
              {e.turn ? <span className="muted-2" style={{ marginLeft: 8, fontSize: 11 }}>{t("game.memory.forced_set_source", { turn: e.turn })}</span> : null}
            </span>
            <button className="iconbtn" data-tip={t("game.memory.forced_set_delete_tip")} aria-label={t("game.memory.forced_set_delete_tip")}
              onClick={async () => {
                if (!await window.__confirm({ message: t("game.memory.forced_set_delete_confirm"), danger: true })) return;
                try {
                  await removeOne(e);
                  refresh();
                  window.__apiToast?.(t("game.memory.deleted_ok"), { kind: "ok" });
                } catch (err) { window.__apiToast?.(t("game.memory.action_failed"), { kind: "danger", detail: err?.message }); }
              }}>
              <Icon name="close" size={12} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export { ForcedSetSection };
