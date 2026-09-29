# Changelog

## 0.2.0

- Privacy: secret-shaped strings (keys, JWTs, Bearer tokens, connection-string passwords, secret-named assignments, long hex/base64 blobs) are redacted from every request, checked against 13 adversarial samples, secret-named files are never read into one, and the README now documents exactly what is sent and that shadow mode still sends.
- The skill-pick hook is now opt-in (`skill_picker` option / `JEV_SKILL_PICKER=1`) because it sends every prompt.
- New `status` skill and `scripts/status.py`; a missing key is now logged as `no_key` instead of failing invisibly.

## 0.1.0

First release.

- Rule enforcer `PreToolUse` hook with strict second look, `shadow` / `active` / `off` modes.
- Skill picker `UserPromptSubmit` hook with stage-two confirmation.
- Skills: `find-files` (two-stage scoring), `browser-nav` (confidence floor), `review-precheck` (seven policy questions), `rule-calibrate` (per-rule verdicts from commit history).
- Shared stdlib client: host pinned to `api.codiv.ai`, redirects refused, explicit User-Agent, JSONL decision log.
- Plugin manifest with sensitive `api_key` option, single-plugin marketplace, 17 offline tests.
