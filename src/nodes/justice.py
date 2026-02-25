"""Chief Justice: synthesis from judicial opinions with hardcoded rules. Report generation."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
)


def _ensure_opinion(o: Any) -> JudicialOpinion:
    if isinstance(o, JudicialOpinion):
        return o
    return JudicialOpinion.model_validate(o) if isinstance(o, dict) else o


def _ensure_evidence(e: Any) -> Evidence:
    if isinstance(e, Evidence):
        return e
    return Evidence.model_validate(e) if isinstance(e, dict) else e


def evidence_missing_node(state: AgentState) -> Dict[str, Any]:
    """
    Fallback node when critical evidence is missing.
    Produces conservative JudicialOpinions per dimension so that ChiefJustice
    can render a clear, failure-aware verdict.
    """
    dims = state.get("rubric_dimensions") or []
    opinions: List[JudicialOpinion] = []
    for d in dims:
        dim_id = d.get("id", "unknown")
        for judge in ("Prosecutor", "Defense", "TechLead"):
            opinions.append(
                JudicialOpinion(
                    judge=judge,  # type: ignore[arg-type]
                    criterion_id=dim_id,
                    score=1,
                    argument="Critical evidence for this criterion was missing; "
                    "automatic minimum score applied.",
                    cited_evidence=[],
                )
            )
    # Merge with any existing opinions via reducer
    return {"opinions": opinions}


def chief_justice_node(state: AgentState) -> Dict[str, Any]:
    """
    Synthesize opinions using rubric synthesis_rules. Deterministic resolution.
    Output: final_report (Markdown path or content) and state update.
    """
    raw_opinions = state.get("opinions") or []
    opinions = [_ensure_opinion(o) for o in raw_opinions]
    raw_evidences = state.get("evidences") or {}
    evidences = {k: [_ensure_evidence(e) for e in v] for k, v in raw_evidences.items()}
    dimensions = state.get("rubric_dimensions") or []
    synthesis_rules = _get_synthesis_rules(state)

    # Group opinions by criterion_id
    by_criterion: Dict[str, List[JudicialOpinion]] = {}
    for op in opinions:
        by_criterion.setdefault(op.criterion_id, []).append(op)

    criteria_results: List[CriterionResult] = []
    remediation_lines: List[str] = []

    for dim in dimensions:
        dim_id = dim.get("id", "")
        dim_name = dim.get("name", dim_id)
        ops = by_criterion.get(dim_id, [])
        prosecutor_ops = [o for o in ops if o.judge == "Prosecutor"]
        defense_ops = [o for o in ops if o.judge == "Defense"]
        tech_ops = [o for o in ops if o.judge == "TechLead"]

        p_score = prosecutor_ops[0].score if prosecutor_ops else 1
        d_score = defense_ops[0].score if defense_ops else 3
        t_score = tech_ops[0].score if tech_ops else 3

        # Rule of Security: security flaw caps at 3
        if synthesis_rules.get("security_override"):
            if any(
                "security" in (o.argument or "").lower()
                or "os.system" in (o.argument or "").lower()
                for o in prosecutor_ops
            ):
                p_score = min(p_score, 3)
                final_score = min(
                    _resolve_score(
                        p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops
                    ),
                    3,
                )
            else:
                final_score = _resolve_score(
                    p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops
                )
        else:
            final_score = _resolve_score(
                p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops
            )

        # Fact supremacy: if evidence says "not found" and Defense claimed depth, cap
        ev_list = evidences.get(dim_id) or []
        if synthesis_rules.get("fact_supremacy") and ev_list:
            if not any(e.found for e in ev_list) and d_score >= 4:
                final_score = min(final_score, 3)

        # Deeper PDF↔code cross-reference for report_accuracy
        if dim_id == "report_accuracy" and ev_list:
            mentioned_paths: List[str] = []
            repo_paths: List[str] = []
            for e in ev_list:
                text = (e.content or "") or ""
                if "src/" in text:
                    for line in text.splitlines():
                        line = line.strip()
                        if line.startswith("src/"):
                            if "architectural" in (e.goal or "").lower():
                                repo_paths.append(line)
                            else:
                                mentioned_paths.append(line)
            mentioned_set = set(mentioned_paths)
            repo_set = set(repo_paths)
            verified = sorted(mentioned_set & repo_set)
            hallucinated = sorted(mentioned_set - repo_set)
            # Penalize if many hallucinated paths and no verified ones
            if hallucinated and not verified:
                final_score = min(final_score, 2)

        dissent = _summarize_dissent(prosecutor_ops, defense_ops, tech_ops, dim_name)
        per_dim_remediation = _remediation_for_criterion(
            dim_id, dim_name, final_score, ev_list, prosecutor_ops, tech_ops
        )
        # Augment remediation with explicit verified vs hallucinated paths, if any
        if dim_id == "report_accuracy" and ev_list:
            if "verified" in locals() or "hallucinated" in locals():
                if verified:
                    per_dim_remediation.append("  - Verified report paths:")
                    for p in verified:
                        per_dim_remediation.append(f"    * {p}")
                if hallucinated:
                    per_dim_remediation.append("  - Hallucinated report paths (not in repo):")
                    for p in hallucinated:
                        per_dim_remediation.append(f"    * {p}")
        remediation_lines.extend(per_dim_remediation)

        criteria_results.append(
            CriterionResult(
                dimension_id=dim_id,
                dimension_name=dim_name,
                final_score=final_score,
                judge_opinions=ops,
                dissent_summary=dissent or None,
                remediation="\n".join(per_dim_remediation)
                if per_dim_remediation
                else f"No remediation required for {dim_name} (score {final_score}/5).",
            )
        )

    overall_score = (
        sum(c.final_score for c in criteria_results) / len(criteria_results)
        if criteria_results
        else 0.0
    )
    repo_url = state.get("repo_url", "")
    executive_summary = (
        f"Overall score {overall_score:.2f}/5 across {len(criteria_results)} criteria. "
        "See Criterion Breakdown for per-dimension verdicts, dissent, and remediation."
    )
    remediation_plan = "\n".join(remediation_lines) if remediation_lines else (
        "No major remediation required based on current criteria scores."
    )

    audit_report = AuditReport(
        repo_url=repo_url,
        executive_summary=executive_summary,
        overall_score=overall_score,
        criteria=criteria_results,
        remediation_plan=remediation_plan,
    )

    pdf_path = state.get("pdf_path", "")
    report_md = _render_report(audit_report, pdf_path)
    output_dir = state.get("output_dir") or "audit/report_onself_generated"
    report_path = write_report_to_file(report_md, output_dir)
    return {"final_report": audit_report, "final_report_path": report_path}


def _get_synthesis_rules(state: AgentState) -> Dict[str, str]:
    """Load synthesis_rules from rubric (passed in state)."""
    rules = state.get("rubric_synthesis_rules")
    if isinstance(rules, dict):
        return rules
    full = state.get("rubric_full")
    if isinstance(full, dict):
        return full.get("synthesis_rules", _default_synthesis_rules())
    return _default_synthesis_rules()


def _default_synthesis_rules() -> Dict[str, str]:
    return {
        "security_override": "Confirmed security flaws (e.g., shell injection in git tools) cap total score at 3.",
        "fact_supremacy": "Forensic evidence (facts) always overrules Judicial opinion (interpretation).",
        "dissent_requirement": "The Chief Justice must summarize why the Prosecutor and Defense disagreed in the final report.",
    }


def _resolve_score(p: int, d: int, t: int, prosecutor_ops: List[JudicialOpinion], defense_ops: List[JudicialOpinion], tech_ops: List[JudicialOpinion]) -> int:
    """Tie-breaker: Tech Lead carries highest weight for architecture/functionality; if variance > 2, lean on evidence."""
    variance = max(p, d, t) - min(p, d, t)
    if variance > 2:
        # Re-evaluate: use Tech Lead as tie-breaker
        return t
    # Average with Tech Lead weight
    return max(1, min(5, round((p + d + 2 * t) / 4)))


def _summarize_dissent(prosecutor_ops: List[JudicialOpinion], defense_ops: List[JudicialOpinion], tech_ops: List[JudicialOpinion], dim_name: str) -> str:
    p = prosecutor_ops[0] if prosecutor_ops else None
    d = defense_ops[0] if defense_ops else None
    t = tech_ops[0] if tech_ops else None
    parts = []
    if p and d:
        parts.append(f"Prosecutor argued: {p.argument[:200]}... (score {p.score}). Defense argued: {d.argument[:200]}... (score {d.score}).")
    if t:
        parts.append(f"Tech Lead: {t.argument[:150]}... (score {t.score}).")
    return " ".join(parts) if parts else f"No dissent summary for {dim_name}."


def _remediation_for_criterion(
    dim_id: str,
    dim_name: str,
    score: int,
    ev_list: List[Evidence],
    prosecutor_ops: List[JudicialOpinion],
    tech_ops: List[JudicialOpinion],
) -> List[str]:
    out: List[str] = []
    if score <= 2:
        out.append(f"**{dim_name}**: Address gaps identified by Prosecutor and Tech Lead.")
        if prosecutor_ops:
            out.append(f"  - Prosecutor: {prosecutor_ops[0].argument[:300]}")
        if tech_ops:
            out.append(f"  - Tech Lead remediation: {tech_ops[0].argument[:300]}")
        for e in ev_list:
            if not e.found and e.location:
                out.append(f"  - Ensure: {e.goal} at {e.location}")

        # Additional, dimension-specific, file-level hints
        if dim_id == "state_management_rigor":
            out.append(
                "  - In src/state.py, ensure AgentState uses Annotated reducers "
                "for evidences (operator.ior) and opinions (operator.add)."
            )
        if dim_id == "graph_orchestration":
            out.append(
                "  - In src/graph.py, wire Detectives and Judges with parallel fan-out/fan-in "
                "using StateGraph.add_edge / add_conditional_edges as per the rubric."
            )
        if dim_id == "safe_tool_engineering":
            out.append(
                "  - In src/tools/git_tools.py, keep git operations inside tempfile.TemporaryDirectory "
                "and avoid raw os.system; rely on subprocess.run with validation."
            )
        if dim_id == "structured_output_enforcement":
            out.append(
                "  - In src/nodes/judges.py, ensure all LLM calls use with_structured_output(JudicialOpinion) "
                "or bind_tools to enforce JSON schema with retry on failure."
            )
        if dim_id == "chief_justice_synthesis":
            out.append(
                "  - In src/nodes/justice.py, implement deterministic if/else rules for security_override, "
                "fact_supremacy, functionality_weight, and variance_re_evaluation."
            )
    return out


def _render_report(report: AuditReport, pdf_path: str) -> str:
    """Serialize an AuditReport into Markdown."""
    import os

    repo_url = report.repo_url
    lines = [
        "# Automaton Auditor – Audit Report",
        "",
        f"**Repository:** {repo_url}",
        f"**Report PDF:** {pdf_path}",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
    ]

    # Optional LangSmith trace link (if provided via environment)
    trace_url = os.getenv("LANGSMITH_RUN_URL")
    if trace_url:
        lines.append(f"LangSmith trace: {trace_url}")
        lines.append("")

    lines.extend(
        [
            "## Criterion Breakdown",
            "",
        ]
    )
    for c in report.criteria:
        lines.append(f"### {c.dimension_name} — Score: {c.final_score}/5")
        # Per-judge scores (if present)
        p_score = next((o.score for o in c.judge_opinions if o.judge == "Prosecutor"), None)
        d_score = next((o.score for o in c.judge_opinions if o.judge == "Defense"), None)
        t_score = next((o.score for o in c.judge_opinions if o.judge == "TechLead"), None)
        if any(s is not None for s in (p_score, d_score, t_score)):
            lines.append("")
            lines.append(
                f"- Prosecutor: {p_score or '-'} | Defense: {d_score or '-'} | Tech Lead: {t_score or '-'}"
            )
        lines.append("")
        if c.dissent_summary:
            lines.append("**Dissent:** " + c.dissent_summary)
        else:
            lines.append("**Dissent:** No significant disagreement recorded.")
        lines.append("")
        if c.remediation:
            lines.append("**Remediation:**")
            lines.append(c.remediation)
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Remediation Plan")
    lines.append("")
    lines.extend(report.remediation_plan.splitlines())
    lines.append("")
    return "\n".join(lines)


def write_report_to_file(report_content: str, output_dir: str) -> str:
    """Write report Markdown to output_dir; return path."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    fname = f"audit_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.md"
    out_path = path / fname
    out_path.write_text(report_content, encoding="utf-8")
    return str(out_path)
