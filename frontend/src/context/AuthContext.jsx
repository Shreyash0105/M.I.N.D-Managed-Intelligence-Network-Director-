import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ls } from "../api/client";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(ls.get("tm_token"));
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [wsId, setWsId] = useState(ls.get("tm_ws"));
  const [ready, setReady] = useState(!ls.get("tm_token"));

  const pick = useCallback((list) => {
    const keep = list.find((w) => w.id === ls.get("tm_ws")) || list[0];
    if (keep) { ls.set("tm_ws", keep.id); setWsId(keep.id); }
  }, []);

  const accept = useCallback((s) => {
    ls.set("tm_token", s.token); setToken(s.token); setUser(s.user); setWorkspaces(s.workspaces); pick(s.workspaces);
  }, [pick]);

  const logout = useCallback(() => {
    ls.del("tm_token"); ls.del("tm_ws"); setToken(null); setUser(null); setWorkspaces([]); setWsId(null);
  }, []);

  useEffect(() => {
    const h = () => logout();
    window.addEventListener("tm-logout", h);
    return () => window.removeEventListener("tm-logout", h);
  }, [logout]);

  useEffect(() => {
    if (!token) return;
    api("/auth/me").then((r) => { setUser(r.user); setWorkspaces(r.workspaces); pick(r.workspaces); })
      .catch(() => {}).finally(() => setReady(true));
  }, []); // eslint-disable-line

  const login = async (email, password) => accept(await api("/auth/login", { method: "POST", body: { email, password } }));
  const register = async (name, email, password) => accept(await api("/auth/register", { method: "POST", body: { name, email, password } }));
  const refresh = async () => { const w = await api("/workspaces"); setWorkspaces(w); return w; };
  const switchWs = (id) => { ls.set("tm_ws", id); setWsId(id); };
  const current = workspaces.find((w) => w.id === wsId);

  return <Ctx.Provider value={{ token, user, workspaces, wsId, current, ready, login, register, logout, refresh, switchWs }}>{children}</Ctx.Provider>;
}
