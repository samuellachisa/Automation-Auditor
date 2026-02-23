"""LangGraph StateGraph: Detectives (parallel) -> EvidenceAggregator -> Judges (parallel) -> ChiefJustice."""

from langgraph.graph import END, START, StateGraph

from src.state import AgentState
from src.nodes.detectives import (
    doc_analyst_node,
    evidence_aggregator_node,
    repo_investigator_node,
    vision_inspector_node,
)
from src.nodes.judges import defense_node, prosecutor_node, tech_lead_node
from src.nodes.justice import chief_justice_node


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

    # Layer 2: Judges (parallel)
    builder.add_node("Prosecutor", prosecutor_node)
    builder.add_node("Defense", defense_node)
    builder.add_node("TechLead", tech_lead_node)

    builder.add_edge("EvidenceAggregator", "Prosecutor")
    builder.add_edge("EvidenceAggregator", "Defense")
    builder.add_edge("EvidenceAggregator", "TechLead")

    # Layer 3: Chief Justice (fan-in from all Judges)
    builder.add_node("ChiefJustice", chief_justice_node)
    builder.add_edge("Prosecutor", "ChiefJustice")
    builder.add_edge("Defense", "ChiefJustice")
    builder.add_edge("TechLead", "ChiefJustice")
    builder.add_edge("ChiefJustice", END)

    return builder.compile()
