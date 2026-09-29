"""OpenJev (Codiv) System One client for Claude Code hooks and skills. Stdlib only.

ask() never raises: it returns None on any failure, so each caller decides
whether to fail open (hooks) or fail safe (review pre-check).

Env: OPENJEV_API_KEY (or TYPESAFE_API_KEY, or the plugin's api_key option), optional OPENJEV_BASE_URL / TYPESAFE_BASE_URL.
JEV_MODE (or the plugin's mode option): shadow (default, log only) | active | off.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "api.codiv.ai"
MODEL = "openjev-latest"  # Codiv also accepts jev-latest as an alias
LOOPBACK = ("localhost", "127.0.0.1", "::1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a redirect would re-send the key to another host
        return None


_OPEN = urllib.request.build_opener(_NoRedirect)


def noul(instructions, true=None, false=None):
    """A yes/no question; true/false describe what each answer means, which steadies borderline cases."""
    q = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {"true": true or "", "false": false or ""}
    return q


def choice(instructions, options):
    return {"type": "choice", "instructions": instructions, "criteria": options}


def score(instructions, levels):
    return {"type": "score", "instructions": instructions, "criteria": levels}


def endpoint():
    base = (os.environ.get("OPENJEV_BASE_URL") or os.environ.get("TYPESAFE_BASE_URL") or f"https://{HOST}").rstrip("/")
    base = base.removesuffix("/v1")
    u = urllib.parse.urlsplit(base)
    # Hooks run unattended, so an env-injected base URL must not be able to redirect the key.
    if not (u.hostname in LOOPBACK or (u.hostname == HOST and u.scheme == "https")):
        raise ValueError(f"refusing to send the API key to {u.hostname!r}")
    return base + "/v1/systemone"


def log(event, **kw):
    try:
        data = os.environ.get("CLAUDE_PLUGIN_DATA")
        p = Path(os.environ.get("JEV_LOG") or (Path(data) if data else Path.home() / ".jev-tools") / "log.jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(time.time()), "event": event, **kw}) + "\n")
    except Exception:
        pass


def ask(state, questions, timeout=8, **extra):
    """POST one System One request. Returns {question_id: answer} or None on any failure."""
    key = (os.environ.get("OPENJEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
           or os.environ.get("CLAUDE_PLUGIN_OPTION_API_KEY"))
    if not key or not questions:
        return None
    t0 = time.monotonic()
    try:
        body = json.dumps({"model": MODEL, "state": state, "questions": questions, **extra}).encode()
        req = urllib.request.Request(
            endpoint(), body,
            # explicit User-Agent: the default Python-urllib one is 403'd by the edge in front of the API
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "jev-tools/0.1"},
            method="POST",
        )
        with _OPEN.open(req, timeout=timeout) as r:
            data = json.load(r)
        log("ask", n=len(questions), ms=int((time.monotonic() - t0) * 1000), tok=(data.get("usage") or {}).get("input_tokens"))
        return data["answers"]
    except Exception as e:
        log("ask_error", err=type(e).__name__, msg=str(e)[:120])
        return None


def mode():
    """shadow (default: log, never act) | active | off."""
    m = (os.environ.get("JEV_MODE") or os.environ.get("CLAUDE_PLUGIN_OPTION_MODE") or "shadow").strip().lower()
    return m if m in ("shadow", "active", "off") else "shadow"


def hook_in():
    """Parse the hook event from stdin; {} if it is missing or malformed."""
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        return json.load(sys.stdin)
    except Exception:
        return {}


if __name__ == "__main__":  # live smoke test: python jevlib.py
    a = ask("The build finished and all tests passed.", {"ok": noul("The text reports a successful outcome")})
    print("OK" if a and a["ok"]["noul"] > 0.5 else f"FAILED: {a}")
