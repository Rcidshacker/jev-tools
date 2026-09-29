# Measurements

Everything below was run live against Codiv's hosted OpenJev (`openjev-latest`, currently `openjev-0.1`) in September 2026. Samples are small and run-to-run noise is real. Treat these as smoke-test evidence, not benchmarks. The offline test suite proves logic and wire format only.

## Rule enforcer

| Test | Result |
|---|---|
| 8 hand-made edits against a 4-rule `CLAUDE.md`, first version | 4 of 4 violations denied (0.99 to 1.0); 3 of 4 clean edits allowed; **1 false positive** (0.91) on a clean edit that reads its host from config |
| Same 8 edits after adding the strict second look | 4 of 4 violations denied, 4 of 4 clean allowed (the false positive scored 0.88 first pass, was vetoed on the second look) |
| Real headless Claude Code session, plugin loaded, `active` mode | violating edit blocked, file unchanged, reason shown to Claude; a clean edit went through |
| Latency | about 1.0 s per edit with no hit, about 2.0 s when a hit triggers the second look |
| Calibration replay on another project | 20 rules x 24 real hunks: no rule fired above 0.35, so every rule reads *quiet* |

The 8-edit set is tiny and I wrote both the edits and the rules, so it flatters the model. The calibration replay is the more honest signal: on real commits from a project that follows its own rules, nothing fired, which is what a good rulebook on clean history should show and also what a blind rulebook would show.

## Skill picker

Three prompts against the author's real roster of installed skills: a resume-tailoring request picked the right skill at 1.00, a GSAP animation request picked `gsap-scrolltrigger` at 0.97, and a weather question correctly picked nothing. About 1.3 s per prompt, plus about 0.8 s for the second-stage confirmation when a pick clears the bar.

Field caution: an independent one-week trial of a similar router measured about 5% of suggestions followed by the agent. Keep the picker in `shadow` and read the log.

## Review pre-check

A rename-only diff routed `fast`. A diff adding a hardcoded key, swallowing an exception and emptying a test file routed `full` and flagged `secrets` (1.00), `tests` (1.00), `errors` (1.00) and `risk` (0.69). About 1.1 s each.

## Browser navigator

Synthetic login page, five consecutive steps for the goal "sign in as admin and open the settings page": type email (0.97), type password (0.99), click Sign in (1.0), click Settings (1.0), then `done`. An earlier run returned `blocked` on the final page because the goal-met probability wobbled between calls (0.93 on one call, below 0.8 on another with identical input); the "nothing left to click and goal probably met" rule fixed that. **Never run against a real browser session.**

## File discovery

Eight labelled queries on eight cloned repositories. "Top 3" means the file that defines the thing asked about is in the first three results.

| Variant | Top-3 hits |
|---|---|
| Plain keyword counting (no model) | 4 of 8 |
| Score, 20 files per request, one stage | 3 of 8 |
| Yes/no, 40 files per request, two stages | 3 of 8 |
| Yes/no, 10 files per request, one stage | 5 of 8 |
| Yes/no, 10 files per request, two stages | 5 of 8 |
| Score, 20 files per request, two stages (shipped) | 6 of 8, then 4 of 8 on an identical rerun |
| Same with 4-sample averaging | 4 of 8 and 6 of 8 |

Conclusion: the model does not measurably beat keyword counting here, and identical reruns differ by up to 2 of 8, even with averaging. It ships because it is not worse and sometimes surfaces the right file, but it is documented as a hint. A first attempt at a different excerpt strategy scored 0 of 4 on a smaller set, which is why the variants above were compared instead of trusting a single run.

## Token cost

Measured with one 6.9k-character diff as `state`:

| Questions | `input_tokens` |
|---|---|
| 1 | 2,394 |
| 5 | 2,490 |
| 20 | 5,291 |

The state is read once per chunk of questions, not once per question. At 20 rules and a diff capped at 8000 characters, a rule check costs on the order of 5k input tokens, so the free 100M-token tier covers roughly 20,000 checked edits. A whole file-discovery run over 100 candidates costs tens of thousands of tokens.

## Other facts checked

- `GET /v1/models` lists `openjev-latest`, `openjev-0.1`, `diffusiongemma-26b`, `laya-1.0`, `verdict-1.4`, `clm-v0.1`, `jevk5-0.2`.
- There is no usage or quota API; `GET /v1/usage`, `/v1/account` and `/v1/keys/self` return 404. Usage is only on the dashboard.
- Responses carry no rate-limit or quota headers.

## Reproducing

```bash
python tests/test_all.py                     # offline, 17 tests
python scripts/jevlib.py                     # one live call
python scripts/rule_calibrate.py --commits 15 --hunks 30   # inside any repo with rules
```
