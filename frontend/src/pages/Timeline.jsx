import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Inspector from "../components/Inspector";
import { Empty, PageTitle, StatusBadge, TypeBadge } from "../components/ui";

export default function Timeline() {
  const { wsId } = useAuth();
  const [days, setDays] = useState(0);
  const [data, setData] = useState({ items: [], total: 0 });
  const [insp, setInsp] = useState(null);
  const when = new Date(Date.now() + days * 86400000);

  useEffect(() => {
    const t = setTimeout(() => api("/memories", { params: { as_of: when.toISOString(), page_size: 100 } }).then(setData).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [days, wsId]); // eslint-disable-line

  return (
    <div>
      <PageTitle title="Time travel" sub="Drag the slider to see what the team's agent knew on that day. Superseded and expired memories drop out at the right moment." />
      <div className="mb-5 rounded-xl border border-line bg-panel p-4">
        <div className="mb-2 flex justify-between text-sm"><span className="font-mono text-amber">{when.toDateString()}</span><span className="text-dim">{days === 0 ? "today" : days < 0 ? `${-days} days ago` : `${days} days from now`}</span></div>
        <input type="range" min={-60} max={30} value={days} onChange={(e) => setDays(+e.target.value)} className="w-full accent-amber" />
        <div className="mt-1 flex justify-between text-xs text-dim"><span>-60d</span><span>today</span><span>+30d</span></div>
      </div>
      <p className="mb-3 text-sm text-dim">{data.total} memories were valid on this day.</p>
      {!data.items.length && <Empty>Nothing was known on this day.</Empty>}
      <div className="space-y-2">
        {data.items.map((m) => (
          <button key={m.id} onClick={() => setInsp(m.id)} className="flex w-full items-start gap-3 rounded-lg border border-line bg-panel p-3 text-left hover:border-amber/60">
            <TypeBadge type={m.type} /><span className="flex-1">{m.content}</span><StatusBadge status={m.status} />
          </button>
        ))}
      </div>
      {insp && <Inspector id={insp} onClose={() => setInsp(null)} onOpen={setInsp} />}
    </div>
  );
}
