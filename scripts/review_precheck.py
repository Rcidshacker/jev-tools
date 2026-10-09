"""Use case 5: review pre-check. Seven yes/no policy questions on a git diff decide fast vs full review.

    python review_precheck.py [git-diff-args, default HEAD]
Prints JSON {route, flags}. Exit 0 = fast (nothing flagged), 10 = full review needed.
Fails safe: Jev down, missing answers or a truncated diff all route to full review.
Edit review_policy.json to change the questions. JEV_PRECHECK_MIN (default 0.25) is the yes-probability that flags.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import SECRET, ask, backend, log, noul, state_chars  # noqa: E402

POLICY = Path(__file__).with_name("review_policy.json")
MIN_P = float(os.environ.get("JEV_PRECHECK_MIN", "0.25"))
MAX_DIFF = min(30000, state_chars() or 30000)  # a small local model reads far less; a cut diff routes to full review
DOCS = (".md", ".txt", ".rst")


DEPS = re.compile(r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|requirements[^/]*\.txt|pyproject\.toml|Pipfile(\.lock)?|"
                  r"poetry\.lock|go\.(mod|sum)|Cargo\.(toml|lock)|Gemfile(\.lock)?|pom\.xml|build\.gradle(\.kts)?|composer\.json)$", re.I)
SCHEMA_PATH = re.compile(r"migrat|schema|\.sql$|openapi|swagger|\.proto$|\.graphql$", re.I)
SCHEMA_LINE = re.compile(r"\b(?:ALTER|CREATE|DROP)\s+TABLE\b|\b(?:add|remove)_column\b", re.I)
AUTH = re.compile(r"\b(?:auth\w*|login|logout|password|passwd|jwt|oauth|permission\w*|csrf|rbac|is_?admin)\b", re.I)
SWALLOW = re.compile(r"except[^\n:]*:[ \t]*\n?[ \t]*pass\b|except\s*:|catch\s*(?:\([^)]*\))?\s*\{\s*\}|\|\|\s*true\b|2>\s*/dev/null")
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)(test_[^/]*|[^/]*\.(test|spec)\.\w+|[^/]*_test\.\w+)$", re.I)
TEST_OFF = re.compile(r"\b(?:xit|xdescribe)\b|\.(?:skip|only)\(|pytest\.mark\.skip|@(?:unittest\.)?skip", re.I)
ASSERT = re.compile(r"\bassert\w*|\bexpect\(")
FAST_MAX = 30  # changed lines; an offline "fast" is only ever claimed for a small diff with no pattern hit


def offline_flags(diff):
    """Pattern checks for six of the seven policy questions, no model. Returns (flags, changed_line_count).
    ponytail: regexes, not understanding; they miss anything phrased unusually. "risk" is judged by size alone."""
    sections = re.split(r"^diff --git ", diff, flags=re.M)[1:]
    flags, changed, added_all = [], 0, []
    for sec in sections:
        m = re.match(r"a/.* b/(.*)", sec)
        path = m.group(1) if m else ""
        lines = sec.splitlines()
        add = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]
        rem = [l[1:] for l in lines if l.startswith("-") and not l.startswith("---")]
        changed += len(add) + len(rem)
        added_all += add
        text = "\n".join(add)
        if DEPS.search(path):
            flags.append(f"dependencies (offline pattern): {path} changed")
        if SCHEMA_PATH.search(path) or SCHEMA_LINE.search(text):
            flags.append(f"schema (offline pattern): {path} looks like a schema, migration or API contract change")
        if TEST_PATH.search(path):
            if "deleted file mode" in sec:
                flags.append(f"tests (offline pattern): test file {path} deleted")
            elif TEST_OFF.search(text):
                flags.append(f"tests (offline pattern): {path} adds a skipped or exclusive test")
            elif sum(len(ASSERT.findall(l)) for l in rem) > sum(len(ASSERT.findall(l)) for l in add):
                flags.append(f"tests (offline pattern): {path} removes more assertions than it adds")
    text = "\n".join(added_all)
    if SECRET.search(text):
        flags.append("secrets (offline pattern): an added line has a secret-shaped string")
    if AUTH.search(text):
        flags.append("auth (offline pattern): added lines mention authentication or permissions")
    if SWALLOW.search(text):
        flags.append("errors (offline pattern): added lines swallow an error (bare except, empty catch, || true)")
    return flags, changed


def route_offline(diff):
    flags, changed = offline_flags(diff)
    if changed > FAST_MAX:
        flags.append(f"risk (offline): {changed} changed lines, too large to call fast without a model")
    return ("full" if flags else "fast"), flags


def route(answers, policy, truncated=False):
    if not answers:
        return "full", ["Jev unavailable"]
    flags = []
    for qid, text in policy.items():
        p = answers.get(qid, {}).get("noul", 1.0)  # a missing answer counts as flagged
        if p >= MIN_P:
            flags.append(f"{qid} ({p:.2f}): {text}")
    if truncated:
        flags.append("diff truncated")
    return ("full" if flags else "fast"), flags


def main():
    r = subprocess.run(["git", "diff", *(sys.argv[1:] or ["HEAD"])], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(r.stderr.strip() or "git diff failed")
    if not r.stdout.strip():
        print(json.dumps({"route": "fast", "flags": [], "note": "empty diff"}))
        return 0
    files = re.findall(r"^diff --git a/.* b/(.*)$", r.stdout, re.M)
    if files and all(f.lower().endswith(DOCS) for f in files):
        print(json.dumps({"route": "fast", "flags": [], "note": "docs only"}))
        return 0
    if backend() == "offline":  # chosen in setup: patterns only, and "fast" only for a small clean diff
        decision, flags = route_offline(r.stdout)
        log("precheck", route=decision, flags=len(flags), offline=True)
        print(json.dumps({"route": decision, "flags": flags, "note": "offline: pattern checks only, risky logic is not assessed"}, indent=2))
        return 0 if decision == "fast" else 10
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    diff = r.stdout[:MAX_DIFF]
    answers = ask(diff, {qid: noul(text) for qid, text in policy.items()}, timeout=20)
    decision, flags = route(answers, policy, truncated=len(r.stdout) > MAX_DIFF)
    if not answers:  # outage: still say what the patterns see, but the route stays full
        flags += offline_flags(r.stdout)[0]
    log("precheck", route=decision, flags=len(flags))
    print(json.dumps({"route": decision, "flags": flags}, indent=2))
    return 0 if decision == "fast" else 10


if __name__ == "__main__":
    sys.exit(main())
