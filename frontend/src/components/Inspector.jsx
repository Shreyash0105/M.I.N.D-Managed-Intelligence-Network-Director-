import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api } from "../api/client";
import { Bar, Countdown, StatusBadge, TypeBadge, ago } from "./ui";

// Right-side drawer: content, why it was selected, score breakdown, version chain, audit trail.
function RunTrace({ runs }) {
  if (!runs) return <p className="text-sm text-dim">Loading…</p>;
  if (!runs.length) return <p className="text-sm text-dim">No traced runs for this conversation yet.</p>;
  const run = runs[0];
  const total = Math.max(1, ...run.trace.map((t) => t.ms || 0));
  const detail = (t) => [t.mode && `mode ${t.mode}`, t.n != null && `n=${t.n}`, t.action && t.action, t.used && `cited ${t.used.length}`, t.error && `error: ${t.error}`]
    .filter(Boolean).join(" · ");
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-dim">Latest chat turn · {run.latency_ms} ms · model {run.model} · retrieval {run.mode || "off"}</p>
      <ol className="space-y-2">
        {run.trace.map((t, i) => (
          <li key={i}>
            <div className="flex items-center justify-between"><span className="font-mono text-amber">{i + 1}. {t.node}</span><span className="font-mono text-xs text-dim">{t.ms ?? 0} ms</span></div>
            <div className="mt-1 h-1.5 rounded bg-white/10"><div className="h-1.5 rounded bg-amber" style={{ width: `${((t.ms || 0) / total) * 100}%` }} /></div>
            {(t.model || detail(t)) && <p className="mt-0.5 text-xs text-dim">{[t.model, detail(t)].filter(Boolean).join(" · ")}</p>}
          </li>
        ))}
      </ol>
      {runs.length > 1 && <p className="text-xs text-dim">{runs.length - 1} earlier turn(s) not shown.</p>}
    </div>
  );
}

export default function Inspector({ id, hit, onClose, onOpen, convId, startTab }) {
  const [tab, setTab] = useState(startTab || (id ? "memory" : "trace"));
  const [runs, setRuns] = useState(null);
  const [m, setM] = useState(null);
  const [lin, setLin] = useState(null);
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => { setTab(startTab || (id ? "memory" : "trace")); }, [id, startTab]);
  useEffect(() => {
    if (tab !== "trace" || !convId) return;
    setRuns(null);
    api(`/runs/${convId}`).then((r) => setRuns(r.items)).catch(() => setRuns([]));
  }, [tab, convId]);

  useEffect(() => {
    setM(null); setLin(null); setEvents([]); setErr("");
    if (!id) return;
    api(`/memories/${id}`).then(setM).catch((e) => setErr(e.message));
    api(`/memories/${id}/lineage`).then(setLin).catch(() => {});
    api(`/memories/${id}/events`).then((r) => setEvents(r.items)).catch(() => {});
  }, [id]);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l border-line bg-panel p-5 shadow-2xl">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-semibold">{tab === "trace" ? "Run trace" : "Memory inspector"}</h2>
        <button onClick={onClose} className="text-dim hover:text-paper"><X size={18} /></button>
      </div>
      {id && convId && (
        <div className="mb-4 flex gap-1 text-xs">
          {[["memory", "Memory"], ["trace", "Run trace"]].map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded-md px-2.5 py-1 ${tab === k ? "bg-amber/15 text-amber" : "text-dim hover:bg-white/5"}`}>{label}</button>
          ))}
        </div>
      )}
      {tab === "trace" && <RunTrace runs={runs} />}
      {tab === "memory" && err && <p className="text-sm text-red-300">{err}</p>}
      {tab === "memory" && m && (
        <div className="space-y-5 text-sm">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2"><TypeBadge type={m.type} /><StatusBadge status={m.status} flags={m.flags} pinned={m.pinned} /><span className="rounded border border-line px-1.5 py-0.5 font-mono text-[11px] text-dim">{m.scope}</span></div>
            <p className="text-base leading-relaxed">{m.content}</p>
            <p className="mt-2 font-mono text-xs text-dim">{m.topic} · {(m.tags || []).join(", ")}</p>
            {m.expires_at && <div className="mt-1"><Countdown to={m.expires_at} /></div>}
          </div>

          {hit && (
            <div className="rounded-lg border border-line p-3">
              <p className="mb-2 text-xs text-dim">Why this was selected</p>
              <p className="mb-3">{hit.why}</p>
              <div className="space-y-1.5">
                {Object.entries(hit.scores).map(([k, v]) => <Bar key={k} label={k} value={v} />)}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 text-xs text-dim">
            <span>confidence <b className="text-paper">{m.confidence?.toFixed?.(2)}</b></span>
            <span>importance <b className="text-paper">{m.importance?.toFixed?.(2)}</b></span>
            <span>used <b className="text-paper">{m.access_count}×</b></span>
            <span>reinforced <b className="text-paper">{m.reinforcement_count}×</b></span>
            <span>source <b className="text-paper">{m.source?.kind}{m.agent_id ? ` · ${m.agent_id}` : ""}</b></span>
            <span>created <b className="text-paper">{ago(m.created_at)}</b></span>
          </div>

          {lin && lin.versions.length > 1 && (
            <div>
              <p className="mb-2 text-xs text-dim">Version chain (old → new)</p>
              <ol className="space-y-2 border-l border-line pl-3">
                {lin.versions.map((v) => (
                  <li key={v.id} className={v.id === id ? "text-paper" : "text-dim"}>
                    <button onClick={() => onOpen?.(v.id)} className="text-left hover:text-amber">{v.content}</button>
                    <div className="mt-0.5"><StatusBadge status={v.status} /></div>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {lin && lin.sources.length > 0 && (
            <div>
              <p className="mb-2 text-xs text-dim">Derived from</p>
              <ul className="space-y-1.5 text-xs">{lin.sources.map((s) => <li key={s.id}><button onClick={() => onOpen?.(s.id)} className="text-left text-dim hover:text-amber">• {s.content}</button></li>)}</ul>
            </div>
          )}

          <div>
            <p className="mb-2 text-xs text-dim">Audit trail</p>
            <ul className="space-y-1.5 text-xs">
              {events.map((e) => (
                <li key={e.id} className="flex gap-2"><span className="w-20 shrink-0 font-mono text-amber">{e.action}</span><span className="text-dim">{e.reason ? `${e.reason} · ` : ""}{ago(e.ts)}</span></li>
              ))}
              {!events.length && <li className="text-dim">No events yet.</li>}
            </ul>
          </div>
        </div>
      )}
    </aside>
  );
}
