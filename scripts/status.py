"""Is jev-tools actually alive? Hooks fail open, so a bad install looks exactly like a good one; this shows the difference.

    python status.py
Reports interpreter, key presence (never the value), mode, whether the skill hook is on, and what the decision log says.
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jevlib import mode  # noqa: E402


def log_path():
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    return Path(os.environ.get("JEV_LOG") or (Path(data) if data else Path.home() / ".jev-tools") / "log.jsonl")


def main():
    key = ("OPENJEV_API_KEY" if os.environ.get("OPENJEV_API_KEY") else "TYPESAFE_API_KEY" if os.environ.get("TYPESAFE_API_KEY")
           else "plugin api_key option" if os.environ.get("CLAUDE_PLUGIN_OPTION_API_KEY") else None)
    picker = (os.environ.get("JEV_SKILL_PICKER") or os.environ.get("CLAUDE_PLUGIN_OPTION_SKILL_PICKER") or "").lower() in ("1", "true", "yes", "on")
    print(f"python      {sys.version.split()[0]}")
    print(f"api key     {'found via ' + key if key else 'MISSING: every hook silently does nothing'}")
    print(f"mode        {mode()}  (shadow = log only, active = block/inject, off = nothing sent)")
    print(f"skill hook  {'on' if picker else 'off (opt-in: it sends every prompt)'}")
    p = log_path()
    print(f"log         {p}")
    if not p.exists():
        print("            no log yet: no hook has run since install, or none could write here")
        return 1
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    day = [r for r in rows if r.get("t", 0) > time.time() - 86400]
    print(f"last 24h    {dict(Counter(r['event'] for r in day)) or 'nothing'}")
    ok = [r for r in rows if r["event"] == "ask"]
    if ok:
        print(f"last ok     {int((time.time() - ok[-1]['t']) / 60)} min ago, {ok[-1].get('ms')} ms")
    errs = [r for r in day if r["event"] in ("ask_error", "hook_error", "no_key")]
    if errs:
        e = errs[-1]
        print(f"last error  {e['event']} {e.get('err', '')} {e.get('msg', '')}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
