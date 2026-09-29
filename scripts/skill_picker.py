"""Use case 3: UserPromptSubmit hook. Jev picks the one installed skill that fits the prompt.

The skill listing is still in Claude's context (a hook cannot remove it), so this is a
pointer, not a token saver. Mode shadow (default) logs the pick without injecting it; active injects it.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import ask, choice, hook_in, log, mode, noul  # noqa: E402

MIN_P = float(os.environ.get("JEV_SKILL_MIN", "0.6"))
TOP = 40  # the shortlist sent to Jev; a choice question allows 255 but the prompt is cheaper when small
WORD = re.compile(r"[a-z0-9]{3,}")


def meta(path):
    fm = re.match(r"---\s*\n(.*?)\n---", path.read_text(encoding="utf-8", errors="replace")[:4000], re.S)
    if not fm:
        return None
    n = re.search(r"^name:\s*(.+)$", fm.group(1), re.M)
    d = re.search(r"^description:\s*(.*?)(?=^\S+:|\Z)", fm.group(1), re.M | re.S)
    if not (n and d):
        return None
    return n.group(1).strip().strip("\"'"), " ".join(d.group(1).split()).lstrip(">|- ").strip("\"'")[:300]


def roster(cwd):
    skills = {}
    for base in (Path.home() / ".claude" / "skills", Path(cwd) / ".claude" / "skills"):  # project wins
        for p in base.glob("*/SKILL.md"):
            try:
                m = meta(p)
            except OSError:
                continue
            if m:
                skills[m[0]] = m[1]
    return skills


def shortlist(prompt, skills):
    q = set(WORD.findall(prompt.lower()))
    scored = []
    for n, d in skills.items():
        s = 3 * len(q & set(WORD.findall(n.lower()))) + len(q & set(WORD.findall(d.lower())))
        if s:
            scored.append((s, n, d))
    scored.sort(reverse=True)
    return {n: d for _, n, d in scored[:TOP]}


def main():
    if mode() == "off":
        return
    ev = hook_in()
    prompt = (ev.get("prompt") or "").strip()
    if len(prompt) < 15 or prompt.startswith("/"):
        return
    short = shortlist(prompt, roster(ev.get("cwd") or "."))
    if not short:
        return
    options = {**short, "none": "No listed skill clearly applies to this request"}
    a = ask(prompt, {"skill": choice("Which single skill is best suited to this request?", options)})
    if not a:
        return
    pick = a["skill"]["choice"]
    p = a["skill"]["probabilities"].get(pick, 0)
    shadow = mode() != "active"
    if pick != "none" and p >= MIN_P:
        # stage 2: the pick must also pass a yes/no on its full description, and "is any skill needed" must be yes
        second = ask({"request": prompt, "skill": f"{pick}: {short[pick]}"}, {
            "needed": noul("Doing this request well requires the specialised instructions of the listed skill"),
            "right": noul("The listed skill is the right procedure for this request")})
        if second and min(second["needed"]["noul"], second["right"]["noul"]) < MIN_P:
            log("skill_pick", pick=pick, p=round(p, 2), vetoed=True)
            return
    log("skill_pick", pick=pick, p=round(p, 2), shadow=shadow)
    if pick == "none" or p < MIN_P or shadow:
        return
    note = f"Jev skill pick: `{pick}` (p={p:.2f}). Load it with the Skill tool if it fits."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a hook must never break the prompt
        log("hook_error", hook="skill_picker", err=repr(e)[:120])
