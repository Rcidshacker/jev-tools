---
name: rule-calibrate
description: Replay a repository's recent commits against its CLAUDE.md / AGENTS.md rules and report per-rule fire rates and verdicts (decisive, noisy, weak, quiet). Use before switching the jev-tools rule hook from shadow to active mode, when the hook blocks too much or too little, or when asked how well the project rules would enforce.
---

# rule-calibrate

Run inside the project's git repo:

```bash
python "${CLAUDE_SKILL_DIR}/../../scripts/rule_calibrate.py" --commits 15 --hunks 30
```

It extracts imperative bullets ("never", "always", "must", "do not") from the project's rule files, asks Jev about each recent code change, and prints `fired/hunks, median, max, verdict, rule`.

- **noisy**: fires on 60%+ of real changes; reword or narrow the rule before enforcing.
- **weak**: never decisive; make the rule concrete.
- **quiet**: never came close to firing; the code follows it, or the rule is too vague to notice.
- **decisive**: separates violations from clean changes.

## Gotchas

- Only bullet lines with imperative wording count as rules; prose paragraphs are ignored. `~/.claude/CLAUDE.md` is never read.
- Shallow clones have one commit; run `git fetch --deepen=40` first.
- It costs roughly 5k input tokens per hunk at 20 rules.
- Zero fires everywhere is not proof of a good rulebook; it only says the rules did not trigger on that history.
