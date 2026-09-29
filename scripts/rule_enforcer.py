"""Use case 7: PreToolUse hook on Edit|Write|MultiEdit. Blocks an edit that Jev says breaks a project rule.

Rules come from CLAUDE.md / AGENTS.md / .claude/rules/*.md between the edited file and the session cwd
(never from ~/.claude). One noul question per rule, all in one request. Fails open on any error.
JEV_THRESHOLD (default 0.80) sets the block level. Mode shadow (default) logs without blocking; active blocks; off does nothing.
"""
import difflib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import ask, hook_in, log, mode, noul, sensitive_path  # noqa: E402

THRESH = float(os.environ.get("JEV_THRESHOLD", "0.80"))
CONFIRM = float(os.environ.get("JEV_CONFIRM", "0.70"))
ENFORCE = mode() == "active"
MAX_RULES, MAX_DIFF = 20, 8000  # input tokens grow with rules x diff, so both are capped
RULE = re.compile(r"\b(never|always|must|do not|don't|should not|shouldn't|avoid|only|no)\b", re.I)
STRONG = re.compile(r"\b(never|must|do not|don't|always)\b", re.I)
BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")
SKIP_EXT = {".md", ".txt", ".json", ".lock", ".svg", ".png", ".jpg", ".ico", ".csv"}


def rule_files(target, cwd):
    home_claude = (Path.home() / ".claude").resolve()
    d, root = target.parent.resolve(), cwd.resolve()
    inside = d == root or root in d.parents
    found = []
    while True:
        found += [d / "CLAUDE.md", d / "AGENTS.md", *sorted((d / ".claude" / "rules").glob("*.md"))]
        if not inside or d == root or d.parent == d:
            break
        d = d.parent
    return [f for f in found if f.is_file() and home_claude not in f.resolve().parents]


def extract_rules(files):
    seen, out = set(), []
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = BULLET.match(line)
            text = m.group(1).strip() if m else ""
            if 15 <= len(text) <= 300 and RULE.search(text) and text.lower() not in seen:
                seen.add(text.lower())
                out.append((text, f.name))
    out.sort(key=lambda r: not STRONG.search(r[0]))  # stable: strong wording first when capping
    return out[:MAX_RULES]


def diff_of(tool, ti):
    path = ti["file_path"]
    if tool == "Write":
        try:
            old = Path(path).read_text(encoding="utf-8")
        except OSError:
            old = ""
        pairs = [(old, ti.get("content", ""))]
    elif tool == "MultiEdit":
        pairs = [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    else:
        pairs = [(ti.get("old_string", ""), ti.get("new_string", ""))]
    return "".join(
        "".join(difflib.unified_diff(o.splitlines(True), n.splitlines(True), "before", "after")) for o, n in pairs
    )


def confirmed(state, rule):
    """Second look at a flagged rule with strict wording; None if Jev is down (the first verdict then stands)."""
    a = ask(state, {"c": noul(f"The changed lines clearly and directly break this rule: {rule}",
                              true="the added or changed code itself does what the rule forbids",
                              false="the change is compatible with the rule, or the rule does not apply to this kind of code")},
            timeout=10)
    return a["c"]["noul"] if a else None


def main():
    if mode() == "off":
        return
    ev = hook_in()
    tool, ti = ev.get("tool_name"), ev.get("tool_input") or {}
    if tool not in ("Edit", "Write", "MultiEdit") or not ti.get("file_path"):
        return
    path = Path(ti["file_path"])
    if path.suffix.lower() in SKIP_EXT or ".claude" in path.parts or sensitive_path(path):
        return
    diff = diff_of(tool, ti)
    if len(diff.strip()) < 15:
        return
    rules = extract_rules(rule_files(path, Path(ev.get("cwd") or ".")))
    if not rules:
        return
    state = f"File: {path.name}\n\n{diff[:MAX_DIFF]}"
    questions = {f"r{i}": noul(f"This change violates the rule: {t}") for i, (t, _) in enumerate(rules)}
    answers = ask(state, questions, timeout=15)
    if not answers:
        return  # fail open
    p, text, src = max((answers[f"r{i}"]["noul"], t, s) for i, (t, s) in enumerate(rules))
    c = confirmed(state, text) if p >= THRESH else None  # a strict second look, only for the rare hit
    log("rule_check", file=path.name, rules=len(rules), top=round(p, 2), confirm=None if c is None else round(c, 2),
        rule=text[:80], enforce=ENFORCE)
    if p >= THRESH and ENFORCE and (c is None or c >= CONFIRM):
        reason = f"Jev flagged a rule violation ({p:.0%}), from {src}: \"{text}\". Revise the edit so it follows the rule."
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("hook_error", hook="rule_enforcer", err=repr(e)[:120])
