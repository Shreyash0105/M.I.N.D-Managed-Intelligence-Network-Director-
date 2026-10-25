# TeamMind Technical Working Document

## 1. Project overview

TeamMind is a collaborative, inspectable memory platform for teams and AI agents.
It provides:

- A FastAPI backend.
- MongoDB persistence, including memory documents, users, workspaces, events,
  conversations, graph checkpoints, decisions, and agent traces.
- LangGraph workflows for chat, retrieval, learning, reflection, and freshness.
- Gemini or fake/offline language-model providers.
- Local or hash-based embeddings, with optional MongoDB Atlas Vector Search.
- A React and Vite frontend.
- Server-sent event (SSE) streaming for chat and live workspace events.
- An MCP server for coding-agent access to recall, remember, correct, forget, and
  decision operations.

The repository has two runtime applications:

```text
backend/   Python, FastAPI, MongoDB, LangGraph
frontend/  React, Vite, JavaScript
```

The root README contains the short setup guide. This document describes how the
system works internally and how to operate it.

---

## 2. High-level architecture

```text
                                +----------------------+
                                | React/Vite frontend  |
                                | localhost:5173       |
                                +----------+-----------+
                                           |
                         REST JSON + POST SSE requests
                                           |
                                +----------v-----------+
                                | FastAPI application  |
                                | localhost:8000       |
                                +----------+-----------+
                                           |
        +------------------+---------------+------------------+
        |                  |                                  |
        v                  v                                  v
  Auth/workspaces   Chat and memory APIs                 SSE/live events
        |                  |                                  |
        +------------------+------------------+---------------+
                                           |
                                           v
                                +----------------------+
                                | LangGraph workflows  |
                                | chat/retrieve/learn  |
                                | reflection/freshness |
                                +----------+-----------+
                                           |
                                           v
                                +----------------------+
                                | Services and agents  |
                                | memory/retrieval/LLM |
                                +----------+-----------+
                                           |
                                           v
                                +----------------------+
                                | MongoDB / Atlas      |
                                | data + checkpoints   |
                                +----------------------+
```

The backend compiles the graphs once when the application starts. API handlers
call graph runners and services; they do not construct a new graph for each
request.

---

## 3. Directory responsibilities

### Backend

| Directory | Responsibility |
|---|---|
| `backend/app/main.py` | Creates the FastAPI application, middleware, routers, startup and shutdown lifecycle |
| `backend/app/api/` | HTTP routes for authentication, chat, decisions, memories, streaming, and administration |
| `backend/app/agents/` | Reusable agent and business functions used by the graph nodes |
| `backend/app/graph/` | LangGraph state, graph definitions, nodes, runners, checkpointing, tracing, and registry |
| `backend/app/core/` | Configuration, authentication/security helpers, IDs, timestamps, and serialization |
| `backend/app/db/` | MongoDB client, schemas, and normal/Atlas Search indexes |
| `backend/app/llm/` | Prompt construction and Gemini/fake provider abstraction |
| `backend/app/services/` | Memory, retrieval, embeddings, conversation, event, decision, and seed services |
| `backend/app/workers/` | Background scheduler for freshness and reflection jobs |
| `backend/mcp_server/` | MCP server used by external coding agents |
| `backend/scripts/` | Operational scripts, including demo-data seeding |
| `backend/tests/` | API, service, graph, safety, and snapshot tests |

### Frontend

| Directory | Responsibility |
|---|---|
| `frontend/src/App.jsx` | Route table and authentication guard |
| `frontend/src/api/client.js` | REST and SSE client, authorization headers, and error handling |
| `frontend/src/context/` | Authentication/session and live-event providers |
| `frontend/src/components/` | Shared layout, cards, inspectors, graph rendering, and UI primitives |
| `frontend/src/pages/` | Chat, decisions, memories, graph, timeline, live, import, analytics, login, and settings pages |
| `frontend/vite.config.js` | Vite development/build configuration |

Generated dependencies are intentionally not part of the source tree:

```text
backend/.venv/
frontend/node_modules/
**/__pycache__/
```

---

## 4. Backend startup sequence

The application is started with:

```powershell
cd "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\backend"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

FastAPI executes the application lifespan startup code in
`backend/app/main.py`:

1. `indexes.ensure_all()` creates normal MongoDB indexes and attempts to create
   Atlas Search indexes.
2. The graph registry is imported when LangGraph is enabled.
3. The chat, retrieve, learn, reflection, and freshness graphs are compiled.
4. The embedding model warmup starts in a daemon thread.
5. The MongoDB change-stream/direct-publish event service starts.
6. The scheduler starts.
7. The API begins accepting requests.

Atlas Search index creation errors are logged as warnings and retrieval can use
the local fallback. Normal MongoDB connectivity errors are logged during startup,
but requests that require the database will still fail until connectivity is
fixed.

Shutdown stops the scheduler. The embedding warmup thread is daemonized.

---

## 5. Configuration

Copy the template before starting:

```powershell
cd "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\backend"
Copy-Item .env.example .env
```

### Required or important settings

| Variable | Purpose | Typical value |
|---|---|---|
| `MONGODB_URI` | MongoDB or Atlas connection string | Atlas URI |
| `MONGODB_DB` | Application database name | `teammind` |
| `JWT_SECRET` | Secret used to sign access tokens | Long random secret |
| `JWT_EXPIRE_MINUTES` | Access-token lifetime | `720` |
| `LLM_PROVIDER` | `gemini` or `fake` | `gemini` |
| `LLM_API_KEY` | Gemini API key | Provider key |
| `LLM_MODEL_MAIN` | Main response model | `gemini-2.5-flash` |
| `LLM_MODEL_FAST` | Fast classification/extraction model | `gemini-2.5-flash-lite` |
| `EMBEDDING_BACKEND` | `local` or `hash` | `local` |
| `EMBEDDING_MODEL` | Sentence-transformer model name | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_DIMS` | Vector dimensionality | `384` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:5173` |
| `USE_LANGGRAPH` | Enable graph workflows | `true` |
| `GRAPH_CHECKPOINTER` | `mongo` or `memory` | `mongo` |
| `RERANK_ENABLED` | Enable LLM reranking | `false` |

### Offline and low-memory mode

For local development without Gemini or the sentence-transformer model:

```env
LLM_PROVIDER=fake
EMBEDDING_BACKEND=hash
```

The fake provider returns deterministic rule-based responses. Hash embeddings
avoid loading PyTorch and sentence-transformers, which is useful on machines
with limited memory. Retrieval quality is lower than with semantic embeddings.

### Frontend configuration

Create `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

The frontend reads this value in `frontend/src/api/client.js`. If it is absent,
the same localhost backend URL is used as the default.

---

## 6. MongoDB requirements and indexes

MongoDB stores all application state. MongoDB Atlas is recommended because it
provides:

- A replica set for change streams.
- Atlas Vector Search.
- Atlas Search.
- Managed networking and backups.

The application creates normal indexes for:

- Memory workspace/status/update queries.
- Memory tags and topics.
- Memory expiration (`expires_at` TTL).
- Unique user emails.
- Memory event lookups.
- API-token hashes.
- Conversation timelines.
- Agent-run traces.
- Workspace graph threads.

The memory collection also uses:

- `memory_vector` for vector retrieval.
- `memory_text` for text search.

If Atlas Search indexes are not ready, the retrieval service uses a local
fallback. The application does not require Atlas Search to start.

### Replica set requirement

Change streams and durable graph checkpoint behavior require a MongoDB replica
set. Atlas is already a replica set. A standalone local MongoDB instance can
run some functionality but will use direct event publication and may not
support every persistence feature.

---

## 7. Authentication and tenancy

The authentication flow is:

1. A user registers or logs in through `/auth/register` or `/auth/login`.
2. The backend returns a signed JWT and the user's workspaces.
3. The frontend stores the token in local storage.
4. Requests include:

   ```http
   Authorization: Bearer <jwt>
   X-Workspace: <workspace-id>
   ```

5. Backend dependencies resolve the current user and workspace context.
6. Every workspace-scoped query filters by the active workspace ID.

Workspace owners can:

- Create workspaces.
- Invite existing users.
- Create and delete MCP agent tokens.

MCP tokens are stored as SHA-256 hashes. The raw token is displayed only when
created.

Demo credentials after seeding:

```text
alex@demo.com / demo1234
priya@demo.com / demo1234
```

---

## 8. LangGraph workflows

The graph registry in `backend/app/graph/registry.py` compiles these graphs:

```text
chat
retrieve
learn
reflection
freshness
```

### 8.1 Chat graph

```text
START
  -> guard
      -> blocked_reply -> finalize -> END
      -> retrieve -> responder -> finalize -> END
      -> responder -> finalize -> END
```

The guard checks incoming content for unsafe or sensitive material. Safe
messages can retrieve relevant memories before the responder generates an
answer. The finalizer removes data that should not remain in the final
checkpoint and records the completed run.

Answer tokens and memory chips are streamed through custom SSE events.

### 8.2 Retrieve subgraph

```text
START
  -> planner, unless a plan already exists
  -> retriever, when memory is needed
  -> END
```

The same retrieval subgraph is used by the chat graph and the MCP `recall`
operation. It combines planning, filters, embeddings, keyword matching, and
optional reranking.

### 8.3 Learn graph

The Learn graph processes candidate memories in a loop:

```text
extractor
  -> pick_next
  -> guard_candidate
  -> find_similar
  -> judge
      -> save_new
      -> reinforce
      -> supersede
      -> ask_user
  -> record_result
  -> pick_next or publish_summary
  -> END
```

The graph can:

- Extract candidate facts from a chat turn or import.
- Reject unsafe candidates.
- Find similar existing memories.
- Save a new memory.
- Reinforce an existing memory.
- Supersede a contradicted memory.
- Pause for a human decision when confidence is low.

The `ask_user` node uses LangGraph interruption. The pending decision is
stored in MongoDB and appears in the Decisions page. A resume request continues
the graph from the checkpoint.

### 8.4 Reflection graph

Reflection groups related historical outcomes, asks the LLM to produce a
strategy or lesson, validates it, optionally requests approval, and saves the
result.

```text
select_groups
  -> reflect
  -> validate
  -> retry, when required
  -> approval interrupt, when enabled
  -> save_strategy
  -> END
```

The `REFLECTION_REQUIRE_APPROVAL` setting controls whether approval is required.

### 8.5 Freshness graph

The freshness workflow performs maintenance:

- Decays memory scores.
- Flags stale memories.
- Archives low-value memories.
- Purges deleted memories.
- Removes old completed graph threads.
- Summarizes maintenance results.

Paused threads are retained so human decisions can still be resumed.

---

## 9. Chat request lifecycle

Typical chat processing is:

1. The frontend sends a POST request to the chat streaming endpoint.
2. The API validates the request and resolves user/workspace context.
3. The chat graph creates or reuses a conversation thread.
4. The guard checks the message.
5. The planner decides whether memory is needed.
6. The retriever searches relevant workspace memories.
7. The responder builds a grounded answer.
8. Custom stream events send answer chunks and memory references to the client.
9. The finalizer records the result and trace.
10. The Learn graph processes extractable facts in the background.
11. The frontend updates the chat, citations, memory chips, and decision badges.

The graph state is JSON-safe. IDs are represented as strings and vectors are
not placed into persisted graph checkpoints.

---

## 10. Memory lifecycle

Memory records can move through these conceptual states:

```text
candidate -> active -> reinforced
                   -> superseded
                   -> stale
                   -> archived
                   -> deleted/expired
```

Important operations:

- **Create:** Add a new fact with metadata and an embedding.
- **Reinforce:** Increase confidence/importance when repeated evidence supports it.
- **Supersede:** Preserve the old version and link it to the replacement.
- **Expire:** Use `expires_at` and MongoDB TTL where appropriate.
- **Archive:** Keep historical data without returning it as active memory.
- **Forget:** Soft-delete or otherwise remove it from active retrieval.

The retrieval service filters by workspace, status, scope, type, and expiration.
The UI exposes memory metadata, source information, version chains, confidence,
and audit events.

---

## 11. API surface

The exact request and response schemas are defined in
`backend/app/db/schemas.py` and the route modules.

### Authentication and workspaces

```text
POST   /auth/register
POST   /auth/login
GET    /auth/me
GET    /workspaces
POST   /workspaces
POST   /workspaces/invite
```

### MCP agent tokens

```text
POST   /tokens
GET    /tokens
DELETE /tokens/{token_id}
```

### Chat and traces

```text
POST   /chat
GET    /conversations
GET    /conversations/{conversation_id}
GET    /runs/{conversation_id}
```

The streaming chat route returns SSE data and is consumed by
`streamSSE()` in the frontend client.

### Memories

The memories API supports listing, creating/importing, updating, and deleting
workspace memories. It also exposes timeline and related memory operations.
Consult `backend/app/api/memories.py` for the exact route paths.

### Decisions

The decisions API supports pending-question lookup and resume actions for
interrupted Learn or Reflection graph runs.

### Administration and live events

The admin API exposes health and graph information. The stream API exposes
workspace events for live updates.

Swagger documentation is available at:

```text
http://localhost:8000/docs
```

---

## 12. Frontend working model

The frontend is a single-page React application.

### Route guard

`App.jsx` wraps the application in `AuthProvider`. Authenticated routes are
inside `Guarded`, which:

1. Waits for session restoration.
2. Redirects unauthenticated users to `/login`.
3. Waits for a workspace to be selected.
4. Mounts `LiveProvider` and the shared `Layout`.

Routes include:

```text
/login
/
/decisions
/memories
/graph
/timeline
/live
/import
/analytics
/settings
```

### API client

`frontend/src/api/client.js`:

- Reads `VITE_API_URL`.
- Adds JSON headers.
- Adds the JWT bearer token.
- Adds the selected `X-Workspace` header.
- Converts non-success responses into JavaScript errors.
- Reads POST-based SSE responses with `ReadableStream`.

### Main user areas

| Page | Function |
|---|---|
| Chat | Grounded conversation, citations, streaming, and inline decisions |
| Decisions | Review and resume paused graph decisions |
| Memories | Browse, inspect, edit, import, and forget memories |
| Graph | View relationships and memory version chains |
| Timeline | Inspect what the system knew over time |
| Live | View workspace event activity |
| Import | Submit batches of facts or source content |
| Analytics | Inspect agent-run and node timing metrics |
| Settings | Health, graph diagrams, demo mode, freshness, tokens, and maintenance |

---

## 13. Local installation and operation

### Backend

```powershell
cd "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, then seed:

```powershell
python -m scripts.seed
```

Start:

```powershell
uvicorn app.main:app --reload
```

### Frontend

In a second PowerShell terminal:

```powershell
cd "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\frontend"
Copy-Item .env.example .env
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

### Production-style frontend check

```powershell
npm run build
npm run preview
```

---

## 14. Testing

Tests are located in `backend/tests/`.

Run the backend test suite:

```powershell
cd "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\backend"
.\.venv\Scripts\Activate.ps1
$env:TEST_MONGODB_URI = "your-test-mongodb-uri"
python -m pytest -q
```

The test suite covers:

- API routes and validation.
- Authentication and tenant isolation.
- Guard behavior.
- Memory service operations.
- Chat graph behavior.
- Learn graph loops, pauses, resumes, and restart survival.
- Reflection and freshness graphs.
- SSE behavior.
- MCP tools.
- JSON-safe graph state.
- Graph Mermaid snapshots.

When a graph intentionally changes:

```powershell
$env:UPDATE_SNAPSHOTS = "1"
python -m pytest -q
```

Review the snapshot change before keeping it.

---

## 15. Background jobs and scheduling

The scheduler starts with the backend and runs maintenance jobs:

- Freshness processing at the configured interval.
- Reflection processing on the configured schedule.

These jobs use the same service and graph code as interactive requests. They
must be written to tolerate missing data and partial external-service
availability.

For local debugging, use the Settings page buttons where available to trigger
freshness or reflection manually.

---

## 16. MCP integration

The MCP server is at `backend/mcp_server/server.py`.

Create an agent token in the Settings page, then configure an MCP client with
the token:

```text
TEAMMIND_TOKEN=tm_...
```

Example Claude Code command:

```powershell
claude mcp add teammind `
  --env TEAMMIND_TOKEN=tm_xxxx `
  -- python "D:\CSE\TransFinitte\claude last\teammind-langgraph\teammind\backend\mcp_server\server.py"
```

The server exposes tools conceptually equivalent to:

```text
recall
remember
correct
forget
list_decisions
open_questions
```

MCP requests are workspace-scoped using the token's stored workspace and user
identity. A low-confidence remember/correct operation can create a pending
decision instead of silently changing memory.

---

## 17. Security and operational safeguards

The project includes these safeguards:

- Password hashing for user passwords.
- Signed JWT authentication.
- Hashed MCP token storage.
- Workspace-scoped database queries.
- Owner checks for administrative actions.
- Guarding of sensitive or unsafe chat content.
- Audit events for memory changes.
- Human approval for uncertain graph decisions.
- No raw API token returned from list endpoints.
- CORS allow-list configuration.

Before production use:

1. Replace the default `JWT_SECRET`.
2. Never commit `.env`.
3. Restrict `CORS_ORIGINS` to trusted domains.
4. Use a dedicated production MongoDB database and credentials.
5. Enable TLS and secure secret storage.
6. Add rate limiting at the reverse proxy as well as the application.
7. Review the prototype authentication model.
8. Rotate compromised Gemini and MCP tokens.
9. Restrict MongoDB network access.
10. Configure backups and retention.

---

## 18. Troubleshooting

### `Index already exists with a different name`

This occurs when an existing MongoDB index has the same key pattern but a
different name. The index declarations should use stable names. The current
code uses `ev_ws_action_resolved` for the pending-decision index. Pull the
latest source and run the seed command again.

### `ModuleNotFoundError: No module named 'bson'`

The wrong Python interpreter is being used or dependencies are not installed.
Use the virtual-environment interpreter explicitly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scripts.seed
```

### Sentence-transformer or PyTorch memory error

Use:

```env
EMBEDDING_BACKEND=hash
```

Then restart the backend and rerun seeding.

### MongoDB connection failure

Check:

- `MONGODB_URI`.
- Atlas IP allow-list.
- Database username and password.
- URL encoding for special password characters.
- Network connectivity.
- MongoDB replica-set availability.

### Frontend cannot call the backend

Check:

```env
VITE_API_URL=http://localhost:8000
CORS_ORIGINS=http://localhost:5173
```

Restart both Vite and Uvicorn after changing environment files.

### Atlas Search is unavailable

The backend can use local fallback retrieval. Check the Settings health view
and wait for `memory_vector` and `memory_text` to become `READY` in Atlas.

### Chat pauses unexpectedly

This is usually an intentional Learn graph interruption caused by low judge
confidence or demo conflict mode. Open Decisions, select the correct outcome,
and resume the graph.

---

## 19. Recommended development workflow

1. Start MongoDB or confirm Atlas connectivity.
2. Activate the backend virtual environment.
3. Use `LLM_PROVIDER=fake` and `EMBEDDING_BACKEND=hash` for quick offline work.
4. Run focused backend tests before changing graph behavior.
5. Start Uvicorn with `--reload`.
6. Start Vite in a second terminal.
7. Inspect `/docs` for route contracts.
8. Use the Settings graph diagrams and health page while debugging.
9. Run the complete backend test suite before delivery.
10. Run `npm run build` before delivery.

When changing a graph:

1. Update the graph definition or node.
2. Update affected state types and services.
3. Update API/frontend behavior if the output shape changes.
4. Add or update focused tests.
5. Regenerate graph snapshots only when the graph change is intentional.
6. Verify pause/resume and restart behavior when checkpoints are involved.

---

## 20. End-to-end demo flow

1. Start MongoDB.
2. Start the backend.
3. Seed demo data.
4. Start the frontend.
5. Sign in as `alex@demo.com`.
6. Ask a question in Chat.
7. Inspect memory citation chips.
8. Add a new fact and inspect the Memories page.
9. Open Graph to inspect relationships and supersession.
10. Turn on Demo mode in Settings.
11. Submit a contradictory fact.
12. Open Decisions and resolve the pending question.
13. Open Analytics to inspect graph node timings.
14. Open Settings to inspect health and Mermaid graph diagrams.
15. Open a second session as `priya@demo.com` to observe live updates.

---

## 21. Important source files

- [Root README](./README.md)
- [Backend entry point](./backend/app/main.py)
- [Backend configuration](./backend/app/core/config.py)
- [MongoDB client](./backend/app/db/mongo.py)
- [Index setup](./backend/app/db/indexes.py)
- [Graph registry](./backend/app/graph/registry.py)
- [Chat graph](./backend/app/graph/chat_graph.py)
- [Learn graph](./backend/app/graph/learn_graph.py)
- [Frontend route entry](./frontend/src/App.jsx)
- [Frontend API client](./frontend/src/api/client.js)

