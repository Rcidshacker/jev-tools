"""OpenJev (Codiv) System One client for Claude Code hooks and skills. Stdlib only.

ask() never raises: it returns None on any failure, so each caller decides
whether to fail open (hooks) or fail safe (review pre-check).

Env: OPENJEV_API_KEY (or TYPESAFE_API_KEY, or the plugin's api_key option), optional OPENJEV_BASE_URL / TYPESAFE_BASE_URL.
JEV_MODE (or the plugin's mode option): shadow (default, log only) | active | off.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOST = "api.codiv.ai"
MODEL = "openjev-latest"  # Codiv also accepts jev-latest as an alias
# Small encoder models run locally by `jev-tools-setup`: (context tokens per question, max choice options). Each question
# is read with its own copy of the state and the model cuts whatever does not fit from the END, so we shrink it ourselves.
LIMITS = {"verdict-1.4": (512, 24), "laya-1.0": (1024, 20)}
CHARS_PER_TOKEN = 3  # ponytail: rough and on the safe side for code/JSON; use the model's tokenizer if edge cases matter
LOOPBACK = ("localhost", "127.0.0.1", "::1")


# Obvious secret shapes are redacted from everything sent to the API, and secret-looking file names are never read
# into a request. This is a seatbelt, not PII detection or a guarantee.
SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
    r"|\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[\w-]{30,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_\w{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9-]{10,}|\bnpm_[A-Za-z0-9]{30,}"
    r"|\beyJ[\w-]{15,}\.[\w-]{15,}\.[\w-]+"
    r"|hooks\.slack\.com/services/[\w/]+"
    r"|\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@"
    r"|(?i:\bbearer)\s+[A-Za-z0-9._~+/=-]{20,}"
    r"|(?i:[\w.-]*(?:password|passwd|pwd|secret|api[_-]?key|apikey|token|credential|private[_-]?key|access[_-]?key)[\w.-]*)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',;]{12,}"
    r"|\b[A-Fa-f0-9]{32,}\b"
    r"|\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{32,}\b")
SENSITIVE_NAME = re.compile(
    r"(?:^|[\\/])(?:\.env(?:\..*)?|[^\\/]*\.(?:pem|key|p12|pfx|keystore|kdbx)|id_(?:rsa|ed25519|ecdsa|dsa)[^\\/]*"
    r"|\.?(?:npmrc|netrc|git-credentials)|credentials[^\\/]*|secrets?[^\\/]*|terraform\.tfstate[^\\/]*)$", re.I)


def sensitive_path(path):
    return bool(SENSITIVE_NAME.search(str(path)))


def scrub(obj):
    """Copy of a state/questions structure with secret-shaped strings replaced by [REDACTED]."""
    if isinstance(obj, str):
        return SECRET.sub("[REDACTED]", obj)
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


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


def home():
    """Where `jev-tools setup` keeps config.json and the credentials file."""
    return Path.home() / ".jev-tools"


def config():
    """Choices made by `jev-tools setup`: {"backend": "api"|"local"|"offline", "base_url": ...}. {} if absent or broken."""
    try:
        c = json.loads((home() / "config.json").read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def backend():
    b = config().get("backend")
    return b if b in ("api", "local", "offline") else "api"


def model():
    """Model id sent in requests: a small local encoder only when setup chose one for the local backend."""
    m = config().get("model")
    return m if backend() == "local" and m in LIMITS else MODEL


def max_options():
    """Most choice options one question may carry on the active model (255 on OpenJev)."""
    return LIMITS[model()][1] - 1 if model() in LIMITS else 255  # one slot is left for the caller's "none"


def state_chars(question_chars=400):
    """Characters of state that fit beside a typical question on a small model, or None when there is no tight limit."""
    lim = LIMITS.get(model())
    return max(200, (lim[0] - 30) * CHARS_PER_TOKEN - question_chars) if lim else None


def fit(obj, chars):
    """Shrink every string in a state to its head so the whole fits `chars`; unchanged when it already fits."""
    n = len(json.dumps(obj, ensure_ascii=False))
    if n <= chars:
        return obj
    ratio = chars / n

    def cut(o):
        if isinstance(o, str):
            return o[:max(40, int(len(o) * ratio))]
        if isinstance(o, dict):
            return {k: cut(v) for k, v in o.items()}
        return [cut(v) for v in o] if isinstance(o, list) else o

    return cut(obj)


def find_key():
    """(key, source) from env, the plugin option, then the setup credentials file; (None, None) if none."""
    for env, name in (("OPENJEV_API_KEY", "OPENJEV_API_KEY"), ("TYPESAFE_API_KEY", "TYPESAFE_API_KEY"),
                      ("CLAUDE_PLUGIN_OPTION_API_KEY", "plugin api_key option")):
        if os.environ.get(env):
            return os.environ[env], name
    try:
        k = (home() / "credentials").read_text(encoding="utf-8").strip()
    except OSError:
        k = ""
    return (k, "credentials file") if k else (None, None)


def endpoint():
    # the setup config may name a loopback server for the local backend; the host check below still applies to it
    base = (os.environ.get("OPENJEV_BASE_URL") or os.environ.get("TYPESAFE_BASE_URL")
            or (config().get("base_url") if backend() == "local" else None) or f"https://{HOST}").rstrip("/")
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
    kind = backend()
    if kind == "offline":
        log("offline")  # chosen in setup: callers take their no-model fallback; the log line shows the hook did run
        return None
    key, _ = find_key()
    if not key and kind != "local":
        log("no_key")  # otherwise a missing key is indistinguishable from a healthy install
        return None
    if not questions:
        return None
    t0 = time.monotonic()
    try:
        mdl, state, questions = model(), scrub(state), scrub(questions)
        if mdl in LIMITS:
            if any(len(q.get("criteria") or ()) > LIMITS[mdl][1] for q in questions.values() if q.get("type") == "choice"):
                log("too_many_options", model=mdl)  # cutting options would change the question, so decline instead
                return None
            q_chars = max(len(json.dumps(q, ensure_ascii=False)) for q in questions.values())
            fitted = fit(state, state_chars(q_chars))
            if fitted != state:
                log("state_cut", model=mdl, chars=len(json.dumps(state, ensure_ascii=False)))
            state = fitted
        body = json.dumps({"model": mdl, "state": state, "questions": questions, **extra}).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "jev-tools/0.1"}  # explicit User-Agent: the default Python-urllib one is 403'd by the edge in front of the API
        if key:
            headers["Authorization"] = f"Bearer {key}"  # a self-hosted server may not need one
        req = urllib.request.Request(endpoint(), body, headers, method="POST")
        with _OPEN.open(req, timeout=timeout) as r:
            data = json.load(r)
        log("ask", n=len(questions), ms=int((time.monotonic() - t0) * 1000), tok=(data.get("usage") or {}).get("input_tokens"))
        return data["answers"]
    except Exception as e:
        log("ask_error", err=type(e).__name__, msg=str(e)[:120])
        return None


def mode():
    """shadow (default: log, never act) | active | off."""
    m = (os.environ.get("JEV_MODE") or os.environ.get("CLAUDE_PLUGIN_OPTION_MODE") or config().get("mode") or "shadow").strip().lower()
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
