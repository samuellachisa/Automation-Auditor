"""Typed state and Pydantic schemas for the Automaton Auditor swarm."""

import operator
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Evidence(BaseModel):
    """Forensic evidence collected by Detective agents."""

    goal: str = Field(description="The forensic goal this evidence addresses")
    found: bool = Field(description="Whether the artifact exists")
    content: Optional[str] = Field(default=None, description="Relevant snippet or content")
    location: str = Field(description="File path or commit hash")
    rationale: str = Field(description="Rationale for confidence in this evidence")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")


class JudicialOpinion(BaseModel):
    """Structured opinion from a single Judge (Prosecutor, Defense, Tech Lead)."""

    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str = Field(description="Rubric dimension id")
    score: int = Field(ge=1, le=5, description="Score 1-5 for this criterion")
    argument: str = Field(description="Reasoning for the score")
    cited_evidence: List[str] = Field(default_factory=list, description="Evidence IDs or snippets cited")


class AgentState(TypedDict, total=False):
    """State for the LangGraph auditor swarm. Use reducers for parallel-safe updates."""

    repo_url: str
    pdf_path: str
    output_dir: str
    rubric_dimensions: List[Dict[str, Any]]
    rubric_synthesis_rules: Dict[str, str]
    # Reducers: parallel nodes merge instead of overwrite
    evidences: Annotated[Dict[str, List[Evidence]], operator.ior]
    opinions: Annotated[List[JudicialOpinion], operator.add]
    final_report: str
