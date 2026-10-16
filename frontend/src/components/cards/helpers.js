/* 角色卡纯工具 + mock 数据 —— 从 pages/cards.jsx 拆出,逐字节不变。
   DTO 表单 init/payload、NPC→用户卡 body、防溢出文本 helper、短摘要、示例卡数据。
   MobileCards / game / tavern / saves / scripts 侧借用这些 helper(经 pages/cards.jsx 转发)。 */

/* ── v28 统一 CharacterCardDTO 编辑套件(NPC / PC / persona 三态共用) ──────
   后端合并三张表为 character_cards 多态表,所有读卡 API 返回同一 DTO。
   字段:name/full_name/identity/aliases/background/appearance/personality/
   speech_style/current_status/secrets/sample_dialogue/importance/
   first_revealed_chapter/token_budget/priority/enabled/scope/tags。 */
const _asLines = (v) => Array.isArray(v)
  ? v.map((x) => (typeof x === 'string' ? x : (x && (x.content || x.text)) || '')).filter(Boolean).join('\n')
  : (v || '');
const _asCsv = (v) => Array.isArray(v) ? v.join(', ') : (v || '');

// 防溢出工具:导入的酒馆卡常把整段人设塞进一个字段,长文本会把表格 / 详情
// 横向撑爆(用户反馈)。这些 helper 把长字段压成可控的单行预览 / 多行夹断,
// 完整内容仍在「设定」tab 与编辑表单里。
const _oneLine = (v, n = 90) => {
  const s = String(v || '').replace(/\s*\n+\s*/g, ' · ').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n).trimEnd() + '…' : s;
};
// 单行省略号(需配合 maxWidth 生效)
const ELLIPSIS_1 = { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' };
// N 行夹断
const clampLines = (n) => ({
  display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: n,
  overflow: 'hidden', wordBreak: 'break-word',
});

function cardFormInit(card) {
  const c = card || {};
  return {
    name: c.name || '',
    full_name: c.full_name || '',
    identity: c.identity || c.role || '',
    aliases: _asCsv(c.aliases),
    tags: _asCsv(c.tags),
    background: c.background || '',
    appearance: c.appearance || '',
    personality: c.personality || '',
    speech_style: c.speech_style || '',
    current_status: c.current_status || '',
    secrets: c.secrets || '',
    sample_dialogue: _asLines(c.sample_dialogue),
    importance: c.importance ?? 100,
    first_revealed_chapter: c.first_revealed_chapter ?? 1,
    token_budget: c.token_budget ?? 450,
    priority: c.priority ?? 100,
    enabled: c.enabled ?? true,
    scope: c.scope || 'private',
  };
}

// CSV 输入(别名 / 标签)拆分。分隔符集与后端 user_cards._normalize_list 一致 ——
// 提示文案只写「逗号分隔」,中文输入法打出的是全角「,」/「、」/「;」,只认半角逗号
// 会把「战姬,剑士」整条当成一个标签(用户看到的就是"标签没保存对")。
const _splitCsv = (s) => (s || '').split(/[,，;；、]/).map((x) => x.trim()).filter(Boolean);

function cardFormPayload(form, card) {
  const trim = (s) => (s || '').trim();
  return {
    ...(card && card.id ? { id: card.id } : {}),
    name: trim(form.name),
    full_name: trim(form.full_name),
    identity: trim(form.identity),
    aliases: _splitCsv(form.aliases),
    tags: _splitCsv(form.tags),
    background: trim(form.background),
    appearance: trim(form.appearance),
    personality: trim(form.personality),
    speech_style: trim(form.speech_style),
    current_status: trim(form.current_status),
    secrets: trim(form.secrets),
    sample_dialogue: trim(form.sample_dialogue).split('\n').map((s) => s.trim()).filter(Boolean),
    importance: Number(form.importance) || 100,
    first_revealed_chapter: Number(form.first_revealed_chapter) || 1,
    token_budget: Number(form.token_budget) || 450,
    priority: Number(form.priority) || 100,
    enabled: !!form.enabled,
    scope: form.scope || 'private',
  };
}

// NPC 卡 → user_card(card_type='pc')payload。剧本编辑器 / 角色卡页共用,避免 shape 漂移。
// 转换 = 完整复制一份独立用户卡(含头像 URL,站内资产不重存),非指针。后端走 POST
// /api/me/character-cards(myUpsert),与 agent 工具 clone_npc_to_user_card 等价。
function npcToUserCardBody(c, { fromNpcTag = 'From NPC', unnamed = 'Unnamed character' } = {}) {
  const raw = (c && c._raw) || c || {};
  const baseTags = Array.isArray(c && c.tags) && c.tags.length ? [...c.tags] : [];
  return {
    name: (c && c.name) || raw.name || unnamed,
    full_name: raw.full_name || '',
    aliases: Array.isArray(raw.aliases) ? raw.aliases : [],
    identity: (c && c.role) || raw.identity || raw.role || '—',
    background: raw.background || '',
    appearance: raw.appearance || (c && c.bio) || '',
    personality: raw.personality || '',
    speech_style: raw.speech_style || '',
    current_status: raw.current_status || '',
    secrets: raw.secrets || '',
    sample_dialogue: Array.isArray(raw.sample_dialogue) ? raw.sample_dialogue : [],
    avatar_path: raw.avatar_path || '',
    tags: baseTags.includes(fromNpcTag) ? baseTags : [...baseTags, fromNpcTag],
    metadata: { source: 'npc_promote', source_script_id: (c && c.script_id) || null, source_npc_id: raw.id ?? (c && c.id) },
    enabled: true,
  };
}

// 短摘要(NPC 卡面用):取最有信息量的字段前 N 字,原样不解析
function cardSnippet(c, n = 160) {
  const raw = (c && c._raw) || c || {};
  const s = String(raw.background || raw.appearance || raw.personality || raw.current_status || raw.summary || raw.description || '').trim();
  return s ? (s.length > n ? s.slice(0, n) + '…' : s) : '';
}

// 离线 / 匿名设计预览用的示例卡(登录态不显示)。
const USER_CARDS = [
  { id: "uc1", name: "Gu Chengyan", role: "Drifting chronicler", tone: "—", origin: "Fog Harbor · default protagonist",
    bio: "Born into an old scholarly family of Nanling, he gained the power to cross between three dynasties after the Fog Harbor incident. He can record events but can hardly change them.",
    tags: ["Chronicler", "Recorder", "Time travel"], pinned: true, uses: 14, updated: "12 minutes ago" },
  { id: "uc2", name: "Shen Zhiwei", role: "Fog Harbor physician", tone: "Neutral",  origin: "Fog Harbor",
    bio: "A physician at the Fog Harbor clinic who knows the old lore: \"With three torn pages, time can be reckoned.\"",
    tags: ["Physician", "Insider", "Female"], pinned: false, uses: 6, updated: "Today" },
  { id: "uc3", name: "Aheng", role: "Lighthouse keeper's daughter", tone: "Friendly", origin: "Generic",
    bio: "Fourteen and stubborn; she keeps the lighthouse for her father.", tags: ["Girl", "Lighthouse"], pinned: false, uses: 2, updated: "3 days ago" },
  { id: "uc4", name: "Nameless traveler", role: "—", tone: "Neutral", origin: "Generic",
    bio: "Default observer point of view; stays out of the core plot.", tags: ["Observer", "Generic"], pinned: false, uses: 8, updated: "Last week" },
];

const NPC_CARDS = [
  { id: "n1", name: "Inspector Han", role: "Nanling patrol inspector", tone: "Wary", save: "Fog Harbor · main · Gu Chengyan",
    bio: "Nanling's inspector stationed at Fog Harbor, tracking down the chronicler's torn pages.", tags: ["Inspector", "Hostile", "Authority"], uses: 9, updated: "12 minutes ago" },
  { id: "n2", name: "Keeper Tong", role: "Lighthouse keeper", tone: "Missing", save: "Fog Harbor · main · Gu Chengyan",
    bio: "The lighthouse keeper, kin to the Tong clan of Nanling. Went missing last night.", tags: ["Missing", "Clue"], uses: 3, updated: "Today" },
  { id: "n3", name: "Tax collector", role: "Dock tax collector", tone: "Hostile", save: "Fog Harbor · main · Gu Chengyan",
    bio: "Asking around the docks about the chronicler's whereabouts.", tags: ["Hostile", "Minor"], uses: 4, updated: "Today" },
  { id: "n4", name: "Chen Duhai", role: "Boatman", tone: "Neutral", save: "Fog Harbor · side · Shen Zhiwei POV",
    bio: "An old Fog Harbor boatman who knows the sea routes.", tags: ["Guide"], uses: 2, updated: "Yesterday" },
  { id: "n5", name: "Chancellor", role: "Nanling power broker", tone: "High rank", save: "Nanling Lamp Records · opening",
    bio: "Leader of Nanling's ruling faction, holder of the dossiers from the thirteenth year of Guangxu.", tags: ["Power broker", "High rank"], uses: 1, updated: "Last week" },
];

export { _oneLine, ELLIPSIS_1, clampLines, cardFormInit, cardFormPayload, npcToUserCardBody, cardSnippet, USER_CARDS, NPC_CARDS };
