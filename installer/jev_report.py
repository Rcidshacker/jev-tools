"""Write LOG.md: a plain-English report of what jev-tools did and what is wrong. Stdlib only, read-only except for the output file.

    python jev_report.py [--out PATH] [--last N]      (also: `jev-tools-setup report`, or the `report` skill inside Claude Code)

Sources: the decision log(s) the hooks and skills append to (JSONL), ~/.jev-tools/config.json, and environment variable NAMES.
Never included: the API key, file contents, prompts. Home directory paths are shortened to ~ and key-shaped strings are redacted,
so the file is safe to attach to an issue.
"""
import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

HOME = Path.home()
JEV = HOME / ".jev-tools"
KEYISH = re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}")
INSTALLER = {"setup_start", "setup_end", "plugin_step", "key_saved", "probe_failed", "config_saved", "serve_start", "local_install"}


def clean(text):
    """Shorten the home path and redact anything key-shaped."""
    return KEYISH.sub("[REDACTED]", str(text).replace(str(HOME), "~"))


def log_files():
    cands = [os.environ.get("JEV_LOG"), (Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "log.jsonl") if os.environ.get("CLAUDE_PLUGIN_DATA") else None,
             JEV / "log.jsonl", *sorted((HOME / ".claude" / "plugins" / "data").glob("jev-tools*/log.jsonl"))]
    seen, out = set(), []
    for c in cands:
        if c and Path(c).is_file() and str(Path(c).resolve()) not in seen:
            seen.add(str(Path(c).resolve()))
            out.append(Path(c))
    return out


def load(files):
    """All events, oldest first. The same line in two files counts once (the plugin dir and ~/.jev-tools can overlap),
    but repeated identical lines inside one file are real repeats and all count."""
    rows, have = [], Counter()
    for f in files:
        local = Counter()
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            local[line] += 1
            if local[line] <= have[line]:
                continue
            have[line] += 1
            try:
                e = json.loads(line)
                if isinstance(e, dict) and "event" in e:
                    rows.append(e)
            except ValueError:
                pass
    return sorted(rows, key=lambda e: e.get("t", 0))


def when(t):
    return datetime.fromtimestamp(t).astimezone().strftime("%Y-%m-%d %H:%M:%S") if t else "?"


def say(e):
    """One human sentence for one log event."""
    k = e["event"]
    if k == "ask":
        return f"model call ok: {e.get('n')} question(s), {e.get('ms')} ms, {e.get('tok')} input tokens"
    if k == "ask_error":
        return f"model call FAILED: {e.get('err')} {e.get('msg', '')}".strip()
    if k == "no_key":
        return "no API key found, so the call was skipped (the hook did nothing)"
    if k == "offline":
        return "offline backend: model call skipped on purpose"
    if k == "hook_error":
        return f"{e.get('hook')} hook crashed with {e.get('err')} and failed open (your edit/prompt was not blocked)"
    if k == "rule_check":
        s = f"rule check on {e.get('file')}: {e.get('rules')} rule(s)"
        if e.get("offline"):
            s += f", {e.get('hits')} literal match(es)"
        else:
            s += f", top score {e.get('top')}" + (f", second look {e.get('confirm')}" if e.get("confirm") is not None else "")
        if e.get("rule"):
            s += f" [{e['rule'][:60]}]"
        return s + (" (enforcing)" if e.get("enforce") else " (shadow: logged only)")
    if k == "skill_pick":
        s = f"skill pick: {e.get('pick')}" + (f" (p={e['p']})" if "p" in e else "")
        return s + (" vetoed by second check" if e.get("vetoed") else " (shadow: not injected)" if e.get("shadow") else " (injected)" if e.get("pick") != "none" else "")
    if k == "precheck":
        return f"review pre-check: {e.get('route')} review, {e.get('flags')} flag(s)" + (" (offline patterns)" if e.get("offline") else "")
    if k == "plugin_step":
        return f"plugin {e.get('step')} " + ("ok" if e.get("ok") else f"FAILED: {e.get('msg', '')}")
    if k == "config_saved":
        return f"config saved: backend={e.get('backend')}, model={e.get('model')}, mode={e.get('mode')}"
    if k == "key_saved":
        return "API key validated and saved to the credentials file (the value is never logged)"
    if k == "probe_failed":
        return f"key/server check failed: {e.get('err')}"
    if k == "local_install":
        return f"local model {e.get('model')} install " + ("ok" if e.get("ok") else "FAILED or declined")
    if k == "serve_start":
        return f"local server started: {e.get('model')} at {e.get('url')}"
    if k == "setup_start":
        return f"setup started (backend flag: {e.get('backend')})"
    if k == "setup_end":
        return f"setup finished with exit code {e.get('rc')}"
    if k == "state_cut":
        return f"input trimmed to fit {e.get('model')}'s context window (was {e.get('chars')} characters)"
    if k == "too_many_options":
        return f"question declined: more options than {e.get('model')} can take"
    return k + ": " + ", ".join(f"{a}={b}" for a, b in e.items() if a not in ("t", "event"))


def classify(msg):
    m = str(msg).lower()
    for pat, label in ((r"401|403|unauthor|forbidden|rejected", "key rejected"), (r"429|quota|rate", "quota or rate limit"),
                       (r"timed out|timeout", "timeout"), (r"refus|10061|connection|getaddrinfo|urlerror|name or service|unreachable", "cannot reach the server"),
                       (r"500|502|503|504|529|overload", "server error")):
        if re.search(pat, m):
            return label
    return "other"


FIX = {
    "key rejected": "The key was refused. Get a fresh one at https://codiv.ai/dashboard and run `jev-tools-setup` (api).",
    "quota or rate limit": "Quota or rate limit hit. Wait, or check usage on the Codiv dashboard. Quota errors are not retried.",
    "timeout": "The server answered too slowly. Try again; for a local server check that it is running and not still loading the model.",
    "cannot reach the server": "Nothing is answering. API: check your network. Local: start the server with `jev-tools-setup serve` (small models) or docker compose (full model).",
    "server error": "The server had an error or is overloaded. It usually clears by itself; hooks fail open meanwhile.",
    "other": "See the message in the recent events table.",
}


def problems(rows, cfg, day, backend, mode="shadow"):
    out, d = [], [e for e in rows if e.get("t", 0) >= day]
    c = Counter(e["event"] for e in d)
    if mode == "off":
        src = "the JEV_MODE environment variable" if os.environ.get("JEV_MODE") == "off" else "the plugin option or saved config"
        out.append(("warn", "Mode is OFF: every hook does nothing and nothing is sent", f"Set by {src}. Hooks return early, so no events are logged either.",
                    "Unset JEV_MODE (or set it to shadow/active) and restart Claude Code."))
    elif rows and not d:
        out.append(("info", "No activity in the last 24 hours", "Either you have not edited files or sent prompts in a session with the plugin, or the hooks are not loading.",
                    "Restart Claude Code and check `/plugin` shows jev-tools enabled."))
    if not rows:
        out.append(("warn", "No events recorded yet", "No hook or skill has run since install, or none could write a log.",
                    "Restart Claude Code (hooks load at session start), confirm the plugin is enabled with `/plugin`, then do an edit and re-run this report."))
    if c["no_key"] and backend == "api":
        out.append(("error", f"API key missing ({c['no_key']} skipped calls in 24h)", "Every hook silently does nothing without a key.",
                    "Run `jev-tools-setup` and choose api, or set OPENJEV_API_KEY."))
    errs = Counter(classify(e.get("msg", "") or e.get("err", "")) for e in d if e["event"] == "ask_error")
    for label, n in errs.most_common():
        sample = next(clean(f"{e.get('err')} {e.get('msg', '')}".strip()) for e in reversed(d) if e["event"] == "ask_error" and classify(e.get("msg", "") or e.get("err", "")) == label)
        out.append(("error", f"Model calls failing: {label} ({n} in 24h)", f"Latest: {sample}", FIX[label]))
    hooks = Counter(e.get("hook") for e in d if e["event"] == "hook_error")
    for h, n in hooks.most_common():
        out.append(("error", f"The {h} hook crashed {n} time(s) in 24h", "It failed open, so nothing was blocked, but it is not doing its job.",
                    "Send this report with the `err` text from the recent events table when you file an issue."))
    if c["state_cut"] or c["too_many_options"]:
        out.append(("warn", "A small local model is trimming or declining inputs", f"{c['state_cut']} trimmed, {c['too_many_options']} declined in 24h.",
                    "Expected with Verdict/Laya (512/1024-token windows). Verdicts on long diffs are less reliable; stay in shadow mode."))
    env_mode = os.environ.get("JEV_MODE")
    if env_mode and cfg.get("mode") and env_mode != cfg["mode"]:
        out.append(("warn", f"JEV_MODE={env_mode} overrides the saved mode ({cfg['mode']})", "The environment variable always wins.", "Unset JEV_MODE to use the saved mode."))
    if backend == "offline" and c["offline"]:
        out.append(("info", f"Offline backend: {c['offline']} model call(s) skipped in 24h", "Expected: no model is configured.", "Run `jev-tools-setup` to pick api or local."))
    return out


def build(last=40):
    files, now = log_files(), time.time()
    rows = load(files)
    cfg = {}
    try:
        cfg = json.loads((JEV / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    backend = cfg.get("backend") if cfg.get("backend") in ("api", "local", "offline") else "api"
    day = now - 86400
    mode = os.environ.get("JEV_MODE") or os.environ.get("CLAUDE_PLUGIN_OPTION_MODE") or cfg.get("mode") or "shadow"
    probs = problems(rows, cfg, day, backend, mode)
    level = "error" if any(p[0] == "error" for p in probs) else "warn" if any(p[0] == "warn" for p in probs) else "ok"
    head = {"ok": "✅ Healthy: nothing needs attention.", "warn": "⚠️ Works, but check the notes below.", "error": "❌ Something is wrong: see Problems."}[level]
    ver = "unknown"
    for pj in (Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json",):
        try:
            ver = json.loads(pj.read_text(encoding="utf-8")).get("version", ver)
        except (OSError, ValueError):
            pass
    keysrc = [n for n in ("OPENJEV_API_KEY", "TYPESAFE_API_KEY", "CLAUDE_PLUGIN_OPTION_API_KEY") if os.environ.get(n)]
    if (JEV / "credentials").exists():
        keysrc.append("credentials file")
    L = [f"# jev-tools log", "", f"_Generated {when(now)} on {platform.system()} {platform.release()}, Python {sys.version.split()[0]}, plugin {ver}._",
         "_Contains no API key, no file contents and no prompts. Safe to attach to an issue._", "", f"## {head}", ""]
    L += ["## Setup", "", "| | |", "|---|---|", f"| Backend | {backend}" + (f" ({cfg.get('model')})" if cfg.get("model") else "") + " |",
          f"| Mode | {mode} (shadow = log only, active = block/inject, off = nothing sent) |",
          f"| API key found in | {', '.join(keysrc) or 'nowhere'} |", f"| Config file | {'present' if cfg else 'absent'} |",
          f"| Log files read | {', '.join(clean(f) for f in files) or 'none'} |", ""]
    L += ["## Problems", ""]
    L += [f"- {'❌' if s == 'error' else '⚠️' if s == 'warn' else 'ℹ️'} **{clean(t)}**: {clean(d)}\n  - Fix: {f}" for s, t, d, f in probs] or ["None found."]
    d24 = [e for e in rows if e.get("t", 0) >= day]
    asks = [e["ms"] for e in d24 if e["event"] == "ask" and isinstance(e.get("ms"), (int, float))]
    L += ["", "## What happened", "", f"{len(rows)} event(s) in total, {len(d24)} in the last 24 hours.", "", "| Event | Last 24h | All time |", "|---|---:|---:|"]
    allc, c24 = Counter(e["event"] for e in rows), Counter(e["event"] for e in d24)
    L += [f"| {k} | {c24[k]} | {allc[k]} |" for k in sorted(allc, key=lambda k: -allc[k])] or ["| (none) | 0 | 0 |"]
    if asks:
        L += ["", f"Model calls last 24h: {len(asks)} ok, median {int(statistics.median(asks))} ms, slowest {int(max(asks))} ms."]
    rc = [e for e in d24 if e["event"] == "rule_check"]
    if rc:
        flagged = [e for e in rc if (e.get("top") or 0) >= 0.8 or e.get("hits")]
        L += [f"Rule checks last 24h: {len(rc)}, {len(flagged)} flagged a rule, enforcement {'on' if any(e.get('enforce') for e in rc) else 'off (shadow)'}."]
    inst = [e for e in rows if e["event"] in INSTALLER]
    if inst:
        L += ["", "## Setup history", "", "| When | What |", "|---|---|"] + [f"| {when(e.get('t'))} | {clean(say(e))} |" for e in inst[-10:]]
    L += ["", f"## Recent events (newest first, last {last})", "", "| When | What |", "|---|---|"]
    L += [f"| {when(e.get('t'))} | {clean(say(e)).replace('|', '/')} |" for e in reversed(rows[-last:])] or ["| - | nothing logged yet |"]
    L += ["", "## How to use this", "",
          "- Something does nothing? Read **Problems** first: the usual causes are a missing key, an unreachable server, or a hook that was not reloaded (restart Claude Code).",
          "- Hooks fail open: an outage never blocks your work, it just means the hook did nothing.",
          "- Run `jev-tools-setup check` to test the machine, or the `status` skill for a one-screen summary. Re-run this report any time.", ""]
    return "\n".join(L), level


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help=f"default {JEV / 'LOG.md'}")
    ap.add_argument("--last", type=int, default=40)
    a = ap.parse_args(argv)
    text, level = build(a.last)
    out = Path(a.out) if a.out else JEV / "LOG.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}  [{ {'ok': 'healthy', 'warn': 'notes', 'error': 'PROBLEMS'}[level] }]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
