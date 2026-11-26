import { FormEvent, useState } from "react";
import { api, fmtDur, fmtTime, go, isActive, Memory, RunRow, Settings, Stats, useApi } from "./api";
import { ConfirmButton, Empty, ErrorBox, Loading, Pill } from "./ui";

const DemoNote = () => (
  <div className="alert alert-info"><strong>Demo mode.</strong> No API key is configured, so agent text is produced by deterministic logic and labelled Simulated.
    Tracing, tools, approvals, memory and persistence are real.</div>);

export function Overview() {
  const { data: s, error, loading, reload } = useApi<Stats>("/stats", () => true, 3000);
  const { data: runs } = useApi<RunRow[]>("/runs", () => true, 3000);
  if (loading) return <Loading />;
  if (error || !s) return <ErrorBox msg={error ?? "Unable to load"} retry={reload} />;
  const max = Math.max(1, ...s.by_agent.map(a => a.n));
  const metrics: [string, string, string][] = [
    ["Total runs", String(s.total_runs), `${s.active} active`],
    ["Success rate", s.success_rate == null ? "-" : `${s.success_rate}%`, `${s.completed} completed, ${s.failed} failed, ${s.rejected} rejected`],
    ["Approval requests", String(s.approval_requests), `${s.pending_approvals} pending`],
    ["Average duration", fmtDur(s.avg_duration_ms), "Active time, excluding approval waits"]];
  return (
    <div className="stack">
      <div className="page-head"><h1>Overview</h1><button className="btn btn-primary" onClick={() => go("/new")}>New task</button></div>
      {s.mode === "demo" && <DemoNote />}
      <div className="metrics">{metrics.map(([l, v, sub]) => <div className="card metric" key={l}><div className="muted">{l}</div><div className="mval">{v}</div><div className="muted small">{sub}</div></div>)}</div>
      {s.total_runs === 0 ? <div className="card"><Empty title="No runs yet" action={<button className="btn btn-primary" onClick={() => go("/new")}>Start your first task</button>}>
        Metrics come from real executions only. Nothing on this page is sample data.</Empty></div> :
        <div className="split">
          <section className="card"><div className="card-head"><h2>Recent runs</h2><a href="#/runs">View all</a></div>
            <RunsTable rows={(runs ?? []).slice(0, 6)} /></section>
          <section className="card"><div className="card-head"><h2>Agent activity</h2></div>
            {s.by_agent.map(a => <div className="bar" key={a.agent}><span>{a.agent}</span><div><i style={{ width: `${(a.n / max) * 100}%` }} /></div><span className="mono">{a.n}</span></div>)}
            <div className="muted small" style={{ marginTop: 12 }}>{s.retries} reviewer retries, {s.memories} saved memories</div></section>
        </div>}
    </div>
  );
}

const EXAMPLES = [
  "Compare supervisor and swarm patterns for multi-agent systems and summarize best practices",
  "Analyze sample sales growth by region and compute 1450*12 + 380",
  "Explain how approval gates and tracing work in agent systems, then email the summary to my team",
  "Describe the migratory patterns of arctic terns",
];

export function NewTask() {
  const [task, setTask] = useState(""); const [req, setReq] = useState(true);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  const { data: st } = useApi<Stats>("/stats");
  const valid = task.trim().length >= 8;
  const submit = async (e: FormEvent) => {
    e.preventDefault(); if (!valid) return;
    setBusy(true); setErr(null);
    try { const r = await api<{ id: number }>("/runs", { method: "POST", body: { task, require_approval: req } }); go(`/runs/${r.id}`); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="stack narrow">
      <div className="page-head"><h1>New task</h1></div>
      {st?.mode === "demo" && <DemoNote />}
      <form className="card stack" onSubmit={submit}>
        <label className="field"><span>Describe the task</span>
          <textarea rows={5} maxLength={2000} value={task} onChange={e => setTask(e.target.value)} placeholder="What should the agents work on?" disabled={busy} /></label>
        <div className="row between muted small"><span>{task.trim().length < 8 && task.length > 0 ? "Enter at least 8 characters." : "The supervisor splits this into subtasks."}</span><span>{task.length}/2000</span></div>
        <label className="check"><input type="checkbox" checked={req} onChange={e => setReq(e.target.checked)} />
          <span>Require my approval before saving the report<small>Approval is also requested automatically for sensitive wording or low-confidence results.</small></span></label>
        {err && <ErrorBox msg={err} />}
        <div className="row"><button className="btn btn-primary" disabled={!valid || busy}>{busy ? "Starting" : "Start run"}</button></div>
      </form>
      <section className="card"><div className="card-head"><h2>Example tasks</h2></div>
        <div className="stack tight">{EXAMPLES.map(x => <button key={x} className="example" onClick={() => setTask(x)}>{x}</button>)}</div></section>
    </div>
  );
}

function RunsTable({ rows }: { rows: RunRow[] }) {
  return (
    <div className="scroll"><table className="tbl clickable"><thead><tr><th>Run</th><th>Task</th><th>Status</th><th>Started</th><th>Duration</th></tr></thead>
      <tbody>{rows.map(r => (
        <tr key={r.id} tabIndex={0} onClick={() => go(`/runs/${r.id}`)} onKeyDown={e => e.key === "Enter" && go(`/runs/${r.id}`)}>
          <td className="mono">#{r.id}</td><td className="ttask">{r.task}</td><td><Pill s={r.status} /></td><td>{fmtTime(r.created_at)}</td><td className="mono">{fmtDur(r.duration_ms)}</td></tr>))}</tbody></table></div>);
}

export function Runs() {
  const [filter, setFilter] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const { data, error, loading, reload } = useApi<RunRow[]>(`/runs${filter ? `?status=${filter}` : ""}`, d => d.some(r => isActive(r.status)), 1500);
  const clear = async () => { try { await api("/runs", { method: "DELETE" }); setErr(null); reload(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="stack">
      <div className="page-head"><h1>Runs</h1>
        <div className="row"><select aria-label="Filter by status" value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="">All statuses</option>{["running", "awaiting_approval", "completed", "rejected", "failed"].map(s => <option key={s} value={s}>{s.replace("_", " ")}</option>)}</select>
          <button className="btn btn-primary" onClick={() => go("/new")}>New task</button></div></div>
      {err && <ErrorBox msg={err} />}
      {loading ? <Loading /> : error ? <ErrorBox msg={error} retry={reload} /> :
        !data?.length ? <div className="card"><Empty title={filter ? "No runs with this status" : "No runs yet"} action={!filter && <button className="btn btn-primary" onClick={() => go("/new")}>Start a task</button>}>
          {filter ? "Try a different filter." : "Executions you start are saved here so you can reopen them later."}</Empty></div> :
          <div className="card"><RunsTable rows={data} />
            <div className="row end" style={{ marginTop: 12 }}><ConfirmButton label="Clear history" confirmLabel="Delete all runs" onConfirm={clear} /></div></div>}
    </div>
  );
}

export function MemoryPage() {
  const [q, setQ] = useState(""); const [term, setTerm] = useState("");
  const { data, error, loading, reload } = useApi<Memory[]>(`/memories${term ? `?q=${encodeURIComponent(term)}` : ""}`);
  const del = async (id: number) => { await api(`/memories/${id}`, { method: "DELETE" }); reload(); };
  const clear = async () => { await api("/memories", { method: "DELETE" }); reload(); };
  return (
    <div className="stack">
      <div className="page-head"><h1>Memory</h1>{!!data?.length && !term && <ConfirmButton label="Delete all" confirmLabel="Delete all memories" onConfirm={clear} />}</div>
      <p className="muted">Summaries of completed runs. The supervisor retrieves the closest matches before planning a new task.</p>
      <form className="row" onSubmit={e => { e.preventDefault(); setTerm(q.trim()); }}>
        <input type="search" placeholder="Test retrieval with a task description" value={q} onChange={e => setQ(e.target.value)} aria-label="Search memories" />
        <button className="btn">Search</button>{term && <button type="button" className="btn" onClick={() => { setQ(""); setTerm(""); }}>Clear</button>}</form>
      {loading ? <Loading /> : error ? <ErrorBox msg={error} retry={reload} /> :
        !data?.length ? <div className="card"><Empty title={term ? "No similar memories" : "No memories yet"}>{term ? "Nothing matched that description." : "A summary is saved automatically when a run completes."}</Empty></div> :
          <div className="stack tight">{data.map(m => (
            <article className="card" key={m.id}>
              <div className="card-head"><h2 className="small-h">{m.task}</h2><button className="btn btn-sm btn-danger" onClick={() => del(m.id)}>Delete</button></div>
              <p>{m.summary}</p>
              <div className="muted small">From <a href={`#/runs/${m.run_id}`}>run {m.run_id}</a>, saved {fmtTime(m.created_at)}{m.score != null && `, match score ${m.score}`}</div></article>))}</div>}
    </div>
  );
}

export function SettingsPage() {
  const { data, error, loading, reload } = useApi<Settings>("/settings");
  const [err, setErr] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const save = async (body: object) => { try { await api("/settings", { method: "PUT", body }); setErr(null); reload(); } catch (e: any) { setErr(e.message); } };
  const clear = async () => { setClearing(true); try { await api("/runs", { method: "DELETE" }); setErr(null); } catch (e: any) { setErr(e.message); } setClearing(false); };
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox msg={error ?? "Unable to load"} retry={reload} />;
  return (
    <div className="stack narrow">
      <div className="page-head"><h1>Settings</h1></div>
      {err && <ErrorBox msg={err} />}
      <section className="card stack">
        <div className="card-head"><h2>Model</h2><span className={`tag ${data.mode === "demo" ? "tag-sim" : "tag-live"}`}>{data.mode === "demo" ? "Demo mode" : "Live"}</span></div>
        <div className="kv"><span>Provider</span><span>{data.provider} ({data.model})</span></div>
        <div className="kv"><span>API key</span><span>{data.key_configured ? "Configured on the server" : "Not set. Add ANTHROPIC_API_KEY to backend/.env and restart."}</span></div>
        <label className="check"><input type="checkbox" checked={data.force_demo} onChange={e => save({ force_demo: e.target.checked })} />
          <span>Force demo mode<small>Use simulated responses even when an API key is present.</small></span></label>
      </section>
      <section className="card stack">
        <div className="card-head"><h2>Workflow</h2></div>
        <label className="field"><span>Maximum attempts per subtask</span>
          <select value={data.max_attempts} onChange={e => save({ max_attempts: Number(e.target.value) })}>{[1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></label>
        <div className="muted small">The reviewer can request a retry until this limit, then accepts the output with low confidence and asks for approval.</div>
      </section>
      <section className="card stack">
        <div className="card-head"><h2>Data</h2></div>
        <div className="kv"><span>Database</span><code>{data.db_path}</code></div>
        <div className="kv"><span>Exports folder</span><code>{data.export_dir}</code></div>
        <div className="row"><ConfirmButton label="Clear run history" confirmLabel="Delete all runs" onConfirm={clear} disabled={clearing} /></div>
      </section>
    </div>
  );
}
