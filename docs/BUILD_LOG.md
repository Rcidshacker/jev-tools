# Build log: how this was made

An honest account of how the plugin came to be, including what did not work. It is written so someone can repeat the process, or disagree with it, from evidence.

## 1. The starting point

The project began from a walkthrough of five concrete uses for a fast decision model inside Claude Code:

1. a **skill picker** hook that chooses one installed skill per prompt,
2. **file discovery** that scores keyword candidates instead of running an exploring sub-agent,
3. a **review pre-check** of seven yes/no policy questions on a diff before an expensive review,
4. a **browser navigator** that picks each next click toward a test goal,
5. a **rule enforcer** hook that blocks an edit when the model is confident it breaks a project rule.

The goal was to build all five from scratch on **OpenJev via Codiv** (a hosted, free-tier System One model) rather than TypeSafe's Jev, then package them as one Claude Code plugin.

## 2. Survey before building

Before writing code, fifteen public repositories built around Jev-style decision models were cloned into one folder and read: skill routers, review tools, a browser agent, rule enforcers, an all-in-one kit. What that turned up:

- **Everything was under two weeks old.** Star counts were high, track records were short. Nothing was proven.
- **Codiv compatibility is mostly free.** Codiv documents the same wire format as TypeSafe's Jev and accepts `jev-latest` as a model alias, so tools work if their base URL is overridable. Some hardcode the URL, one pins the host on purpose (a sound key-exfiltration guard), and some use an entirely different API.
- **Static safety pass.** All fifteen were grepped for reverse shells, credential-file reads, exfiltration hosts and obfuscated payloads in non-test code; none turned up. A dedicated skill-security scanner was attempted but every route to it was blocked by tooling errors in that session, so it did not run. That gap is stated, not hidden.
- **One honest negative result.** An independent field report on a Jev skill router found only about 5% of its suggestions were used and the author removed it. That shaped the decision to ship in shadow mode.

## 3. Design rules chosen up front

- **Stdlib only, one shared client.** Nothing to install, one file to audit.
- **Decisions are thresholds in code.** The model answers typed questions; code applies the bar.
- **Explicit failure policy per piece.** Hooks fail open, the review pre-check fails safe.
- **Shadow first.** Because OpenJev is new and thresholds tuned on other models do not transfer, nothing acts until you turn it on.
- **Secrets stay out of everything.** Environment variable or sensitive plugin option; host pinned; redirects refused; never logged.

## 4. What live testing changed

The first version passed its offline tests. Running it against the real API and real Claude Code sessions found problems the mock could not:

| Finding | Fix |
|---|---|
| Every live call returned **403** | Codiv's edge rejects Python's default `User-Agent`; the client now sends its own |
| A clean edit that reads its host from config scored **0.91** against "do not hardcode API hosts" | Added a strict **second look** on any hit; the same case now vetoes at the second question |
| Browser navigator returned `blocked` on a page where the goal was met | The goal-met probability wobbled around the bar between identical calls; added "nothing left to click and goal probably met means done" |
| Browser navigator had no low-confidence exit | Added a **0.65 confidence floor** returning `unsure`, a value another project measured |
| Skill picker could inject on a shallow match | Added a **stage-two confirmation** on the pick's full description |
| Enforcer token cost was unknown | Measured it (state is re-read per chunk of questions), capped rules at 20 and diffs at 8000 chars |
| File discovery scored 3 of 4, then 0 of 4 after a rewrite | Built a labelled evaluation of six variants; none clearly beat keyword counting. Shipped the best and documented it as a hint |
| Hook payload format was only tested with fake events | Ran the hook inside real headless Claude Code sessions; violating edit blocked, clean edit allowed |

## 5. Ideas taken from other projects

| Idea | Taken from |
|---|---|
| Compile-once rules with a per-rule verdict (decisive / noisy / weak) from replaying real history | [abide](https://github.com/coldteadotai/abide), reimplemented as `rule-calibrate` |
| Strict re-check before acting on a hit | abide's criteria-based questions and [jevgate](https://github.com/Tech-Byte-Frontier/jevgate)'s confirmation step |
| Confidence floor measured against known wrong picks; a two-stage "rank wide, then ask again" retrieval; "is any skill needed at all" gating | [hermes-jev-skills](https://github.com/kerpopule/hermes-jev-skills) |
| Shadow-first rollout and fail-open everywhere | [jev-kit](https://github.com/jonathanavis96/jev-kit) |
| Plugin manifest with a sensitive `api_key` option and a `mode` option; a candid write-up of what a skill router can and cannot do | [jev-skill-router](https://github.com/shimo4228/jev-skill-router) |

No code was copied; the ideas were re-implemented small.

## 6. Packaging as a plugin

The scripts were moved under `scripts/`, hooks declared in `hooks/hooks.json`, four skills added under `skills/`, and a manifest plus single-plugin marketplace added under `.claude-plugin/`. `claude plugin validate` passes. Skills locate scripts with `${CLAUDE_SKILL_DIR}/../../scripts/...`, and hooks with `${CLAUDE_PLUGIN_ROOT}`; both were confirmed to resolve in real sessions (the `find-files` skill ran and logged its Jev calls; the rule hook blocked an edit).

## 7. Known gaps

- File discovery is not better than keyword search on our evaluation.
- The browser navigator has only been run on a synthetic page.
- `review-precheck` and `rule-calibrate` were exercised by script, not through the plugin's skill loader.
- Samples throughout are small; thresholds are defaults, not tuned values.
- No published skill-security scan; the static check is a grep, not a substitute.
- The hooks call `python`; a system with only `python3` needs an alias.

## 8. If you want to extend it

Add a question, not a model call: write the yes/no in `scripts/review_policy.json`, or add a rule bullet to your `CLAUDE.md`. Run `rule-calibrate` on your history to see whether it fires too often. Keep a new decision behind `shadow` until the log looks right.
