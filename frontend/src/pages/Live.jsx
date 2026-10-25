import { useLive } from "../context/LiveContext";
import { useAuth } from "../context/AuthContext";
import { Empty, PageTitle, TypeBadge, ago } from "../components/ui";

const VERB = { created: "learned", updated: "updated", superseded: "replaced", deleted: "forgot", archived: "archived", stale: "marked stale", purged: "erased", learned: "auto-remembered" };

export default function Live() {
  const { events, status, mode } = useLive();
  const { current } = useAuth();
  const who = (e) => e.agent || current?.members.find((m) => m.user_id === e.user_id)?.name || "Someone";
  return (
    <div>
      <PageTitle title="Live feed" sub="Changes from teammates and their agents, pushed instantly. Open a second window as another user to see it.">
        <span className="rounded-md border border-line px-2 py-1 font-mono text-xs text-dim">{status}{mode ? ` · ${mode}` : ""}</span>
      </PageTitle>
      {!events.length && <Empty>Waiting for activity. Save a memory in another window or from an MCP agent.</Empty>}
      <div className="space-y-2">
        {events.filter((e) => e.kind !== "learned" || e.memory).map((e, i) => {
          const body = e.kind === "learned" ? e.memory : e;
          return (
            <div key={i} className="slidein flex items-start gap-3 rounded-lg border border-line bg-panel p-3 text-sm">
              <TypeBadge type={body.type} />
              <div className="flex-1"><b>{e.kind === "learned" ? "M.I.N.D" : who(e)}</b> <span className="text-dim">{VERB[e.kind] || e.kind}:</span> {body.content || e.message}</div>
              <span className="font-mono text-xs text-dim">{ago(e.ts)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
