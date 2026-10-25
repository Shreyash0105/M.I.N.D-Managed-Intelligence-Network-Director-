import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { btnPrimary, field } from "../components/ui";

export default function Login() {
  const { login, register, token, ready } = useAuth();
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ name: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (ready && token) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try { mode === "login" ? await login(f.email, f.password) : await register(f.name, f.email, f.password); }
    catch (x) { setErr(x.message); }
    setBusy(false);
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <div className="grid min-h-screen place-items-center p-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-3xl font-semibold tracking-tight"><span className="text-amber">M.I.N.D</span></h1>
        <p className="mb-6 text-sm text-dim">A shared memory for your team and its AI agents. It remembers, corrects itself and forgets safely.</p>
        <form onSubmit={submit} className="space-y-3 rounded-xl border border-line bg-panel p-5">
          {mode === "register" && <input className={field} placeholder="Your name" value={f.name} onChange={set("name")} />}
          <input className={field} placeholder="Email" type="email" value={f.email} onChange={set("email")} />
          <input className={field} placeholder="Password (6+ characters)" type="password" value={f.password} onChange={set("password")} />
          {err && <p className="text-sm text-red-300">{err}</p>}
          <button className={btnPrimary + " w-full"} disabled={busy}>{mode === "login" ? "Log in" : "Create account"}</button>
          <button type="button" className="w-full text-xs text-dim hover:text-paper" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "New here? Create an account" : "Have an account? Log in"}
          </button>
        </form>
        <p className="mt-4 text-xs text-dim">Demo accounts (after running the seed script): alex@demo.com or priya@demo.com, password demo1234.</p>
      </div>
    </div>
  );
}
