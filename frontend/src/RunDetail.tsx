import { useMemo, useState } from "react";
import { api, Approval, fmtDur, fmtTime, go, isActive, Run, Step, useApi } from "./api";
import { Empty, ErrorBox, Json, Loading, Md, Pill, SimBadge } from "./ui";

function ApprovalPanel({ run, a, reload }: { run: Run; a: Approval; reload: () => void }) {
  const original = a.proposed.content;
  const [text, setText] = useState(original);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const edited = text !== original;
  const send = async (decision: "approve" | "reject" | "modify") => {
    setBusy(true); setErr(null);
    try { await api(`/runs/${run.id}/approval`, { method: "POST", body: { decision, content: decision === "modify" ? text : undefined } }); reload(); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <section className="card approval" aria-label="Approval required">
      <div className="card-head"><h2>Approval required</h2><Pill s="awaiting_approval" /></div>
      <p className="muted">The workflow is paused. Nothing has been written yet.</p>
      <ul className="reasons">{a.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      <div className="kv"><span>Proposed action</span><code>Save report to {a.proposed.path}</code></div>
      <label className="field"><span>Report content (editable)</span>
        <textarea rows={10} value={text} onChange={e => setText(e.target.value)} disabled={busy} spellCheck={false} /></label>
      {err && <ErrorBox msg={err} />}
      <div className="row wrap">
        <button className="btn btn-primary" disabled={busy || edited} onClick={() => send("approve")}>Approve</button>
        <button className="btn" disabled={busy || !edited || !text.trim()} onClick={() => send("modify")}>Save changes and approve</button>
        <button className="btn btn-danger" disabled={busy} onClick={() => send("reject")}>Reject</button>
      </div>
    </section>
  );
}

function Outputs({ run }: { run: Run }) {
  const tabs = useMemo(() => {
    const t: { key: string; label: string; text: string; simulated: boolean }[] = [];
    run.plan.forEach(s => {
      const st = [...run.steps].reverse().find(x => x.kind === "agent" && x.subtask_id === s.id && x.status === "done");
      if (st?.output?.text) t.push({ key: s.id, label: s.title, text: st.output.text, simulated: st.simulated });
    });
    if (run.result) t.push({ key: "final", label: "Final report", text: run.result, simulated: run.mode === "demo" });
    return t;
  }, [run]);
  const [sel, setSel] = useState<string | null>(null);
  const cur = tabs.find(t => t.key === sel) ?? tabs[tabs.length - 1];
  return (
    <section className="card">
      <div className="card-head"><h2>Outputs</h2>{cur && <SimBadge simulated={cur.simulated} />}</div>
      {!tabs.length ? <p className="muted">Outputs appear here as each agent finishes.</p> : <>
        <div className="tabs" role="tablist">{tabs.map(t => <button key={t.key} role="tab" aria-selected={cur?.key === t.key} className={cur?.key === t.key ? "tab on" : "tab"} onClick={() => setSel(t.key)}>{t.label}</button>)}</div>
        <Md text={cur!.text} /></>}
    </section>
  );
}

const KIND: Record<string, string> = { agent: "Agent", tool: "Tool", review: "Review", memory: "Memory", approval: "Approval", llm: "LLM" };

function Trace({ run }: { run: Run }) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [kind, setKind] = useState("all");
  const now = Date.now() / 1000;
  const steps = run.steps;
  const t0 = steps.length ? Math.min(...steps.map(s => s.started_at)) : 0;
  const t1 = Math.max(t0 + 0.001, ...steps.map(s => s.ended_at ?? (isActive(run.status) || s.status === "waiting" ? now : s.started_at)));
  const shown = steps.filter(s => kind === "all" || s.kind === kind);
  const toggle = (id: number) => setOpen(o => { const n = new Set(o); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const kinds = ["all", ...Array.from(new Set(steps.map(s => s.kind)))];
  return (
    <section className="card">
      <div className="card-head"><h2>Trace explorer</h2><span className="muted">{steps.length} steps over {fmtDur(Math.round((t1 - t0) * 1000))}</span></div>
      <div className="chips" role="group" aria-label="Filter steps">{kinds.map(k => <button key={k} className={kind === k ? "chip on" : "chip"} onClick={() => setKind(k)}>{k === "all" ? "All" : KIND[k] ?? k}</button>)}</div>
      {!shown.length ? <p className="muted">No steps recorded yet.</p> :
        <div className="trace">{shown.map((s: Step) => {
          const isOpen = open.has(s.id);
          const left = ((s.started_at - t0) / (t1 - t0)) * 100;
          const width = Math.max(0.8, (((s.ended_at ?? now) - s.started_at) / (t1 - t0)) * 100);
          return (
            <div key={s.id} className={`trow ${s.parent_id ? "child" : ""} st-${s.status}`}>
              <button className="thead" aria-expanded={isOpen} onClick={() => toggle(s.id)}>
                <span className="caret">{isOpen ? "v" : ">"}</span>
                <span className="tname"><span className="tkind">{KIND[s.kind] ?? s.kind}</span>{s.name}</span>
                <span className="tmeta"><Pill s={s.status} /><span className="mono dur">{fmtDur(s.duration_ms)}</span></span>
                <span className="gantt" aria-hidden><i style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }} /></span>
              </button>
              {isOpen && <div className="tbody">
                <div className="kvgrid">
                  <div><span>Agent</span>{s.agent}</div><div><span>Started</span>{fmtTime(s.started_at)}</div>
                  <div><span>Duration</span>{fmtDur(s.duration_ms)}</div><div><span>Source</span>{s.simulated ? "Simulated output" : "Computed / live"}</div>
                </div>
                {s.error && <div className="alert alert-error">{s.error}</div>}
                {s.input != null && <><div className="sub">Input</div><Json v={s.input} /></>}
                {s.output != null && <><div className="sub">Output</div><Json v={s.output} /></>}
              </div>}
            </div>);
        })}</div>}
    </section>
  );
}

export default function RunDetail({ id }: { id: string }) {
  const { data: run, error, loading, reload } = useApi<Run>(`/runs/${id}`, r => isActive(r.status) || r.status === "awaiting_approval");
  if (loading) return <Loading label="Loading run" />;
  if (error || !run) return <ErrorBox msg={error ?? "Run not found"} retry={reload} />;
  const agentSteps = run.steps.filter(s => s.kind === "agent" || s.kind === "tool" || s.kind === "review");
  const byAgent = Object.entries(agentSteps.reduce<Record<string, { steps: number; tools: number; ms: number }>>((m, s) => {
    const a = m[s.agent] ??= { steps: 0, tools: 0, ms: 0 };
    if (s.kind === "agent") { a.steps++; a.ms += s.duration_ms ?? 0; } else if (s.kind === "tool") a.tools++;
    return m;
  }, {}));
  const running = run.steps.find(s => s.kind === "agent" && s.status === "running");
  return (
    <div className="stack">
      <div className="crumbs"><a href="#/runs">Runs</a> / Run {run.id}</div>
      <section className="card">
        <div className="card-head"><h1 className="task">{run.task}</h1><Pill s={run.status} /></div>
        <div className="meta">
          <span>Started {fmtTime(run.created_at)}</span><span>Active time {fmtDur(run.duration_ms)}</span>
          <span className={`tag ${run.mode === "demo" ? "tag-sim" : "tag-live"}`}>{run.mode === "demo" ? "Demo mode: simulated agent text" : "Live LLM"}</span>
        </div>
        {run.error && <ErrorBox msg={run.error} />}
        {isActive(run.status) && <Loading label={running ? `${running.name}` : "Working"} />}
        {run.status === "rejected" && <p className="muted">You rejected the proposed action, so no file was written. The report is still shown below.</p>}
      </section>
      <div className="split">
        <div className="stack">
          {run.approval?.status === "pending" && run.status === "awaiting_approval" && <ApprovalPanel key={run.approval.id} run={run} a={run.approval} reload={reload} />}
          {run.approval && run.approval.status !== "pending" && <div className="alert alert-info">Approval decision: <strong>{run.approval.status}</strong> at {fmtTime(run.approval.decided_at)}.</div>}
          <Outputs run={run} />
          <Trace run={run} />
        </div>
        <aside className="stack">
          <section className="card">
            <div className="card-head"><h2>Workflow progress</h2></div>
            {!run.plan.length ? <p className="muted">The supervisor is planning.</p> :
              <ol className="steps">{run.plan.map(s => (
                <li key={s.id} className={`wf wf-${s.status}`}>
                  <span className="dot" /><div><div className="wf-title">{s.title}</div>
                    <div className="muted small">{s.agent} agent{s.attempts > 1 ? `, ${s.attempts} attempts` : ""}{s.confidence != null ? `, review score ${s.confidence}` : ""}</div></div>
                  <Pill s={s.status} /></li>))}</ol>}
          </section>
          <section className="card">
            <div className="card-head"><h2>Agent activity</h2></div>
            {!byAgent.length ? <p className="muted">No activity yet.</p> :
              <table className="tbl"><thead><tr><th>Agent</th><th>Runs</th><th>Tools</th><th>Time</th></tr></thead>
                <tbody>{byAgent.map(([a, v]) => <tr key={a}><td>{a}</td><td>{v.steps}</td><td>{v.tools}</td><td className="mono">{fmtDur(v.ms)}</td></tr>)}</tbody></table>}
          </section>
        </aside>
      </div>
    </div>
  );
}
