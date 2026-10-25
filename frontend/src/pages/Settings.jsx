import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useLive } from "../context/LiveContext";
import MermaidView from "../components/MermaidView";
import { PageTitle, btn, btnPrimary, field, ago } from "../components/ui";

function Card({ title, children }) {
  return <section className="rounded-xl border border-line bg-panel p-4"><h2 className="mb-3 font-medium">{title}</h2>{children}</section>;
}

export default function Settings() {
  const { current, refresh, wsId } = useAuth();
  const { toast } = useLive();
  const [health, setHealth] = useState(null);
  const [tokens, setTokens] = useState([]);
  const [newTok, setNewTok] = useState(null);
  const [label, setLabel] = useState("claude-code");
  const [invite, setInvite] = useState("");
  const [days, setDays] = useState(0);
  const [jobOut, setJobOut] = useState(null);
  const [graphs, setGraphs] = useState(null);
  const [graphName, setGraphName] = useState("chat");
  const owner = current?.role === "owner";

  const load = () => {
    api("/admin/health").then(setHealth).catch(() => {});
    api("/tokens").then(setTokens).catch(() => {});
  };
  useEffect(load, [wsId]);
  const run = async (fn, ok) => { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, { tone: "warn" }); } };

  return (
    <div className="grid max-w-5xl gap-5 lg:grid-cols-2">
      <div className="lg:col-span-2"><PageTitle title="Settings" sub={`Workspace: ${current?.name} · your role: ${current?.role}`} /></div>

      <Card title="Demo scenario">
        <p className="mb-3 text-sm text-dim">Loads ~13 memories that tell a story (constraints, a REST decision to supersede, three failed Friday deploys, an expiring note, a stale fact, an injection test). Replaces earlier demo data.</p>
        <button className={btnPrimary} disabled={!owner} onClick={() => run(() => api("/admin/seed", { method: "POST" }), "Demo scenario loaded.")}>Load demo scenario</button>
        {!owner && <p className="mt-2 text-xs text-dim">Only the workspace owner can do this.</p>}
      </Card>

      <Card title="Background agents">
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-dim">Time machine: pretend it is +</label>
          <input className={field + " w-20"} type="number" min="0" value={days} onChange={(e) => setDays(+e.target.value)} /><span className="text-xs text-dim">days</span>
          <button className={btn} disabled={!owner} onClick={async () => setJobOut(await run(() => api("/admin/jobs/freshness", { method: "POST", body: { days_ahead: days, dry_run: true } })))}>Preview</button>
          <button className={btnPrimary} disabled={!owner} onClick={async () => setJobOut(await run(() => api("/admin/jobs/freshness", { method: "POST", body: { days_ahead: days } }), "Freshness Keeper ran."))}>Run Freshness Keeper</button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className={btn} disabled={!owner} onClick={async () => setJobOut(await run(() => api("/admin/jobs/reflection", { method: "POST", body: {} }), "Reflection graph ran."))}>Run Reflection (consolidate)</button>
          <button className={btn} disabled={!owner} onClick={async () => { const r = await run(() => api("/admin/jobs/reflection", { method: "POST", body: { require_approval: true } }), "Reflection graph ran."); setJobOut(r); if (r?.status === "needs_user_choice") toast("A lesson is waiting for your approval in Decisions.", { tone: "warn" }); }}>Run Reflection (ask me first)</button>
        </div>
        {jobOut && <pre className="mt-3 max-h-56 overflow-auto rounded-md bg-ink p-3 font-mono text-[11px] text-dim">{JSON.stringify(jobOut, null, 2)}</pre>}
      </Card>

      <Card title="Demo mode">
        <p className="mb-3 text-sm text-dim">A real model is not “unsure” on cue. When this is on, the Learn graph always pauses and asks a human whenever a new statement contradicts an older memory, so you can show the Decision inbox on demand.</p>
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" className="accent-amber" disabled={!owner} checked={!!health?.demo_mode?.ask_on_conflict}
            onChange={async (e) => { await run(() => api("/admin/demo-mode", { method: "POST", body: { ask_on_conflict: e.target.checked } }), e.target.checked ? "Demo mode on: contradictions will ask you." : "Demo mode off."); load(); }} />
          Ask me when something contradicts an older memory
        </label>
      </Card>

      <Card title="Agent tokens (MCP)">
        <p className="mb-3 text-sm text-dim">Give Claude Code, Cursor or Codex access to this workspace's memory. The token is shown once.</p>
        <div className="flex gap-2"><input className={field} value={label} onChange={(e) => setLabel(e.target.value)} /><button className={btnPrimary} disabled={!owner} onClick={async () => { const r = await run(() => api("/tokens", { method: "POST", body: { label, scope: "readwrite" } })); if (r) { setNewTok(r.token); load(); } }}>Create</button></div>
        {newTok && <div className="mt-3 rounded-md border border-amber/50 p-2"><code className="break-all font-mono text-xs">{newTok}</code><button className={btn + " mt-2 block"} onClick={() => { navigator.clipboard?.writeText(newTok); toast("Copied"); }}>Copy</button></div>}
        <ul className="mt-3 space-y-1 text-sm">{tokens.map((t) => <li key={t.id} className="flex justify-between"><span>{t.label} <span className="text-xs text-dim">({t.scope}, last used {t.last_used_at ? ago(t.last_used_at) : "never"})</span></span><button className="text-xs text-red-300" onClick={() => run(() => api(`/tokens/${t.id}`, { method: "DELETE" })).then(load)}>revoke</button></li>)}</ul>
      </Card>

      <Card title="Members">
        <ul className="mb-3 space-y-1 text-sm">{current?.members.map((m) => <li key={m.user_id} className="flex justify-between"><span>{m.name} <span className="text-xs text-dim">{m.email}</span></span><span className="font-mono text-xs text-dim">{m.role}</span></li>)}</ul>
        <div className="flex gap-2"><input className={field} placeholder="teammate@email.com (must have an account)" value={invite} onChange={(e) => setInvite(e.target.value)} />
          <button className={btn} disabled={!owner} onClick={async () => { await run(() => api("/workspaces/invite", { method: "POST", body: { email: invite, role: "member" } }), "Member added."); setInvite(""); refresh(); }}>Invite</button></div>
      </Card>

      {health?.graphs?.enabled && (
        <div className="lg:col-span-2">
          <Card title="Workflow graphs">
            <p className="mb-3 text-sm text-dim">The four LangGraph workflows (plus the Retrieve subgraph), drawn from the compiled graphs. Dotted lines are conditional edges.</p>
            {!graphs ? (
              <button className={btn} disabled={!owner} onClick={async () => { const r = await run(() => api("/admin/graphs")); if (r) setGraphs(r.graphs); }}>Show graphs</button>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap gap-1 text-xs">
                  {Object.keys(graphs).map((k) => <button key={k} onClick={() => setGraphName(k)} className={`rounded-md px-2.5 py-1 ${graphName === k ? "bg-amber/15 text-amber" : "text-dim hover:bg-white/5"}`}>{k}</button>)}
                </div>
                <MermaidView code={graphs[graphName]} />
              </>
            )}
            {!owner && <p className="mt-2 text-xs text-dim">Only the workspace owner can view this.</p>}
          </Card>
        </div>
      )}

      <Card title="System health">
        {health ? (
          <ul className="space-y-1 font-mono text-xs text-dim">
            <li>mongo: <b className="text-paper">{health.mongo}</b></li>
            {Object.entries(health.indexes).map(([k, v]) => <li key={k}>index {k}: <b className={v === "READY" ? "text-emerald-300" : "text-amber"}>{String(v)}</b></li>)}
            <li>llm: <b className="text-paper">{health.llm_provider} · {health.model_main}</b></li>
            <li>embeddings: <b className="text-paper">{health.embedding_backend}</b> · rerank: <b className="text-paper">{String(health.rerank_enabled)}</b></li>
            <li>live updates: <b className="text-paper">{health.live_mode}</b></li>
            <li>langgraph: <b className="text-paper">{health.graphs?.enabled ? `${health.graphs.compiled?.length} graphs · checkpoints in ${health.graphs.checkpointer}` : "off (plain functions)"}</b></li>
            <li>questions waiting: <b className={health.pending_decisions ? "text-amber" : "text-paper"}>{health.pending_decisions}</b></li>
            <li>last retrieval: <b className="text-paper">{health.last_retrieval.mode}</b>{health.last_retrieval.errors?.length > 0 && <span className="text-amber"> (Atlas error, fell back to local)</span>}</li>
          </ul>
        ) : <p className="text-sm text-dim">Loading…</p>}
        <button className={btn + " mt-3"} onClick={load}>Refresh</button>
      </Card>
    </div>
  );
}
