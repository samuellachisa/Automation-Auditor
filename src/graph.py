"""LangGraph StateGraph: Detectives (parallel) -> EvidenceAggregator -> Judges (parallel) -> ChiefJustice."""

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.state import AgentState
from src.nodes.detectives import (
    doc_analyst_node,
    evidence_aggregator_node,
    repo_investigator_node,
    vision_inspector_node,
)
from src.nodes.judges import defense_node, prosecutor_node, tech_lead_node
from src.nodes.justice import chief_justice_node, evidence_missing_node


def _judges_entry_node(state: AgentState) -> Dict[str, Any]:
    """
    Simple pass-through node that fans out to all Judges.
    Used so conditional routing from EvidenceAggregator maps to a single node.
    """
    return {}


def build_auditor_graph():
    """Build and compile the Digital Courtroom StateGraph."""
    builder = StateGraph(AgentState)

    # Layer 1: Detectives (parallel)
    builder.add_node("RepoInvestigator", repo_investigator_node)
    builder.add_node("DocAnalyst", doc_analyst_node)
    builder.add_node("VisionInspector", vision_inspector_node)

    builder.add_node("EvidenceAggregator", evidence_aggregator_node)

    # Fan-in: all Detectives -> EvidenceAggregator
    builder.add_edge(START, "RepoInvestigator")
    builder.add_edge(START, "DocAnalyst")
    builder.add_edge(START, "VisionInspector")
    builder.add_edge("RepoInvestigator", "EvidenceAggregator")
    builder.add_edge("DocAnalyst", "EvidenceAggregator")
    builder.add_edge("VisionInspector", "EvidenceAggregator")

    # Layer 2: Judges (parallel) and failure-aware routing
    builder.add_node("Prosecutor", prosecutor_node)
    builder.add_node("Defense", defense_node)
    builder.add_node("TechLead", tech_lead_node)
    builder.add_node("EvidenceMissing", evidence_missing_node)
    builder.add_node("JudgesEntry", _judges_entry_node)

    # Conditional edges: if critical evidence is mostly missing, skip normal
    # judges and route to EvidenceMissing; otherwise route to JudgesEntry.
    # critical_ids come from rubric rubric_metadata.critical_dimensions or default.
    # Require at least 2 of N critical dimensions to have found=True.
    def _evidence_status(state: AgentState) -> str:  # type: ignore[override]
        evidences = (state.get("evidences") or {})  # type: ignore[assignment]
        critical_ids = state.get("rubric_critical_dimensions") or [
            "git_forensic_analysis",
            "state_management_rigor",
            "graph_orchestration",
            "safe_tool_engineering",
        ]
        ok_count = 0
        for cid in critical_ids:
            ev_list = evidences.get(cid) or []
            if ev_list and any(getattr(e, "found", False) for e in ev_list):
                ok_count += 1
        return "ok" if ok_count >= 2 else "missing"

    builder.add_conditional_edges(
        "EvidenceAggregator",
        _evidence_status,
        {
            "ok": "JudgesEntry",
            "missing": "EvidenceMissing",
        },
    )

    # Fan-out from JudgesEntry to all Judges
    builder.add_edge("JudgesEntry", "Prosecutor")
    builder.add_edge("JudgesEntry", "Defense")
    builder.add_edge("JudgesEntry", "TechLead")

    # Layer 3: Chief Justice (fan-in from all Judges / EvidenceMissing)
    builder.add_node("ChiefJustice", chief_justice_node)
    builder.add_edge("Prosecutor", "ChiefJustice")
    builder.add_edge("Defense", "ChiefJustice")
    builder.add_edge("TechLead", "ChiefJustice")
    builder.add_edge("EvidenceMissing", "ChiefJustice")
    builder.add_edge("ChiefJustice", END)

    return builder.compile()
