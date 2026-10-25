import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, streamSSE } from "../api/client";
import { useAuth } from "./AuthContext";

const Ctx = createContext(null);
export const useLive = () => useContext(Ctx);

export function LiveProvider({ children }) {
  const { token, wsId } = useAuth();
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState("offline");
  const [mode, setMode] = useState("");
  const [toasts, setToasts] = useState([]);
  const [pending, setPending] = useState([]);   // questions that paused a graph and wait for a human (Decision inbox)
  const seq = useRef(0);
  const refreshPending = useCallback(() => api("/decisions/pending").then((r) => setPending(r.items)).catch(() => {}), []);

  const dismiss = useCallback((id) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const toast = useCallback((text, opts = {}) => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, text, ...opts }]);
    setTimeout(() => dismiss(id), opts.undo ? 9000 : 5000);
  }, [dismiss]);

  const handle = useCallback((ev) => {
    setEvents((p) => [ev, ...p].slice(0, 100));
    if (ev.kind === "learned") {
      const undo = ["saved", "superseded", "saved_flagged", "saved_review"].includes(ev.status) && ev.memory
        ? async () => {
            await api(`/memories/${ev.memory.id}`, { method: "DELETE" });
            if (ev.old_id) await api(`/memories/${ev.old_id}/restore`, { method: "POST" });
          } : null;
      toast(ev.message, { undo, tone: ["blocked", "saved_flagged", "error", "capped"].includes(ev.status) ? "warn" : "ok" });
    } else if (ev.kind === "needs_user_choice") {
      refreshPending();
      toast("M.I.N.D has a question for you. Open Decisions.", { tone: "warn" });
    } else if (ev.kind === "decision_resolved") {
      refreshPending();
    }
  }, [toast, refreshPending]);

  useEffect(() => { if (token && wsId) refreshPending(); else setPending([]); }, [token, wsId, refreshPending]);

  useEffect(() => {
    if (!token || !wsId) return undefined;
    const ctrl = new AbortController();
    let stop = false;
    (async () => {
      while (!stop) {
        try {
          setStatus("connecting");
          await streamSSE("/stream/memories", { signal: ctrl.signal }, (ev) => {
            if (ev.kind === "hello") { setStatus("live"); setMode(ev.mode); return; }
            handle(ev);
          });
        } catch { /* reconnect below */ }
        if (stop) return;
        setStatus("offline");
        await new Promise((r) => setTimeout(r, 3000));
      }
    })();
    return () => { stop = true; ctrl.abort(); setEvents([]); };
  }, [token, wsId, handle]);

  return <Ctx.Provider value={{ events, status, mode, toasts, dismiss, toast, pending, refreshPending }}>{children}</Ctx.Provider>;
}
