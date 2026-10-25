# TeamMind: shared, inspectable memory for a team and its AI agents

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
- Never commit `.env`. Prototype-grade auth: review before real use.
