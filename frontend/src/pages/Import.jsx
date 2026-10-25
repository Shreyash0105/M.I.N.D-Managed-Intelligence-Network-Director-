import { useState } from "react";
import { api } from "../api/client";
import { useLive } from "../context/LiveContext";
import { Empty, PageTitle, TypeBadge, btn, btnPrimary, field } from "../components/ui";

export default function Import() {
  const { toast } = useLive();
  const [text, setText] = useState("");
  const [items, setItems] = useState(null);
  const [busy, setBusy] = useState(false);

  const extract = async () => {
    setBusy(true);
    try { const r = await api("/memories/import", { method: "POST", body: { text } }); setItems(r.items.map((x) => ({ ...x, approved: !x.blocked }))); }
    catch (e) { toast(e.message, { tone: "warn" }); }
    setBusy(false);
  };
  const commit = async () => {
    const chosen = items.filter((i) => i.approved && !i.blocked);
    try {
      const r = await api("/memories/import/commit", { method: "POST", body: { items: chosen } });
      const saved = r.results.filter((x) => !["blocked", "error", "kept_old"].includes(x.status)).length;
      const waiting = r.pending?.length ? ` ${r.pending.length} waiting in Decisions.` : "";
      toast(`Saved ${saved} of ${chosen.length} memories.${waiting}`, { tone: waiting ? "warn" : "ok" });
      setItems(null); setText("");
    } catch (e) { toast(e.message, { tone: "warn" }); }
  };
  const edit = (i, patch) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  return (
    <div className="max-w-3xl">
      <PageTitle title="Import notes" sub="Paste meeting notes. M.I.N.D proposes memories; nothing is saved until you approve it." />
      <textarea className={field + " h-40"} placeholder="e.g. We decided to deploy on Thursdays only. Priya prefers short stand-ups. The client cannot use Google services." value={text} onChange={(e) => setText(e.target.value)} />
      <button className={btnPrimary + " mt-3"} onClick={extract} disabled={busy || !text.trim()}>{busy ? "Reading…" : "Find memories"}</button>
      {items && !items.length && <div className="mt-5"><Empty>Nothing worth remembering was found.</Empty></div>}
      {items?.length > 0 && (
        <div className="mt-5 space-y-2">
          {items.map((it, i) => (
            <div key={i} className={`rounded-lg border bg-panel p-3 ${it.blocked ? "border-red-400/50" : "border-line"}`}>
              <div className="mb-2 flex items-center gap-2">
                <input type="checkbox" className="accent-amber" checked={it.approved} disabled={it.blocked} onChange={(e) => edit(i, { approved: e.target.checked })} />
                <TypeBadge type={it.type} /><span className="font-mono text-xs text-dim">worthiness {it.worthiness?.toFixed?.(2)}</span>
                {it.guard?.length > 0 && <span className="text-xs text-amber">guard: {it.guard.join(", ")}{it.blocked ? " (blocked)" : ""}</span>}
              </div>
              <input className={field} value={it.content} onChange={(e) => edit(i, { content: e.target.value })} disabled={it.blocked} />
            </div>
          ))}
          <button className={btnPrimary} onClick={commit}>Save approved</button>
          <button className={btn + " ml-2"} onClick={() => setItems(null)}>Discard</button>
        </div>
      )}
    </div>
  );
}
