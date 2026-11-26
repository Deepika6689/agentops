"""SQLite persistence: runs, trace steps, approvals, memories, settings."""
import json, math, os, re, sqlite3, threading, time
from collections import Counter
from contextlib import contextmanager

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("AGENTOPS_DB", os.path.join(BASE, "agentops.db"))
CKPT_PATH = os.environ.get("AGENTOPS_CKPT", os.path.join(BASE, "checkpoints.db"))
EXPORT_DIR = os.environ.get("AGENTOPS_EXPORTS", os.path.join(BASE, "exports"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL, status TEXT NOT NULL,
  mode TEXT NOT NULL, require_approval INTEGER NOT NULL, plan TEXT DEFAULT '[]', result TEXT, error TEXT,
  created_at REAL NOT NULL, finished_at REAL, duration_ms INTEGER);
CREATE TABLE IF NOT EXISTS steps(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, parent_id INTEGER,
  subtask_id TEXT, kind TEXT, agent TEXT, name TEXT, status TEXT, input TEXT, output TEXT, error TEXT,
  simulated INTEGER DEFAULT 0, started_at REAL, ended_at REAL, duration_ms INTEGER);
CREATE INDEX IF NOT EXISTS idx_steps_run ON steps(run_id);
CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, status TEXT NOT NULL,
  reasons TEXT, proposed TEXT, final TEXT, created_at REAL, decided_at REAL);
CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, task TEXT, summary TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)

def q(sql, args=(), one=False):
    with _lock, conn() as c:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    return (rows[0] if rows else None) if one else rows

def x(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid

def dumps(v):
    return None if v is None else json.dumps(v, default=str)

def loads(v):
    try:
        return json.loads(v) if v is not None else None
    except (TypeError, ValueError):
        return v

# ---- settings
DEFAULTS = {"force_demo": "0", "max_attempts": "2"}
def get_setting(k):
    r = q("SELECT value FROM settings WHERE key=?", (k,), one=True)
    return r["value"] if r else DEFAULTS[k]

def set_setting(k, v):
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))

# ---- runs
def create_run(task, mode, require_approval):
    return x("INSERT INTO runs(task,status,mode,require_approval,created_at) VALUES(?,?,?,?,?)",
             (task, "queued", mode, int(require_approval), time.time()))

def set_run(run_id, **f):
    if not f: return
    cols = ", ".join(f"{k}=?" for k in f)
    x(f"UPDATE runs SET {cols} WHERE id=?", (*f.values(), run_id))

def get_run(run_id):
    r = q("SELECT * FROM runs WHERE id=?", (run_id,), one=True)
    if r: r["plan"] = loads(r["plan"]) or []
    return r

# ---- trace
class Trace:
    def __init__(self, run_id): self.run_id = run_id

    def begin(self, kind, agent, name, input=None, subtask_id=None, parent=None, status="running"):
        return x("INSERT INTO steps(run_id,parent_id,subtask_id,kind,agent,name,status,input,started_at) VALUES(?,?,?,?,?,?,?,?,?)",
                 (self.run_id, parent, subtask_id, kind, agent, name, status, dumps(input), time.time()))

    def end(self, sid, status, output=None, error=None, simulated=False):
        now = time.time()
        s = q("SELECT started_at FROM steps WHERE id=?", (sid,), one=True)
        x("UPDATE steps SET status=?,output=?,error=?,simulated=?,ended_at=?,duration_ms=? WHERE id=?",
          (status, dumps(output), error, int(simulated), now, int((now - s["started_at"]) * 1000), sid))

    @contextmanager
    def step(self, kind, agent, name, input=None, subtask_id=None, parent=None):
        sid = self.begin(kind, agent, name, input, subtask_id, parent)
        rec = {"id": sid, "output": None, "simulated": False, "status": "done"}
        try:
            yield rec
        except Exception as e:
            self.end(sid, "failed", rec["output"], f"{type(e).__name__}: {e}", rec["simulated"])
            raise
        self.end(sid, rec["status"], rec["output"], None, rec["simulated"])

def run_steps(run_id):
    rows = q("SELECT * FROM steps WHERE run_id=? ORDER BY id", (run_id,))
    for r in rows:
        r["input"], r["output"], r["simulated"] = loads(r["input"]), loads(r["output"]), bool(r["simulated"])
    return rows

# ---- approvals
def get_approval(run_id):
    a = q("SELECT * FROM approvals WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,), one=True)
    if a:
        for k in ("reasons", "proposed", "final"): a[k] = loads(a[k])
    return a

# ---- memory (lexical TF-IDF retrieval; see README for why ChromaDB is not used)
STOP = set("a an the and or of to in on for with is are be this that it as at by from how what why do does can i we you my our your please about into".split())
def tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in STOP and len(t) > 1]

def memory_search(query, k=3, min_score=0.12):
    mems = q("SELECT * FROM memories")
    if not mems: return []
    docs = [Counter(tokens(m["task"] + " " + m["summary"])) for m in mems]
    df = Counter(t for d in docs for t in d)
    n = len(docs)
    idf = lambda t: math.log((n + 1) / (df.get(t, 0) + 1)) + 1
    qv = Counter(tokens(query))
    def vec(c): return {t: (1 + math.log(v)) * idf(t) for t, v in c.items()}
    qw = vec(qv); qn = math.sqrt(sum(v * v for v in qw.values())) or 1
    out = []
    for m, d in zip(mems, docs):
        dw = vec(d); dn = math.sqrt(sum(v * v for v in dw.values())) or 1
        s = sum(qw[t] * dw.get(t, 0) for t in qw) / (qn * dn)
        if s >= min_score: out.append({**m, "score": round(s, 3)})
    return sorted(out, key=lambda m: -m["score"])[:k]
