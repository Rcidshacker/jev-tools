---
name: find-files
description: Rank the files in a repository by relevance to a plain-language question, using keyword search then OpenJev scoring. Use before exploring an unfamiliar codebase, when asked "where is X handled", "which files deal with Y", "find the code that does Z", or before spawning an Explore agent. Not for exact-symbol lookups (use grep) or reading a file you already know.
---

# find-files

Gathers keyword candidates, has Jev score them in two stages, and prints the best. Read only the top few.

```bash
python "${CLAUDE_SKILL_DIR}/../../scripts/find_files.py" "<the question in plain words>" --root . --top 8
```

Output is `percent  path`, best first.

## Gotchas

- It is a hint, not an oracle. On 8 labelled queries it matched plain keyword counting (top-3 hits 4-6 of 8, and repeat runs of the same query differed by up to 2 of 8). Confirm by opening the top 2-3 files rather than trusting rank 1.
- "Jev unavailable: keyword order only" on stderr means the ranking is raw keyword counts.
- "no keyword candidates" means the query words appear nowhere; rephrase with identifiers likely to be in the code.
- READMEs and docs can outrank the code that implements the thing; skip them when you want code.
- Needs `OPENJEV_API_KEY` (or the plugin's api_key option). Never print or echo it.
