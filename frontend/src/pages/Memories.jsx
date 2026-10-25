import { useCallback, useEffect, useState } from "react";
import { Pin, PinOff, RotateCcw, Trash2, Pencil, History } from "lucide-react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useLive } from "../context/LiveContext";
import Inspector from "../components/Inspector";
import { Countdown, Empty, PageTitle, StatusBadge, TypeBadge, TYPE_COLOR, ago, btn, btnPrimary, field } from "../components/ui";

const TYPES = Object.keys(TYPE_COLOR);

export default function Memories() {
  const { current } = useAuth();
  const { events, toast } = useLive();
  const [data, setData] = useState({ items: [], total: 0 });
  const [f, setF] = useState({ type: "", status: "", scope: "", q: "" });
  const [insp, setInsp] = useState(null);
  const [err, setErr] = useState("");
  const [nm, setNm] = useState({ content: "", type: "decision", expires_in_days: "" });
  const isOwner = current?.role === "owner";
  const canWrite = current?.role !== "viewer";

  const load = useCallback(() => api("/memories", { params: { ...f, page_size: 100 } }).then(setData).catch((e) => setErr(e.message)), [f]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);
  useEffect(() => { if (events[0] && events[0].kind !== "learned") load(); }, [events]); // eslint-disable-line

  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); load(); } catch (e) { toast(e.message, { tone: "warn" }); } };
  const correct = (m) => {
    const v = window.prompt("Corrected text (the old version is kept as history):", m.content);
    if (v && v.trim() && v !== m.content) act(() => api(`/memories/${m.id}`, { method: "PATCH", body: { content: v, reason: "manual correction" } }), "Corrected. Old version kept as superseded.");
  };
  const create = async (e) => {
    e.preventDefault();
    if (!nm.content.trim()) return;
    try {
      const r = await api("/memories", { method: "POST", body: { content: nm.content, type: nm.type, expires_in_days: nm.expires_in_days ? +nm.expires_in_days : null } });
      toast(r.message, { tone: ["blocked", "needs_user_choice", "error"].includes(r.status) ? "warn" : "ok" });
      setNm({ ...nm, content: "" }); load();
    } catch (x) { toast(x.message, { tone: "warn" }); }
  };

  return (
    <div>
      <PageTitle title="Memory explorer" sub="Every memory the team has. Correct it, forget it, pin it, or inspect why it was used." />
      {canWrite && (
        <form onSubmit={create} className="mb-5 flex flex-wrap gap-2 rounded-xl border border-line bg-panel p-3">
          <input className={field + " min-w-[16rem] flex-1"} placeholder="Add a memory by hand (goes through Guard + Conflict Resolver)" value={nm.content} onChange={(e) => setNm({ ...nm, content: e.target.value })} />
          <select className={field + " w-36"} value={nm.type} onChange={(e) => setNm({ ...nm, type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
          <input className={field + " w-32"} placeholder="expires (days)" type="number" min="0" step="any" value={nm.expires_in_days} onChange={(e) => setNm({ ...nm, expires_in_days: e.target.value })} />
          <button className={btnPrimary}>Save</button>
        </form>
      )}
      <div className="mb-4 flex flex-wrap gap-2">
        <input className={field + " w-56"} placeholder="Search text, topic, tag" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select className={field + " w-36"} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="">all types</option>{TYPES.map((t) => <option key={t}>{t}</option>)}</select>
        <select className={field + " w-36"} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">not deleted</option>{["active", "superseded", "archived", "stale", "deleted", "all"].map((t) => <option key={t}>{t}</option>)}</select>
        <select className={field + " w-36"} value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })}><option value="">any scope</option>{["private", "workspace", "shared"].map((t) => <option key={t}>{t}</option>)}</select>
        <span className="self-center text-xs text-dim">{data.total} memories</span>
      </div>
      {err && <p className="mb-3 text-sm text-red-300">{err}</p>}
      {!data.items.length && <Empty>No memories yet. Chat with M.I.N.D, or load the demo scenario from Settings.</Empty>}
      <div className="grid gap-3 lg:grid-cols-2">
        {data.items.map((m) => (
          <div key={m.id} className={`rounded-xl border border-line bg-panel p-4 ${["superseded", "archived", "deleted"].includes(m.status) ? "opacity-60" : ""}`}>
            <div className="mb-2 flex flex-wrap items-center gap-2"><TypeBadge type={m.type} /><StatusBadge status={m.status} flags={m.flags} pinned={m.pinned} /><span className="font-mono text-[11px] text-dim">{m.scope}</span></div>
            <p className="mb-2 leading-relaxed">{m.content}</p>
            <p className="font-mono text-[11px] text-dim">{m.topic} · conf {m.confidence?.toFixed(2)} · used {m.access_count}× · {ago(m.updated_at)}</p>
            <div className="mt-1"><Countdown to={m.expires_at} /></div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <button className={btn + " flex items-center gap-1"} onClick={() => setInsp(m.id)}><History size={12} />History</button>
              {canWrite && m.status === "active" && <button className={btn + " flex items-center gap-1"} onClick={() => correct(m)}><Pencil size={12} />Correct</button>}
              {canWrite && ["active", "stale"].includes(m.status) && (
                <button className={btn + " flex items-center gap-1"} onClick={() => act(() => api(`/memories/${m.id}`, { method: "PATCH", body: { pinned: !m.pinned } }))}>{m.pinned ? <><PinOff size={12} />Unpin</> : <><Pin size={12} />Pin</>}</button>
              )}
              {canWrite && ["active", "stale"].includes(m.status) && <button className={btn + " flex items-center gap-1"} onClick={() => act(() => api(`/memories/${m.id}`, { method: "DELETE" }), "Forgotten (soft delete).")}><Trash2 size={12} />Forget</button>}
              {canWrite && ["deleted", "archived", "stale"].includes(m.status) && <button className={btn + " flex items-center gap-1"} onClick={() => act(() => api(`/memories/${m.id}/restore`, { method: "POST" }), "Restored.")}><RotateCcw size={12} />Restore</button>}
              {isOwner && m.status === "deleted" && <button className={btn + " text-red-300"} onClick={() => window.confirm("Delete forever? This cannot be undone.") && act(() => api(`/memories/${m.id}`, { method: "DELETE", params: { hard: true } }), "Deleted forever.")}>Delete forever</button>}
            </div>
          </div>
        ))}
      </div>
      {insp && <Inspector id={insp} onClose={() => setInsp(null)} onOpen={setInsp} />}
    </div>
  );
}
