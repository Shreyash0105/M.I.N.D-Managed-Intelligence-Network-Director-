import { useEffect, useRef, useState } from "react";

// Draws Mermaid text (from GET /admin/graphs). The library is loaded only when this component is used.
export default function MermaidView({ code }) {
  const ref = useRef(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let dead = false;
    setErr("");
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default", securityLevel: "strict" });
        const { svg } = await mermaid.render("mm" + Math.random().toString(36).slice(2), code);
        if (!dead && ref.current) ref.current.innerHTML = svg;
      } catch (e) { if (!dead) setErr(String(e?.message || e)); }
    })();
    return () => { dead = true; };
  }, [code]);
  if (err) return <pre className="max-h-72 overflow-auto rounded-md bg-ink p-3 font-mono text-[11px] text-dim">{code}</pre>;
  return <div ref={ref} className="overflow-x-auto rounded-md bg-[#f7f5ff] p-3" />;
}
