"""Check Python files against the project Python style instructions.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["radon", "cognitive-complexity", "rich"]
# ///

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze
from rich.console import Console
from rich.table import Table

BANNER_RE = re.compile(r"^\s*#\s*[-=]{3,}")
PATH_HACK_RE = re.compile(
    r"^\s*(?:sys\.path\.(?:insert|append)|import\s+importlib\.util"
    r"|from\s+importlib\s+import\s+util)"
)
NESTING_TYPES = {"If", "For", "While", "With", "Try", "TryStar", "Match", "AsyncFor", "AsyncWith"}
IO_NAMES = {"print", "open", "input", "write", "read", "send", "recv"}
IO_ATTRS = {
    "glob","rglob","mkdir", "Popen", "run", "unlink",
    "read_bytes", "read_csv", "read_excel", "read_json", "read_parquet", "read_text",
    "to_csv", "to_excel", "to_json", "to_parquet",
    "write_bytes", "write_text",
}
MUTATING_METHODS = {"add", "append", "clear", "discard", "extend", "insert", "pop", "remove", "reverse", "sort", "update"}
LOGGING_NAMES = {"logging", "logger", "log"}
COMP_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


# Ousterhout on abstractions approximately:
# * deep expose a simple interface while hiding lots of functionality.
# * shallow force an interface almost as costly as reading the implementation. 

# approximate the interface by caller-visible parameters and the hidden
# functionality by executable LOC adjusted for branching/cognitive complexity.

# [r] unnecessary constants repeated
OUSTERHOUT_SINGLE_LOC = 1
OUSTERHOUT_LOW_LOC = 3
OUSTERHOUT_LOW_DEPTH = 4.0
OUSTERHOUT_PARAM_RATIO = 0.5
OUSTERHOUT_PARAM_RATIO_MIN_PARAMS = 2
OUSTERHOUT_PARAM_RATIO_MAX_LOC = 8
OUSTERHOUT_CC_WEIGHT = 1.0
OUSTERHOUT_COGNITIVE_WEIGHT = 0.5


@dataclass(frozen=True)
class Limit: target: float; soft: float; hard: float | None = None; weight: float = 1.0
LIMITS = {
  "cyclomatic": Limit(8, 12, hard=16, weight=2),
  "cognitive": Limit(10, 16, hard=25, weight=2),
  "nesting": Limit(3, 4, hard=6, weight=1.5),
  "fn_loc": Limit(40, 60, hard=100),
  "line_length": Limit(80, 120, hard=200, weight=0.25),
  "cell_sloc": Limit(80, 120, hard=180, weight=0.5),
  "cell_complexity": Limit(25, 40, hard=80),
  "impure_fns": Limit(1, 3, weight=2),
  "hidden_global_fns": Limit(0, 2, weight=2),
  "shallow_fns": Limit(6, 12, weight=0.5),
  "string_split_lists": Limit(0, 2),
  "tuple_specs": Limit(0, 3),
  "dense_comps": Limit(0, 2),
  "repeated_transforms": Limit(0, 3, weight=0.5),
  "bare_asserts": Limit(0, 2, weight=0.5),
  "intent_docstring": Limit(0, 1, hard=0, weight=2),
  "banners": Limit(0, 2, hard=5),
  "path_hacks": Limit(0, 1, hard=0, weight=10),
  "import_names": Limit(3, 5, weight=0.5),
}

@dataclass(frozen=True)
class RuffIssue: line: int; code: str; message: str

@dataclass
class FunctionMetric:
    name: str; line: int; loc: int; impl_loc: int; params: int; depth: float
    cc: int; cognitive: int; nesting: int; halstead: float
    pure: bool; shallow: bool; shallow_reason: str = ""
    reasons: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    path: Path; total_loc: int; sloc: int
    mi: float; max_line: int; max_cell: int; max_cell_complexity: int
    functions: list[FunctionMetric]; ruff: list[RuffIssue]
    issues: dict[str, list[str]] = field(default_factory=dict)

RUFF_WEIGHTS = { "F401": 0.5, "F841": 0.5, "I001": 0.25}


class NestingVisitor(ast.NodeVisitor):
    def __init__(self): self.depth = 0; self.max_depth = 0;
    def __getattr__(self, name: str):
        if name.startswith("visit_") and name[6:] in NESTING_TYPES:
            return self.visit_nested
        raise AttributeError(name)

    def visit_nested(self, node) -> None:
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        self.generic_visit(node)
        self.depth -= 1


class PurityVisitor(ast.NodeVisitor):
    def __init__(self, locals_: set[str], globals_: set[str]):
        self.locals = locals_; self.globals = globals_; self.reasons: list[str] = []

    def visit_Name(self, node) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in self.globals:
            if node.id not in self.locals:
                self.reasons.append(f"L{node.lineno}: hidden global read: {node.id}")

    def visit_Global(self, node) -> None:
        self.reasons.append(f"L{node.lineno}: global statement")

    def visit_Nonlocal(self, node) -> None:
        self.reasons.append(f"L{node.lineno}: nonlocal statement")

    def visit_Assign(self, node) -> None:
        if any(is_nonself_attr(target) for target in node.targets):
            self.reasons.append(f"L{node.lineno}: assigns attribute on non-self object")
        self.generic_visit(node)

    def visit_Call(self, node) -> None:
        for reason in call_reasons(node.func, self.locals):
            self.reasons.append(f"L{node.lineno}: {reason}")
        self.generic_visit(node)


def cost(name: str, val: float) -> float:
    l = LIMITS[name]
    if l.hard is not None and val > l.hard: return math.inf
    if val <= l.target: return 0.0
    return l.weight * ((val - l.target) / l.soft) ** 2


def target_names(node) -> list[str]:
    if isinstance(node, ast.Name): return [node.id]
    if isinstance(node, ast.Starred): return target_names(node.value)
    if isinstance(node, (ast.Tuple, ast.List)): return sum(
        map(target_names, node.elts), [])
    return []


def assigned_names(node) -> list[str]:
    if isinstance(node, ast.Assign):
        return sum(map(target_names, node.targets), [])
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return target_names(node.target)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return target_names(node.target)
    if isinstance(node, ast.With):
        return with_names(node)
    return except_names(node)


def with_names(node: ast.With) -> list[str]:
    names: list[str] = []
    for item in node.items:
        if item.optional_vars:
            names.extend(target_names(item.optional_vars))
    return names


def except_names(node) -> list[str]:
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [node.name]
    return []


def arg_names(node) -> set[str]:
    args = node.args
    groups = (args.posonlyargs, args.args, args.kwonlyargs)
    names = {arg.arg for group in groups for arg in group}
    names.update(x.arg for x in (args.vararg, args.kwarg) if x)
    return names


def local_names(node) -> set[str]:
    names = arg_names(node)
    for child in ast.walk(node):
        names.update(assigned_names(child))
    return names


def module_values(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        names.update(assigned_names(node))
    return {name for name in names if not name.isupper()}


def is_nonself_attr(node) -> bool:
    if not isinstance(node, ast.Attribute):
        return False
    return not (isinstance(node.value, ast.Name) and node.value.id == "self")


def call_reasons(func, locals_: set[str]) -> list[str]:
    if isinstance(func, ast.Name):
        return [f"I/O call: {func.id}()"] if func.id in IO_NAMES else []
    if not isinstance(func, ast.Attribute):
        return []
    reasons: list[str] = []
    if func.attr in IO_ATTRS or func.attr in IO_NAMES:
        reasons.append(f"I/O call: .{func.attr}()")
    if mutates_global(func, locals_):
        reasons.append(f"mutates non-local via .{func.attr}()")
    root_name = getattr(func.value, "id", "")
    if root_name in LOGGING_NAMES:
        reasons.append(f"logging call: {root_name}")
    return reasons


def root_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return root_name(node.value)
    return ""


def mutates_global(func: ast.Attribute, locals_: set[str]) -> bool:
    if func.attr not in MUTATING_METHODS:
        return False
    return root_name(func.value) not in locals_



def purity(node, globals_: set[str]) -> tuple[bool, list[str]]:
    visitor = PurityVisitor(local_names(node), globals_)
    for stmt in node.body:
        visitor.visit(stmt)
    reasons = sorted(set(visitor.reasons))
    return not reasons, reasons


def fn_loc(node) -> int:
    if not node.body:
        return 0
    start = node.body[0].lineno
    end = node.end_lineno or node.body[-1].end_lineno or start
    return end - start + 1


def nesting(node) -> int:
    visitor = NestingVisitor()
    for child in node.body:
        visitor.visit(child)
    return visitor.max_depth


def cognitive(node) -> int:
    try:
        from cognitive_complexity.api import get_cognitive_complexity
    except Exception:
        return 0
    return get_cognitive_complexity(node)


def halstead(lines: list[str], node) -> float:
    start = node.lineno - 1
    end = node.end_lineno or len(lines)
    try:
        result = h_visit("\n".join(lines[start:end]))
    except Exception:
        return 0.0
    return round(result.total.volume, 1) if result.total else 0.0


def executable_body(node) -> list[ast.stmt]:
    if node.body and is_docstring_stmt(node.body[0]):
        return node.body[1:]
    return node.body


def is_docstring_stmt(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def impl_loc(node) -> int:
    body = executable_body(node)
    if not body:
        return 0
    start = body[0].lineno
    end = body[-1].end_lineno or body[-1].lineno
    return end - start + 1


def caller_param_count(node) -> int:
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    if positional and positional[0].arg in {"self", "cls"}:
        positional = positional[1:]
    variadic = int(args.vararg is not None) + int(args.kwarg is not None)
    return len(positional) + len(args.kwonlyargs) + variadic


def shallow_reason(params: int, loc: int, depth: float) -> str:
    if loc == 0:
        return f"no executable LOC behind params={params}"
    if loc <= OUSTERHOUT_SINGLE_LOC:
        return f"one executable LOC behind params={params}"
    if loc <= OUSTERHOUT_LOW_LOC and depth <= OUSTERHOUT_LOW_DEPTH:
        return f"low hidden functionality: loc={loc}, depth={depth:.1f}"
    ratio = params / max(depth, 1.0)
    if (
        params >= OUSTERHOUT_PARAM_RATIO_MIN_PARAMS
        and loc <= OUSTERHOUT_PARAM_RATIO_MAX_LOC
        and ratio >= OUSTERHOUT_PARAM_RATIO
    ):
        return f"wide interface: params/depth={ratio:.2f}"
    return ""


def function_metric(node, lines, cc_map, globals_) -> FunctionMetric:
    pure, reasons = purity(node, globals_)
    loc = fn_loc(node)
    impl = impl_loc(node)
    cc = cc_map.get((node.name, node.lineno), 1)
    cogn = cognitive(node)
    params = caller_param_count(node)
    depth = (
        impl
        + max(0, cc - 1) * OUSTERHOUT_CC_WEIGHT
        + cogn * OUSTERHOUT_COGNITIVE_WEIGHT
    )
    shallow = shallow_reason(params, impl, depth)
    return FunctionMetric(
        name=node.name,
        line=node.lineno,
        loc=loc,
        impl_loc=impl,
        params=params,
        depth=depth,
        cc=cc,
        cognitive=cogn,
        nesting=nesting(node),
        halstead=halstead(lines, node),
        pure=pure,
        shallow=bool(shallow),
        shallow_reason=shallow,
        reasons=reasons,
    )


def cell_spans(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines, 1) if line.startswith("# %%")]
    if not starts:
        return []
    ends = starts[1:] + [len(lines) + 1]
    return [(start, end - 1) for start, end in zip(starts, ends)]


def is_declarative_cell(lines: list[str], start: int, end: int) -> bool:
    text = "\n".join(lines[start - 1:end])
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    allowed = (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)
    return bool(tree.body) and all(
        isinstance(stmt, allowed)
        for stmt in tree.body
    )


def cell_stats(lines: list[str]) -> tuple[int, list[str]]:
    cells = [
        (start, end, cell_sloc(lines[start - 1:end]))
        for start, end in cell_spans(lines)
        if not is_declarative_cell(lines, start, end)
    ]
    target = LIMITS["cell_sloc"].target
    large = [f"L{a}-{b}: cell SLOC={n}" for a, b, n in cells if n > target]
    return max((n for _, _, n in cells), default=0), large


def cell_sloc(lines: list[str]) -> int:
    total = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            total += 1
    return total


def cell_complexity(
    tree: ast.Module,
    lines: list[str],
) -> tuple[int, list[str]]:
    cells = []
    for start, end in cell_spans(lines):
        score = sum(cell_stmt_cost(stmt) for stmt in tree.body
                    if start <= getattr(stmt, "lineno", 0) <= end)
        cells.append((start, end, score))
    complex_cells = [
        f"L{a}-{b}: cell complexity={n}"
        for a, b, n in cells if n > LIMITS["cell_complexity"].target
    ]
    return max((n for _, _, n in cells), default=0), complex_cells


def cell_stmt_cost(stmt) -> int:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return 0
    if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Expr)):
        return 0
    if isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.Match)):
        return 3
    return 1



def literal_split_width(node) -> int:
    if not isinstance(node, ast.Call):
        return 0
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "split":
        return 0
    value = func.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return len(value.value.split())
    return 0

def string_split_lists(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        width = literal_split_width(getattr(node, "value", None))
        if isinstance(node, ast.Assign) and width >= 4:
            names = ", ".join(sum(map(target_names, node.targets), [])) or "<expr>"
            issues.append(f"L{node.lineno}: {names} .split() {width} ids")
    return issues


def tuple_specs(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        specs = [x for x in node.elts if isinstance(x, ast.Tuple)]
        specs = [x for x in specs if len(x.elts) >= 4]
        if len(specs) >= 3:
            issues.append(f"L{node.lineno}: {len(specs)} tuple specs")
    return issues


def dense_comps(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, COMP_TYPES):
            continue
        filters = sum(len(gen.ifs) for gen in node.generators)
        width = comp_width(node)
        if len(node.generators) > 1 and (filters or width >= 3):
            issues.append(f"L{node.lineno}: dense comprehension")
    return issues

def comp_width(node) -> int:
    if isinstance(node, ast.DictComp): return 2
    elt = getattr(node, "elt", None)
    return len(elt.elts) if isinstance(elt, ast.Tuple) else 1




def repeated_transforms(tree: ast.Module) -> list[str]:
    counts = {}
    for body in ast_bodies(tree):
        for stmt in body:
            if hit := transform_assignment(stmt):
                target, func, line = hit
                key = (target, func)
                counts[key] = counts.get(key, []) + [line]
    return [
        f"L{lines[0]}: {target} repeatedly uses {func}"
        for (target, func), lines in counts.items()
        if len(lines) >= 3
    ]


def ast_bodies(tree: ast.Module) -> list[list[ast.stmt]]:
    bodies: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        valid = isinstance(body, list)
        if valid and all(isinstance(x, ast.stmt) for x in body):
            bodies.append(body)
    return bodies


def transform_assignment(stmt) -> tuple[str, str, int] | None:
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return None
    target = stmt.targets[0]
    if not isinstance(target, ast.Name) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    if not (call.args and isinstance(call.args[0], ast.Name) and call.args[0].id == target.id):
        return None
    return target.id, call_name(call.func), stmt.lineno


def call_name(func) -> str:
    if isinstance(func, ast.Name): return func.id
    if isinstance(func, ast.Attribute): return func.attr
    return "<call>"


def source_issues(
    tree: ast.Module,
    lines: list[str],
    ruff: list[RuffIssue],
) -> dict[str, list[str]]:
    max_cell, large = cell_stats(lines)
    max_complexity, complex_cells = cell_complexity(tree, lines)
    issues = {
        "large_cells": large,
        "complex_cells": complex_cells,
        "string_split_lists": string_split_lists(tree),
        "tuple_specs": tuple_specs(tree),
        "dense_comps": dense_comps(tree),
        "repeated_transforms": repeated_transforms(tree),
        "bare_asserts": [
            f"L{x.lineno}: bare assert" for x in ast.walk(tree)
            if isinstance(x, ast.Assert) and x.msg is None],
        "intent_docstring": intent_docstring(tree),
        "banners": [x for x in lines if BANNER_RE.match(x)],
        "path_hacks": [
            f"L{i}: {line.strip()}" for i, line in enumerate(lines, 1)
            if PATH_HACK_RE.match(line)
        ],
        "import_names": import_bloat(tree),
        "ruff": [f"L{x.line}: {x.code} {x.message}" for x in ruff],
    }
    issues["_max_cell"] = [str(max_cell)]
    issues["_max_cell_complexity"] = [str(max_complexity)]
    return issues


def intent_docstring(tree: ast.Module) -> list[str]:
    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return [] if isinstance(first.value.value, str) else ["missing"]
    return ["file should start with intent docstring"]


def import_bloat(tree: ast.Module) -> list[str]:
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [x.name for x in node.names if x.name != "*"]
            if len(names) > LIMITS["import_names"].target:
                issues.append(f"L{node.lineno}: {len(names)} imported names")
    return issues


def analyze_source(path: Path, source: str, ruff: list[RuffIssue]) -> Analysis:
    lines = source.splitlines()
    tree = ast.parse(source)
    raw = analyze(source)
    cc_map = {(x.name, x.lineno): x.complexity for x in cc_visit(source)}
    globals_ = module_values(tree)
    fn_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    fn_nodes = [x for x in ast.walk(tree) if isinstance(x, fn_types)]
    functions = [function_metric(x, lines, cc_map, globals_) for x in fn_nodes]
    issues = source_issues(tree, lines, ruff)
    return Analysis(
        path,
        raw.loc,
        raw.sloc,
        round(mi_visit(source, multi=True), 1),
        max((len(line) for line in lines), default=0),
        int(issues.pop("_max_cell")[0]),
        int(issues.pop("_max_cell_complexity")[0]),
        functions,
        ruff,
        issues,
    )



def metric_values(result: Analysis) -> dict[str, float]:
    hidden = sum(
        1
        for fn in result.functions
        if any("hidden global read" in reason for reason in fn.reasons)
    )
    shallow = shallow_functions(result.functions)
    return {
        "line_length": result.max_line,
        "cell_sloc": result.max_cell,
        "cell_complexity": result.max_cell_complexity,
        "impure_fns": sum(not fn.pure for fn in result.functions),
        "hidden_global_fns": hidden,
        "shallow_fns": len(shallow),
        "string_split_lists": len(result.issues["string_split_lists"]),
        "tuple_specs": len(result.issues["tuple_specs"]),
        "dense_comps": len(result.issues["dense_comps"]),
        "repeated_transforms": len(result.issues["repeated_transforms"]),
        "bare_asserts": len(result.issues["bare_asserts"]),
        "intent_docstring": len(result.issues["intent_docstring"]),
        "banners": len(result.issues["banners"]),
        "path_hacks": len(result.issues["path_hacks"]),
        "import_names": len(result.issues["import_names"]),
    }


is_protocol_hook = lambda n: n.startswith("visit_") or (n.startswith("__") and n.endswith("__"))


def shallow_functions(functions: list[FunctionMetric]) -> list[FunctionMetric]:
    return [fn for fn in functions if fn.shallow and not is_protocol_hook(fn.name)]


def score(result: Analysis) -> tuple[dict[str, float], list[str]]:
    details = score_functions(result.functions) | score_file(result)
    details |= {
        name: cost(name, val)
        for name, val in metric_values(result).items()
    }
    details["ruff"] = ruff_cost(result.ruff)
    hard = [name for name, value in details.items() if math.isinf(value)]
    return details, hard


def score_functions(functions: list[FunctionMetric]) -> dict[str, float]:
    return {
        "cyclomatic": sum(cost("cyclomatic", fn.cc) for fn in functions),
        "cognitive": sum(cost("cognitive", fn.cognitive) for fn in functions),
        "nesting": sum(cost("nesting", fn.nesting) for fn in functions),
        "fn_loc": sum(cost("fn_loc", fn.loc) for fn in functions),
    }


def score_file(result: Analysis) -> dict[str, float]:
    return {
        "line_length": cost("line_length", result.max_line),
        "cell_sloc": cost("cell_sloc", result.max_cell),
        "cell_complexity": cost(
            "cell_complexity",
            result.max_cell_complexity,
        ),
    }


def hints(result: Analysis) -> list[str]:
    out = hard_ruff_hints(result.ruff)
    out += function_hints(result.functions)
    out += shallow_hints(result.functions)
    out += impure_hints(result.functions)
    out += issue_hints(result.issues)
    if result.max_line > LIMITS["line_length"].target:
        out.append(f"max line={result.max_line}: wrap expression")
    return out


def hard_ruff_hints(issues: list[RuffIssue]) -> list[str]:
    return [
        f"RUFF HARD: L{issue.line}: {issue.code} {issue.message}"
        for issue in issues
        if math.isinf(ruff_issue_cost(issue))
    ]


def impure_hints(functions: list[FunctionMetric]) -> list[str]:
    impure = [fn for fn in functions if not fn.pure]
    if len(impure) <= LIMITS["impure_fns"].target:
        return []
    return [f"IMPURE {fn.name}:{fn.line}: {fn.reasons[0]}" for fn in impure]


def shallow_hints(functions: list[FunctionMetric]) -> list[str]:
    shallow = shallow_functions(functions)
    if len(shallow) <= LIMITS["shallow_fns"].target:
        return []
    return [
        f"SHALLOW {fn.name}:{fn.line}: {fn.shallow_reason}"
        for fn in shallow
    ]


def function_hints(functions: list[FunctionMetric]) -> list[str]:
    out: list[str] = []
    for fn in functions:
        if fn.cc > LIMITS["cyclomatic"].target:
            out.append(f"{fn.name}:{fn.line} CC={fn.cc}: simplify")
        if fn.cognitive > LIMITS["cognitive"].target:
            out.append(f"{fn.name}:{fn.line} cognitive={fn.cognitive}: flatten")
    return out


def issue_hints(issues: dict[str, list[str]]) -> list[str]:
    labels = {
        "large_cells": "CELL",
        "complex_cells": "CELL COMPLEXITY",
        "string_split_lists": "SPLIT",
        "tuple_specs": "TUPLE DSL",
        "dense_comps": "DENSE COMP",
        "repeated_transforms": "REPEATED TRANSFORM",
        "bare_asserts": "ASSERT",
        "intent_docstring": "DOCSTRING",
        "path_hacks": "PATH",
        "import_names": "IMPORT",
        "ruff": "RUFF",
    }
    return [f"{label}: {issue}" for key, label in labels.items()
            for issue in issues[key][:3]]


def parse_ruff(stdout: str) -> list[RuffIssue]:
    if not stdout.strip(): return []
    try: data = json.loads(stdout)
    except json.JSONDecodeError:
        return [RuffIssue(0, "RUFF", stdout.strip())]
    return [RuffIssue(x["location"]["row"], x["code"], x["message"]) for x in data]


def ruff_cost(issues: list[RuffIssue]) -> float:
    costs = [ruff_issue_cost(issue) for issue in issues]
    return math.inf if any(math.isinf(val) for val in costs) else sum(costs)


def ruff_issue_cost(issue: RuffIssue) -> float:
    if issue.code.startswith("F") and issue.code not in {"F401", "F841"}:
        return math.inf
    return RUFF_WEIGHTS.get(issue.code, 1.0)


def summary_table(result: Analysis) -> Table:
    table = Table(title=f"File: {result.path.name}", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    values = metric_values(result)
    rows = {
        "Total LOC": result.total_loc,
        "SLOC": result.sloc,
        "Functions": len(result.functions),
        "Maintainability Index": result.mi,
        "Max Line Length": result.max_line,
        "Max Cell SLOC": result.max_cell,
        "Max Cell Complexity": result.max_cell_complexity,
        "Impure Functions": values["impure_fns"],
        "Hidden Global Fns": values["hidden_global_fns"],
        "Shallow Functions": values["shallow_fns"],
    }
    for name, value in rows.items():
        table.add_row(name, str(value))
    for key in display_issue_keys:
        label = key.replace("_", " ").title()
        table.add_row(label, str(len(result.issues[key])))
    return table


display_issue_keys = "large_cells", "complex_cells", "string_split_lists", "tuple_specs", "dense_comps", "repeated_transforms", "bare_asserts", "intent_docstring", "banners", "path_hacks", "import_names", "ruff"


def score_table(details: dict[str, float]) -> Table:
    table = Table(title="Score Breakdown", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Cost", justify="right")
    for name, value in sorted(details.items(), key=lambda x: -x[1]):
        label = "INF" if math.isinf(value) else f"{value:.2f}"
        table.add_row(name, label)
    total = sum(details.values())
    table.add_row("TOTAL", "INF" if math.isinf(total) else f"{total:.2f}")
    return table


def function_table(result: Analysis) -> Table:
    table = Table(title="Per-Function Metrics", show_header=True)
    for col in ("Function", "Line", "LOC", "Impl", "Args", "Depth", "CC", "Cogn", "Nest", "Pure", "Shallow"): table.add_column(col)
    for fn in sorted(result.functions, key=lambda x: -x.loc):
        reported_shallow = fn.shallow and not is_protocol_hook(fn.name)
        table.add_row(
            fn.name,
            str(fn.line),
            str(fn.loc),
            str(fn.impl_loc),
            str(fn.params),
            f"{fn.depth:.1f}",
            str(fn.cc),
            str(fn.cognitive),
            str(fn.nesting),
            "Y" if fn.pure else "N",
            "Y" if reported_shallow else "",
        )
    return table


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: uv run --script codestyle.py <file.py>", file=sys.stderr)
        return 2
    target = Path(argv[1])
    if not target.exists():
        print(f"File not found: {target}", file=sys.stderr)
        return 2
    source = target.read_text()
    ruff = subprocess.run(["uvx", "ruff", "check", "--select", "I,F401,F841", "--output-format", "json", str(target)], capture_output=True, text=True)
    result = analyze_source(target, source, parse_ruff(ruff.stdout))
    details, hard = score(result)
    console = Console()
    reports = [
        summary_table(result),
        score_table(details),
        function_table(result),
    ]
    for item in reports:
        console.print(item)
    for hint in hints(result):
        console.print(f"  > {hint}")
    total = sum(details.values())
    if not hard and not total: console.print("FEASIBLE (score=0.00)")
    else: console.print(f"INFEASIBLE (score={total:.2f}) hard={hard}")
    return 1 if hard or total > 0 else 0

if __name__ == "__main__": sys.exit(main(sys.argv))

