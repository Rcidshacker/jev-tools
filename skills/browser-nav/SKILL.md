---
name: browser-nav
description: Drive a browser toward a test goal ("sign in as admin and open settings", role-based access checks, multi-step UI flows) by letting Jev pick each next click from the page's interactive elements. Use for end-to-end UI navigation and permission testing where you would otherwise reason about the DOM at every step.
---

# browser-nav

Jev chooses the step; you execute it with the browser tool and give the final pass/fail. At most 25 steps.

1. Read the page's interactive elements (`read_page` with the interactive filter): `ref`, `role`, `name`.
2. Ask for the next step:
   ```bash
   echo '{"goal":"<goal>","url":"<url>","elements":[{"ref":"ref_1","role":"button","name":"Sign in"}],"history":["clicked ref_4"]}' | python "${CLAUDE_SKILL_DIR}/../../scripts/pick_next.py"
   ```
3. Act on the JSON it prints:
   - `click`: click `ref`.
   - `type`: focus `ref` and type the value the goal calls for (it never invents text; credentials come from the user).
   - `done`: verify the goal on screen and report pass.
   - `blocked`: stop and report fail with the last page state.
   - `unsure` or `error`: Jev is not confident or unavailable; choose this step yourself.
4. Append what you did to `history` and repeat, passing the new `url` and elements.

## Gotchas

- Pass the current `url` and the recent `history`; without them Jev can call a finished goal unmet.
- Answers vary slightly between identical calls, so `done` also fires when nothing is left to click and the goal looks probably met.
- Only tested on a synthetic login page, never against a real browser session.
- Never submit payments or destructive actions without asking the user.
