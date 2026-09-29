# jev-tools

A [Claude Code](https://code.claude.com) plugin that lets a small **decision model** make the cheap, frequent judgments an agent would otherwise spend a full LLM call on: *does this edit break a project rule? which skill fits this prompt? which file matters? what should the browser click next? does this diff need a careful review?*

It talks to **OpenJev** on [Codiv](https://codiv.ai), a hosted "System One" model that answers typed questions (yes/no, pick-one, score) with calibrated probabilities instead of writing text. Python 3.10+, standard library only, no build step.

> **Status: early, shadow-first.** Everything here was built and tested against a live Codiv key, and the numbers are in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md), but the samples are small and OpenJev is a young model. The plugin ships in **shadow mode**: hooks only log what they would have done. Nothing blocks or injects until you switch to `active`.
> Independent project. Not affiliated with Codiv, OpenJev or TypeSafe AI.

## What's in it

| Piece | Kind | What it does |
|---|---|---|
| `rule_enforcer.py` | `PreToolUse` hook on `Edit\|Write\|MultiEdit` | Reads your `CLAUDE.md` / `AGENTS.md` rules, asks Jev whether the pending edit breaks one, re-checks any hit with a stricter question, and (in `active` mode) blocks the write with the rule it broke |
| `skill_picker.py` | `UserPromptSubmit` hook | Picks the one installed skill that fits your prompt, confirms it, and (in `active` mode) adds a one-line pointer to the context |
| `find-files` | skill | Keyword candidates, then two-stage Jev scoring, prints the most relevant files. A hint, not an oracle |
| `browser-nav` | skill | Jev picks each next click from the page's interactive elements; Claude executes and judges pass/fail |
| `review-precheck` | skill | Seven yes/no policy questions on a git diff decide *fast pass* vs *full review* |
| `rule-calibrate` | skill | Replays recent commits against your rules and reports which rules are decisive, noisy, weak or quiet, before you enforce anything |

## Install

You need Python 3.10+ on your `PATH` (the hooks call `python`) and an OpenJev key from the [Codiv dashboard](https://codiv.ai/dashboard) (free tier: 100M input tokens).

```text
/plugin marketplace add Rcidshacker/jev-tools
/plugin install jev-tools@jev-tools
```

Try it for one session without installing: `claude --plugin-dir /path/to/jev-tools`.

### Give it your key

Either of these, never both in a repo:

- **Environment variable (recommended):** set a user-level `OPENJEV_API_KEY`.
  Windows: `setx OPENJEV_API_KEY "sk-codiv-..."` then restart Claude Code. macOS/Linux: export it in your shell profile.
- **Plugin option:** Claude Code prompts for the plugin's `api_key` setting, stored as sensitive.

Do not put the key in `settings.json`, `CLAUDE.md`, or any file in a repo. The client only ever sends it to `api.codiv.ai` (or loopback for tests), refuses redirects, and never logs it.

Check the wiring with one live call: `python scripts/jevlib.py` prints `OK`.

## Modes

Set with the plugin's `mode` option or the `JEV_MODE` environment variable (the variable wins).

| Mode | Rule hook | Skill hook |
|---|---|---|
| `shadow` (default) | logs the verdict, never blocks | logs the pick, injects nothing |
| `active` | blocks an edit Jev flags at ≥ 0.80 **and** confirms at ≥ 0.70 | injects `Jev skill pick: <name>` |
| `off` | does nothing, makes no API call | does nothing |

Recommended path: run in `shadow` for a week, read the log, run the `rule-calibrate` skill on a project, then switch that setup to `active`.

## Settings reference

| Variable | Default | Meaning |
|---|---|---|
| `OPENJEV_API_KEY` | none | API key (also `TYPESAFE_API_KEY`, or the plugin's `api_key` option) |
| `OPENJEV_BASE_URL` | `https://api.codiv.ai` | Must be `api.codiv.ai` or loopback |
| `JEV_MODE` | `shadow` | `shadow`, `active` or `off` |
| `JEV_THRESHOLD` | `0.80` | Rule-violation probability that can block |
| `JEV_CONFIRM` | `0.70` | Second-look probability required to block |
| `JEV_SKILL_MIN` | `0.60` | Minimum probability to inject a skill pick |
| `JEV_PRECHECK_MIN` | `0.25` | Yes-probability that flags a diff for full review |
| `JEV_LOG` | plugin data dir | Where decisions are appended (JSONL) |

Every decision is one JSON line: verdict, probability, latency, input tokens. Never the key, never file contents.

## How it works, in one paragraph

Each piece turns a fuzzy judgment into typed questions, sends them with the relevant text as `state` to `POST /v1/systemone`, and applies thresholds in ordinary code. The model never writes text, so there is nothing to parse and nothing to hallucinate. Every failure path is explicit: hooks **fail open** (an outage never blocks your edit or prompt), the review pre-check **fails safe** (an outage routes to full review). Details, diagrams and the reasoning behind each threshold are in [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md).

## What we measured

Small samples, live against Codiv, all reproducible from the scripts. Full method and caveats in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

| Component | Result |
|---|---|
| Rule enforcer | 4 of 4 planted violations blocked, 4 of 4 clean edits allowed after the second-look check was added; also blocked and allowed correctly inside real headless Claude Code sessions |
| Skill picker | 3 of 3 correct on a large real skill roster (two matches, one correct "none") |
| Review pre-check | benign rename routed *fast*; a diff with a hardcoded key, swallowed exception and emptied tests routed *full* with the right flags |
| Browser navigator | 5 of 5 steps correct on a synthetic login flow (never run against a real browser) |
| File discovery | **no better than plain keyword counting** on 8 labelled queries (top-3 hits 4 to 6 of 8 vs 4 of 8); repeat runs differ by up to 2 |
| Cost and speed | about 1 s per prompt or edit, 2 s when a violation is confirmed; about 5k input tokens per edit at 20 rules |

## Repository layout

```text
.claude-plugin/plugin.json       plugin manifest and user settings (api_key, mode)
.claude-plugin/marketplace.json  single-plugin marketplace so /plugin marketplace add works
hooks/hooks.json                 the two hooks
scripts/                         jevlib.py (client) and one script per piece, review_policy.json
skills/<name>/SKILL.md           four skills
tests/test_all.py                offline suite against a local mock of /v1/systemone
docs/                            how it works, measurements, build log, Codiv API notes
```

## Development

```bash
python tests/test_all.py     # 17 offline tests, no network, no key needed
python scripts/jevlib.py     # one live call, needs OPENJEV_API_KEY
```

The tests spin up a local server that mimics `/v1/systemone`, so they prove the logic and the wire format, not OpenJev's accuracy. Accuracy claims come only from the live runs recorded in the docs.

## Credits

Ideas and hard-won numbers borrowed, with thanks, from projects that got there first. See [docs/BUILD_LOG.md](docs/BUILD_LOG.md) for exactly what was taken from each:
[abide](https://github.com/coldteadotai/abide) (rule compilation, calibration verdicts, second look),
[hermes-jev-skills](https://github.com/kerpopule/hermes-jev-skills) (confidence floor, two-stage retrieval),
[jev-kit](https://github.com/jonathanavis96/jev-kit) (shadow-first rollout),
[jevgate](https://github.com/Tech-Byte-Frontier/jevgate) (confirming before acting),
[jev-skill-router](https://github.com/shimo4228/jev-skill-router) (plugin layout, honest field report on skill routing).

Built with [Claude Code](https://claude.com/claude-code). MIT licensed, see [LICENSE](LICENSE).
