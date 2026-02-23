# Automaton Auditor

Production-grade LangGraph "Digital Courtroom" for autonomous auditing of a GitHub repository and its architectural PDF report.

## Architecture

- **Layer 1 (Detectives):** RepoInvestigator (code + AST + git), DocAnalyst (PDF), VisionInspector (optional diagrams). Run in parallel; output structured `Evidence`.
- **Layer 2 (Judges):** Prosecutor, Defense, Tech Lead. Each evaluates evidence per rubric dimension with distinct personas; output structured `JudicialOpinion` via `with_structured_output`.
- **Layer 3:** Chief Justice synthesizes opinions using hardcoded synthesis rules and writes the final Markdown audit report.

## Setup

- **Python:** 3.11+
- **Package manager:** `uv` (recommended) or `pip`

```bash
# With uv
uv sync

# Or with pip
pip install -r requirements.txt
# Or editable: pip install -e .
```

- **Environment:** Copy `.env.example` to `.env` and set at least one of:
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`

Optional (LangSmith tracing):

- `LANGCHAIN_TRACING_V2=true`
- `LANGCHAIN_API_KEY=...`
- `LANGCHAIN_PROJECT=automaton-auditor`

## Run

```bash
# From project root
python -m src.run_audit --repo-url https://github.com/org/repo --pdf-path /path/to/report.pdf

# Optional
python -m src.run_audit --repo-url URL --pdf-path PATH --output-dir audit/report_onself_generated --rubric-path rubric/week2_rubric.json
```

With `uv` and the installed script:

```bash
uv run run-audit --repo-url URL --pdf-path PATH
```

## Outputs

- **Audit report:** Markdown file written to `--output-dir` (default: `audit/report_onself_generated/`), e.g. `audit_YYYYMMDD_HHMM.md`.
- **LangSmith:** If tracing is enabled, open your LangSmith project to inspect the reasoning loop (Detectives → Judges → Chief Justice).

## Repository layout

- `src/state.py` – Pydantic `Evidence` / `JudicialOpinion` and `AgentState` (with reducers).
- `src/graph.py` – LangGraph definition (parallel Detectives → EvidenceAggregator → parallel Judges → ChiefJustice).
- `src/nodes/detectives.py` – RepoInvestigator, DocAnalyst, VisionInspector, EvidenceAggregator.
- `src/nodes/judges.py` – Prosecutor, Defense, Tech Lead (structured output).
- `src/nodes/justice.py` – Chief Justice synthesis and report generation.
- `src/tools/` – Git (sandboxed clone, log), AST (state/graph analysis), PDF (ingest + chunk query).
- `rubric/week2_rubric.json` – Machine-readable rubric (dimensions + synthesis rules).

## Audit folders (deliverables)

- `audit/report_bypeer_received/` – Place peer audit reports here.
- `audit/report_onpeer_generated/` – Reports your agent produced for peers.
- `audit/report_onself_generated/` – Self-audit reports.
- `audit/langsmith_logs/` – Export or link LangSmith traces here.

## Docker (optional)

```bash
docker build -t automaton-auditor .
docker run --env-file .env -v "$(pwd)/audit:/app/audit" automaton-auditor run-audit --repo-url URL --pdf-path /path/to/report.pdf
```

(Ensure the PDF is mounted or available inside the container.)
