"""Conservative static report-tampering tripwires; not a sandbox or proof."""
import ast
import re

_RULES = (
    ("process_exit_or_shutdown_hook", r"\b(?:atexit|faulthandler|_exit)\b|\bos\s*\.\s*_exit\s*\("),
    ("pytest_execution_control", r"\b_pytest\b|\bpytest\s*\.\s*(?:main|exit|hookimpl|Session|Config)\b"),
    ("report_path_or_write", r"(?i)junit|--junitxml|(?:open|write_text|write_bytes|write|rename|replace)\s*\([^\n]*[\"'][^\"'\n]*\.xml[\"']"),
    ("interpreter_rebinding", r"\b(?:builtins|__builtins__)\b\s*(?:=|\[[^\n]*\]\s*=|\.\w+\s*=|\.__dict__\s*\.\s*(?:update|clear)\s*\()|\bsys\s*\.\s*modules\s*(?:\[[^\n]*\]\s*=|\.(?:update|pop|clear|setdefault)\s*\(|=)|\bdel\s+sys\s*\.\s*modules\b"),
)


def _import_exit_risk(source: str) -> bool | None:
    """None means a partial hunk mentions exit but its execution scope is unknown."""
    if not re.search(r"\bexit\b", source):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    modules, names = {"sys"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "sys")
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            names.update(a.asname or a.name for a in node.names if a.name == "exit")
    class Visitor(ast.NodeVisitor):
        found = False
        def visit_Call(self, node):
            fn = node.func
            if ((isinstance(fn, ast.Name) and fn.id in names) or
                    (isinstance(fn, ast.Attribute) and fn.attr == "exit" and
                     isinstance(fn.value, ast.Name) and fn.value.id in modules)):
                self.found = True
            self.generic_visit(node)
        def visit_FunctionDef(self, node):
            # Defaults/decorators are evaluated when a function is defined.
            for item in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults, node.returns,
                         *(a.annotation for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                                                 node.args.vararg, node.args.kwarg] if a is not None)]:
                if item is not None:
                    self.visit(item)
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_Lambda(self, node):
            for item in [*node.args.defaults, *node.args.kw_defaults]:
                if item is not None:
                    self.visit(item)
        def visit_If(self, node):
            test = node.test
            main_guard = (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                          and test.left.id == "__name__" and len(test.ops) == 1
                          and isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1
                          and isinstance(test.comparators[0], ast.Constant)
                          and test.comparators[0].value == "__main__")
            if main_guard:
                for item in node.orelse:
                    self.visit(item)
            else:
                self.generic_visit(node)
    visitor = Visitor()
    visitor.visit(tree)
    return visitor.found


def report_tampering_risks(diff: str, tests: list | None = None) -> list[str]:
    """Inspect added lines and visible snippets, without executing candidate code.

    Reasons are fixed codes so neither source nor sensitive strings enter errors.
    Aliasing, dynamic construction and arbitrary same-UID attacks can bypass
    static tripwires; independent observation is still required.
    """
    added, risks = [], set()
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split("\t", 1)[0].strip('"').replace("\\", "/")
            name = path.rsplit("/", 1)[-1]
            if name in {"conftest.py", "sitecustomize.py", "usercustomize.py"} or name.endswith(".pth"):
                risks.add("test_environment_control_file")
        elif line.startswith("+"):
            added.append(line[1:])
    snippets = ["\n".join(added)]
    snippets.extend(t.get("code", "") for t in (tests or []) if isinstance(t, dict) and isinstance(t.get("code"), str))
    for snippet in snippets:
        risk = _import_exit_risk(snippet)
        if risk is True:
            risks.add("process_exit_at_import")
        elif risk is None:
            risks.add("process_exit_scope_unknown")
    for code, pattern in _RULES:
        if any(re.search(pattern, snippet) for snippet in snippets):
            risks.add(code)
    return sorted(risks)
