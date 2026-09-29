"""Use case 6: browser navigation. Jev picks the next element toward a goal; Claude only executes and judges.

stdin  {"goal": str, "url": str, "elements": [{"ref","role","name"}], "history": [str]}
stdout {"action": "click"|"type"|"done"|"blocked"|"unsure"|"error", "ref": str, "p": float}
Exit 0 unless action is "error" (exit 1): then Claude should choose the step itself.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import ask, choice, hook_in, noul  # noqa: E402

ACT = 0.8
FLOOR = 0.65  # hermes-jev-skills measured wrong picks at 0.45-0.60 and right ones above 0.74
TYPING = {"textbox", "input", "searchbox", "combobox", "textarea"}
MAX_EL = 200  # a choice question allows 255 options


def decide(ans, els):
    """Pure: Jev answers + {ref: element} -> action."""
    pick = ans["next"]["choice"]
    # "nothing left to click" plus a likely-met goal is success; live runs showed goal_met wobbling around the bar
    if ans["goal_met"]["noul"] >= ACT or (pick == "none" and ans["goal_met"]["noul"] >= 0.5):
        return {"action": "done"}
    if ans["stuck"]["noul"] >= ACT or pick == "none" or pick not in els:
        return {"action": "blocked"}
    p = round(ans["next"]["probabilities"][pick], 2)
    if p < FLOOR:
        return {"action": "unsure", "ref": pick, "p": p}  # Claude chooses this step itself
    kind = "type" if els[pick].get("role") in TYPING else "click"
    return {"action": kind, "ref": pick, "p": p}


def main():
    req = hook_in()
    els = {e["ref"]: e for e in (req.get("elements") or [])[:MAX_EL]}
    if not req.get("goal") or not els:
        print(json.dumps({"action": "error", "why": "need goal and elements"}))
        return 1
    state = {
        "goal": req["goal"], "url": req.get("url", ""), "recent_actions": (req.get("history") or [])[-8:],
        "elements": [f'{r} {e.get("role", "")} {e.get("name", "")}'.strip() for r, e in els.items()],
    }
    options = {r: f'{e.get("role", "")}: {e.get("name", "")}' for r, e in els.items()}
    options["none"] = "No visible element moves toward the goal"
    ans = ask(state, {
        "next": choice("Which single element should be interacted with next to make progress toward the goal?", options),
        "goal_met": noul("The goal has already been achieved on the current page"),
        "stuck": noul("Recent actions repeat or make no progress, so the goal cannot be reached from here"),
    })
    if not ans:
        print(json.dumps({"action": "error", "why": "jev unavailable"}))
        return 1
    print(json.dumps(decide(ans, els)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
