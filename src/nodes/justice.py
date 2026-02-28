"""Chief Justice: synthesis from judicial opinions with hardcoded rules. Report generation."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from pydantic import ValidationError

from src.state import (
    AgentState,
    AuditReport,
    CriterionResult,
    Evidence,
    JudicialOpinion,
)

logger = logging.getLogger(__name__)


# Security flaw indicators: phrases/patterns in Prosecutor arguments that trigger
# the security override (cap score at 3). Covers common vulnerabilities in tool code.
_SECURITY_INDICATORS: List[str] = [
    "security",
    "os.system",
    "os.popen",
    "shell=true",
    "shell=True",
    "command injection",
    "shell injection",
    "code injection",
    "path traversal",
    "unsanitized",
    "unsanitized input",
    "eval(",
    "exec(",
    "pickle.loads",
    "yaml.unsafe_load",
    "live working directory",
    "arbitrary code execution",
    "privilege escalation",
    "no sandbox",
    "no tempfile",
]


def _prosecutor_cites_security_flaw(argument: str) -> bool:
    """True if Prosecutor argument indicates a confirmed security vulnerability."""
    text = (argument or "").lower()
    return any(indicator.lower() in text for indicator in _SECURITY_INDICATORS)


def _ensure_opinion(o: Any, fallback_judge: str = "TechLead", fallback_criterion: str = "unknown") -> JudicialOpinion | None:
    """Normalize raw opinion to JudicialOpinion; return None if unrecoverable."""
    if isinstance(o, JudicialOpinion):
        return _safe_opinion(o)
    if isinstance(o, dict):
        try:
            op = JudicialOpinion.model_validate(o)
            return _safe_opinion(op)
        except (ValidationError, TypeError) as e:
            logger.warning("Malformed opinion dict: %s", e)
    return None


def _safe_opinion(op: JudicialOpinion) -> JudicialOpinion:
    """Clamp score to [1,5] and ensure required fields."""
    score = getattr(op, "score", 3)
    if not isinstance(score, (int, float)):
        score = 3
    score = max(1, min(5, int(score)))
    return JudicialOpinion(
        judge=op.judge,
        criterion_id=op.criterion_id or "unknown",
        score=score,
        argument=op.argument or "No argument provided.",
        cited_evidence=op.cited_evidence or [],
    )


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
    opinions: List[JudicialOpinion] = []
    for o in raw_opinions:
        op = _ensure_opinion(o)
        if op is not None:
            opinions.append(op)
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

        # Default scores when judges did not produce opinions (partial/empty)
        p_score = prosecutor_ops[0].score if prosecutor_ops else 1
        d_score = defense_ops[0].score if defense_ops else 3
        t_score = tech_ops[0].score if tech_ops else 3
        # Clamp any out-of-range scores from malformed opinions
        p_score = max(1, min(5, int(p_score) if p_score is not None else 1))
        d_score = max(1, min(5, int(d_score) if d_score is not None else 3))
        t_score = max(1, min(5, int(t_score) if t_score is not None else 3))

        # Rule of Security: security flaw caps at 3
        if synthesis_rules.get("security_override"):
            if any(_prosecutor_cites_security_flaw(o.argument or "") for o in prosecutor_ops):
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
        # RepoInvestigator: location = repo path (dir), content = enumerated src/* paths
        # DocAnalyst: location = pdf_path (.pdf), content = paths mentioned in report
        if dim_id == "report_accuracy" and ev_list:
            mentioned_paths: List[str] = []
            repo_paths: List[str] = []
            for e in ev_list:
                text = (e.content or "") or ""
                if not text or "src/" not in text:
                    continue
                is_from_pdf = (e.location or "").lower().endswith(".pdf")
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("src/"):
                        if is_from_pdf:
                            mentioned_paths.append(line)
                        else:
                            repo_paths.append(line)
            mentioned_set = set(mentioned_paths)
            repo_set = set(repo_paths)
            verified = sorted(mentioned_set & repo_set)
            hallucinated = sorted(mentioned_set - repo_set)
            # Penalize if many hallucinated paths and no verified ones
            if hallucinated and not verified:
                final_score = min(final_score, 2)

        dissent = (
            f"*No judge opinions received for {dim_name}; conservative default score applied.*"
            if not ops
            else _summarize_dissent(prosecutor_ops, defense_ops, tech_ops, dim_name)
        )
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
    executive_summary = _build_executive_summary(criteria_results, overall_score)
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


def _build_executive_summary(
    criteria_results: List[CriterionResult], overall_score: float
) -> str:
    """Build a detailed executive summary with score distribution and highlights."""
    n = len(criteria_results)
    if n == 0:
        return "No criteria evaluated."
    # Score distribution
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for c in criteria_results:
        s = int(c.final_score)
        if s in counts:
            counts[s] += 1
    dist_parts = [f"{s}×{counts[s]}" for s in (5, 4, 3, 2, 1) if counts[s] > 0]
    dist_str = ", ".join(dist_parts) if dist_parts else "N/A"
    # Strengths (4–5)
    strengths = [c.dimension_name for c in criteria_results if c.final_score >= 4]
    # Weaknesses (1–2)
    weaknesses = [c.dimension_name for c in criteria_results if c.final_score <= 2]
    lines = [
        "| Metric | Value |",
        "|:-------|:------|",
        f"| **Overall Score** | **{overall_score:.2f}/5** |",
        f"| Criteria Evaluated | {n} |",
        f"| Score Distribution | {dist_str} |",
        "",
        "#### Strengths (score ≥ 4)",
        "",
    ]
    if strengths:
        lines.extend([
            "| Criterion |",
            "|:----------|",
        ])
        for s in strengths:
            lines.append(f"| ✓ {s} |")
    else:
        lines.append("*None identified.*")
    lines.extend([
        "",
        "#### Weaknesses (score ≤ 2)",
        "",
    ])
    if weaknesses:
        lines.extend([
            "| Criterion |",
            "|:----------|",
        ])
        for w in weaknesses:
            lines.append(f"| ⚠ {w} |")
    else:
        lines.append("*None identified.*")
    lines.extend([
        "",
        "*See Criterion Breakdown below for per-dimension verdicts, judge arguments, and remediation guidance.*",
    ])
    return "\n".join(lines)


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
        "security_override": (
            "Confirmed security flaws (os.system/os.popen, shell injection, unsanitized input, "
            "eval/exec, pickle.loads, yaml.unsafe_load, live working dir, no sandbox, etc.) "
            "cap total score at 3."
        ),
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


def _summarize_dissent(
    prosecutor_ops: List[JudicialOpinion],
    defense_ops: List[JudicialOpinion],
    tech_ops: List[JudicialOpinion],
    dim_name: str,
) -> str:
    """Summarize judicial disagreement for inclusion in the report."""
    p = prosecutor_ops[0] if prosecutor_ops else None
    d = defense_ops[0] if defense_ops else None
    t = tech_ops[0] if tech_ops else None
    parts: List[str] = []
    if p and d:
        p_arg = (p.argument or "").strip()
        d_arg = (d.argument or "").strip()
        parts.append(f"**Prosecutor** (score {p.score}): {p_arg[:500]}{'...' if len(p_arg) > 500 else ''}")
        parts.append("")
        parts.append(f"**Defense** (score {d.score}): {d_arg[:500]}{'...' if len(d_arg) > 500 else ''}")
    if t:
        t_arg = (t.argument or "").strip()
        parts.append("")
        parts.append(f"**Tech Lead** (score {t.score}): {t_arg[:400]}{'...' if len(t_arg) > 400 else ''}")
    return "\n".join(parts) if parts else f"No dissent summary for {dim_name}."


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
                "  - In src/tools/repo_tools.py (and underlying git tools), keep git operations "
                "inside tempfile.TemporaryDirectory and avoid raw os.system; rely on subprocess.run with validation."
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


def _score_badge(score: float) -> str:
    """Return a visual badge for the score."""
    s = int(round(score))
    badges = {5: "🟢 Strong", 4: "🟢 Good", 3: "🟡 Adequate", 2: "🟠 Weak", 1: "🔴 Critical"}
    return badges.get(s, str(s))


def _render_report(report: AuditReport, pdf_path: str) -> str:
    """Serialize an AuditReport into well-formatted, table-driven Markdown."""
    import os

    repo_url = report.repo_url
    gen_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    badge = _score_badge(report.overall_score)

    trace_url = os.getenv("LANGSMITH_RUN_URL")
    lines = [
        "# Automaton Auditor – Audit Report",
        "",
        "> Production-grade audit of the Automaton Auditor repository against the Week 2 rubric.",
        "",
        "### Report Metadata",
        "",
        "| Field | Value |",
        "|:------|:------|",
        f"| **Repository** | `{repo_url}` |",
        f"| **Report PDF** | {pdf_path or 'N/A'} |",
        f"| **Overall Score** | **{report.overall_score:.2f}/5** {badge} |",
        f"| **Generated** | {gen_time} |",
    ]
    if trace_url:
        lines.append(f"| **Trace** | [LangSmith]({trace_url}) |")
    lines.append("")
    lines.extend(
        [
            "---",
            "",
            "## Table of Contents",
            "",
            "| # | Section |",
            "|:--|:--------|",
            "| 1 | [Executive Summary](#executive-summary) |",
            "| 2 | [Criterion Overview](#criterion-overview) |",
            "| 3 | [Criterion Breakdown](#criterion-breakdown) |",
            "| 4 | [Remediation Plan](#remediation-plan) |",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            report.executive_summary,
            "",
            "---",
            "",
            "## Criterion Overview",
            "",
            "| # | Criterion | Score | Status |",
            "|:--|:----------|------:|:------:|",
        ]
    )
    for idx, c in enumerate(report.criteria, 1):
        b = _score_badge(c.final_score)
        lines.append(f"| {idx} | {c.dimension_name} | {c.final_score}/5 | {b} |")
    lines.extend(["", "---", "", "## Criterion Breakdown", ""])

    for idx, c in enumerate(report.criteria, 1):
        badge = _score_badge(c.final_score)
        lines.extend(
            [
                f"### {idx}. {c.dimension_name}",
                "",
                f"**Final score: {c.final_score}/5** {badge}",
                "",
                "#### Judge Scores",
                "",
                "| Role | Score |",
                "|:-----|------:|",
            ]
        )
        for o in c.judge_opinions:
            lines.append(f"| {o.judge} | {o.score}/5 |")
        lines.extend(
            [
                "",
                "#### Judge Arguments",
                "",
                "| Role | Argument |",
                "|:-----|:---------|",
            ]
        )
        for o in c.judge_opinions:
            arg = (o.argument or "").strip() or "*(No argument provided)*"
            arg_escaped = arg.replace("|", "\\|").replace("\n", " ")[:400]
            if len(arg) > 400:
                arg_escaped += "..."
            lines.append(f"| **{o.judge}** ({o.score}/5) | {arg_escaped} |")
        lines.extend(
            [
                "",
                "#### Dissent Summary",
                "",
            ]
        )
        if c.dissent_summary:
            lines.append(c.dissent_summary)
        else:
            lines.append("*No significant disagreement recorded.*")
        lines.append("")
        if c.remediation and c.remediation.strip():
            lines.append("#### Remediation")
            lines.append("")
            lines.extend(c.remediation.splitlines())
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend(
        [
            "## Remediation Plan",
            "",
        ]
    )
    rp = report.remediation_plan.strip()
    if rp:
        lines.append("**Consolidated action items across all dimensions:**")
        lines.append("")
        for line in report.remediation_plan.splitlines():
            line = line.rstrip()
            if line.strip():
                lines.append(line)
    else:
        lines.append("*No major remediation required based on current criteria scores.*")
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
