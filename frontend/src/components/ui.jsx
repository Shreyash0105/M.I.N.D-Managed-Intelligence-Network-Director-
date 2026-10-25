import { useEffect, useState } from "react";

export const TYPE_COLOR = {
  decision: "#6ea8fe", constraint: "#f27b7b", preference: "#c39bf5", feedback: "#e8b84a",
  outcome: "#5fcf9b", strategy: "#4fd0dd", fact: "#a8a290", episode: "#f08fc0",
};
export const btn = "rounded-md border border-line px-2.5 py-1 text-xs text-paper hover:bg-white/5 disabled:opacity-40";
export const btnPrimary = "rounded-md bg-amber px-3 py-1.5 text-sm font-medium text-ink hover:brightness-110 disabled:opacity-40";
export const field = "w-full rounded-md border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-amber";

export function TypeBadge({ type }) {
  const c = TYPE_COLOR[type] || "#a8a290";
  return <span className="rounded px-1.5 py-0.5 font-mono text-[11px]" style={{ background: c + "22", color: c, border: `1px solid ${c}55` }}>{type}</span>;
}

const STATUS = { active: "#5fcf9b", superseded: "#f27b7b", archived: "#a8a290", deleted: "#a8a290", stale: "#e8b84a" };
export function StatusBadge({ status, flags = [], pinned }) {
  const c = STATUS[status] || "#a8a290";
  return (
    <span className="inline-flex gap-1">
      <span className="rounded px-1.5 py-0.5 font-mono text-[11px]" style={{ color: c, border: `1px solid ${c}55` }}>{status}</span>
      {pinned && <span className="rounded border border-amber/40 px-1.5 py-0.5 font-mono text-[11px] text-amber">pinned</span>}
      {flags.includes("injection") && <span className="rounded border border-red-400/50 px-1.5 py-0.5 font-mono text-[11px] text-red-300">suspicious</span>}
      {flags.includes("needs_review") && <span className="rounded border border-amber/40 px-1.5 py-0.5 font-mono text-[11px] text-amber">review</span>}
    </span>
  );
}

export function Bar({ label, value, max = 1 }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 shrink-0 text-dim">{label}</span>
      <div className="h-1.5 flex-1 rounded bg-white/10"><div className="h-1.5 rounded bg-amber" style={{ width: pct + "%" }} /></div>
      <span className="w-10 text-right font-mono text-dim">{Number(value).toFixed(2)}</span>
    </div>
  );
}

export function Countdown({ to }) {
  const [, tick] = useState(0);
  useEffect(() => { const i = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(i); }, []);
  if (!to) return null;
  const s = Math.floor((new Date(to) - Date.now()) / 1000);
  if (s <= 0) return <span className="font-mono text-xs text-red-300">expired</span>;
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return <span className="font-mono text-xs text-amber">expires in {d ? `${d}d ` : ""}{h ? `${h}h ` : ""}{m}m {s % 60}s</span>;
}

export function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function Empty({ children }) {
  return <div className="rounded-lg border border-dashed border-line p-8 text-center text-sm text-dim">{children}</div>;
}
export function PageTitle({ title, sub, children }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-xl font-semibold">{title}</h1>{sub && <p className="mt-1 max-w-2xl text-sm text-dim">{sub}</p>}</div>
      <div className="flex gap-2">{children}</div>
    </div>
  );
}
