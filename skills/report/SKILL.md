---
name: report
description: Write LOG.md, a plain-English report of what jev-tools has done and what is wrong, with a health verdict, setup summary, counts, problems with fixes and recent events. Use when something seems broken, a hook seems to do nothing, a hook blocked an edit and you want to know why, when asked "what is jev-tools doing", "what happened" or "write me a log", or before filing an issue (attach the file). Contains no API key, file contents or prompts.
---

# report

```bash
python "${CLAUDE_SKILL_DIR}/../../installer/jev_report.py"
```

It writes `~/.jev-tools/LOG.md` and prints the path and a one-word verdict. Read the file, then tell the user:

1. the health line at the top,
2. each item under **Problems** with its fix,
3. anything surprising in **Recent events**.

The report merges every decision log it can find (the plugin data directory and `~/.jev-tools`), so run it from any project. It never includes the key; home paths are shortened to `~`, so the file is safe to attach to an issue.
