---
name: review-precheck
description: Decide whether a git diff needs a full code review or a quick pass, by asking Jev seven yes/no policy questions (secrets, dependencies, auth, schema, tests, swallowed errors, risky logic). Use before launching an expensive multi-model or multi-turn review, or when asked "does this change need a careful review". Not a review itself.
---

# review-precheck

```bash
python "${CLAUDE_SKILL_DIR}/../../scripts/review_precheck.py" [git-diff-args]
```

Defaults to `git diff HEAD`. Prints `{route, flags}`; exit code 0 means fast, 10 means full review. If the route is `full`, run the full review and tell the reviewer which flags fired. If `fast`, a single quick pass is enough.

## Gotchas

- It fails safe: Jev down, a missing answer or a truncated diff (over 30k chars) all route to full review.
- Any question at or above 0.25 flags (`JEV_PRECHECK_MIN`); that is deliberately conservative for an uncalibrated model.
- Docs-only diffs (`.md`, `.txt`, `.rst`) skip the model call. Untracked files are not in `git diff`; run `git add -N <file>` first.
- The seven questions live in `scripts/review_policy.json`; edit them to match your policy.
