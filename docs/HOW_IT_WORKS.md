# How it works

## The model, in two minutes

OpenJev (served at `api.codiv.ai`) is a **System One** model: it does not generate text. You send a `state` (any string or JSON) and a set of typed **questions**; it returns one calibrated answer per question in tens to hundreds of milliseconds.

| Question type | You send | You get |
|---|---|---|
| `noul` (yes/no) | `instructions`, optional `criteria: {true, false}` | `{"noul": 0.93}`, the probability of yes |
| `choice` (pick one) | `instructions`, `criteria: {option: description}` | the pick, `probabilities` for every option, `confidence` |
| `score` (ordered scale) | `instructions`, `criteria: [level0, level1, ...]` | expected level `score`, per-level `probabilities` |

Because answers are probabilities, decisions become thresholds in plain code. Because the model never writes free text, there is no output to parse and no invented content.

All questions about one state go in **one request**; they share one read of the state. Question ids never reach the model, so the question text must carry the meaning.

## Shared client: `scripts/jevlib.py`

- `ask(state, questions, timeout, **extra)` returns `{question_id: answer}` or `None`. It never raises, so each caller chooses its own failure policy.
- Key lookup: `OPENJEV_API_KEY`, then `TYPESAFE_API_KEY`, then the plugin's `api_key` option.
- **Host pinning:** the endpoint must be `api.codiv.ai` over HTTPS (or loopback for tests). Hooks run unattended, so a base URL injected through an environment file must not be able to redirect the key.
- **No redirects:** a redirect would re-send the `Authorization` header elsewhere, so redirects are refused.
- Sends an explicit `User-Agent`. The API's edge returns 403 for Python's default one.
- `mode()` resolves `shadow` / `active` / `off`. `log()` appends JSONL rows (verdicts, latency, tokens, never the key).

## Failure policy

| Piece | If Jev is down or slow | Why |
|---|---|---|
| Rule hook | allow the edit | an outage must never block your work |
| Skill hook | inject nothing | a missing hint is harmless |
| Review pre-check | route to **full review** | skipping a review silently is the unsafe direction |
| find-files | fall back to keyword order and say so | still returns something useful |
| browser-nav | print `error`; Claude picks the step | the loop keeps going |

Every hook also catches its own exceptions, so a bug in a hook can never break the prompt or the tool call.

## Rule enforcer (`PreToolUse`)

```text
Edit/Write/MultiEdit event
  -> skip: docs/data extensions, files under .claude/, diffs under 15 chars
  -> build a unified diff (Write diffs against the file already on disk)
  -> collect rules: CLAUDE.md, AGENTS.md, .claude/rules/*.md from the edited
     file's folder up to the session cwd (never ~/.claude), imperative bullets only
     ("never", "always", "must", "do not", "avoid", ...), strong wording first, capped at 20
  -> ONE request: a noul question per rule, state = file name + diff (8000 chars max)
  -> top rule >= JEV_THRESHOLD (0.80)?
       -> second look: a strictly worded noul with true/false criteria
          "the changed lines clearly and directly break this rule"
       -> confirm >= JEV_CONFIRM (0.70)?  active mode: deny with the rule text
                                          shadow mode: log only
```

The second look exists because the live run produced a false positive: a clean edit that read its host from config scored 0.91 against "do not hardcode API hosts". The strict re-ask scores such cases low. It only runs on the rare hit, so it adds latency only when it matters.

The deny response is the standard `permissionDecision: "deny"` with a reason that names the rule and its source file, so Claude can fix the edit and retry.

**Token cost.** Input tokens grow with `state size x chunks of questions`, not with question count alone (measured in [MEASUREMENTS.md](MEASUREMENTS.md)). Capping at 20 rules and 8000 diff characters keeps a check near 5k tokens.

## Skill picker (`UserPromptSubmit`)

Stage 1 shortlists up to 40 installed skills by word overlap with the prompt (name weighted 3x) and asks one `choice` question over them plus a `none` option. Stage 2, only if a skill clears `JEV_SKILL_MIN` (0.60), asks two yes/no questions on the pick's full description: "does this request need the listed skill" and "is it the right procedure". Both must clear the bar. In `active` mode the hook prints `additionalContext` naming the skill.

Limit worth knowing: a hook cannot shrink Claude's own skill listing, so this is a pointer, not a token saver. A one-week field report on a similar router found only about 5% of its suggestions were used ([jev-skill-router](https://github.com/shimo4228/jev-skill-router)); keep it in `shadow` and check the log before trusting it.

## find-files

```text
query -> keywords (stopwords dropped, max 8)
      -> walk the tree (skips .git, node_modules, venvs, build dirs, files > 300 KB, binaries)
      -> score by keyword count + 5x for path matches, keep the top 100
stage 1: score each candidate 0-4 from a ~700 char excerpt, 20 files per request, in parallel
stage 2: re-score the best 10 from ~2500 char excerpts; final = 0.3 x stage1 + 0.7 x stage2
```

Excerpts are the file's first lines plus the lines matching the most query keywords, each with a line of context. Honest status: on 8 labelled queries it does not beat plain keyword counting. See [MEASUREMENTS.md](MEASUREMENTS.md).

## browser-nav

`pick_next.py` takes `{goal, url, elements[], history[]}` on stdin and asks three things in one request: a `choice` over the element refs plus `none` ("which element next"), a `noul` "goal already achieved", and a `noul` "stuck".

| Output | When |
|---|---|
| `done` | goal-met >= 0.8, or nothing left to click and goal-met >= 0.5 |
| `blocked` | stuck >= 0.8, or nothing to click |
| `unsure` | best element below the 0.65 confidence floor: Claude chooses |
| `click` / `type` | best element, `type` for text fields (it never invents the text) |
| `error` | Jev unavailable: Claude chooses |

The 0.65 floor is borrowed from measurements in hermes-jev-skills, where wrong picks sat at 0.45 to 0.60 and right ones above 0.74. Claude Code still executes every action through its browser tool; what Jev replaces is the per-step DOM reasoning.

## review-precheck

`git diff` (default `HEAD`) goes to seven yes/no questions in [`scripts/review_policy.json`](../scripts/review_policy.json): hardcoded secrets, new dependencies, auth changes, schema/API changes, weakened tests, swallowed errors, risky logic. Any answer at or above 0.25 (or a missing answer, or a diff over 30k chars) routes to `full`; otherwise `fast`. Exit code 0 is fast, 10 is full, so a workflow can branch on it. Docs-only diffs skip the model call.

## rule-calibrate

Replays the last N commits (per-file hunks) against the same extracted rules and prints, per rule, how many hunks would fire, the median and max probability, and a verdict borrowed from abide's calibration: **noisy** (fires on 60%+), **weak** (never decisive), **quiet** (never near firing), **decisive**, or **skipped** (fewer than 5 hunks). Run it before switching to `active`.

## Plugin packaging

- `.claude-plugin/plugin.json` declares two `userConfig` options: `api_key` (sensitive) and `mode`.
- `hooks/hooks.json` registers both hooks with `python` and `${CLAUDE_PLUGIN_ROOT}/scripts/...`.
- Skills call scripts through `${CLAUDE_SKILL_DIR}/../../scripts/...`, which resolves inside the installed plugin.
- `.claude-plugin/marketplace.json` makes the repo its own single-plugin marketplace.
