/* Generic novel mock state (shown only offline / in anonymous design preview).
   Do not hardcode this into UI components —
   render from these structures so swapping data updates the entire surface. */

window.MOCK_NOVEL = {
  script_title: "Fog Harbor",
  script_author: "Sample novel",
  script_chapter_count: 1208,
  script_word_count: 2_413_000,
  script_mode_label: "Standard chapter headings",
  script_confidence: 0.92,
};

window.MOCK_STATE = {
  player: {
    name: "Gu Chengyan",
    role: "Drifting chronicler",
    background:
      "Born into an old scholarly family of Nanling, he was swept up in the Fog Harbor incident and gained the power to cross between three dynasties. He can record events but can hardly change them.",
    current_location: "North Harbor docks · below the abandoned lighthouse",
    inventory: [
      { name: "Torn page · Guangxu 13", quality: "Can be used to reckon time" },
      { name: "Black iron pocket watch", quality: "Stopped at 3:42" },
      { name: "Mother's jade pendant", quality: "Broken, two pieces" },
    ],
  },
  world: {
    time: "Late afternoon · two days before Frost's Descent",
    weather: "Sea fog has not lifted; visibility about sixty meters",
    timeline: {
      anchor_state: "locked",
      current_label: "Fog Harbor incident · day 2",
      current_phase: "Searching for survivors",
      pending_jump: null,
      anchors: [
        { id: "a1", label: "The night before the crossing", phase: "Setup", at: 0 },
        { id: "a2", label: "Fog Harbor incident · day 1", phase: "Development", at: 1 },
        { id: "a3", label: "Fog Harbor incident · day 2", phase: "Turn · you are here", at: 2, current: true },
        { id: "a4", label: "Meeting at the lighthouse", phase: "Turn", at: 3, pending: true },
        { id: "a5", label: "Return to Nanling", phase: "Resolution", at: 4, locked: true },
      ],
    },
    known_events: [
      "Three bodies surfaced in the morning fog; one wore the robes of a former-dynasty official.",
      "The lighthouse keeper vanished last night, leaving half a candle wick.",
      "A dock tax collector has been quietly asking after \"the chronicler\".",
    ],
  },
  relationships: {
    "Shen Zhiwei": { tone: "friendly", note: "Fog Harbor physician who knows your true identity" },
    "Inspector Han": { tone: "warn", note: "Nanling's inspector at Fog Harbor, hunting for you" },
    "Aheng": { tone: "info", note: "The lighthouse keeper's daughter, fourteen" },
  },
  permissions: {
    mode: "full_access",
    pending_writes: [
      {
        id: "pw-1",
        field: "world.timeline.pending_jump",
        from: null,
        to: { label: "Meeting at the lighthouse", reason: "Revealing your identity triggers the meeting" },
        risk: "high",
        reason: "Major worldline branch: changes the plot of the next three chapters",
      },
      {
        id: "pw-2",
        field: "relationships.Inspector Han.tone",
        from: "Wary",
        to: "Hostile",
        risk: "medium",
        reason: "The player refused the inspector's questioning",
      },
    ],
    pending_questions: [
      {
        id: "pq-1",
        text: "Reveal your true identity to Shen Zhiwei?",
        choices: ["Reveal it", "Keep hiding it", "Trade a torn page for her trust"],
      },
    ],
  },
  worldline: {
    user_variables: {
      "Gu Chengyan.identity_exposure": "37%",
      "Inspector Han.alertness": "Slowly rising",
      "Lighthouse.lit": "No",
    },
    constraints: ["Events before Guangxu 13 cannot be changed", "The torn pages can be cited only three times"],
    last_projection: "If you reveal your identity now: 82% chance of triggering \"Meeting at the lighthouse\", 14% chance of being detained by the inspector.",
  },
  memory: {
    mode: "normal",
    main_quest: "Find who really started the Fog Harbor incident",
    current_objective: "Reach the lighthouse before dark and check your father's last words with Aheng",
    pinned: [
      "The black iron pocket watch stopped at 3:42, matching the time on the torn page",
      "Shen Zhiwei said: \"With three torn pages, time can be reckoned\"",
    ],
    facts: [
      "In Guangxu 13 a ship sank at Fog Harbor with 142 passengers aboard",
      "The lighthouse keeper's surname is Tong, kin to the Tong clan of Nanling",
    ],
    notes: [
      "Player note: Aheng may not be the keeper's own daughter",
    ],
    last_retrieval:
      "Fog Harbor incident, morning of day 2; the sea fog has not lifted. Since last night the dock tax collector has been asking after a chronicler carrying torn pages. In the clinic, Shen Zhiwei sets down her copper needles and looks out toward the lighthouse.",
    last_context: {
      chapter_refs: ["Chapter 312 · First day at Fog Harbor", "Chapter 313 · The drowned"],
      retrieval_chunks: 6,
      tokens_used: 4180,
    },
  },
  suggestions: [
    "Take the stone steps along the docks toward the lighthouse, avoiding the tax collector",
    "Go back to the clinic and tell Shen Zhiwei what you found in the torn pages",
    "Wait below the lighthouse until dark and approach under cover of the fog",
    "Check the pocket watch to see whether the hour named on the torn page has come",
  ],
  history: [
    {
      role: "assistant",
      content:
        "The sea fog lies evenly over the docks, like a sheet of paper not yet dry. You stand in the shadow of the abandoned lighthouse and can hear your pocket watch ticking out of tune. It is still stopped at 3:42.\n\nThe tax collector passes in the distance, the sound of his boots on the wet stones muffled by the fog. He glances your way, does not stop, and heads toward the north harbor.\n\nLight footsteps come from behind you. You do not need to turn around to know it is Shen Zhiwei. \"Mr. Gu,\" she says, \"do you have three torn pages yet?\"",
      ts: "21:42",
      game_ts: "15:15",
    },
    {
      role: "user",
      content: "I lay the broken pieces of my mother's jade pendant in my palm and hold them out for her to see.",
      ts: "21:44",
      game_ts: "15:30",
    },
    {
      role: "assistant",
      content:
        "Shen Zhiwei's gaze rests on the two pieces of jade for a moment, but she does not reach for them.\n\n\"These are not torn pages,\" she says quietly. \"But I understand. You are not ready to let me see those papers yet.\"\n\nThe fog suddenly thickens, swallowing the top of the lighthouse. From the north harbor comes the sound of a gong: three short strikes and one long, the old Fog Harbor signal that strangers have come ashore. Shen Zhiwei looks up, a slight frown between her brows.",
      ts: "21:47",
      game_ts: "15:45",
      streaming_done: true,
    },
  ],
};

window.MOCK_RUN_STEPS = [
  { phase: "context_retrieve", message: "Recalling context · searching the source text and history", status: "done", elapsed_ms: 820, detail: "Returned 6 chapter excerpts, covering chapters 312-315." },
  { phase: "context_agent", message: "Sub-agent filtering context · keeping only what relates to \"revealing identity\"", status: "done", elapsed_ms: 1240, detail: "Dropped 11 passages, kept 4; budget 4180 tokens." },
  { phase: "world_check", message: "Checking worldline constraints · torn page citations", status: "done", elapsed_ms: 180, detail: "Torn page citations remaining: 1." },
  { phase: "prompt_assemble", message: "Assembling the prompt · injecting state, memory and pinned memory", status: "done", elapsed_ms: 90 },
  { phase: "main_gm", message: "Main GM is writing the narration", status: "running", elapsed_ms: 2860 },
];

window.MOCK_PLATFORM = {
  user: {
    username: "demo_user",
    display_name: "Demo user",
    role: "admin",
    uid: "demo_preview",
    bio: "Turning long novels into RPGs; mainly testing narrative quality.",
  },
  database: { driver: "PostgreSQL", url: "postgresql://localhost/rpg", ok: true },
  stats: { scripts: 4, saves: 12, branches: 38, assets: 67, api_calls: 21_400 },
  scripts: [
    {
      id: 1, uid: "scr_7c1a", title: "Fog Harbor", description: "Sample script · 1208 chapters detected",
      chapter_count: 1208, word_count: 2_413_000,
      import_report: { mode_label: "Standard chapter headings", confidence: 0.92, problem_label: "No obvious issues found" },
      updated_at: "2 hours ago",
    },
    {
      id: 2, uid: "scr_3e44", title: "Nanling Lamp Records", description: "Imported script · 612 chapters",
      chapter_count: 612, word_count: 1_204_000,
      import_report: { mode_label: "Chinese chapter rules", confidence: 0.86, problem_label: "Irregular volume titles", reasons: ["Missing final chapter across volumes"] },
      updated_at: "Yesterday",
    },
    {
      id: 3, uid: "scr_b811", title: "Stars Fallen at Sea", description: "Imported script · collection of 88 stories",
      chapter_count: 88, word_count: 220_000,
      import_report: { mode_label: "Numbered heading rules", confidence: 0.74, problem_label: "3 passages look like prefaces", reasons: ["Passages 12, 43 and 77 have unusual length"] },
      updated_at: "3 days ago",
    },
    {
      id: 4, uid: "scr_a02f", title: "Fog Harbor Tales (side volume)", description: "Imported script · 124 passages",
      chapter_count: 124, word_count: 340_000,
      import_report: { mode_label: "Custom rules", confidence: 0.81, problem_label: "No obvious issues found" },
      updated_at: "Last week",
    },
  ],
  saves: [
    { id: 11, uid: "sv_a1", title: "Fog Harbor · main · Gu Chengyan", script_id: 1, branch_count: 14, updated_at: "12 minutes ago", current: true },
    { id: 12, uid: "sv_a2", title: "Fog Harbor · side · Shen Zhiwei POV", script_id: 1, branch_count: 6, updated_at: "Yesterday" },
    { id: 13, uid: "sv_a3", title: "Nanling Lamp Records · opening", script_id: 2, branch_count: 2, updated_at: "Last week" },
    { id: 14, uid: "sv_a4", title: "Stars Fallen at Sea · trial", script_id: 3, branch_count: 1, updated_at: "Last month" },
  ],
  // task: 文件库已禁用(task #66),清空 mock 假资源数据,防新注册用户看到莫名其妙的 3 个文件
  recent_assets: [],
};
