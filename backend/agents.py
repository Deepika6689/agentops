"""Supervisor planning, specialist agents and reviewer. Deterministic in demo mode; LLM-assisted when a key is set."""
import json, re
import db, llm, tools

LABEL = {"research": "Research", "analysis": "Data Analysis", "writing": "Writing"}
DATA_WORDS = r"\b(data|sales|revenue|region|growth|calculate|compute|average|percent|trend|metrics?|numbers?|analy[sz]e|analysis|total|sum)\b"
RESEARCH_WORDS = r"\b(research|explain|compare|overview|best practices?|what|how|why|summari[sz]e|agents?|llm|memory|tracing|approval|orchestration)\b"
SENSITIVE_WORDS = r"\b(email|send|delete|remove|publish|post|pay|payment|purchase|buy|deploy|transfer|share|upload|submit)\b"

class Ctx:
    def __init__(self, trace, agent, sub, parent, task, outputs, memories, attempt, feedback):
        self.t, self.agent, self.sub, self.parent = trace, agent, sub, parent
        self.task, self.outputs, self.memories, self.attempt, self.feedback = task, outputs, memories, attempt, feedback

    def tool(self, name, fn, **args):
        try:
            with self.t.step("tool", self.agent, name, input=args, subtask_id=self.sub["id"], parent=self.parent) as r:
                res = fn(**args); r["output"] = res
                return res, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def llm(self, system, prompt, fallback):
        if not llm.live_available():
            return fallback, True
        with self.t.step("llm", self.agent, f"LLM call ({llm.MODEL})", input={"prompt_chars": len(prompt)},
                         subtask_id=self.sub["id"], parent=self.parent) as r:
            text, sim, err = llm.generate(system, prompt, fallback)
            r["output"] = {"text": text[:1500], "error": err}; r["simulated"] = sim
            return text, sim

def plan_rules(task):
    steps = []
    has_expr = bool(tools.extract_expressions(task))
    wants_data = bool(re.search(DATA_WORDS, task, re.I)) or has_expr
    wants_research = bool(re.search(RESEARCH_WORDS, task, re.I)) or not wants_data
    if wants_research:
        steps.append(("research", "Gather background", "Search the knowledge base for notes relevant to the task and summarise them."))
    if wants_data:
        steps.append(("analysis", "Analyse data", "Evaluate any arithmetic in the task and summarise the sample dataset."))
    steps.append(("writing", "Write the report", "Combine the earlier outputs into a short structured report."))
    return steps

def make_plan(task, memories):
    steps, simulated, err = plan_rules(task), True, None
    if llm.live_available():
        mem = "\n".join(f"- {m['summary'][:200]}" for m in memories)
        text, sim, err = llm.generate(
            "You are a supervisor agent. Reply with ONLY a JSON array of 2-4 objects with keys agent (research|analysis|writing), title, instruction. The last item must be writing.",
            f"Task: {task}\nRelevant past runs:\n{mem or 'none'}", "")
        try:
            parsed = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
            ok = [(s["agent"], s["title"], s["instruction"]) for s in parsed if s.get("agent") in LABEL]
            if ok and ok[-1][0] == "writing": steps, simulated = ok[:4], sim
        except Exception:
            err = err or "Planner returned invalid JSON; used rule-based plan."
    return [{"id": f"s{i+1}", "agent": a, "title": t, "instruction": ins, "status": "pending", "attempts": 0, "confidence": None}
            for i, (a, t, ins) in enumerate(steps)], simulated, err

def research(c):
    broad = c.attempt > 0
    hits, err = c.tool("search_notes", tools.search_notes, query=c.task,
                       k=4 if broad else 2, min_overlap=1 if broad else 2)
    hits = hits or []
    lines = [f"- **{h['title']}**: {h['text']} (source: notes/{h['id']})" for h in hits] or ["- No matching notes were found in the sample knowledge base."]
    mem = [f"- Run #{m['run_id']}: {m['summary'][:180]}" for m in c.memories]
    base = "### Findings\n" + "\n".join(lines) + ("\n\n### Related past runs\n" + "\n".join(mem) if mem else "")
    text, sim = c.llm("You are a research specialist. Summarise only the supplied notes; do not invent sources.",
                      f"Task: {c.task}\nNotes:\n{base}", base)
    return {"text": text, "sources": len(hits), "tool_results": len(hits), "simulated": sim}

def analysis(c):
    parts, ok = ["### Calculations"], 0
    exprs = tools.extract_expressions(c.task)
    for e in exprs:
        v, err = c.tool("calculator", tools.calculator, expression=e)
        if err: parts.append(f"- `{e}` could not be evaluated ({err}).")
        else: parts.append(f"- `{e}` = **{v}**"); ok += 1
    if not exprs: parts.append("- No arithmetic expressions found in the task.")
    d, err = c.tool("analyze_sample_data", tools.analyze_sample_data)
    parts.append("### Sample dataset (illustrative, not real company data)")
    if d:
        ok += 1
        parts.append(f"- Total revenue: **${d['total_revenue_k']:,}k** across {len(d['by_quarter_k'])} quarters.")
        parts += [f"- {r}: ${v:,}k, Q1 to Q4 growth {d['q1_to_q4_growth_pct'][r]}%" for r, v in d["by_region_k"].items()]
        parts.append(f"- Top region: {d['top_region']}. Fastest growing: {d['fastest_growing']}.")
    else:
        parts.append(f"- Dataset analysis failed: {err}")
    base = "\n".join(parts)
    text, sim = c.llm("You are a data analyst. Restate the supplied figures clearly; do not add numbers.", f"Task: {c.task}\n{base}", base)
    return {"text": text, "sources": 0, "tool_results": ok, "simulated": sim}

def writing(c):
    prior = [(sid, o) for sid, o in c.outputs.items() if o.get("agent") != "writing"]
    title = c.task.strip().rstrip(".?!")
    title = title[:70] + ("..." if len(title) > 70 else "")
    body = []
    for sid, o in prior:
        body.append(f"## {o['title']}\n{o['text']}")
    first = next((l[2:].split(": ", 1)[-1][:160] for _, o in prior for l in o["text"].splitlines() if l.startswith("- ")), "See the sections below.")
    base = f"# Report: {title}\n\n## Summary\nThis report covers {len(prior)} specialist step(s). Key point: {first}\n\n" + "\n\n".join(body) + \
           "\n\n## Caveats\n- Findings come from a small built-in sample knowledge base and sample dataset, not live sources."
    if c.feedback: base += f"\n- Revision note applied: {c.feedback}"
    text, sim = c.llm("You are a writing specialist. Produce a concise markdown report with a Summary heading and one section per input. Keep all figures unchanged.",
                      f"Task: {c.task}\n\n{base}", base)
    stats, _ = c.tool("text_stats", tools.text_stats, text=text)
    return {"text": text, "sources": 0, "tool_results": 1 if stats else 0, "simulated": sim, "stats": stats}

AGENTS = {"research": research, "analysis": analysis, "writing": writing}

def review(sub, out, prior_count):
    t, checks = out["text"], []
    if sub["agent"] == "research":
        checks = [("At least 2 distinct sources", out["sources"] >= 2), ("Non-trivial length", len(t) >= 120)]
        fb = "Broaden the search: fewer than 2 sources were found."
    elif sub["agent"] == "analysis":
        checks = [("At least one tool result", out["tool_results"] >= 1), ("Contains figures", bool(re.search(r"\d", t)))]
        fb = "Use the calculator or dataset tool to produce at least one figure."
    else:
        checks = [("Has a Summary section", "## Summary" in t), ("Includes every prior section", prior_count == 0 or t.count("\n## ") >= prior_count),
                  ("Reasonable length", len(t) >= 200)]
        fb = "Add a Summary heading and include every specialist section."
    res = [{"name": n, "ok": bool(ok)} for n, ok in checks]
    score = round(sum(c["ok"] for c in res) / len(res), 2)
    return {"passed": score == 1, "score": score, "checks": res, "feedback": "" if score == 1 else fb}
