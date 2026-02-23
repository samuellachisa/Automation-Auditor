"""AST-based analysis of LangGraph state and graph structure. No regex for structure."""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def analyze_state_structure(repo_path: Path) -> Dict[str, Any]:
    """
    Scan for state definition in src/state.py or src/graph.py.
    Look for BaseModel (Pydantic) or TypedDict. Return snippets and booleans.
    """
    result = {
        "state_file_exists": False,
        "graph_file_has_state": False,
        "has_pydantic": False,
        "has_typed_dict": False,
        "has_evidence": False,
        "has_judicial_opinion": False,
        "has_reducers": False,
        "snippet": None,
    }
    for rel in ["src/state.py", "src/graph.py"]:
        f = repo_path / rel
        if not f.exists():
            continue
        if "state.py" in rel:
            result["state_file_exists"] = True
        text = _read_file(f)
        if not text:
            continue
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    name = node.name
                    if "Evidence" in name:
                        result["has_evidence"] = True
                    if "JudicialOpinion" in name or "Opinion" in name:
                        result["has_judicial_opinion"] = True
                    for base in getattr(node, "bases", []):
                        if isinstance(base, ast.Name):
                            if base.id == "BaseModel":
                                result["has_pydantic"] = True
                            if base.id == "TypedDict":
                                result["has_typed_dict"] = True
                    # Check for Annotated with operator.ior / operator.add
                    for st in node.body:
                        if isinstance(st, ast.AnnAssign) and isinstance(st.annotation, ast.Subscript):
                            ann = st.annotation
                            if isinstance(getattr(ann, "value", None), ast.Name):
                                if ann.value.id == "Annotated":
                                    result["has_reducers"] = True
            if "AgentState" in text or "State" in text:
                # Extract a short snippet around AgentState or state definition
                for i, line in enumerate(text.splitlines()):
                    if "AgentState" in line or ("TypedDict" in line and "State" in line):
                        start = max(0, i - 1)
                        result["snippet"] = "\n".join(text.splitlines()[start : start + 25])
                        break
        except SyntaxError:
            pass
        if result["snippet"]:
            break
    return result


def analyze_graph_structure(repo_path: Path) -> Dict[str, Any]:
    """
    Find StateGraph usage and add_edge/add_node patterns via AST.
    Detect fan-out (multiple edges from one node) and fan-in (multiple edges to one node).
    """
    result = {
        "has_state_graph": False,
        "graph_file": None,
        "nodes": [],
        "edges": [],  # (from, to) list
        "parallel_fan_out": False,
        "parallel_fan_in": False,
        "snippet": None,
    }
    graph_file = repo_path / "src" / "graph.py"
    if not graph_file.exists():
        return result
    result["graph_file"] = str(graph_file)
    text = _read_file(graph_file)
    if not text:
        return result
    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = getattr(node.func, "value", node.func)
                if isinstance(f, ast.Attribute):
                    name = f.attr
                    if isinstance(getattr(node.func, "value", None), ast.Name):
                        caller = node.func.value.id
                    else:
                        caller = ""
                    if "StateGraph" in (getattr(node.func, "id", "") or str(node.func)):
                        # StateGraph(...)
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call) and getattr(child.func, "attr", None) == "StateGraph":
                                result["has_state_graph"] = True
                                break
                    if name == "add_edge":
                        args = node.args
                        if len(args) >= 2:
                            from_n = _ast_to_str(args[0])
                            to_n = _ast_to_str(args[1])
                            result["edges"].append((from_n, to_n))
                        if len(args) == 1 and caller:
                            # add_edge(x) for conditional?
                            result["edges"].append((caller, args[0]))
                    if name == "add_node":
                        if node.args:
                            n = _ast_to_str(node.args[0])
                            if n and n not in result["nodes"]:
                                result["nodes"].append(n)
        # Infer fan-out: one node with multiple edges out
        from_nodes = [e[0] for e in result["edges"]]
        to_nodes = [e[1] for e in result["edges"]]
        for n in set(from_nodes):
            if from_nodes.count(n) > 1:
                result["parallel_fan_out"] = True
                break
        for n in set(to_nodes):
            if to_nodes.count(n) > 1:
                result["parallel_fan_in"] = True
                break
        # Snippet: block defining graph (add_edge/add_node)
        for i, line in enumerate(text.splitlines()):
            if "add_edge" in line or "StateGraph" in line:
                start = max(0, i - 2)
                result["snippet"] = "\n".join(text.splitlines()[start : start + 40])
                break
    except SyntaxError:
        pass
    return result


def _ast_to_str(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Str):
        return node.s
    return ""


def scan_tools_for_sandbox(repo_path: Path) -> Dict[str, Any]:
    """Check src/tools for tempfile.TemporaryDirectory and absence of raw os.system."""
    result = {
        "uses_tempfile": False,
        "uses_os_system": False,
        "clone_function_snippet": None,
    }
    tools_dir = repo_path / "src" / "tools"
    if not tools_dir.exists():
        return result
    for f in tools_dir.glob("*.py"):
        text = _read_file(f)
        if not text:
            continue
        if "TemporaryDirectory" in text or "tempfile" in text:
            result["uses_tempfile"] = True
        if "os.system" in text:
            result["uses_os_system"] = True
        if "clone" in text.lower() or "git" in text:
            for i, line in enumerate(text.splitlines()):
                if "def " in line and ("clone" in line.lower() or "git" in line.lower()):
                    start = max(0, i)
                    result["clone_function_snippet"] = "\n".join(text.splitlines()[start : start + 25])
                    break
    return result


def scan_judges_structured_output(repo_path: Path) -> Dict[str, Any]:
    """Scan Judge nodes for .with_structured_output() or .bind_tools() with JudicialOpinion."""
    result = {
        "with_structured_output": False,
        "bind_tools": False,
        "judicial_opinion_schema": False,
        "snippet": None,
    }
    nodes_dir = repo_path / "src" / "nodes"
    if not nodes_dir.exists():
        return result
    for f in nodes_dir.glob("*.py"):
        text = _read_file(f)
        if not text:
            continue
        if "with_structured_output" in text:
            result["with_structured_output"] = True
        if "bind_tools" in text:
            result["bind_tools"] = True
        if "JudicialOpinion" in text or "judicial_opinion" in text:
            result["judicial_opinion_schema"] = True
        if "with_structured_output" in text or "bind_tools" in text:
            for i, line in enumerate(text.splitlines()):
                if "with_structured_output" in line or "bind_tools" in line:
                    start = max(0, i - 2)
                    result["snippet"] = "\n".join(text.splitlines()[start : start + 8])
                    break
    return result
