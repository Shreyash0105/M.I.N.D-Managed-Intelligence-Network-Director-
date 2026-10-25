export const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};

function headers() {
  const h = { "Content-Type": "application/json" };
  const t = ls.get("tm_token"); if (t) h.Authorization = `Bearer ${t}`;
  const w = ls.get("tm_ws"); if (w) h["X-Workspace"] = w;
  return h;
}

async function fail(res) {
  if (res.status === 401) window.dispatchEvent(new Event("tm-logout"));
  const d = await res.json().catch(() => ({}));
  throw new Error(d.error || (typeof d.detail === "string" ? d.detail : res.statusText) || "Request failed");
}

export async function api(path, { method = "GET", body, params } = {}) {
  const clean = params ? Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "") : [];
  const qs = clean.length ? "?" + new URLSearchParams(clean) : "";
  const res = await fetch(API + path + qs, { method, headers: headers(), body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) await fail(res);
  return res.json().catch(() => ({}));
}

// Reads a Server-Sent-Events response (works with POST + auth headers, unlike EventSource)
export async function streamSSE(path, { method = "GET", body, signal } = {}, onEvent) {
  const res = await fetch(API + path, { method, headers: headers(), body: body ? JSON.stringify(body) : undefined, signal });
  if (!res.ok) await fail(res);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const p of parts) {
      const line = p.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      let ev = null;
      try { ev = JSON.parse(line.slice(6)); } catch { /* skip */ }
      if (ev) onEvent(ev);
    }
  }
}
