import os, tempfile, time
_d = tempfile.mkdtemp()
os.environ.update(AGENTOPS_DB=f"{_d}/t.db", AGENTOPS_CKPT=f"{_d}/c.db", AGENTOPS_EXPORTS=f"{_d}/ex")
os.environ.pop("ANTHROPIC_API_KEY", None)
from fastapi.testclient import TestClient
import main, tools

c = TestClient(main.app)

def wait(rid, until=("completed", "failed", "rejected", "awaiting_approval")):
    for _ in range(200):
        r = c.get(f"/api/runs/{rid}").json()
        if r["status"] in until: return r
        time.sleep(0.1)
    raise AssertionError(f"timeout, status={r['status']}")

def start(task, approval=True):
    return c.post("/api/runs", json={"task": task, "require_approval": approval}).json()["id"]

def test_validation():
    assert c.post("/api/runs", json={"task": "hi"}).status_code == 422

def test_calculator_is_safe():
    assert tools.calculator("12*7+3") == 87
    for bad in ("__import__('os')", "2**9999", "open('x')"):
        try: tools.calculator(bad); raise AssertionError(bad)
        except (ValueError, SyntaxError): pass

def test_approval_modify_and_export():
    rid = wait(start("Compare supervisor patterns and analyze sales growth; compute 12*7+3"))["id"]
    assert c.get(f"/api/runs/{rid}").json()["status"] == "awaiting_approval"
    assert not os.path.exists(f"{_d}/ex/run-{rid}.md")           # nothing written before approval
    assert c.post(f"/api/runs/{rid}/approval", json={"decision": "modify"}).status_code == 422
    c.post(f"/api/runs/{rid}/approval", json={"decision": "modify", "content": "# Edited\n## Summary\nok"})
    r = wait(rid, ("completed", "failed"))
    assert r["status"] == "completed" and open(f"{_d}/ex/run-{rid}.md").read().startswith("# Edited")
    assert c.post(f"/api/runs/{rid}/approval", json={"decision": "approve"}).status_code == 409

def test_reject_writes_nothing_and_memory_is_used():
    rid = wait(start("Explain supervisor patterns for multi-agent systems"))["id"]
    mem = next(s for s in c.get(f"/api/runs/{rid}").json()["steps"] if s["name"].startswith("Retrieve"))
    assert mem["output"]["matches"], "earlier completed run should be retrieved"
    c.post(f"/api/runs/{rid}/approval", json={"decision": "reject"})
    assert wait(rid, ("rejected",))["status"] == "rejected" and not os.path.exists(f"{_d}/ex/run-{rid}.md")

def test_retry_and_tool_error_are_traced():
    r = wait(start("What is 10/0 and 5+5 for quarterly planning?", approval=False))
    verdicts = [s["output"]["verdict"] for s in r["steps"] if s["kind"] == "review"]
    assert "retry" in verdicts and r["status"] == "completed"
    assert any(s["kind"] == "tool" and s["status"] == "failed" and "division" in s["error"] for s in r["steps"])

def test_low_confidence_forces_approval():
    r = wait(start("Describe the migratory patterns of arctic terns", approval=False))
    assert r["status"] == "awaiting_approval" and "low-confidence" in r["approval"]["reasons"][0]

def test_memory_delete_and_stats():
    mems = c.get("/api/memories").json(); assert mems
    assert c.delete(f"/api/memories/{mems[0]['id']}").status_code == 200
    s = c.get("/api/stats").json(); assert s["total_runs"] >= 4 and s["mode"] == "demo"
