"""Chief Justice: synthesis from judicial opinions with hardcoded rules. Report generation."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.state import AgentState, Evidence, JudicialOpinion


def _ensure_opinion(o: Any) -> JudicialOpinion:
    if isinstance(o, JudicialOpinion):
        return o
    return JudicialOpinion.model_validate(o) if isinstance(o, dict) else o


def _ensure_evidence(e: Any) -> Evidence:
    if isinstance(e, Evidence):
        return e
    return Evidence.model_validate(e) if isinstance(e, dict) else e


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

    verdicts: List[Dict[str, Any]] = []
    remediations: List[str] = []

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
            if any("security" in (o.argument or "").lower() or "os.system" in (o.argument or "").lower() for o in prosecutor_ops):
                p_score = min(p_score, 3)
                final_score = min(_resolve_score(p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops), 3)
            else:
                final_score = _resolve_score(p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops)
        else:
            final_score = _resolve_score(p_score, d_score, t_score, prosecutor_ops, defense_ops, tech_ops)

        # Fact supremacy: if evidence says "not found" and Defense claimed depth, cap
        ev_list = evidences.get(dim_id) or []
        if synthesis_rules.get("fact_supremacy") and ev_list:
            if not any(e.found for e in ev_list) and d_score >= 4:
                final_score = min(final_score, 3)

        dissent = _summarize_dissent(prosecutor_ops, defense_ops, tech_ops, dim_name)
        verdicts.append({
            "criterion_id": dim_id,
            "name": dim_name,
            "score": final_score,
            "dissent": dissent,
            "prosecutor_score": p_score,
            "defense_score": d_score,
            "tech_lead_score": t_score,
        })
        remediations.extend(_remediation_for_criterion(dim_id, dim_name, final_score, ev_list, prosecutor_ops, tech_ops))

    report_md = _render_report(state, verdicts, remediations)
    output_dir = state.get("output_dir") or "audit/report_onself_generated"
    report_path = write_report_to_file(report_md, output_dir)
    return {"final_report": report_path}


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
    out = []
    if score <= 2:
        out.append(f"**{dim_name}**: Address gaps identified by Prosecutor and Tech Lead.")
        if prosecutor_ops:
            out.append(f"  - Prosecutor: {prosecutor_ops[0].argument[:300]}")
        if tech_ops:
            out.append(f"  - Tech Lead remediation: {tech_ops[0].argument[:300]}")
        for e in ev_list:
            if not e.found and e.location:
                out.append(f"  - Ensure: {e.goal} at {e.location}")
    return out


def _render_report(state: AgentState, verdicts: List[Dict[str, Any]], remediations: List[str]) -> str:
    repo_url = state.get("repo_url", "")
    pdf_path = state.get("pdf_path", "")
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
    ]
    total = sum(v["score"] for v in verdicts)
    max_total = 5 * len(verdicts)
    lines.append(f"Overall: {total}/{max_total} across {len(verdicts)} criteria.")
    lines.append("")
    lines.append("## Criterion Breakdown")
    lines.append("")
    for v in verdicts:
        lines.append(f"### {v['name']} — Score: {v['score']}/5")
        lines.append("")
        lines.append(f"- Prosecutor: {v['prosecutor_score']} | Defense: {v['defense_score']} | Tech Lead: {v['tech_lead_score']}")
        lines.append("")
        lines.append("**Dissent:** " + v["dissent"])
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Remediation Plan")
    lines.append("")
    for r in remediations:
        lines.append(r)
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
