"""LangGraph workflow: memory -> plan -> (execute -> review)* -> approval gate -> finalize."""
import sqlite3, threading, time
from typing import TypedDict
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
import agents, db, llm, tools
from db import Trace

class S(TypedDict, total=False):
    run_id: int; task: str; require_approval: bool; memories: list; plan: list; idx: int; attempt: int
    feedback: str; outputs: dict; route: str; needs_approval: bool; approval_step: int; report: str
    reasons: list; decision: dict; low_conf: list

def save_plan(s): db.set_run(s["run_id"], plan=db.dumps(s["plan"]))

def n_memory(s):
    t = Trace(s["run_id"]); db.set_run(s["run_id"], status="running")
    with t.step("memory", "supervisor", "Retrieve similar past tasks", input={"query": s["task"]}) as r:
        hits = db.memory_search(s["task"], 3)
        r["output"] = {"matches": [{"id": h["id"], "run_id": h["run_id"], "score": h["score"], "task": h["task"]} for h in hits]}
    return {"memories": hits}

def n_plan(s):
    t = Trace(s["run_id"])
    with t.step("agent", "supervisor", "Plan subtasks", input={"task": s["task"], "memories_used": len(s["memories"])}) as r:
        plan, sim, err = agents.make_plan(s["task"], s["memories"])
        r["output"] = {"subtasks": [{k: p[k] for k in ("id", "agent", "title")} for p in plan], "note": err}; r["simulated"] = sim
    s = {**s, "plan": plan}; save_plan(s)
    return {"plan": plan, "idx": 0, "attempt": 0, "feedback": "", "outputs": {}, "low_conf": []}

def n_execute(s):
    t, st = Trace(s["run_id"]), s["plan"][s["idx"]]
    st["status"], st["attempts"] = "running", s["attempt"] + 1; save_plan(s)
    with t.step("agent", st["agent"], f"{agents.LABEL[st['agent']]}: {st['title']}", subtask_id=st["id"],
                input={"instruction": st["instruction"], "attempt": s["attempt"] + 1, "reviewer_feedback": s["feedback"] or None}) as r:
        c = agents.Ctx(t, st["agent"], st, r["id"], s["task"], s["outputs"], s["memories"], s["attempt"], s["feedback"])
        out = agents.AGENTS[st["agent"]](c)
        out.update(agent=st["agent"], title=st["title"])
        r["output"] = {"text": out["text"], "tool_results": out["tool_results"], "sources": out["sources"]}; r["simulated"] = out["simulated"]
    return {"outputs": {**s["outputs"], st["id"]: out}}

def n_review(s):
    t, st = Trace(s["run_id"]), s["plan"][s["idx"]]
    out = s["outputs"][st["id"]]
    max_attempts = int(db.get_setting("max_attempts"))
    with t.step("review", "reviewer", f"Review: {st['title']}", subtask_id=st["id"], input={"attempt": s["attempt"] + 1}) as r:
        v = agents.review(st, out, len(s["outputs"]) - 1)
        st["confidence"] = v["score"]
        if v["passed"]: verdict = "accepted"
        elif s["attempt"] + 1 < max_attempts: verdict = "retry"
        else: verdict = "accepted_low_confidence"
        r["output"] = {**v, "verdict": verdict}
    low = list(s["low_conf"])
    if verdict == "retry":
        st["status"] = "revising"; save_plan(s)
        return {"route": "retry", "attempt": s["attempt"] + 1, "feedback": v["feedback"]}
    st["status"] = "done" if verdict == "accepted" else "done_low_confidence"
    if verdict != "accepted": low.append(st["title"])
    save_plan(s)
    nxt = s["idx"] + 1
    return {"route": "next" if nxt < len(s["plan"]) else "finish", "idx": nxt, "attempt": 0, "feedback": "", "low_conf": low}

def after_review(s): return "execute" if s["route"] in ("retry", "next") else "prepare"

def n_prepare(s):
    t, rid = Trace(s["run_id"]), s["run_id"]
    report = next(o["text"] for o in reversed(list(s["outputs"].values())) if o["agent"] == "writing")
    reasons = []
    if s["require_approval"]: reasons.append("Policy: saving a report requires approval for this run.")
    import re
    m = re.search(agents.SENSITIVE_WORDS, s["task"], re.I)
    if m: reasons.append(f"The task mentions a sensitive action (\"{m.group(0)}\"). This demo cannot perform it; the only action available is saving the report locally.")
    if s["low_conf"]: reasons.append("Reviewer accepted low-confidence output for: " + ", ".join(s["low_conf"]) + ".")
    action = {"type": "save_report", "path": f"exports/run-{rid}.md", "content": report}
    if not reasons:
        sid = t.begin("approval", "system", "Approval gate", input={"action": action["type"]})
        t.end(sid, "skipped", {"result": "No approval needed by policy."})
        return {"report": report, "needs_approval": False, "reasons": []}
    sid = t.begin("approval", "system", "Waiting for human approval", input={"reasons": reasons, "action": action["type"]}, status="waiting")
    x = db.x("INSERT INTO approvals(run_id,status,reasons,proposed,created_at) VALUES(?,?,?,?,?)",
             (rid, "pending", db.dumps(reasons), db.dumps(action), time.time()))
    db.set_run(rid, status="awaiting_approval")
    return {"report": report, "needs_approval": True, "reasons": reasons, "approval_step": sid}

def after_prepare(s): return "await_approval" if s["needs_approval"] else "finalize"

def n_await(s):
    d = interrupt({"run_id": s["run_id"], "action": "save_report"})   # graph pauses here until resumed
    t, rid = Trace(s["run_id"]), s["run_id"]
    decision = d["decision"]
    status = {"approve": "approved", "reject": "rejected", "modify": "modified"}[decision]
    final = {"type": "save_report", "path": f"exports/run-{rid}.md", "content": d.get("content") or s["report"]}
    db.x("UPDATE approvals SET status=?,final=?,decided_at=? WHERE run_id=? AND status='pending'",
         (status, db.dumps(final), time.time(), rid))
    t.end(s["approval_step"], "done", {"decision": status})
    db.set_run(rid, status="running")
    return {"decision": {"decision": decision, "content": final["content"]}}

def n_finalize(s):
    t, rid = Trace(s["run_id"]), s["run_id"]
    d = s.get("decision") or {"decision": "approve", "content": s["report"]}
    content, status = d["content"], "completed"
    if d["decision"] == "reject":
        status = "rejected"
        sid = t.begin("tool", "system", "save_report", input={"path": f"run-{rid}.md"})
        t.end(sid, "skipped", {"result": "Rejected by user; nothing was written."})
    else:
        with t.step("tool", "system", "save_report", input={"path": f"run-{rid}.md", "bytes": len(content)}) as r:
            r["output"] = tools.save_report(f"run-{rid}.md", content)
        def first_point(text):
            for l in text.splitlines():
                if l.startswith("- ") and not any(b in l for b in ("could not be", "No matching", "No arithmetic")):
                    return l[2:].split(": ", 1)[-1][:110]
            return "no usable findings"
        summary = " | ".join(f"{o['title']}: {first_point(o['text'])}" for o in s["outputs"].values() if o["agent"] != "writing")
        with t.step("memory", "supervisor", "Save task summary to memory", input={"task": s["task"]}) as r:
            mid = db.x("INSERT INTO memories(run_id,task,summary,created_at) VALUES(?,?,?,?)", (rid, s["task"], summary or content[:200], time.time()))
            r["output"] = {"memory_id": mid, "summary": summary}
    run = db.get_run(rid)
    wait = 0
    a = db.get_approval(rid)
    if a and a["decided_at"]: wait = a["decided_at"] - a["created_at"]
    now = time.time()
    db.set_run(rid, status=status, result=content, finished_at=now, duration_ms=int(max(0, now - run["created_at"] - wait) * 1000))
    return {}

def build():
    g = StateGraph(S)
    for name, fn in [("memory", n_memory), ("plan", n_plan), ("execute", n_execute), ("review", n_review),
                     ("prepare", n_prepare), ("await_approval", n_await), ("finalize", n_finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "memory"); g.add_edge("memory", "plan"); g.add_edge("plan", "execute"); g.add_edge("execute", "review")
    g.add_conditional_edges("review", after_review, {"execute": "execute", "prepare": "prepare"})
    g.add_conditional_edges("prepare", after_prepare, {"await_approval": "await_approval", "finalize": "finalize"})
    g.add_edge("await_approval", "finalize"); g.add_edge("finalize", END)
    return g.compile(checkpointer=SqliteSaver(sqlite3.connect(db.CKPT_PATH, check_same_thread=False)))

_graph = None
def graph():
    global _graph
    if _graph is None: _graph = build()
    return _graph

def _drive(run_id, payload):
    cfg = {"configurable": {"thread_id": str(run_id)}, "recursion_limit": 100}
    try:
        graph().invoke(payload, cfg)
    except Exception as e:
        db.set_run(run_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=time.time())
        # close any step left open so the trace never shows a stuck spinner
        for s in db.q("SELECT id FROM steps WHERE run_id=? AND status IN ('running','waiting')", (run_id,)):
            Trace(run_id).end(s["id"], "failed", error="Run aborted")

def start(run_id, task, require_approval):
    threading.Thread(target=_drive, args=(run_id, {"run_id": run_id, "task": task, "require_approval": require_approval}), daemon=True).start()

def resume(run_id, decision, content=None):
    threading.Thread(target=_drive, args=(run_id, Command(resume={"decision": decision, "content": content})), daemon=True).start()