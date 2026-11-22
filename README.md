<!-- # TeamMind: shared, inspectable memory for a team and its AI agents

FastAPI + MongoDB Atlas (Vector Search, Atlas Search, TTL, Change Streams, transactions) + Gemini + React + MCP server,
with the workflows running as **LangGraph** graphs (checkpoints in the same Atlas cluster).

## 1. MongoDB Atlas (5 min)
1. Create a free **M0** cluster. Add a database user (letters+numbers password) and allow your IP in Network Access.
2. Copy the connection string into `backend/.env` as `MONGODB_URI`.
3. The backend creates the normal indexes, the **TTL index**, and the two Atlas search indexes
   (`memory_vector`, `memory_text`) on first start. Wait until both show **READY** in Atlas -> Search
   (also visible in the app under Settings -> System health). Until then, retrieval uses a local fallback
   and the UI badge says `local-fallback`. It never fails silently.

## 2. Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                      # fill MONGODB_URI, JWT_SECRET, LLM_API_KEY (Gemini key from aistudio.google.com)
python -m scripts.seed                                    # demo users + workspace + ~13 story memories
uvicorn app.main:app --reload                             # http://localhost:8000/docs
```
No API key / no internet? Set `LLM_PROVIDER=fake` and `EMBEDDING_BACKEND=hash` for a rule-based offline mode.
Gemini model names change; check the current list and edit `LLM_MODEL_MAIN` / `LLM_MODEL_FAST`.
Free-tier Gemini has per-minute limits (one chat turn makes ~3-4 LLM calls); the app retries once and degrades gracefully.

## 2b. LangGraph (what runs, in which order)
Four graphs, compiled once at startup in `backend/app/graph/registry.py`. The LLM thinks inside nodes; code decides the order.

| Graph | Trigger | Path |
|---|---|---|
| **Chat** (foreground) | `POST /chat` | `guard -> (blocked_reply \| retrieve -> responder) -> finalize`. `retrieve` runs the reusable **Retrieve** subgraph (`planner -> retriever`), also used by MCP `recall`. Memory chips and answer tokens are streamed with `stream_mode="custom"`. |
| **Learn** (background, loops, can pause) | after a chat turn, `POST /memories`, import commit, MCP `remember` / `correct`, `PATCH /memories/{id}` | `extractor -> pick_next -> guard_candidate -> find_similar -> judge -> save_new \| reinforce \| supersede \| ask_user` -> `record_result` -> next candidate. Judge confidence < `JUDGE_CONFIDENCE_MIN` calls `interrupt()` and the run waits in MongoDB. |
| **Reflection** (nightly / button) | scheduler, Settings | `select_groups -> reflect -> validate (retry max 2) -> [approval interrupt] -> save_strategy` |
| **Freshness** (hourly) | scheduler, Settings | `decay_archive`, `stale_flag`, `purge_deleted`, `purge_threads` in parallel, then `summarize` |

* **Pause and resume:** an unsure judgement (or a lesson that needs approval) opens a question in **Decisions** (sidebar badge, plus an inline card in the chat). `POST /decisions/{thread_id}/resume` continues the run. Questions live in MongoDB, so they survive a refresh and a server restart. Resume checks that the thread belongs to your workspace (the thread id contains it), that you can write, and that nobody answered already.
* **Demo mode** (Settings): a real model is not "unsure" on cue. When on, a contradiction always asks you.
* **Run trace:** every chat turn stores node-by-node timings (`agent_runs.trace`). Open it from the chat ("run trace") or `GET /runs/{conversation_id}`. Analytics shows the average time per node.
* **Graph pictures:** Settings -> Workflow graphs (Mermaid drawn from the compiled graphs), or `GET /admin/graphs`.
* **State rules:** everything in graph state is JSON-safe (string ids, no vectors). `finalize` strips memory text from the final chat checkpoint, and the Freshness graph deletes old finished threads (paused ones are kept).
* **Safety net:** `USE_LANGGRAPH=false` switches back to the plain-function pipeline of version 1.0 (`agents/orchestrator.py`, `conflict.store_candidate`, `freshness.run`, `reflection.run`).

Deliberate differences from the build guide: answer tokens are streamed as custom events from the existing Gemini wrapper (no LangChain chat-model dependency, and the fake provider streams the same way); the Retrieve subgraph is called from a thin wrapper node (a compiled subgraph used directly as a node duplicates reducer lists and hides custom events); a blocked message also goes through `finalize` so it is audited.

## 2c. Tests
```bash
cd backend && pip install -r requirements.txt
# needs a MongoDB replica set (Atlas works; or a local single-node one). Uses the database teammind_test and the fake LLM.
TEST_MONGODB_URI="mongodb+srv://..."  python -m pytest -q
```
44 tests: memory service, guard, every router function, Chat / Learn (pause, resume, restart survival, JSON-safe state, loop and cap) / Reflection / Freshness graphs, REST + SSE API, decision tenant checks, MCP tools, and a snapshot of every graph (`UPDATE_SNAPSHOTS=1` regenerates it when you change a workflow on purpose).
Atlas Search indexes do not exist on a plain MongoDB, so tests exercise the local-fallback retrieval path.

## 3. Frontend
```bash
cd frontend
cp .env.example .env
npm install
npm run dev                                               # http://localhost:5173
```
Log in as `alex@demo.com` / `demo1234`. Open a private window as `priya@demo.com` to see live sharing.

## 4. Connect a coding agent (MCP)
Settings -> Agent tokens -> Create, copy the token. Then, for Claude Code:
```bash
claude mcp add teammind --env TEAMMIND_TOKEN=tm_xxxx -- python /ABSOLUTE/PATH/teammind/backend/mcp_server/server.py
```
(Cursor/Codex: add the same command + env var in their MCP config; check each tool's docs for the file format.)
Tools: `recall` (Retrieve subgraph), `remember` / `correct` (Learn graph), `forget`, `list_decisions`, `open_questions`.
If `remember` is unsure it returns `needs_user_choice`; the question shows up in the web app's **Decisions** inbox.

## 5. Demo script (4 min)
1. Chat: "We must keep the demo under 4 minutes." -> "Remembered" toast with Undo.
2. New chat: "How should we plan the demo?" -> **Compare** (memory off vs on); click a citation chip -> Inspector (score bars, source, audit).
3. Say "We switched from REST to GraphQL." -> old memory superseded; open **Graph** (red dashed edge) and Inspector version chain.
4. Second window (Priya) or an MCP agent edits a memory -> **Live feed** updates in ~1 s.
5. Paste `sk-TESTTESTTESTTESTTESTTEST` -> Guard hides it, nothing saved. Seeded "ignore all previous instructions" memory is flagged *suspicious* and never reaches the model.
6. **Pause and resume:** Settings -> Demo mode on, then say "We switched from REST to GraphQL." The Learn graph pauses; the Decision inbox (and an inline chat card) asks which is right; one click resumes it. Restart the backend while it is paused and the click still works.
7. Open **run trace** under an answer (nodes, milliseconds, models) and Settings -> Workflow graphs for the four diagrams.
8. Memories page shows an expiry countdown. Settings -> Freshness Keeper with Time machine +30 days -> facts go stale, low-value memories archive. **Timeline** shows what the agent knew on any day. **Run Reflection** turns the 3 Friday-deploy outcomes into one strategy.

## Notes
- **TTL** removes expired documents ~every 60 s; the Retriever also filters them at read time. Only expiring memories use TTL; everything else is archived/soft-deleted.
- **Change Streams** need a replica set (Atlas is one). On a standalone MongoDB the app falls back to direct publish; health shows `live updates: direct`.
- Set `RERANK_ENABLED=true` for the LLM reranker (one extra LLM call per turn).
- `mcp` is pinned below 2.x (2.x renamed `FastMCP`).
- Never commit `.env`. Prototype-grade auth: review before real use. -->


<div align="center">

# 🧠 M.I.N.D. (TeamMind)

**A shared, inspectable memory platform for your team and its AI agents.**  
*It remembers, corrects itself, and forgets safely.*

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Workflows-1C3C3C?style=flat-square)
![MongoDB Atlas](https://img.shields.io/badge/MongoDB_Atlas-Vector_%26_Search-47A248?style=flat-square&logo=mongodb&logoColor=white)
![React](https://img.shields.io/badge/React_+_Vite-61DAFB?style=flat-square&logo=react&logoColor=black)
![MCP](https://img.shields.io/badge/MCP-Agent_Ready-D97706?style=flat-square)

</div>

---

## Overview

**M.I.N.D.** gives human teammates and external AI coding agents (Claude Code, Cursor, Codex) a single, workspace-isolated source of institutional knowledge. Rather than acting as an opaque black-box vector store, every memory in M.I.N.D. is **typed, cited, versioned, audited, and governed by stateful LangGraph workflows**:

* **Grounded Chat with Inline Citations:** Retrieves relevant team facts, constraints, and outcomes, streaming answers alongside interactive citation chips (`m1`, `m2`, ...) and a side-by-side **Compare** mode (memory off vs. on).
* **Self-Correcting Memory Lifecycle:** Automatically extracts candidate knowledge from conversations and imports, reinforcing repeated facts, superseding contradicted ones with full version chains, and expiring temporary notes via MongoDB TTL indexes.
* **Human-in-the-Loop Decisions:** When confidence is low or a contradiction is detected, the **Learn** graph pauses via LangGraph `interrupt()`, persists its checkpoint in MongoDB, and surfaces a one-click resolution card in **Decisions** and inline in **Chat**—surviving browser refreshes and backend restarts.
* **Guardrails & Graceful Degradation:** Redacts leaked secrets (e.g., API keys), quarantines prompt-injection attempts so they never reach the LLM, and degrades cleanly to **Memory-Only Mode** when upstream model quotas or connectivity drop.
* **Native MCP Server:** Connects directly to AI coding assistants via Model Context Protocol (`recall`, `remember`, `correct`, `forget`, `list_decisions`, `open_questions`).

---

## Interface & Visual Tour

### Grounded Chat, Citation Chips & Graceful Fallback
Conversations display active memory toggles, typed citation badges (`constraint`, `fact`, `outcome`), side-by-side comparison, and automatic memory-only fallback if the LLM provider is unreachable:

![M.I.N.D. Chat Interface with Memory Citations and Fallback Mode](Screenshot%202026-10-25%20133401.png)

### Workspace Authentication
Multi-tenant workspace isolation with JWT authentication, role-based workspace invites, and ready-to-seed demo accounts:

![M.I.N.D. Login Screen](Screenshot%202026-10-25%20151710.png)

---

## System Architecture

```text
                      ┌──────────────────────────┐
                      │   React / Vite Frontend  │
                      │   http://localhost:5173  │
                      └────────────┬─────────────┘
                                   │ REST JSON + POST SSE
┌────────────────────┐             ▼
│  MCP Coding Agent  │   ┌──────────────────────────┐
│ (Claude / Cursor)  ├──►│   FastAPI Application    │
└────────────────────┘   │   http://localhost:8000  │
                         └────────────┬─────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
┌───────────────────┐     ┌───────────────────────┐     ┌───────────────────┐
│ Auth & Workspaces │     │  LangGraph Workflows  │     │ Live SSE Streams  │
│  JWT + MCP Tokens │     │  chat/retrieve/learn  │     │  Change Streams   │
└───────────────────┘     │  reflection/freshness │     └───────────────────┘
                          └───────────┬───────────┘
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │   MongoDB / Atlas     │
                          │ • Vector & Text Index │
                          │ • TTL Auto-Expiry     │
                          │ • Graph Checkpoints   │
                          │ • Audit & Run Traces  │
                          └───────────────────────┘
```

All LangGraph workflows are compiled once at FastAPI startup (`backend/app/graph/registry.py`) and backed by JSON-safe state checkpoints in MongoDB (`GRAPH_CHECKPOINTER=mongo`).

---

## LangGraph Workflows

The LLM reasons strictly inside individual nodes while deterministic Python code controls routing, retries, and state transitions:

| Graph | Trigger | Execution Path | Purpose |
| :--- | :--- | :--- | :--- |
| **Chat** *(foreground)* | `POST /chat` | `guard` → (`blocked_reply` \| `retrieve` → `responder`) → `finalize` | Screens input for secrets/injections, invokes `retrieve`, streams answer tokens & memory chips via custom SSE events, and records node timings. |
| **Retrieve** *(subgraph)* | Chat `retrieve` node, MCP `recall` | `planner` → `retriever` | Plans search filters, runs hybrid vector + keyword retrieval (with local fallback), and optionally reranks results. |
| **Learn** *(background loop)* | Post-chat turn, `POST /memories`, Import, MCP `remember` / `correct` | `extractor` → `pick_next` → `guard_candidate` → `find_similar` → `judge` → (`save_new` \| `reinforce` \| `supersede` \| `ask_user`) → `record_result` → `publish_summary` | Extracts candidate memories in a loop. Pauses with `interrupt()` when confidence `< JUDGE_CONFIDENCE_MIN` (or on contradictions in Demo Mode). |
| **Reflection** *(nightly / manual)* | Background scheduler, Settings UI | `select_groups` → `reflect` → `validate` *(max 2 retries)* → `[approval interrupt]` → `save_strategy` | Synthesizes recurring historical outcomes into reusable team strategies, optionally requiring human approval. |
| **Freshness** *(hourly / manual)* | Background scheduler, Settings UI | `decay_archive` ∥ `stale_flag` ∥ `purge_deleted` ∥ `purge_threads` → `summarize` | Runs parallel maintenance: decays scores, flags stale facts, purges soft-deleted memories, and cleans up completed threads while preserving paused ones. |

> **Legacy Fallback:** Setting `USE_LANGGRAPH=false` switches execution back to the plain-function pipeline in `backend/app/agents/`.

---

## Repository Structure

```text
teammind/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, lifespan startup, index & graph initialization
│   │   ├── agents/              # Core agent logic (guard, planner, extractor, conflict, reflection, freshness)
│   │   ├── api/                 # REST & SSE routers (auth, chat, memories, decisions, stream, admin)
│   │   ├── core/                # Environment config, JWT/token hashing, IDs, serialization
│   │   ├── db/                  # MongoDB client, Pydantic schemas, normal + Atlas Search indexes
│   │   ├── graph/               # LangGraph definitions, nodes, runners, checkpointer, tracing
│   │   ├── llm/                 # Prompt templates & Gemini / deterministic fake provider
│   │   ├── services/            # Memory lifecycle, hybrid retrieval, embeddings, events, seeding
│   │   └── workers/             # Background scheduler for Freshness & Reflection jobs
│   ├── mcp_server/
│   │   └── server.py            # FastMCP server for external coding agents
│   ├── scripts/
│   │   └── seed.py              # Seeds demo users, workspace, and ~13 story memories
│   └── tests/                   # 44 unit, graph, API, tenant-isolation, and Mermaid snapshot tests
│
└── frontend/
    └── src/
        ├── api/client.js        # REST & POST-SSE stream client with workspace headers
        ├── components/          # DecisionCard, Inspector, MermaidView, Layout, UI primitives
        ├── context/             # AuthContext & LiveContext (real-time workspace event feed)
        └── pages/               # Chat, Decisions, Memories, Graph, Timeline, Live, Import, Analytics, Settings
```

---

## Quickstart Guide

### 1. MongoDB Atlas Setup (5 Minutes)
1. Create a free **M0** cluster on [MongoDB Atlas](https://www.mongodb.com/atlas) (provides a replica set required for Change Streams and durable graph checkpoints).
2. Create a database user and allow your IP address under **Network Access**.
3. Copy your connection string (`MONGODB_URI`) for the backend `.env` file.
4. On first startup, the backend automatically creates standard indexes, the **`expires_at` TTL index**, and the two Atlas Search indexes (`memory_vector` and `memory_text`). Until Atlas reports both indexes as **READY** (visible under **Settings → System health**), M.I.N.D. seamlessly uses a local retrieval fallback (`local-fallback` badge).

### 2. Backend Setup

**macOS / Linux:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in MONGODB_URI, JWT_SECRET, and LLM_API_KEY (from aistudio.google.com)
python -m scripts.seed
uvicorn app.main:app --reload
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and fill in MONGODB_URI, JWT_SECRET, and LLM_API_KEY
python -m scripts.seed
uvicorn app.main:app --reload
```

The API and interactive Swagger documentation will be available at **`http://localhost:8000/docs`**.

#### Offline & Low-Memory Mode
Running without a Gemini API key, internet access, or PyTorch/Sentence-Transformers RAM? Set the following in `backend/.env`:
```env
LLM_PROVIDER=fake
EMBEDDING_BACKEND=hash
```

### 3. Frontend Setup

```bash
cd frontend
cp .env.example .env          # Windows: Copy-Item .env.example .env
npm install
npm run dev
```

Open **`http://localhost:5173`** and sign in with either seeded demo account:
* **User 1:** `alex@demo.com` / `demo1234`
* **User 2:** `priya@demo.com` / `demo1234` *(open in an incognito window to test real-time workspace sync)*

---

## Key Environment Variables (`backend/.env`)

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `MONGODB_URI` | MongoDB Atlas replica-set connection string | `mongodb+srv://...` |
| `MONGODB_DB` | Target database name | `teammind` |
| `JWT_SECRET` | Secret key for signing user session JWTs | Long random string |
| `LLM_PROVIDER` | LLM backend (`gemini` or `fake`) | `gemini` |
| `LLM_API_KEY` | Google AI Studio API key | `AIza...` |
| `LLM_MODEL_MAIN` | Primary response & reasoning model | `gemini-2.5-flash` |
| `LLM_MODEL_FAST` | Fast extraction & classification model | `gemini-2.5-flash-lite` |
| `EMBEDDING_BACKEND` | Embedding engine (`local` or `hash`) | `local` |
| `EMBEDDING_MODEL` | HuggingFace sentence-transformer model | `sentence-transformers/all-MiniLM-L6-v2` |
| `USE_LANGGRAPH` | Toggle LangGraph workflows vs. v1 functions | `true` |
| `GRAPH_CHECKPOINTER` | Checkpoint store (`mongo` or `memory`) | `mongo` |
| `RERANK_ENABLED` | Enable optional LLM reranking on retrieval | `false` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5173` |

---

## Connecting Coding Agents (MCP)

M.I.N.D. ships with an MCP server (`backend/mcp_server/server.py`) scoped to your active workspace:

1. Navigate to **Settings → Agent tokens → Create** in the web app and copy the generated `tm_...` token.
2. Register the server with **Claude Code**:
   ```bash
   claude mcp add teammind \
     --env TEAMMIND_TOKEN=tm_xxxx \
     -- python /ABSOLUTE/PATH/TO/teammind/backend/mcp_server/server.py
   ```
   *(For **Cursor** or **Codex**, add the same command and `TEAMMIND_TOKEN` environment variable to your MCP configuration file.)*

**Exposed MCP Tools:**
* `recall` — Queries team memory via the LangGraph **Retrieve** subgraph.
* `remember` / `correct` — Submits new facts or corrections through the **Learn** graph (returns `needs_user_choice` and queues a card in **Decisions** if uncertain).
* `forget` — Soft-deletes obsolete memories with an audit trail.
* `list_decisions` & `open_questions` — Inspects workspace decisions and pending human-in-the-loop prompts.

---

## API Overview

All workspace-scoped endpoints require `Authorization: Bearer <jwt>` and `X-Workspace: <workspace_id>`:

* **Auth & Workspaces:** `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `GET|POST /workspaces`, `POST /workspaces/invite`
* **Agent Tokens:** `GET|POST /tokens`, `DELETE /tokens/{token_id}`
* **Chat & Traces:** `POST /chat` *(SSE stream)*, `GET /conversations`, `GET /conversations/{id}`, `GET /runs/{conversation_id}`
* **Memories:** `GET|POST /memories`, `PATCH|DELETE /memories/{id}`, timeline & version-chain queries
* **Decisions (HITL):** Pending decision queries and `POST /decisions/{thread_id}/resume`
* **Admin & Live Feed:** Workspace SSE event stream, system health checks, and `GET /admin/graphs` (live Mermaid diagrams)

---

## Running Tests

The backend includes **44 automated tests** covering memory operations, secret/injection guards, graph routers, Chat/Learn/Reflection/Freshness workflows, checkpoint persistence across restarts, tenant isolation, MCP tools, and Mermaid graph snapshots:

```bash
cd backend
TEST_MONGODB_URI="mongodb+srv://..." python -m pytest -q
```

* To regenerate graph snapshots after intentionally modifying a LangGraph topology:
  ```bash
  UPDATE_SNAPSHOTS=1 python -m pytest -q
  ```

---

## 4-Minute End-to-End Demo Script

1. **Remember:** In **Chat**, send `"We must keep the demo under 4 minutes."` → Observe the *"Remembered"* toast with one-click **Undo**.
2. **Recall & Inspect:** Open a new chat and ask `"How should we plan the demo?"` → Toggle **Compare** (memory off vs. on) and click any citation chip (`m1`) to open the **Inspector** (similarity scores, source provenance, and audit log).
3. **Supersede & Version:** Tell the chat `"We switched from REST to GraphQL."` → The previous REST memory is superseded; open **Graph** to see the red dashed supersession edge and version chain.
4. **Live Multi-User / MCP Sync:** Open a second browser window as `priya@demo.com` (or trigger `remember` from an MCP agent) → Watch the **Live** feed update in ~1 second.
5. **Security Guard:** Paste `sk-TESTTESTTESTTESTTESTTEST` into Chat → The Guard masks the secret and prevents persistence. Seeded prompt-injection memories remain flagged as *suspicious* and never reach the LLM context.
6. **Pause & Resume (HITL):** Enable **Demo mode** in **Settings**, then send `"We switched from REST to GraphQL."` → The **Learn** graph pauses and opens a question in **Decisions** (and inline in Chat). Restart the backend server while paused, then click to resolve—the graph resumes cleanly from MongoDB.
7. **Observability:** Click **run trace** beneath any assistant response to inspect per-node millisecond latencies, or visit **Settings → Workflow graphs** to view live Mermaid diagrams.
8. **Time Machine & Reflection:** Visit **Memories** to view TTL expiry countdowns, run **Freshness Keeper (+30 days)** in **Settings** to watch stale facts get flagged and low-value notes archive, explore historical snapshots in **Timeline**, and click **Run Reflection** to distill recurring outcomes into a team strategy.