import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { Empty, PageTitle, TYPE_COLOR } from "../components/ui";

function Stat({ label, value }) {
  return <div className="rounded-xl border border-line bg-panel p-4"><div className="text-2xl font-semibold">{value}</div><div className="text-xs text-dim">{label}</div></div>;
}
function Bars({ data, colors }) {
  const max = Math.max(1, ...Object.values(data));
  return (
    <div className="space-y-2">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex items-center gap-3 text-sm">
          <span className="w-24 text-dim">{k}</span>
          <div className="h-3 flex-1 rounded bg-white/5"><div className="h-3 rounded" style={{ width: `${(v / max) * 100}%`, background: colors?.[k] || "#e0a63a" }} /></div>
          <span className="w-8 text-right font-mono text-xs">{v}</span>
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const { wsId } = useAuth();
  const [s, setS] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api("/analytics/summary").then(setS).catch((e) => setErr(e.message)); }, [wsId]);
  if (err) return <p className="text-red-300">{err}</p>;
  if (!s) return <p className="text-dim">Loading…</p>;
  const total = Object.values(s.by_status).reduce((a, b) => a + b, 0);
  return (
    <div>
      <PageTitle title="Analytics" sub="How the memory is used, and how healthy it is." />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="memories (all statuses)" value={total} /><Stat label="stale" value={s.by_status.stale || 0} />
        <Stat label="chat turns" value={s.chat_turns} /><Stat label="avg latency (ms)" value={s.avg_latency_ms} />
        <Stat label="with an expiry" value={s.expiring} /><Stat label="flagged (injection/review)" value={s.flagged} />
        <Stat label="audit events, 24h" value={s.events_24h} /><Stat label="superseded (history kept)" value={s.by_status.superseded || 0} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-line bg-panel p-4"><h2 className="mb-3 font-medium">Active memories by type</h2>{Object.keys(s.by_type).length ? <Bars data={s.by_type} colors={TYPE_COLOR} /> : <Empty>No data.</Empty>}</section>
        <section className="rounded-xl border border-line bg-panel p-4"><h2 className="mb-3 font-medium">Retrieval mode used</h2>{Object.keys(s.retrieval_modes).length ? <Bars data={s.retrieval_modes} /> : <Empty>No chats yet.</Empty>}</section>
        <section className="rounded-xl border border-line bg-panel p-4 lg:col-span-2">
          <h2 className="mb-3 font-medium">Average time per graph node (ms)</h2>
          {s.node_latency?.length ? <Bars data={Object.fromEntries(s.node_latency.map((n) => [n.node, n.avg_ms]))} /> : <Empty>No traced chat turns yet.</Empty>}
        </section>
        <section className="rounded-xl border border-line bg-panel p-4 lg:col-span-2">
          <h2 className="mb-3 font-medium">Most used memories</h2>
          {s.top_used.length ? s.top_used.map((m) => <div key={m.id} className="flex justify-between border-b border-line py-2 text-sm last:border-0"><span>{m.content}</span><span className="font-mono text-dim">{m.access_count}×</span></div>) : <Empty>Nothing has been retrieved yet.</Empty>}
        </section>
      </div>
    </div>
  );
}
