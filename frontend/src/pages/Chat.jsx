import { useEffect, useRef, useState } from "react";
import { GitCompare, Plus, Send } from "lucide-react";
import { api, streamSSE } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useLive } from "../context/LiveContext";
import DecisionCard from "../components/DecisionCard";
import Inspector from "../components/Inspector";
import { TypeBadge, btn, btnPrimary, field } from "../components/ui";

// Turns [m:2] in the answer into clickable chips that open the inspector.
function Answer({ text, memories, onChip }) {
  const parts = text.split(/(\[m:\d+\])/g);
  return (
    <p className="whitespace-pre-wrap leading-relaxed">
      {parts.map((p, i) => {
        const m = p.match(/^\[m:(\d+)\]$/);
        if (!m) return p;
        const mem = memories?.find((x) => x.ref === +m[1]);
        return mem
          ? <button key={i} onClick={() => onChip(mem)} title={mem.content} className="mx-0.5 rounded bg-amber/20 px-1.5 font-mono text-xs text-amber hover:bg-amber/30">m{m[1]}</button>
          : p;
      })}
    </p>
  );
}

function Chips({ memories, onChip }) {
  if (!memories?.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {memories.map((m) => (
        <button key={m.id} onClick={() => onChip(m)} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-dim hover:border-amber hover:text-paper">
          <span className="font-mono text-amber">m{m.ref}</span><TypeBadge type={m.type} /><span className="max-w-[12rem] truncate">{m.topic}</span>
        </button>
      ))}
    </div>
  );
}

export default function Chat() {
  const { wsId } = useAuth();
  const { pending } = useLive();
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [convId, setConvId] = useState(null);
  const [memOn, setMemOn] = useState(true);
  const [busy, setBusy] = useState(false);
  const [insp, setInsp] = useState(null);
  const [cmp, setCmp] = useState(null);
  const [convs, setConvs] = useState([]);
  const bottom = useRef();

  const loadConvs = () => api("/conversations").then((r) => setConvs(r.items)).catch(() => {});
  useEffect(() => { setMsgs([]); setConvId(null); setCmp(null); loadConvs(); }, [wsId]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  const patchLast = (fn) => setMsgs((m) => m.map((x, i) => (i === m.length - 1 ? fn(x) : x)));

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", text }, { role: "assistant", text: "", memories: [] }]);
    try {
      await streamSSE("/chat", { method: "POST", body: { text, conversation_id: convId, memory_on: memOn } }, (ev) => {
        if (ev.type === "conversation") setConvId(ev.id);
        else if (ev.type === "guard") patchLast((x) => ({ ...x, guard: ev }));
        else if (ev.type === "memories") patchLast((x) => ({ ...x, memories: ev.items, info: { mode: ev.mode } }));
        else if (ev.type === "token") patchLast((x) => ({ ...x, text: x.text + ev.text }));
        else if (ev.type === "done") patchLast((x) => ({ ...x, info: { ...x.info, ms: ev.latency_ms, memoryOnly: ev.memory_only } }));
        else if (ev.type === "error") patchLast((x) => ({ ...x, text: x.text + `\n⚠ ${ev.message}` }));
      });
    } catch (e) { patchLast((x) => ({ ...x, text: `⚠ ${e.message}` })); }
    setBusy(false); loadConvs();
  }

  async function compare() {
    const text = input.trim() || [...msgs].reverse().find((m) => m.role === "user")?.text;
    if (!text) return;
    setCmp({ text, off: { text: "", memories: [] }, on: { text: "", memories: [] }, loading: true });
    const run = (key, memory_on) => streamSSE("/chat", { method: "POST", body: { text, memory_on, ephemeral: true } }, (ev) => {
      setCmp((c) => {
        if (!c) return c;
        const s = { ...c[key] };
        if (ev.type === "token") s.text += ev.text;
        if (ev.type === "memories") { s.memories = ev.items; s.mode = ev.mode; }
        if (ev.type === "error") s.text += `\n⚠ ${ev.message}`;
        return { ...c, [key]: s };
      });
    });
    try { await Promise.all([run("off", false), run("on", true)]); } catch (e) { setCmp((c) => c && { ...c, error: e.message }); }
    setCmp((c) => c && { ...c, loading: false });
  }

  async function openConv(id) {
    const c = await api(`/conversations/${id}`);
    setConvId(id); setCmp(null);
    setMsgs(c.messages.map((m) => ({ role: m.role, text: m.text, memories: m.memories || [] })));
  }
  const newChat = () => { setMsgs([]); setConvId(null); setCmp(null); };

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-5">
      <div className="hidden w-52 shrink-0 flex-col gap-1 overflow-y-auto lg:flex">
        <button className={btn + " mb-2 flex items-center justify-center gap-1"} onClick={newChat}><Plus size={14} />New chat</button>
        {convs.map((c) => (
          <button key={c.id} onClick={() => openConv(c.id)} className={`truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-white/5 ${c.id === convId ? "bg-white/5 text-amber" : "text-dim"}`}>{c.title || "Chat"}</button>
        ))}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Chat</h1>
            <p className="text-xs text-dim">Say something durable, like “We cannot use paid APIs.” Open a new chat later and ask a related question.</p>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={memOn} onChange={(e) => setMemOn(e.target.checked)} className="accent-amber" />
            Memory {memOn ? "on" : "off"}
          </label>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto rounded-xl border border-line bg-panel/60 p-4">
          {!msgs.length && !cmp && <p className="py-12 text-center text-sm text-dim">No messages yet. Try: “We have no budget for paid tools.”</p>}
          {msgs.map((m, i) => (
            <div key={i} className={m.role === "user" ? "ml-auto max-w-[80%] rounded-xl bg-amber/15 px-3 py-2" : "max-w-[90%]"}>
              {m.guard && <div className="mb-2 rounded-md border border-amber/50 bg-amber/10 px-3 py-1.5 text-xs text-amber">Guard: {m.guard.action === "block" ? "I hid and did not save" : "I hid"} {m.guard.findings.join(", ")}.</div>}
              {m.role === "user" ? <p>{m.text}</p> : (
                <>
                  <Answer text={m.text || (busy && i === msgs.length - 1 ? "…" : "")} memories={m.memories} onChip={setInsp} />
                  <Chips memories={m.memories} onChip={setInsp} />
                  {m.info?.mode && (
                    <p className="mt-2 font-mono text-[11px] text-dim">
                      retrieval: {m.info.mode} · {m.memories?.length || 0} memories{m.info.ms ? ` · ${(m.info.ms / 1000).toFixed(1)} s` : ""}
                      {m.info.memoryOnly && <span className="ml-1 rounded border border-amber/50 px-1 text-amber">memory only mode</span>}
                      {convId && i === msgs.length - 1 && !busy && <button onClick={() => setInsp({ id: null, trace: true })} className="ml-2 text-amber hover:underline">run trace</button>}
                    </p>
                  )}
                </>
              )}
            </div>
          ))}

          {cmp && (
            <div className="rounded-xl border border-amber/40 p-3">
              <p className="mb-3 text-sm text-dim">Same question, two answers: “{cmp.text}”</p>
              {cmp.error && <p className="text-sm text-red-300">{cmp.error}</p>}
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-line p-3"><p className="mb-2 text-xs font-medium text-dim">Without memory</p><Answer text={cmp.off.text || "…"} /></div>
                <div className="rounded-lg border border-amber/50 p-3"><p className="mb-2 text-xs font-medium text-amber">With memory</p><Answer text={cmp.on.text || "…"} memories={cmp.on.memories} onChip={setInsp} /><Chips memories={cmp.on.memories} onChip={setInsp} /></div>
              </div>
              <button className={btn + " mt-3"} onClick={() => setCmp(null)}>Close comparison</button>
            </div>
          )}
          {pending.slice(0, 2).map((d) => <DecisionCard key={d.id} d={d} />)}
          <div ref={bottom} />
        </div>

        <div className="mt-3 flex gap-2">
          <input className={field} placeholder="Message M.I.N.D…" value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()} />
          <button className={btn + " flex items-center gap-1"} onClick={compare} disabled={cmp?.loading}><GitCompare size={14} />Compare</button>
          <button className={btnPrimary + " flex items-center gap-1"} onClick={send} disabled={busy}><Send size={14} />Send</button>
        </div>
      </div>
      {insp && <Inspector id={insp.id} hit={insp.scores ? insp : null} convId={convId} startTab={insp.trace ? "trace" : undefined} onClose={() => setInsp(null)} onOpen={(id) => setInsp({ id })} />}
    </div>
  );
}
