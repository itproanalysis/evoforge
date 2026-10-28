"""Unified-diff application (stdlib). Hunk counts are recomputed from the body when they
disagree; context must match exactly. A hunk applies exactly or not at all."""
from __future__ import annotations

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
NULL = "/dev/null"


class PatchError(ValueError):
    pass


def _header_path(line: str) -> str:
    p = line[4:].split("\t", 1)[0].strip()
    if p == NULL:
        return p
    return p[2:] if p.startswith(("a/", "b/")) else p


def _is_file_pair(lines: list[str], i: int) -> bool:
    return (
        lines[i].startswith("--- ")
        and i + 1 < len(lines)
        and lines[i + 1].startswith("+++ ")
    )


def _is_boundary(lines: list[str], i: int) -> bool:
    ln = lines[i]
    if ln.startswith("@@ ") or ln.startswith("diff --git"):
        return True
    if ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
        return True
    return False


def _is_body_line(ln: str) -> bool:
    if ln == "" or ln.startswith("\\"):
        return True
    return ln[0] in (" ", "+", "-")


def _split_lines(diff: str) -> list[str]:
    lines = diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _parse_hunk_body(body_lines: list[str], hdr: str) -> tuple[list[str], list[str]]:
    old_l: list[str] = []
    new_l: list[str] = []
    last: list[str] = []
    for body in body_lines:
        if body.startswith("\\"):  # "\ No newline at end of file" -> previous line had none
            for side in last:
                side[-1] = side[-1][:-1] if side[-1].endswith("\n") else side[-1]
            continue
        tag, text = (body[0], body[1:]) if body else (" ", "")
        if tag == " ":
            old_l.append(text + "\n"); new_l.append(text + "\n")
            last = [old_l, new_l]
        elif tag == "-":
            old_l.append(text + "\n"); last = [old_l]
        elif tag == "+":
            new_l.append(text + "\n"); last = [new_l]
        else:
            raise PatchError(f"unexpected line in hunk: {body[:40]!r}")
    return old_l, new_l


def _parse_strict(diff: str) -> list[dict]:
    """[{old, new, path, hunks: [(old_start, old_lines, new_lines)]}] in diff order."""
    lines = _split_lines(diff)
    files: list[dict] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _is_file_pair(lines, i):
            old, new = _header_path(ln), _header_path(lines[i + 1])
            files.append({"old": old, "new": new, "path": old if new == NULL else new, "hunks": []})
            i += 2
            continue
        m = _HUNK.match(ln)
        if not m:
            if ln.startswith("@@ "):
                raise PatchError(f"malformed hunk header: {ln[:40]!r}")
            i += 1  # diff --git / index / mode lines
            continue
        if not files:
            raise PatchError("hunk before any file header")
        a = int(m.group(1))
        a_n = 1 if m.group(2) is None else int(m.group(2))
        b_n = 1 if m.group(4) is None else int(m.group(4))
        old_l: list[str] = []
        new_l: list[str] = []
        last: list[str] = []  # which sides the previous line went to
        i += 1
        while i < len(lines) and (a_n > 0 or b_n > 0 or lines[i].startswith("\\")):
            if _is_boundary(lines, i):
                raise PatchError(f"hunk @@ -{m.group(1)} line counts do not match its body")
            body = lines[i]
            if body.startswith("\\"):  # "\ No newline at end of file" -> previous line had none
                for side in last:
                    side[-1] = side[-1][:-1] if side[-1].endswith("\n") else side[-1]
                i += 1
                continue
            tag, text = (body[0], body[1:]) if body else (" ", "")
            if tag == " ":
                old_l.append(text + "\n"); new_l.append(text + "\n")
                last, a_n, b_n = [old_l, new_l], a_n - 1, b_n - 1
            elif tag == "-":
                old_l.append(text + "\n"); last, a_n = [old_l], a_n - 1
            elif tag == "+":
                new_l.append(text + "\n"); last, b_n = [new_l], b_n - 1
            else:
                raise PatchError(f"unexpected line in hunk: {body[:40]!r}")
            if a_n < 0 or b_n < 0:
                raise PatchError(f"hunk @@ -{m.group(1)} line counts do not match its body")
            i += 1
        if a_n or b_n:
            raise PatchError(f"truncated hunk @@ -{m.group(1)} in {files[-1]['path']}")
        if i < len(lines) and not _is_boundary(lines, i) and _is_body_line(lines[i]):
            raise PatchError(f"hunk @@ -{m.group(1)} line counts do not match its body")
        files[-1]["hunks"].append((a, old_l, new_l))
    if not files:
        raise PatchError("no file headers in diff")
    return files


def _parse_recount(diff: str) -> list[dict]:
    """Structural re-parse: hunk body runs to the next boundary; counts recomputed."""
    lines = _split_lines(diff)
    files: list[dict] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _is_file_pair(lines, i):
            old, new = _header_path(ln), _header_path(lines[i + 1])
            files.append({"old": old, "new": new, "path": old if new == NULL else new, "hunks": []})
            i += 2
            continue
        m = _HUNK.match(ln)
        if not m:
            if ln.startswith("@@ "):
                raise PatchError(f"malformed hunk header: {ln[:40]!r}")
            i += 1  # diff --git / index / mode lines
            continue
        if not files:
            raise PatchError("hunk before any file header")
        a = int(m.group(1))
        j = i + 1
        while j < len(lines) and not _is_boundary(lines, j):
            j += 1
        body_lines = lines[i + 1:j]
        while body_lines and body_lines[-1] == "" and j >= len(lines):
            body_lines.pop()
        old_l, new_l = _parse_hunk_body(body_lines, ln)
        files[-1]["hunks"].append((a, old_l, new_l))
        i = j
    if not files:
        raise PatchError("no file headers in diff")
    return files


def _parse(diff: str, recount: bool = True) -> list[dict]:
    """[{old, new, path, hunks: [(old_start, old_lines, new_lines)]}] in diff order."""
    try:
        return _parse_strict(diff)
    except PatchError:
        if not recount:  # harness /1: strict counts only
            raise
        return _parse_recount(diff)


def paths_in_diff(diff: str) -> list[str]:
    return [f["path"] for f in _parse(diff)]


def _apply(path: str, orig: list[str], hunks: list) -> list[str]:
    out: list[str] = []
    cursor = 0
    for n, (a, old_l, new_l) in enumerate(hunks, 1):
        want = a - 1 if old_l else a
        if old_l and orig[want:want + len(old_l)] != old_l:
            hits = [k for k in range(cursor, len(orig) - len(old_l) + 1) if orig[k:k + len(old_l)] == old_l]
            if len(hits) != 1:
                raise PatchError(f"hunk {n} does not apply to {path}"
                                 + (" (ambiguous context)" if hits else ""))
            want = hits[0]
        if want < cursor or want > len(orig):
            raise PatchError(f"hunk {n} does not apply to {path} (out of order or past end)")
        out += orig[cursor:want] + new_l
        cursor = want + len(old_l)
    return out + orig[cursor:]


def apply_unified_diff(files: dict[str, str | None], diff: str, recount: bool = True) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for f in _parse(diff, recount):
        path = f["path"]
        cur = result[path] if path in result else files.get(path)
        if f["old"] == NULL and cur is not None:
            raise PatchError(f"cannot add {path}: file already exists")
        if f["old"] != NULL and cur is None:
            raise PatchError(f"cannot modify {path}: file is absent")
        new = _apply(path, [] if cur is None else cur.splitlines(keepends=True), f["hunks"])
        if f["new"] == NULL:
            if new:
                raise PatchError(f"delete of {path} leaves {len(new)} line(s)")
            result[path] = None
        else:
            result[path] = "".join(new)
    return result
