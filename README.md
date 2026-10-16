<div align="center">

# RPG Roleplay

**Self-hostable LLM RPG engine that turns a novel into a playable world.**

[![status](https://img.shields.io/badge/status-private%20beta-orange)](https://play.stellatrix.icu)
[![python](https://img.shields.io/badge/python-3.12%2B-blue)](#)
[![license](https://img.shields.io/badge/license-AGPL--3.0-blue)](./LICENSE)
[![waitlist](https://img.shields.io/badge/waitlist-open-success)](https://play.stellatrix.icu)

[Landing & waitlist](https://play.stellatrix.icu) · [中文 README](./README.zh-CN.md)

</div>

![RPG Roleplay — live game console](./docs/assets/hero.png)

---

## What it is

**Every reader who plays your story plays a different one.**

RPG Roleplay drops a long-form novel into a self-hosted, LLM-driven RPG runtime: branching saves, retrieval over the original text, agent-driven scenes, and all the boring scaffolding — dice, provider routing, token accounting, cards, worldbook — is already wired up. Originally written to host one 4.85-million-character novel as a playable world; now any author or GM can point it at their own.

## What works today

> The table below is the actual state, not marketing.
> ✅ = tests pass and the feature is used in production by the author.
> 🟡 = the code is there, rough edges remain.
> ❌ = planned but not built.

| Layer | Status |
|---|---|
| **Python core game loop** (state, ops, scenes, dice, D&D 5E core, encounters, inventory, retrieval, agents) | ✅ Stable |
| **LLM routing** (Anthropic native, OpenAI, Vertex Gemini, OpenAI-compatible) | ✅ Stable, streaming + tool-use + multimodal |
| **Postgres + pgvector storage**, v96+ versioned migrations, auto-apply on boot under advisory lock | ✅ Stable |
| **Vite + React 19**, JSDoc type annotations, multi-page entries | ✅ Stable |
| **Branchable saves** — commit / ref / checkout work like Git, hard-delete with 30-day grace queue | ✅ Stable |
| **Script ingestion** — TXT / ZIP upload, 7 chapter splitters, auto-extract character cards + worldbook + timeline, vector index | ✅ Stable |
| **SillyTavern V2/V3 import** — character cards (PNG tEXt / JSON) + chat history (JSONL → new save) | ✅ Stable |
| **Tavern Mode** — SillyTavern-style 1:1 character chat: drop-in cards, agent tools (create/swap character, popup choices, import/export card), per-conversation system-prompt editor, round-trip JSONL | ✅ Stable |
| **Script & novel editor** (`/md-editor`) — three-pane IDE (file tree · CodeMirror 6 · AI side-panel) over chapters / cards / worldbook / personas with lossless Markdown round-trip; AI writing copilot: inline ghost-text continuation, per-hunk diff accept/reject, persistent Problems panel, delegated BYOK sub-models | ✅ Stable |
| **Native iOS / iPadOS client** — native SwiftUI client (bring-your-own-server) that connects to this open-source server over its public API, **in this repo under `ios/`** (XcodeGen + Xcode automatic signing). Mirrors the web game console; QR scan-login, invite-link join, register / OTP / forgot-password | ✅ Open source (beta) |
| **Achievements** — declarative catalog, unlock toasts, public profile wall | ✅ Stable |
| **Image generation** — covers / avatars / in-chat scene art / character + persona portraits, unified provider layer, BYOK | ✅ Stable |
| **Provider catalog** — 11 providers (Anthropic / OpenAI / Vertex / DeepSeek / DashScope / Doubao / Hunyuan / MiniMax / SiliconFlow / OpenRouter / MiMo), BYOK encrypted at-rest (AES-256-GCM HKDF per-user-per-api), live model sniffing | ✅ Stable |
| **i18n** — zh-CN + en, ~6400 keys, full UI coverage (settings / login / platform / game / admin) | ✅ Stable |
| **Help system** — in-app HelpDrawer with ~34 module docs | ✅ Stable |
| **Compliance suite** — adult-content splash gate, AGPL legal banner, feedback channel with NSFW pre-moderation, AUP/DMCA/CSAM admin runbooks | ✅ Stable |
| **Auth + registration** — invite-code gate, email verification (Resend), Argon2id with rehash-on-login, forgot-password, two-step register | ✅ Stable |
| **Account lifecycle** — soft deactivate, request-delete (30-day grace), data export, hard-delete cron | ✅ Stable |
| **License** | ✅ AGPL-3.0-or-later (this repo) + commercial dual-license available — contact <chaosai31@gmail.com> |

## Tavern Mode — SillyTavern-style 1:1 character chat

A second way to play, alongside the script-driven Game Console. **Tavern Mode** is a 1:1 character chat (think SillyTavern) where you talk directly to a *character* instead of a GM. It reuses the entire GM turn pipeline — memory, worldbook, branching, token accounting, prompt caching — so there is **no separate engine**; it just runs script-free, with its own saves and a Claude-web-style UI.

- **Drop-in character cards.** Import SillyTavern V2 cards (PNG / JSON / WebP) by drag-and-drop, or upload one mid-chat and let the agent parse + import it via the `import_character_card` tool. Export any character back to V2 JSON.
- **Harness agent, not a fixed script.** The character is a full tool-using agent: it can create/switch characters and personas, optionally bind one of *your own* scripts to ground the roleplay in a novel (permission-gated), and pop a **multiple-choice question** to you (`ask_player_choice`) when the story needs your decision.
- **Dedicated, branchable saves.** Each chat is its own save with persistent memory + relationships and git-style fork; the sidebar lists conversations Claude-Code-style (archive / rename / delete / auto-title). Pick who to talk to from a dedicated character-selection panel.
- **In-page right panel** (collapsible, never covers the top nav) with three tabs: the AI character card, your editable persona, and a **per-conversation system-prompt editor** (jailbreak / persona / behaviour overrides).
- **Immersion-first transcript.** Roleplay prose stays clean; tool calls and the model's reasoning stream render as collapsible blocks and **persist in history** (still there after reload). Live turn timer + a context-usage ring fed by real token accounting.
- **Round-trippable export.** Export a conversation to SillyTavern JSONL (with a confirm step) and re-import it losslessly — opening message included.
- **User-level tool fencing.** Every agent tool call is scoped to your own account + save: it can read/write only *your* data, never another user's or any server-level state.

Worldbook overlays, character-book ingestion, a deterministic opening (`first_mes` pasted verbatim, never LLM-invented), and BYOK routing (Anthropic / OpenAI-compatible / Vertex Gemini, streaming + tool-use) are all wired in.

## Quick start

Four ways to play the same server: **self-hosted web** (below), the **desktop app** (Electron, one-click), **iOS / iPadOS** (native SwiftUI, built from `ios/`), and **Android** (Expo app in `mobile/`).

### Easiest — desktop app (no setup, one click)

Don't want to touch a terminal? Download the desktop app — it bundles its own PostgreSQL + Python and runs the whole stack locally with one click (fully offline, your data never leaves the machine; NSFW is on you). It also has an online mode that just connects to the cloud account.

**[→ Download for macOS / Windows (Releases)](https://github.com/felixchaos/rpg-roleplay-platform/releases)**

- macOS (Apple Silicon) `.dmg` · Windows `.exe` — signed/notarized
- Built-in console: start/stop the service, logs, LAN sharing (a phone scans a **login QR** to sign in passwordlessly, or an **invite QR/link** to register on your instance), backup & restore, in-app updates
- Auto-creates a local account; set a username/password if you expose it on your LAN
- Update channel: pulls from GitHub Releases, falls back to a mirror if GitHub is slow

### Native iOS / iPadOS app

The native SwiftUI client (bring-your-own-server) now lives **in this repo under `ios/`** and is covered by the same AGPL license as the rest of the codebase. Point it at the official cloud or your own self-hosted server; sign in by typing your credentials or by **scanning a QR code** from the desktop app — either a passwordless login QR for your own account, or an invite link to register on a self-hosted LAN instance. Build it with XcodeGen + Xcode automatic signing — see [`ios/README.md`](./ios/README.md). Currently in beta.

### Self-host from source — one command

With Postgres installed and running:

```bash
git clone https://github.com/felixchaos/rpg-roleplay-platform.git
cd rpg-roleplay-platform
./scripts/setup.sh        # venv + deps + database + .env + migrations, then launches
```

`setup.sh` is idempotent (safe to re-run): it creates the venv + installs deps, creates the `rpg` database/role + extensions, writes `rpg/.env`, runs migrations, then starts the backend (`:7860`) + frontend (`:5173`). Open <http://localhost:5173/Login.html> when it finishes; pass `--no-start` to set up without launching. Creating the database + the `vector` extension needs a Postgres **superuser** (a default local install runs as one; on a Linux server pre-create the role/db/extensions as `postgres`, then re-run).

### Manual setup

```bash
git clone https://github.com/felixchaos/rpg-roleplay-platform.git
cd rpg-roleplay-platform

# 1. Install Postgres + pgvector (macOS example; Ubuntu: apt install postgresql-16 postgresql-16-pgvector)
brew install postgresql pgvector
brew services start postgresql

# 2. Create rpg user + database
psql postgres -c "CREATE USER rpg WITH PASSWORD 'rpg_dev';"
psql postgres -c "CREATE DATABASE rpg OWNER rpg;"
psql -U rpg -d rpg -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -U rpg -d rpg -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 3. Install Python dependencies
#    !! IMPORTANT: run from rpg/ sub-directory, not the repo root !!
cd rpg/
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. Configure .env  (only DATABASE_URL is required to boot)
cp .env.example .env   # rpg/.env.example — annotated template
$EDITOR .env           # set DATABASE_URL; everything else degrades gracefully

# 5. Run migrations — fresh DB requires "full", not "up"
#    !! Must run from rpg/ directory (module resolution depends on cwd) !!
.venv/bin/python -m platform_app.migrate full

# 6. Start the backend
.venv/bin/uvicorn app:app --port 7860 --reload   # dev
# Or use the one-shot script (starts postgres + backend + frontend):
# cd .. && ./scripts/dev.sh start

# 7. Start the frontend (separate terminal)
cd ../frontend && npm install && npm run dev

# 8. Open the login page (multi-page Vite build, not a SPA)
open http://localhost:5173/Login.html
```

You'll land on the Login page, create a user, then bounce to `Platform.html` (library + cards + scripts) or `Game Console.html` (the actual gameplay screen).

### Windows — one-click start / stop (local, single user)

Once the manual setup above has been done once (Postgres, `rpg\.venv`, `rpg\.env`), double-click `start-local.cmd` in the repo root. It starts Postgres if it isn't already listening on 5432, installs Python / npm dependencies only when their manifests changed, runs migrations, starts the backend (7860) and Vite (5173) hidden in the background, and opens http://localhost:5173/. Auth is off in local mode, so there is no login. `stop-local.cmd` stops all three. Logs go to `.dev-logs\`.

```powershell
.\scripts\windows\local.ps1 shortcuts   # put "RPG Roleplay" / "Stop RPG Roleplay" on the desktop
.\scripts\windows\local.ps1 status
```

For a portable Postgres, put it in a folder named `rpg-pg` next to the repo (with `start-pg.cmd` / `stop-pg.cmd`, or `pg\bin\pg_ctl.exe` + `data\`), or point `RPG_PG_DIR` at it. A Postgres Windows service just needs to be running.

> **Production deployment**: see `deploy/` for Docker / bare-metal templates.

## Architecture

```
┌─ browser ──────────────────────────────────────────────────┐
│  React 19 + Vite + JS (ESM multi-page)                     │
│  Login.html · Platform.html · Game Console.html            │
│  Cloudscape Design System · api-client.js · i18n           │
└───────────────────────────────┬────────────────────────────┘
                                │ fetch / SSE
┌─ uvicorn :7860 ───────────────▼────────────────────────────┐
│  FastAPI · Python 3.12 · async + asyncio.to_thread         │
│                                                            │
│  platform_app/   auth · saves · branches · cards ·         │
│                  scripts · admin · feedback · policy       │
│                                                            │
│  agents/         gm/master · context · extractor ·         │
│                  black_swan · verifier                     │
│                                                            │
│  tools_dsl/      tool_registry · MCP · Skill · executor    │
│                                                            │
│  state/          GameState · op protocol                   │
│  retrieval/      BM25-lite · pgvector                      │
│  knowledge/      chapter_indexer · embeddings              │
└───────────────┬──────────────────────────┬─────────────────┘
                │ psycopg                  │ httpx
                ▼                          ▼
┌────────────────────────────┐   ┌────────────────────────────┐
│  pgbouncer :6432           │   │  LLM providers (BYOK)      │
│  Postgres 16 + pgvector    │   │  Anthropic · OpenAI ·      │
│  v96+ migrations           │   │  Vertex · DeepSeek ·       │
│                            │   │  DashScope · Doubao ·      │
│  Redis :6379               │   │  Hunyuan · MiniMax · MiMo  │
│  session · cache · ratelim │   │  SiliconFlow · OpenRouter  │
└────────────────────────────┘   └────────────────────────────┘
```

FastAPI backend with ~30+ route modules / agents / state mixins, ~2700 pytest cases.

## LLM providers

| Provider | Catalog | Streaming | Tool use | Multimodal | Extended thinking |
|---|---|---|---|---|---|
| Anthropic | ✅ | ✅ | ✅ | ✅ | ✅ |
| OpenAI (Chat Completions, openai-compat backend) | ✅ | ✅ | ✅ | ✅ | — |
| Google Vertex (Gemini) | ✅ | ✅ | ✅ | ✅ | — |
| OpenRouter | ✅ | ✅ via OpenAI-compat | partial | — | — |
| DeepSeek | ✅ | ✅ via OpenAI-compat | partial | — | — |
| SiliconFlow | ✅ | ✅ via OpenAI-compat | partial | — | — |
| MiniMax | ✅ | ✅ via OpenAI-compat | partial | — | — |
| Doubao (ByteDance) | ✅ | ✅ via OpenAI-compat | partial | — | — |
| MiMo (Xiaomi) | ✅ | ✅ via OpenAI-compat | partial | — | — |
| Hunyuan (Tencent) | ✅ | ✅ via OpenAI-compat | partial | — | — |
| DashScope (Qwen) | catalog only | — | — | — | — |

> Google AI Studio was delisted (datacenter-IP ban); Gemini is served through Vertex AI instead.

Adding a provider = one entry in `rpg/config/model_catalog.json` + (if a new wire protocol) one backend in `rpg/agents/gm/backends/`. Everything else — picker, capability filtering, cost accounting — is automatic.

## Companion PyPI packages

Seven reusable pieces were extracted from this repo and published standalone under MIT (author `felixchaos`):

- [`tavern-card`](https://pypi.org/project/tavern-card/) — SillyTavern V2/V3 character-card parse / import / export
- [`llm-scrub`](https://pypi.org/project/llm-scrub/) — PII / secret scrubbing for LLM inputs & outputs
- [`zh-narrative-guard`](https://pypi.org/project/zh-narrative-guard/) — deterministic Chinese-narrative consistency checks (dates / weekdays / time)
- [`byok-vault`](https://pypi.org/project/byok-vault/) — per-user AES-256-GCM HKDF encryption for BYOK credentials
- [`gram-recall`](https://pypi.org/project/gram-recall/) — episodic / long-form recall helpers for retrieval
- [`safe-outbound`](https://pypi.org/project/safe-outbound/) — SSRF-safe outbound HTTP (urlopen / httpx) layer
- [`zh-chapter-splitter`](https://pypi.org/project/zh-chapter-splitter/) — Chinese-novel chapter splitters

## Stack

`Python 3.12+` · `FastAPI` · `uvicorn` · `psycopg` · `pgvector` · `pgbouncer` · `Redis` · `React 19` · `Vite` · `Cloudscape Design System`

## Why not SillyTavern / Risu / KoboldCpp?

We love SillyTavern. It's an incredible character-card playground. But it answers a different question:

- **SillyTavern** = *"I have a character card. Let me chat with it."*
- **RPG Roleplay** = *"I have a million-character novel. Let me play **inside** it."*

| Concern | SillyTavern / Risu | RPG Roleplay |
|---|---|---|
| Primary unit | Character card | Novel + setting bible |
| Long-form retrieval | Extension required | Built-in: BM25 + pgvector over the original text |
| Branching saves | Manual chat export | Git-style commit / ref / checkout |
| Engine state | Conversation history | Typed `GameState` + op protocol + D&D 5E core |
| Worldbook | YAML / JSON files | DB-backed entries with semantic activation |
| Multi-user | Single-user app | Auth + per-user runtime + quota |
| Stack | Node, plain HTML/CSS | Python + FastAPI + pgvector + React |
| Tests | Mostly ad-hoc | ~2700 pytest cases |

Use SillyTavern when your story is a character. Use RPG Roleplay when your story is a *world*. The two import the same V2 card format, so moving sideways is trivial.

## Configuration

Only `DATABASE_URL` is required to boot; everything else is optional and degrades gracefully.

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | Postgres connection string. Use a **direct** 5432 connection — `migrate` cannot go through PgBouncer (its advisory lock breaks under transaction pooling) | ✅ |
| `RPG_MASTER_KEY` | Encrypts stored BYOK keys at rest; auto-generated + persisted on first boot if unset (back it up) | optional |
| `RPG_REQUIRE_AUTH` | `0` = local single-user, auth off; `1` = multi-user / public (login + registration) | optional |
| `ANTHROPIC_API_KEY` | Server-side fallback LLM before any user configures BYOK | optional |
| `EMBED_API_ID` / `EMBED_BASE_URL` / `EMBED_MODEL` / `EMBED_API_KEY` | Embedding provider for semantic retrieval; unset = keyword search only | optional |
| `EMBED_DIM` | Vector dimension of the embedding model (default 768); must be fixed before the first deploy | optional |
| `REDIS_URL` | Rate-limit + cache backend; unset = in-process fallback (fine for a single node) | optional |
| `RPG_CORS_ORIGINS` | Comma-separated allowed origins (multi-user / public deploys) | optional |
| `RESEND_API_KEY` / `RESEND_FROM` | Resend email for registration verification codes; required only for self-service signup | optional |
| `EMAIL_CODE_SECRET` | HMAC key for email OTP; set the same value across workers when `workers>1` | optional |
| `RPG_SETUP_TOKEN` | One-time token that promotes the first registration to admin (server mode) | optional |
| `RPG_SKIP_AUTO_MIGRATE=1` | Skip the boot-time migration runner | optional |

A full annotated example lives in [`rpg/.env.example`](./rpg/.env.example).

## Project layout

```
.
├── rpg/                       # Backend (Python 3.12+) — FastAPI app + GM / KB / import / LLM
│   ├── app.py                 # FastAPI · uvicorn :7860 (router assembly + lifespan)
│   ├── platform_app/          # auth / saves / branches / scripts / cards / admin
│   │   ├── api/               # FastAPI route modules
│   │   ├── db/migrations.py   # v96+ versioned migrations + auto-apply
│   │   ├── knowledge/         # chapter indexer / canon repo
│   │   ├── import_pipeline/   # script-import stage orchestration
│   │   ├── tavern_cards.py    # SillyTavern V2 PNG/JSON import
│   │   └── crypto.py          # AES-256-GCM HKDF per-user key
│   ├── chat_pipeline/         # /api/chat SSE turn pipeline (directives → context → rules → gm → persist)
│   ├── agents/gm/             # three-sage GM (master.py) + backends/ (Anthropic / OpenAI / Vertex / compat)
│   ├── context_engine/        # layered context assembly (+ context_providers/)
│   ├── kb/ · extract/ · ingest/   # save KB · novel → facts extraction · split / clean
│   ├── retrieval/             # BM25-lite + pgvector (packaged)
│   ├── tools_dsl/             # tool registry + dispatcher + MCP broker
│   ├── state/                 # GameState + op protocol
│   └── tests/                 # ~2700 pytest cases
│
├── frontend/                  # React 19 + Vite (multi-page ESM)
│   ├── Login.html · Platform.html · Game Console.html
│   └── src/                   # pages/ · components/ · i18n/ (zh-CN + en) · api-client.js
│
├── ios/                       # Native SwiftUI client (BYO-server, XcodeGen) — see ios/README.md
├── mobile/                    # Expo / React Native app (rpg-roleplay-mobile)
├── desktop/                   # Electron desktop shell (self-updating, channel B)
├── docs-site/                 # Starlight documentation site (Astro)
├── scripts/                   # dev.sh / setup.sh / bump_version.sh / windows/local.ps1
│
├── deploy/                    # Docker / bare-metal production templates
├── docs/                      # design docs · runbooks · docs/knowledge/ (AI-collaborator map)
└── CLAUDE.md                  # repo navigation for AI collaborators
```

## Community

Player community (Chinese): **QQ group 584876566** — [join via QQ](https://qm.qq.com/q/49Dqcr0aw0). Bug reports, feature requests, and gameplay chat welcome.

<a href="https://qm.qq.com/q/49Dqcr0aw0"><img src="./docs/assets/qq-group.jpg" alt="QQ group 584876566 — scan to join" width="240"></a>

## Contributing

This is an open-source project — contributions welcome. For now, please file issues and follow the [landing page](https://play.stellatrix.icu) for the public release window.

## License

Licensed under the **GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [LICENSE](./LICENSE) and [NOTICE](./NOTICE). The license covers the **entire** repository — server, web frontend, desktop shell, and the native iOS client under `ios/`.

**Why AGPL?** RPG Roleplay is a server-side application. AGPL ensures any operator running it as a public service must also make their modified source available to users — keeping the engine open even when used as a SaaS.

**Commercial / closed-source use** is available under a separate dual-license. Contact <chaosai31@gmail.com>.

---

*Originally written to host one 4.85 million-character novel as a playable world. The engine has since outgrown its first story.*
