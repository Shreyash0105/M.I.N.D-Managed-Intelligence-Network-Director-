import { useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import Inspector from "../components/Inspector";
import { PageTitle, TYPE_COLOR } from "../components/ui";

export default function Graph() {
  const { wsId } = useAuth();
  const [g, setG] = useState({ nodes: [], edges: [] });
  const [insp, setInsp] = useState(null);
  const [tags, setTags] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { api("/memories/graph").then(setG).catch((e) => setErr(e.message)); }, [wsId]);

  const { nodes, edges } = useMemo(() => {
    const cols = Object.keys(TYPE_COLOR), count = {};
    const nodes = g.nodes.map((m) => {
      const c = cols.indexOf(m.type), r = (count[m.type] = (count[m.type] || 0) + 1) - 1;
      const dead = ["superseded", "archived", "deleted"].includes(m.status);
      const col = TYPE_COLOR[m.type] || "#a8a290";
      return {
        id: m.id, position: { x: Math.max(c, 0) * 240, y: r * 110 },
        data: { label: m.content.length > 70 ? m.content.slice(0, 70) + "…" : m.content },
        style: { width: 200, fontSize: 11, color: "#ece6d6", background: "#1f1c15", border: `1.5px ${dead ? "dashed" : "solid"} ${col}`, borderRadius: 8, opacity: dead ? 0.45 : 1, padding: 8 },
      };
    });
    const edges = g.edges.filter((e) => tags || e.kind !== "tag").map((e, i) => ({
      id: `${e.kind}-${i}`, source: e.source, target: e.target,
      animated: e.kind === "derived",
      style: e.kind === "supersedes" ? { stroke: "#f27b7b", strokeDasharray: "6 4" } : e.kind === "derived" ? { stroke: "#6ea8fe" } : { stroke: "#4a4538" },
      markerEnd: e.kind === "tag" ? undefined : { type: MarkerType.ArrowClosed, color: e.kind === "supersedes" ? "#f27b7b" : "#6ea8fe" },
    }));
    return { nodes, edges };
  }, [g, tags]);

  return (
    <div>
      <PageTitle title="Memory graph" sub="Columns are memory types. Red dashed arrows: an older memory replaced by a newer one. Blue: a lesson derived from its sources.">
        <label className="flex items-center gap-2 text-sm text-dim"><input type="checkbox" className="accent-amber" checked={tags} onChange={(e) => setTags(e.target.checked)} />Show shared-tag links</label>
      </PageTitle>
      {err && <p className="text-sm text-red-300">{err}</p>}
      <div className="h-[70vh] rounded-xl border border-line">
        <ReactFlow nodes={nodes} edges={edges} fitView colorMode="dark" onNodeClick={(_, n) => setInsp(n.id)} nodesConnectable={false}>
          <Background color="#38332a" /><Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-dim">{Object.entries(TYPE_COLOR).map(([t, c]) => <span key={t} className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />{t}</span>)}</div>
      {insp && <Inspector id={insp} onClose={() => setInsp(null)} onOpen={setInsp} />}
    </div>
  );
}
