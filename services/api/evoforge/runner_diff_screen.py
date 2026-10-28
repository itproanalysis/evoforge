"""Conservative static report-tampering tripwires; not a sandbox or proof."""
import re

_RULES = (
    ("process_exit_or_shutdown_hook", r"\b(?:atexit|faulthandler|_exit)\b|\b(?:os|sys)\s*\.\s*(?:exit|_exit)\s*\(|\bfrom\s+sys\s+import\s+.*\bexit\b"),
    ("pytest_execution_control", r"\b_pytest\b|\bpytest\s*\.\s*(?:main|exit|hookimpl|Session|Config)\b"),
    ("report_path_or_write", r"(?i)junit|--junitxml|(?:open|write_text|write_bytes|write|rename|replace)\s*\([^\n]*[\"'][^\"'\n]*\.xml[\"']"),
    ("interpreter_rebinding", r"\b(?:builtins|__builtins__)\b\s*(?:=|\[[^\n]*\]\s*=|\.\w+\s*=|\.__dict__\s*\.\s*(?:update|clear)\s*\()|\bsys\s*\.\s*modules\s*(?:\[[^\n]*\]\s*=|\.(?:update|pop|clear|setdefault)\s*\(|=)|\bdel\s+sys\s*\.\s*modules\b"),
)


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
    for code, pattern in _RULES:
        if any(re.search(pattern, snippet) for snippet in snippets):
            risks.add(code)
    return sorted(risks)
