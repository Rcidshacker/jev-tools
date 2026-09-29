# Codiv / OpenJev API notes

Practical notes gathered while building. Codiv's own documentation is the source of truth: <https://codiv.ai/docs>.

## Endpoint and auth

```text
POST https://api.codiv.ai/v1/systemone
Authorization: Bearer <key>          key format: sk-codiv-...
Content-Type: application/json
User-Agent: <anything explicit>      the default Python-urllib UA is rejected with 403
```

Body: `{"model": "openjev-latest", "state": <string|object|array>, "questions": {...}}`. Response: `{"model", "answers": {id: {...}}, "usage": {"input_tokens", "output_tokens"}}`.

## Compatibility with TypeSafe's Jev

Codiv documents the same wire format, question types and error shapes. Setting `TYPESAFE_API_KEY` and `TYPESAFE_BASE_URL=https://api.codiv.ai` makes TypeSafe's SDKs work unchanged, and `jev-latest` / `jev-preview` are accepted as aliases for `openjev-latest`. Differences that matter:

- A pinned Jev version such as `jev-1.13.0` returns 400 `Unknown model`.
- Answers come from a different model, so probabilities differ; thresholds tuned on Jev must be re-checked.
- Optional OpenJev extensions: `images`, `steps`, `samples`, `think`, `sequential`. jev-tools does not use them; note that `samples` averaging did not reduce run-to-run variation in our file-discovery experiment.

## Models seen from `GET /v1/models`

`openjev-latest` (alias of `openjev-0.1`), `openjev-0.1`, `diffusiongemma-26b`, `laya-1.0`, `verdict-1.4`, `clm-v0.1`, `jevk5-0.2`. jev-tools uses `openjev-latest`.

## Limits (free tier at time of writing)

- 100M System One input tokens, plus a separate 10M for text generation.
- 1,200 requests per minute per key, 10 active keys per account.
- 65,536-token context (state and questions together), 8 MB body.
- `choice`: up to 255 options; `score`: 2 to 10 levels.
- `429 quota_exceeded_error` means the quota is spent: do not retry. `429 rate_limit_error` and `529` are retryable with backoff.

## Token accounting

Only `usage.input_tokens` counts. The state is read once per **chunk** of questions: one 6.9k-character state cost 2,394 tokens with 1 question, 2,490 with 5, and 5,291 with 20. Batch related questions in one request, and cap the state size.

## Things that are not there

- No usage, quota or account endpoint (`/v1/usage`, `/v1/account`, `/v1/keys/self` return 404) and no quota headers on responses. Usage is on the web dashboard only.
- Answers are not deterministic: identical requests can differ by several hundredths, occasionally more, so put a margin between your thresholds and the values you care about.

## Security notes

- Keep the key in an environment variable or the plugin's sensitive option, never in a repo or in chat.
- Pin the host and refuse redirects, as `scripts/jevlib.py` does, so an injected base URL cannot receive the key.
- Do not send secrets as `state`. The rule hook sends diffs, so run it only on code you are comfortable sending to the API.
