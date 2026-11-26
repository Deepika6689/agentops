import os, time
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
import db, graph, llm

db.init()
for r in db.q("SELECT id FROM runs WHERE status IN ('queued','running')"):
    db.set_run(r["id"], status="failed", error="Server restarted while this run was in progress.", finished_at=time.time())
    for s in db.q("SELECT id FROM steps WHERE run_id=? AND status='running'", (r["id"],)):
        db.Trace(r["id"]).end(s["id"], "failed", error="Server restarted")

app = FastAPI(title="AgentOps")

class NewRun(BaseModel):
    task: str = Field(min_length=8, max_length=2000)
    require_approval: bool = True

class Decision(BaseModel):
    decision: Literal["approve", "reject", "modify"]
    content: Optional[str] = Field(default=None, max_length=50000)

class SettingsIn(BaseModel):
    force_demo: Optional[bool] = None
    max_attempts: Optional[int] = Field(default=None, ge=1, le=4)

def mode(): return "live" if llm.live_available() else "demo"

@app.post("/api/runs", status_code=201)
def create_run(b: NewRun):
    task = " ".join(b.task.split())
    if len(task) < 8: raise HTTPException(422, "Task must be at least 8 characters.")
    rid = db.create_run(task, mode(), b.require_approval)
    graph.start(rid, task, b.require_approval)
    return db.get_run(rid)

@app.get("/api/runs")
def list_runs(status: Optional[str] = None):
    rows = db.q("SELECT id,task,status,mode,created_at,finished_at,duration_ms FROM runs" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 200", (status,) if status else ())
    return rows

@app.get("/api/runs/{rid}")
def get_run(rid: int):
    r = db.get_run(rid)
    if not r: raise HTTPException(404, "Run not found")
    return {**r, "steps": db.run_steps(rid), "approval": db.get_approval(rid)}

@app.post("/api/runs/{rid}/approval")
def decide(rid: int, d: Decision):
    r, a = db.get_run(rid), db.get_approval(rid)
    if not r: raise HTTPException(404, "Run not found")
    if not a or a["status"] != "pending" or r["status"] != "awaiting_approval":
        raise HTTPException(409, "This run has no pending approval.")
    if d.decision == "modify" and not (d.content and d.content.strip()):
        raise HTTPException(422, "Provide the modified content.")
    db.set_run(rid, status="running")
    graph.resume(rid, d.decision, d.content)
    return {"ok": True}

@app.delete("/api/runs/{rid}")
def delete_run(rid: int):
    r = db.get_run(rid)
    if not r: raise HTTPException(404, "Run not found")
    if r["status"] in ("queued", "running"): raise HTTPException(409, "Wait for the run to finish first.")
    for t in ("steps", "approvals"): db.x(f"DELETE FROM {t} WHERE run_id=?", (rid,))
    db.x("DELETE FROM runs WHERE id=?", (rid,))
    return {"ok": True}

@app.get("/api/stats")
def stats():
    runs = db.q("SELECT status,duration_ms FROM runs")
    done = [r for r in runs if r["status"] == "completed"]
    failed = sum(r["status"] == "failed" for r in runs)
    durs = [r["duration_ms"] for r in done if r["duration_ms"] is not None]
    by_agent = db.q("SELECT agent, COUNT(*) n, COALESCE(SUM(duration_ms),0) ms FROM steps WHERE kind='agent' GROUP BY agent ORDER BY n DESC")
    return {"total_runs": len(runs), "completed": len(done), "failed": failed,
            "rejected": sum(r["status"] == "rejected" for r in runs),
            "active": sum(r["status"] in ("queued", "running", "awaiting_approval") for r in runs),
            "success_rate": round(len(done) / (len(done) + failed) * 100, 1) if (len(done) + failed) else None,
            "approval_requests": db.q("SELECT COUNT(*) n FROM approvals", one=True)["n"],
            "pending_approvals": db.q("SELECT COUNT(*) n FROM approvals WHERE status='pending'", one=True)["n"],
            "avg_duration_ms": int(sum(durs) / len(durs)) if durs else None,
            "retries": db.q("SELECT COUNT(*) n FROM steps WHERE kind='review' AND output LIKE '%\"verdict\": \"retry\"%'", one=True)["n"],
            "by_agent": by_agent, "memories": db.q("SELECT COUNT(*) n FROM memories", one=True)["n"], "mode": mode()}

@app.get("/api/memories")
def memories(q: Optional[str] = None):
    if q and q.strip(): return db.memory_search(q, 20, min_score=0.01)
    return db.q("SELECT * FROM memories ORDER BY id DESC")

@app.delete("/api/memories/{mid}")
def del_memory(mid: int):
    db.x("DELETE FROM memories WHERE id=?", (mid,)); return {"ok": True}

@app.delete("/api/memories")
def clear_memories():
    db.x("DELETE FROM memories"); return {"ok": True}

@app.get("/api/settings")
def get_settings():
    return {"mode": mode(), "provider": "anthropic", "model": llm.MODEL, "key_configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "force_demo": db.get_setting("force_demo") == "1", "max_attempts": int(db.get_setting("max_attempts")),
            "export_dir": db.EXPORT_DIR, "db_path": db.DB_PATH}

@app.put("/api/settings")
def put_settings(s: SettingsIn):
    if s.force_demo is not None: db.set_setting("force_demo", int(s.force_demo))
    if s.max_attempts is not None: db.set_setting("max_attempts", s.max_attempts)
    return get_settings()

@app.delete("/api/runs")
def clear_runs():
    if db.q("SELECT 1 FROM runs WHERE status IN ('queued','running','awaiting_approval')"):
        raise HTTPException(409, "Finish or resolve active runs first.")
    for t in ("steps", "approvals", "runs"): db.x(f"DELETE FROM {t}")
    return {"ok": True}

DIST = os.path.join(os.path.dirname(db.BASE), "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")
    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
