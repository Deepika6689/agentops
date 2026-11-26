import { ReactNode, useState } from "react";

export const STATUS_LABEL: Record<string, string> = { queued: "Queued", running: "Running", awaiting_approval: "Awaiting approval", completed: "Completed", failed: "Failed",
  rejected: "Rejected", pending: "Pending", done: "Done", done_low_confidence: "Done, low confidence", revising: "Revising", waiting: "Waiting", skipped: "Skipped" };

export const Pill = ({ s }: { s: string }) => <span className={`pill pill-${s}`}>{STATUS_LABEL[s] ?? s}</span>;
export const SimBadge = ({ simulated }: { simulated: boolean }) => <span className={`tag ${simulated ? "tag-sim" : "tag-live"}`}>{simulated ? "Simulated" : "Live LLM"}</span>;

export const Empty = ({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) => (
  <div className="empty"><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>);
export const Loading = ({ label = "Loading" }: { label?: string }) => <div className="loading" role="status"><span className="spinner" />{label}</div>;
export const ErrorBox = ({ msg, retry }: { msg: string; retry?: () => void }) => (
  <div className="alert alert-error" role="alert"><span>{msg}</span>{retry && <button className="btn btn-sm" onClick={retry}>Retry</button>}</div>);

export function ConfirmButton({ label, confirmLabel, onConfirm, disabled }: { label: string; confirmLabel: string; onConfirm: () => void; disabled?: boolean }) {
  const [armed, setArmed] = useState(false);
  return armed
    ? <span className="row"><button className="btn btn-danger btn-sm" onClick={() => { setArmed(false); onConfirm(); }}>{confirmLabel}</button><button className="btn btn-sm" onClick={() => setArmed(false)}>Cancel</button></span>
    : <button className="btn btn-sm" disabled={disabled} onClick={() => setArmed(true)}>{label}</button>;
}

function inline(t: string): ReactNode[] {
  return t.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code> : p);
}
/** Minimal markdown: headings, bullets, quotes, bold, code. */
export function Md({ text }: { text: string }) {
  const out: ReactNode[] = []; let list: string[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={out.length}>{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; } };
  text.split("\n").forEach(line => {
    if (line.startsWith("- ")) return void list.push(line.slice(2));
    flush();
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) out.push(<div key={out.length} className={`md-h md-h${h[1].length}`}>{inline(h[2])}</div>);
    else if (line.startsWith("> ")) out.push(<blockquote key={out.length}>{inline(line.slice(2))}</blockquote>);
    else if (line.trim()) out.push(<p key={out.length}>{inline(line)}</p>);
  });
  flush();
  return <div className="md">{out}</div>;
}

export const Json = ({ v }: { v: unknown }) => <pre className="json">{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</pre>;
