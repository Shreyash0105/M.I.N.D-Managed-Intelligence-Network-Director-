import { useState } from "react";
import { api } from "../api/client";
import { useLive } from "../context/LiveContext";
import { btn, btnPrimary, ago } from "./ui";

// One question that paused a graph (interrupt). Clicking an answer resumes the run from MongoDB.
export default function DecisionCard({ d }) {
  const { toast, refreshPending } = useLive();
  const [busy, setBusy] = useState(false);
  const p = d.payload || {};

  async function choose(choice) {
    setBusy(true);
    try {
      const r = await api(`/decisions/${encodeURIComponent(d.thread_id)}/resume`, { method: "POST", body: { choice } });
      const last = r.results?.[r.results.length - 1];
      toast(last?.message || "Thanks, done.");
      if (r.pending?.length) toast("Another question is waiting in Decisions.", { tone: "warn" });
    } catch (e) { toast(e.message, { tone: "warn" }); }
    setBusy(false);
    refreshPending();
  }

  return (
    <div className="rounded-xl border border-amber/50 bg-panel p-4 text-sm">
      <div className="mb-2 flex items-center justify-between text-xs text-dim">
        <span className="font-mono text-amber">{p.kind === "lesson" ? "lesson to approve" : "which one is right?"}</span>
        <span>{ago(d.ts)}{d.private ? " · private to you" : ""}</span>
      </div>
      {p.kind === "lesson" ? (
        <>
          <p className="mb-1 text-dim">M.I.N.D found a pattern in “{p.topic}” and wants to save this lesson:</p>
          <p className="mb-2 rounded-md border border-line bg-ink p-2">{p.text}</p>
          {p.sources?.length > 0 && <ul className="mb-3 space-y-0.5 text-xs text-dim">{p.sources.map((s, i) => <li key={i}>• {s}</li>)}</ul>}
          <div className="flex gap-2">
            <button className={btnPrimary} disabled={busy} onClick={() => choose("approve")}>Approve</button>
            <button className={btn} disabled={busy} onClick={() => choose("reject")}>Reject</button>
          </div>
        </>
      ) : (
        <>
          <p className="mb-2 text-dim">You said this before, and now something different. {p.reason ? `(${p.reason}) ` : ""}confidence {Number(p.confidence ?? 0).toFixed(2)}</p>
          <div className="mb-3 grid gap-2 md:grid-cols-2">
            <div className="rounded-md border border-line p-2"><p className="mb-1 text-xs text-dim">Before</p>{p.old}</div>
            <div className="rounded-md border border-amber/50 p-2"><p className="mb-1 text-xs text-amber">Now</p>{p.new}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className={btnPrimary} disabled={busy} onClick={() => choose("use_new")}>Use new</button>
            <button className={btn} disabled={busy} onClick={() => choose("keep_old")}>Keep old</button>
            <button className={btn} disabled={busy} onClick={() => choose("keep_both")}>Keep both</button>
          </div>
        </>
      )}
    </div>
  );
}
