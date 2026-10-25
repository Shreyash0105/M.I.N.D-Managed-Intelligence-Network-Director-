import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, Brain, Clock, Inbox, MessageSquare, Network, Radio, Settings, Upload, X } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useLive } from "../context/LiveContext";

const NAV = [
  ["/", "Chat", MessageSquare], ["/decisions", "Decisions", Inbox], ["/memories", "Memories", Brain], ["/graph", "Graph", Network],
  ["/timeline", "Timeline", Clock], ["/live", "Live feed", Radio], ["/import", "Import", Upload],
  ["/analytics", "Analytics", BarChart3], ["/settings", "Settings", Settings],
];

export default function Layout() {
  const { user, workspaces, wsId, switchWs, logout } = useAuth();
  const { status, toasts, dismiss, pending } = useLive();
  const dot = status === "live" ? "bg-emerald-400" : status === "connecting" ? "bg-amber" : "bg-red-400";
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-line bg-panel md:w-56 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-4">
          <span className="text-lg font-semibold tracking-tight">Team<span className="text-amber">M.I.N.D</span></span>
          <span className="flex items-center gap-1.5 text-xs text-dim"><i className={`h-2 w-2 rounded-full ${dot}`} />{status}</span>
        </div>
        <div className="px-3 pb-2">
          <select value={wsId || ""} onChange={(e) => switchWs(e.target.value)} className="w-full rounded-md border border-line bg-ink px-2 py-1.5 text-sm">
            {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible">
          {NAV.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) =>
              `flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm ${isActive ? "bg-amber/15 text-amber" : "text-dim hover:bg-white/5 hover:text-paper"}`}>
              <Icon size={16} />{label}{label === "Decisions" && pending.length > 0 && <span className="ml-auto rounded-full bg-amber px-1.5 text-[11px] font-medium text-ink">{pending.length}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-line p-3 text-xs text-dim md:block">
          <div className="truncate">{user?.name} · {user?.email}</div>
          <button onClick={logout} className="mt-1 text-amber hover:underline">Log out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8"><Outlet /></main>

      <div className="fixed bottom-24 right-4 z-50 flex w-80 max-w-[90vw] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`slidein flex items-start gap-3 rounded-lg border bg-panel p-3 text-sm shadow-xl ${t.tone === "warn" ? "border-amber/60" : "border-line"}`}>
            <span className="flex-1">{t.text}</span>
            {t.undo && <button onClick={async () => { try { await t.undo(); } catch { /* ignore */ } dismiss(t.id); }} className="rounded border border-amber/50 px-2 py-0.5 text-xs text-amber hover:bg-amber/10">Undo</button>}
            <button onClick={() => dismiss(t.id)} className="text-dim hover:text-paper"><X size={14} /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
