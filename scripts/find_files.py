"""Use case 4: file discovery, in two stages (the shape hermes-jev-skills uses for retrieval).

    python find_files.py "how is login token refresh handled" [--root .] [--top 8]
1. keyword walk gathers up to 100 candidates;
2. Jev scores each from a short excerpt (20 files per request), keeping the top 10;
3. Jev re-judges those 10 from long excerpts, and the final order blends both.
Prints "percent  path", best first. Falls back to keyword order if Jev is unavailable.
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import ask, score, sensitive_path  # noqa: E402

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", ".idea"}
STOP = set("the and for with that this from into how what where which does about file files code find show all any are was you your get its why who when not".split())
POOL, WIDE, FINALISTS = 100, 20, 10  # candidates, files per stage-1 request, files re-judged in stage 2
WIDE_CHARS, DEEP_CHARS = 700, 2500
LEVELS = ["irrelevant", "weakly related", "related", "relevant", "essential to the query"]
Q1 = "How relevant is file {} to the query?"
Q2 = "How much is file {} the place where the thing the query asks about is implemented or defined?"


def keywords(query):
    words = []
    for w in re.findall(r"[a-z0-9_]{3,}", query.lower()):
        if w not in STOP and w not in words:
            words.append(w)
    return words[:8]


def candidates(root, kws):
    # ponytail: pure-Python walk; switch to ripgrep if a repo has 50k+ files
    hits = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        for f in fn:
            p = Path(dp) / f
            if sensitive_path(p):
                continue
            try:
                if p.stat().st_size > 300_000:
                    continue
                text = p.read_text(encoding="utf-8")  # binary files raise and are skipped
            except (OSError, UnicodeDecodeError):
                continue
            rel = str(p.relative_to(root)).lower()
            n = sum(text.lower().count(k) for k in kws) + 5 * sum(k in rel for k in kws)
            if n:
                hits.append((n, p, text))
    hits.sort(key=lambda h: -h[0])
    return hits[:POOL]


def excerpt(text, kws, limit):
    """The file's opening lines plus the lines that match the most keywords, each with a line of context."""
    lines = [l[:160] for l in text.splitlines()]
    hit = [sum(k in l.lower() for k in kws) for l in lines]
    keep = {i for i, l in enumerate(lines[:3]) if l.strip()}
    size = sum(len(lines[i]) for i in keep)
    for i in sorted(range(len(lines)), key=lambda i: -hit[i]):
        if hit[i] == 0 or size >= limit:
            break
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(lines) and j not in keep and lines[j].strip():
                keep.add(j)
                size += len(lines[j]) + 1
    return "\n".join(lines[i] for i in sorted(keep))[:limit]


def judge(query, kws, cands, limit, size, question):
    """{path: relevance 0..1} for every candidate, or None if any request fails."""
    def one(chunk):
        state = {"query": query, "files": {f"F{j}": f"{p}\n{excerpt(t, kws, limit)}" for j, (_, p, t) in enumerate(chunk)}}
        a = ask(state, {f"f{j}": score(question.format(f"F{j}"), LEVELS) for j in range(len(chunk))}, timeout=20)
        return None if not a else {str(p): a[f"f{j}"]["score"] / (len(LEVELS) - 1) for j, (_, p, _) in enumerate(chunk)}

    chunks = [cands[i:i + size] for i in range(0, len(cands), size)]
    with ThreadPoolExecutor(5) as ex:
        parts = list(ex.map(one, chunks))
    return None if any(p is None for p in parts) else {k: v for part in parts for k, v in part.items()}


def rank(query, cands, kws):
    s1 = judge(query, kws, cands, WIDE_CHARS, WIDE, Q1)
    if s1 is None:
        return None
    top = sorted(cands, key=lambda c: -s1[str(c[1])])[:FINALISTS]
    s2 = judge(query, kws, top, DEEP_CHARS, FINALISTS, Q2)
    if s2 is None:  # stage 2 failed: stage 1 alone is still a ranking
        return {k: v * 100 for k, v in s1.items()}
    return {str(p): (0.3 * s1[str(p)] + 0.7 * s2[str(p)]) * 100 for _, p, _ in top}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--root", default=".")
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    root = Path(a.root).resolve()
    kws = keywords(a.query)
    cands = candidates(root, kws) if kws else []
    if not cands:
        print("no keyword candidates", file=sys.stderr)
        return 1
    scores = rank(a.query, cands, kws)
    if scores is None:
        print("Jev unavailable: keyword order only", file=sys.stderr)
        scores = {str(p): float(n) for n, p, _ in cands}
    for path, s in sorted(scores.items(), key=lambda kv: -kv[1])[: a.top]:
        print(f"{s:5.0f}  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
