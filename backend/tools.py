"""Safe, limited demo tools. No code execution, no network, no filesystem access outside exports."""
import ast, operator, os, re
from collections import Counter
from db import EXPORT_DIR, tokens

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}

def calculator(expression: str):
    if len(expression) > 100: raise ValueError("Expression too long")
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(r) > 100: raise ValueError("Exponent too large")
            return _OPS[type(n.op)](l, r)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS: return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("Unsupported expression")
    return round(ev(ast.parse(expression.strip().replace("^", "**"), mode="eval")), 6)

def extract_expressions(text):
    out = []
    for m in re.finditer(r"(?<![\w.\-])\(?\d[\d\s.+\-*/%()^]*\d\)?", text):
        e = m.group(0).strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e) or not re.search(r"\d\s*[-+*/^%]\s*[\d(]", e): continue
        if e not in out: out.append(e)
    return out[:3]

def text_stats(text: str):
    words = re.findall(r"\w+", text)
    sentences = [s for s in re.split(r"[.!?]+\s", text) if s.strip()]
    top = Counter(tokens(text)).most_common(5)
    return {"words": len(words), "sentences": len(sentences),
            "avg_sentence_words": round(len(words) / max(1, len(sentences)), 1), "top_terms": [t for t, _ in top]}

# Sample dataset (illustrative, not real company data): revenue in $k by region and quarter.
SALES = [{"region": r, "quarter": f"Q{i+1}", "revenue_k": v, "units": u} for r, vals in {
    "North America": [(1210, 5400), (1295, 5720), (1410, 6100), (1580, 6650)],
    "Europe": [(860, 3900), (905, 4050), (950, 4300), (1040, 4620)],
    "Asia-Pacific": [(540, 2600), (640, 3000), (790, 3600), (960, 4400)],
    "Latin America": [(210, 1100), (220, 1150), (215, 1130), (240, 1260)]}.items() for i, (v, u) in enumerate(vals)]

def analyze_sample_data():
    by_region, by_q = Counter(), Counter()
    for r in SALES:
        by_region[r["region"]] += r["revenue_k"]; by_q[r["quarter"]] += r["revenue_k"]
    total = sum(by_q.values())
    growth = {}
    for reg in by_region:
        q1 = next(r["revenue_k"] for r in SALES if r["region"] == reg and r["quarter"] == "Q1")
        q4 = next(r["revenue_k"] for r in SALES if r["region"] == reg and r["quarter"] == "Q4")
        growth[reg] = round((q4 - q1) / q1 * 100, 1)
    return {"dataset": "sample_sales_2025 (illustrative)", "total_revenue_k": total, "by_region_k": dict(by_region),
            "by_quarter_k": dict(by_q), "q1_to_q4_growth_pct": growth,
            "top_region": by_region.most_common(1)[0][0], "fastest_growing": max(growth, key=growth.get)}

NOTES = [
 {"id": "agents-01", "title": "Supervisor pattern", "tags": "orchestration supervisor agents multi-agent planning delegation",
  "text": "A supervisor agent decomposes a goal into ordered subtasks and routes each to a specialist. Keeping planning separate from execution makes failures easier to localize and lets each specialist use a narrow prompt and toolset."},
 {"id": "agents-02", "title": "Reviewer and retry loops", "tags": "reviewer quality retry revision evaluation agents",
  "text": "A reviewer step checks a specialist's output against explicit criteria before the workflow continues. Bounded retries with concrete feedback usually beat unbounded loops, which can burn budget without improving results."},
 {"id": "obs-01", "title": "Tracing agent runs", "tags": "observability tracing trace logging debugging timeline latency",
  "text": "Useful traces record every agent step and tool call with inputs, outputs, status, errors and timing. A timeline view makes slow steps and repeated retries obvious, and is the first place to look when output quality drops."},
 {"id": "hitl-01", "title": "Human approval gates", "tags": "approval human-in-the-loop safety review sensitive actions oversight",
  "text": "Pause before actions that are sensitive, irreversible or low-confidence. Show the proposed action in full and let the person approve, reject or edit it. The workflow should resume from a checkpoint rather than restart."},
 {"id": "mem-01", "title": "Memory for agents", "tags": "memory retrieval semantic past tasks context rag",
  "text": "Storing short summaries of completed tasks lets later runs retrieve relevant context. Summaries should be inspectable and deletable by the user, since stale or wrong memories can mislead future plans."},
 {"id": "sec-01", "title": "Tool safety", "tags": "security safety tools sandbox prompt injection permissions calculator",
  "text": "Give agents the smallest toolset that works. Prefer deterministic tools such as calculators and parsers over code execution, validate all tool inputs, and treat retrieved text as untrusted data rather than instructions."},
 {"id": "cost-01", "title": "Cost and latency", "tags": "cost latency tokens budget performance evaluation metrics",
  "text": "Multi-agent workflows multiply model calls. Track duration and call counts per run, cap retries, and use cheaper models for routine specialist steps while reserving stronger models for planning and review."},
 {"id": "eval-01", "title": "Evaluating agent systems", "tags": "evaluation testing metrics success rate quality benchmarks",
  "text": "Measure success rate, approval rate, retries per step and end-to-end duration across runs. Small fixed task sets run on every change catch regressions that spot checks miss."},
]

def search_notes(query: str, k: int = 2, min_overlap: int = 2):
    qt = set(tokens(query)); hits = []
    for n in NOTES:
        ov = len(qt & set(tokens(n["title"] + " " + n["tags"] + " " + n["text"])))
        if ov >= min_overlap: hits.append((ov, n))
    hits.sort(key=lambda h: -h[0])
    return [{"id": n["id"], "title": n["title"], "text": n["text"], "overlap": ov} for ov, n in hits[:k]]

def save_report(path_name: str, content: str):
    """The only side-effecting tool: writes a markdown file inside the exports directory."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(path_name)) or "report.md"
    full = os.path.join(EXPORT_DIR, name)
    with open(full, "w", encoding="utf-8") as f: f.write(content)
    return {"path": f"exports/{name}", "bytes": len(content.encode())}
