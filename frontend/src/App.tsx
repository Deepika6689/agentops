import { useEffect, useState } from "react";
import { Stats, useApi, useHash } from "./api";
import { MemoryPage, NewTask, Overview, Runs, SettingsPage } from "./pages";
import RunDetail from "./RunDetail";

const NAV: [string, string][] = [["/", "Overview"], ["/new", "New task"], ["/runs", "Runs"], ["/memory", "Memory"], ["/settings", "Settings"]];

export default function App() {
  const path = useHash();
  const [open, setOpen] = useState(false);
  const { data: st } = useApi<Stats>("/stats", () => true, 4000);
  useEffect(() => { setOpen(false); window.scrollTo(0, 0); }, [path]);
  const run = path.match(/^\/runs\/(\d+)$/);
  const active = run ? "/runs" : path;
  let page;
  if (run) page = <RunDetail key={run[1]} id={run[1]} />;
  else if (path === "/new") page = <NewTask />;
  else if (path === "/runs") page = <Runs />;
  else if (path === "/memory") page = <MemoryPage />;
  else if (path === "/settings") page = <SettingsPage />;
  else page = <Overview />;
  return (
    <div className="app">
      <header className="topbar"><button className="btn btn-sm" aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)}>Menu</button><strong>AgentOps</strong></header>
      <nav id="nav" className={open ? "side open" : "side"} aria-label="Main">
        <div className="brand">AgentOps<small>Multi-agent orchestration</small></div>
        {NAV.map(([p, l]) => (
          <a key={p} href={`#${p}`} className={active === p ? "navlink on" : "navlink"} aria-current={active === p ? "page" : undefined}>
            {l}{p === "/runs" && !!st?.pending_approvals && <span className="badge" title="Pending approvals">{st.pending_approvals}</span>}</a>))}
        <div className="side-foot"><span className={`dotm ${st?.mode === "live" ? "live" : "demo"}`} />{st ? (st.mode === "live" ? "Live mode" : "Demo mode") : "Connecting"}</div>
      </nav>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <main>{page}</main>
    </div>
  );
}
