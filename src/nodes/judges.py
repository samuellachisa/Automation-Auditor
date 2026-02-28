"""Judicial layer: Prosecutor, Defense, Tech Lead. Structured output only (JudicialOpinion)."""

import logging
from typing import Any, Dict, List, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError

from src.state import AgentState, Evidence, JudicialOpinion

logger = logging.getLogger(__name__)

JUDGE_MAX_RETRIES = 2


# System prompts for each persona (skeleton; judicial_logic from rubric is injected per dimension)
PROSECUTOR_SYSTEM = """You are the Prosecutor in a Digital Courtroom. Your philosophy: "Trust No One. Assume Vibe Coding."
Your job is to scrutinize the evidence for gaps, security flaws, and laziness. Be harsh. If the rubric asks for parallel orchestration and the evidence shows a linear pipeline, argue for Score 1. If Judges return freeform text instead of Pydantic models, charge "Hallucination Liability." Provide a low score (1-2) and list specific missing elements."""

DEFENSE_SYSTEM = """You are the Defense Attorney. Your philosophy: "Reward Effort and Intent. Look for the Spirit of the Law."
Highlight creative workarounds, deep thought, and effort even if implementation is imperfect. If the code is buggy but the architecture report shows deep understanding, argue for a higher score. If git history shows iteration and struggle, argue for "Engineering Process." Provide a generous score (3-5) and highlight strengths."""

TECH_LEAD_SYSTEM = """You are the Tech Lead. Your philosophy: "Does it actually work? Is it maintainable?"
Ignore vibe and struggle. Focus on artifacts: Are state reducers (operator.add, operator.ior) used correctly? Are tool calls sandboxed? You are the tie-breaker. Provide a realistic score (1, 3, or 5) and technical remediation advice."""


def _evidence_summary(evidences: Dict[str, List[Evidence]], dimension_id: str) -> str:
    elist = evidences.get(dimension_id) or evidences.get("unknown") or []
    parts = []
    for e in elist:
        parts.append(f"- [{e.goal}] found={e.found} confidence={e.confidence}\n  location: {e.location}\n  rationale: {e.rationale}\n  content: {(e.content or '')[:500]}")
    return "\n".join(parts) if parts else "No evidence for this dimension."


def _get_judge_prompt(role: str, dimension: Dict[str, Any], evidence_text: str, judicial_logic: Dict[str, str]) -> str:
    logic = judicial_logic.get(role.lower().replace(" ", "_"), judicial_logic.get("tech_lead", ""))
    return f"""Dimension: {dimension.get('name', dimension.get('id'))}
Criterion ID: {dimension.get('id')}

Your specific instruction for this dimension:
{logic}

Evidence collected by Detectives:
{evidence_text}

Respond with your JudicialOpinion: judge={role}, criterion_id={dimension.get('id')}, score (1-5), argument (reasoning), and cited_evidence (list of evidence snippets you relied on). Use structured output only."""


def _invoke_judge(llm: BaseChatModel, role: Literal["Prosecutor", "Defense", "TechLead"], dimension: Dict[str, Any], state: AgentState) -> JudicialOpinion:
    evidences = state.get("evidences") or {}
    dim_id = dimension.get("id", "unknown")
    evidence_text = _evidence_summary(evidences, dim_id)
    judicial_logic = dimension.get("judicial_logic") or {}
    if role == "Prosecutor":
        system = PROSECUTOR_SYSTEM
        logic_key = "prosecutor"
    elif role == "Defense":
        system = DEFENSE_SYSTEM
        logic_key = "defense"
    else:
        system = TECH_LEAD_SYSTEM
        logic_key = "tech_lead"
    logic = judicial_logic.get(logic_key, "")
    prompt = _get_judge_prompt(role, dimension, evidence_text, judicial_logic)

    structured_llm = llm.with_structured_output(JudicialOpinion)
    msg = HumanMessage(content=prompt)
    last_err: Exception | None = None

    for attempt in range(JUDGE_MAX_RETRIES + 1):
        try:
            out = structured_llm.invoke([SystemMessage(content=system), msg])
            if isinstance(out, JudicialOpinion):
                return _clamp_opinion(out)
            if isinstance(out, dict):
                return _clamp_opinion(JudicialOpinion(**out))
            raise ValueError("Judge must return JudicialOpinion")
        except (ValidationError, ValueError, TypeError) as e:
            last_err = e
            logger.warning(
                "Judge %s malformed output for %s (attempt %d/%d): %s",
                role, dim_id, attempt + 1, JUDGE_MAX_RETRIES + 1, e,
            )
            if attempt < JUDGE_MAX_RETRIES:
                continue
            # Final fallback
            return JudicialOpinion(
                judge=role,
                criterion_id=dim_id,
                score=3,
                argument=f"Retry exhausted after malformed output: {last_err}",
                cited_evidence=[],
            )
    raise RuntimeError("Unreachable")  # type: ignore[unreachable]


def _clamp_opinion(op: JudicialOpinion) -> JudicialOpinion:
    """Ensure score is in [1,5] and judge/criterion_id are valid."""
    score = max(1, min(5, int(op.score) if op.score is not None else 3))
    return JudicialOpinion(
        judge=op.judge,
        criterion_id=op.criterion_id or "unknown",
        score=score,
        argument=op.argument or "No argument provided.",
        cited_evidence=op.cited_evidence or [],
    )


def prosecutor_node(state: AgentState) -> Dict[str, Any]:
    """Prosecutor: critical lens. Returns opinions for all dimensions."""
    return _judge_node(state, "Prosecutor")


def defense_node(state: AgentState) -> Dict[str, Any]:
    """Defense: optimistic lens."""
    return _judge_node(state, "Defense")


def tech_lead_node(state: AgentState) -> Dict[str, Any]:
    """Tech Lead: pragmatic lens."""
    return _judge_node(state, "TechLead")


def _judge_node(state: AgentState, role: Literal["Prosecutor", "Defense", "TechLead"]) -> Dict[str, Any]:
    llm = _get_llm()
    dimensions = state.get("rubric_dimensions") or []
    opinions: List[JudicialOpinion] = []
    for d in dimensions:
        try:
            op = _invoke_judge(llm, role, d, state)  # type: ignore[arg-type]
            # Ensure judge and criterion_id are set
            if op.judge != role:
                op = JudicialOpinion(judge=role, criterion_id=op.criterion_id, score=op.score, argument=op.argument, cited_evidence=op.cited_evidence)
            if op.criterion_id != d.get("id"):
                op = JudicialOpinion(judge=op.judge, criterion_id=d.get("id", op.criterion_id), score=op.score, argument=op.argument, cited_evidence=op.cited_evidence)
            opinions.append(op)
        except Exception as e:
            opinions.append(
                JudicialOpinion(
                    judge=role,
                    criterion_id=d.get("id", "unknown"),
                    score=1,
                    argument=f"Error producing opinion: {e}",
                    cited_evidence=[],
                )
            )
    return {"opinions": opinions}


def _get_llm() -> BaseChatModel:
    import os
    from dotenv import load_dotenv
    load_dotenv()
    # Local Ollama (e.g. OLLAMA_MODEL=qwen2.5); ensure Ollama is running: ollama run qwen2.5
    if os.getenv("OLLAMA_MODEL"):
        from langchain_ollama import ChatOllama
        model = os.getenv("OLLAMA_MODEL", "qwen2.5")
        base_url = os.getenv("OLLAMA_BASE_URL")  # e.g. http://localhost:11434
        kwargs = {"model": model, "temperature": 0.2}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOllama(**kwargs)
    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    if os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0.2)
    if os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return ChatGoogleGenerativeAI(model=model, temperature=0.2)
    raise RuntimeError("Set OLLAMA_MODEL (local), OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY in .env")
