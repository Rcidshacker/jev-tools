# Changelog

## Unreleased

- Measured the small local models for real (installer run end to end with the PyPI package; Verdict and Laya servers on CPU) and acted on it: `jevlib.TRUSTED` limits each small model to what it proved able to judge. Verdict is only asked for skill picking; Laya for skill picking and `browser-nav`. The rule hook, `review-precheck`, `find-files` (and Verdict's `browser-nav`) use the pattern fallbacks instead. Details and numbers in the README.
- Local servers get one client request at a time: parallel requests queued behind a CPU-bound server and caused mass timeouts.
- Fixed: `jev-tools-setup check` reported "HTTP 400" for a healthy Verdict/Laya server because its probe always asked for `openjev-latest`; it now probes with the configured model.
- Removed the now-unused small-model sizing code from `find-files` and `review-precheck`.

## 0.3.0

- New one-command installer (`uv tool install jev-tools-setup`, then `jev-tools-setup`; also `pipx install` or `uvx jev-tools-setup`. The bare `jev-tools` name on PyPI belongs to an unrelated project, so this package is `jev-tools-setup`): installs the plugin through the `claude` CLI and asks how Jev should run: hosted `api`, self-hosted `local` (GPU and Docker checked first), or `offline` (no model, documented fallbacks).
- New `LOG.md`: a plain-English report built from the decision logs (health verdict, setup, problems with fixes, counts, setup history, recent events), written at the end of every `jev-tools-setup` run (also failed ones), by `jev-tools-setup report`, and by the new `report` skill. It merges the plugin data directory and `~/.jev-tools`, shortens home paths and redacts key-shaped strings. The installer now logs its own steps (plugin install, key check, config, local install, serve) to the same log.
- Offline backend no longer goes silent: `review-precheck` runs regex checks for six of its seven questions (and also lists them during an API outage), the rule hook catches a literal forbidden token, the skill hook uses its keyword shortlist, `browser-nav` gives a keyword hint, `find-files` prints percent scores, `rule-calibrate` says plainly that it needs a model, and skipped calls are logged so `status` shows the hooks ran.
- Fixed: the rule hook's diff for `Edit` calls glued the removed and added lines together (`-old+new`) because Edit strings have no trailing newline; this affected the diff sent to the model too.
- `local` backend now includes the small encoder models Verdict (151M) and Laya (421M), which run on the CPU or any GPU: setup installs OpenJev's `[verdict]`/`[laya]` extra into `~/.jev-tools` after confirmation, and `jev-tools-setup serve` runs the server. `jevlib` sends the right model id, trims the state to the model's context window, caps option lists, and `find-files`, `review-precheck` and `browser-nav` size their inputs to it. The full OpenJev model stays available for Blackwell GPUs.
- New read-only `jev-tools-setup check` command: verifies `python` (3.10+, as the hooks call it), the `claude` CLI, git, network, GPU and Docker, and warns when `JEV_MODE` is set and will override the saved mode.
- The API key is read from a hidden prompt or stdin, validated with one live call, and stored in `~/.jev-tools/credentials` with owner-only permissions. Lookup order is env vars, the plugin option, then that file.
- `~/.jev-tools/config.json` holds backend, local `base_url` and mode. The host check (api.codiv.ai or loopback) still applies to it.
- `status` now shows the backend and where the key was found, never the key.

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
