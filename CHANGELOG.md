# Changelog

## 0.1.0

First release.

- Rule enforcer `PreToolUse` hook with strict second look, `shadow` / `active` / `off` modes.
- Skill picker `UserPromptSubmit` hook with stage-two confirmation.
- Skills: `find-files` (two-stage scoring), `browser-nav` (confidence floor), `review-precheck` (seven policy questions), `rule-calibrate` (per-rule verdicts from commit history).
- Shared stdlib client: host pinned to `api.codiv.ai`, redirects refused, explicit User-Agent, JSONL decision log.
- Plugin manifest with sensitive `api_key` option, single-plugin marketplace, 17 offline tests.
