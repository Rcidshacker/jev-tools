---
name: status
description: Check whether the jev-tools plugin is actually working: key found, mode, hook state, and what the decision log shows. Use right after installing, when a hook seems to do nothing, when asked "is jev-tools running", "why isn't the rule hook firing", or before trusting its verdicts. Hooks fail open, so a broken install looks identical to a working one until you run this.
---

# status

```bash
python "${CLAUDE_SKILL_DIR}/../../scripts/status.py"
```

It prints the Python version, whether an API key was found (never the value), the mode, whether the skill hook is on, and a summary of the decision log: events in the last 24 hours, minutes since the last successful call, and the last error.

## Reading it

- `api key MISSING`: set `OPENJEV_API_KEY` (or the plugin's `api_key` option) and restart Claude Code.
- `no log yet`: no hook has run since install. Send a prompt or make an edit in a project that has a `CLAUDE.md` with rules, then run this again.
- `last 24h` shows `no_key` or `ask_error`: the hooks are running but failing; the last-error line says why (`HTTP Error 403` usually means the key or a proxy, `HTTP Error 429` means quota or rate limit).
- `rule_check` rows with `enforce: False` are normal in shadow mode.

## Gotchas

- The hooks call `python`; if that is not on PATH the hook never starts and writes nothing, so an empty log can also mean a wrong interpreter. Run `python --version` in the same shell Claude Code uses.
- Environment variables set after Claude Code started are not seen until it restarts.
