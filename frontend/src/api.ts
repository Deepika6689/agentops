import { useEffect, useRef, useState, useCallback } from "react";

export type Sub = { id: string; agent: string; title: string; instruction: string; status: string; attempts: number; confidence: number | null };
export type Step = { id: number; parent_id: number | null; subtask_id: string | null; kind: string; agent: string; name: string; status: string;
  input: any; output: any; error: string | null; simulated: boolean; started_at: number; ended_at: number | null; duration_ms: number | null };
export type Approval = { id: number; status: string; reasons: string[]; proposed: { type: string; path: string; content: string }; final: any; created_at: number; decided_at: number | null };
export type RunRow = { id: number; task: string; status: string; mode: string; created_at: number; finished_at: number | null; duration_ms: number | null };
export type Run = RunRow & { plan: Sub[]; result: string | null; error: string | null; require_approval: number; steps: Step[]; approval: Approval | null };
export type Stats = { total_runs: number; completed: number; failed: number; rejected: number; active: number; success_rate: number | null; approval_requests: number;
  pending_approvals: number; avg_duration_ms: number | null; retries: number; by_agent: { agent: string; n: number; ms: number }[]; memories: number; mode: string };
export type Memory = { id: number; run_id: number; task: string; summary: string; created_at: number; score?: number };
export type Settings = { mode: string; provider: string; model: string; key_configured: boolean; force_demo: boolean; max_attempts: number; export_dir: string; db_path: string };

export async function api<T = any>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch("/api" + path, { method: init?.method ?? "GET", headers: init?.body ? { "Content-Type": "application/json" } : undefined, body: init?.body ? JSON.stringify(init.body) : undefined });
  } catch {
    throw new Error("Cannot reach the backend. Check that the server is running on port 8000.");
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try { const j = await res.json(); const d = j.detail; msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e: any) => e.msg).join("; ") : msg; } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

/** Loads data and re-polls while `active(data)` is true. */
export function useApi<T>(path: string, active?: (d: T) => boolean, every = 1000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const act = useRef(active); act.current = active;
  const load = useCallback(async () => {
    try { setData(await api<T>(path)); setError(null); } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, [path]);
  useEffect(() => { setLoading(true); setData(null); load(); }, [load]);
  useEffect(() => {
    if (!data || !act.current?.(data)) return;
    const t = setTimeout(load, every);
    return () => clearTimeout(t);
  }, [data, load, every]);
  return { data, error, loading, reload: load };
}

export function useHash() {
  const [h, setH] = useState(location.hash.slice(1) || "/");
  useEffect(() => { const f = () => setH(location.hash.slice(1) || "/"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  return h;
}
export const go = (p: string) => { location.hash = p; };

export const fmtDur = (ms: number | null | undefined) => ms == null ? "-" : ms < 1000 ? `${ms} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)} m ${Math.round((ms % 60000) / 1000)} s`;
export const fmtTime = (t: number | null | undefined) => t ? new Date(t * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "-";
export const isActive = (s: string) => ["queued", "running"].includes(s);
