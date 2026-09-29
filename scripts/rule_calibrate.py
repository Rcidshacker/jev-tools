"""Replay recent commits against this project's rules and report which rules would fire, and how often.

    python rule_calibrate.py [--commits 15] [--hunks 30]      (run inside the repo)
Do this before turning enforcement on. Verdicts follow abide's calibration: a rule that fires on
60%+ of real changes is noisy, one that never gets decisive is weak, one that never comes close is quiet.
"""
import argparse
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import ask, noul, sensitive_path  # noqa: E402
from rule_enforcer import MAX_DIFF, SKIP_EXT, THRESH, extract_rules, rule_files  # noqa: E402

MIN_HUNKS = 5


def hunks(commits, limit):
    out = subprocess.run(["git", "log", f"-{commits}", "--no-merges", "-p", "--format=", "--unified=3"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    found = []
    for part in re.split(r"^diff --git ", out, flags=re.M)[1:]:
        name = part.split("\n", 1)[0].split(" b/")[-1]
        if Path(name).suffix.lower() not in SKIP_EXT and not sensitive_path(name) and len(part) > 80:
            found.append((name, part[:MAX_DIFF]))
    return found[:limit]


def verdict(ps):
    if len(ps) < MIN_HUNKS:
        return "skipped"
    fired = sum(p >= THRESH for p in ps)
    if fired / len(ps) >= 0.6:
        return "noisy"
    if max(ps) < 0.5:
        return "quiet"  # never came close to firing: either the code follows it, or the rule is too vague to notice
    if max(ps) < 0.7 and statistics.median(ps) >= 0.25:
        return "weak"
    return "decisive"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commits", type=int, default=15)
    ap.add_argument("--hunks", type=int, default=30)
    a = ap.parse_args()
    rules = extract_rules(rule_files(Path.cwd() / "x", Path.cwd()))
    changes = hunks(a.commits, a.hunks)
    if not rules or not changes:
        sys.exit("need rules (CLAUDE.md / AGENTS.md bullets) and recent code commits")
    qs = {f"r{i}": noul(f"This change violates the rule: {t}") for i, (t, _) in enumerate(rules)}

    def one(c):
        ans = ask(f"File: {c[0]}\n\n{c[1]}", qs, timeout=30)
        return [ans[f"r{i}"]["noul"] for i in range(len(rules))] if ans else None

    with ThreadPoolExecutor(4) as ex:
        rows = [r for r in ex.map(one, changes) if r]
    print(f"{len(rows)} of {len(changes)} hunks judged against {len(rules)} rules (fire level {THRESH})\n")
    stats = []
    for i, (text, _) in enumerate(rules):
        ps = [r[i] for r in rows]
        stats.append((sum(p >= THRESH for p in ps), statistics.median(ps) if ps else 0, max(ps, default=0), verdict(ps), text))
    for fired, med, mx, v, text in sorted(stats, reverse=True):
        print(f"{fired:3d}/{len(rows):<3d} median {med:.2f} max {mx:.2f}  {v:9} {text[:80]}")


if __name__ == "__main__":
    main()
