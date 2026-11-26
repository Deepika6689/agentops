# AgentOps: multi-agent orchestration platform

A supervisor agent splits a task into ordered subtasks, hands them to specialist agents, has a reviewer check each result,
pauses for human approval before saving a report, remembers past tasks, and records a full execution trace you can explore in a dashboard.

## Run it

Requirements: Python 3.11+ and Node 18+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example backend/.env            # optional: add ANTHROPIC_API_KEY for live mode
(cd frontend && npm install && npm run build)
cd backend && uvicorn main:app --port 8000
```

Open http://localhost:8000. For frontend development run `npm run dev` in `frontend/` (http://localhost:5173, proxies `/api` to port 8000).
Tests: `cd backend && PYTHONPATH=. pytest tests`.

## Architecture

```
React + TS (Vite)  --/api-->  FastAPI  -->  LangGraph workflow  -->  SQLite
                                              memory -> plan -> execute <-> review -> approval gate -> finalize
```

- **Workflow** (`backend/graph.py`): LangGraph `StateGraph`. `execute` and `review` loop with bounded retries (Settings, default 2 attempts).
  The approval gate uses LangGraph `interrupt()` with a SQLite checkpointer, so a paused run survives a server restart.
- **Agents** (`backend/agents.py`): Supervisor (rule-based plan), Research, Data Analysis, Writing, and a rule-based Reviewer with explicit checks.
- **Tools** (`backend/tools.py`): safe calculator (AST-evaluated, no `eval`), text statistics, sample-data analysis, knowledge-base search, and `save_report`,
  the only side effect, which writes one Markdown file into `backend/exports/`.
- **Trace** (`backend/db.py`): every agent step, tool call, review, memory operation and approval is stored with timestamps, status, errors and duration.
- **Memory**: summaries of completed runs, retrieved by TF-IDF cosine similarity before planning. Users can search and delete them.

## Implemented vs simulated

| Area | Status |
|---|---|
| LangGraph orchestration, retries, approval pause/resume, persistence, trace, memory, history, metrics | Implemented and tested |
| Agent text in demo mode (no API key) | Simulated by deterministic logic, labelled "Simulated" in the UI |
| Research sources | A small built-in sample knowledge base, not the web |
| Data analysis | A built-in illustrative sales dataset, not real data |
| Live mode (`ANTHROPIC_API_KEY`) | Wired for planning and agent text via the Anthropic Messages API. A successful live call has **not** been tested; the failure path (bad key falls back to demo output) has |
| Semantic memory | Lexical TF-IDF, not embeddings. ChromaDB was skipped because its default embedding model needs a network download |
| Docker | Not included (not verified in this environment) |

Safety: the app never executes arbitrary code, makes no external actions, and the API key stays on the server.
Requests that mention sending email, deleting, paying, etc. trigger an approval, but the demo cannot perform those actions; it only offers to save the report locally.
