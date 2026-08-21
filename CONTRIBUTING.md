# Contributing

[简体中文](CONTRIBUTING.zh-CN.md)

The single most likely reason you're here: **ChatGPT shipped a UI change and something
broke.** That case is first.

## Fixing a broken selector

When a UI change breaks something, `cgh` fails loudly — `ui_changed`, `effort_not_found`
or `attachment_state` — and saves the scene. It does **not** return a wrong answer.
That's the design; keep it that way when you patch things.

1. Reproduce: `./bin/cgh doctor`, then a real `submit` on a cheap tier.
2. Read `bin/cgh_web.py`. Every anchor has a comment saying what it is and why it's
   written that way. Most of those comments are the residue of a bug — read before editing.
3. Element location priority, in order — **do not skip down the list**:
   1. accessible role + name
   2. visible page text
   3. `data-testid` / `data-message-author-role`
   4. give up: save the snapshot, set `ui_changed`
   Never hardcode a CSS selector path. Never click blind coordinates.
4. Keep failures loud. If you find yourself adding a fallback that lets the flow continue
   in an unknown state, you're building the exact defect class this tool exists to avoid.

## Adding your UI language

Two places are language-coupled, both in `bin/cgh_web.py`:

```python
EFFORT_LABELS = {"instant": ["极速", "Instant"], ...}   # reasoning tier names
/在文本字段中显示|Show in text field/                    # the "pasted text" attachment chip
```

Add your labels to both. If your tier label is missing, `cgh` stops at `effort_not_found`
and prints what it actually saw — paste that list into the PR.

## Verifying a change

**There are no unit tests, on purpose.** Half of this program lives inside a browser
someone else controls; a mocked test of that half asserts your assumptions, not reality.
What's real:

```bash
./scripts/dryrun.sh          # 25 checks, no browser needed — CI runs this too
```

`dryrun.sh` covers the ledger, locks, state machine, tier resolution, sentinel parsing and
content gates. It does **not** cover opening tabs, setting the tier, injecting the body,
sending, or completion detection.

So after it goes green:

```bash
./bin/cgh new --action review -- "<something small, in your own words>"
# fill request.md
./bin/cgh submit --id <job_id> && ./bin/cgh wait --id <job_id>
```

Say in the PR that you did this, and on which tier. A PR touching `bin/` that was only
dry-run tested is not verified, and will be treated as such.

## Layer boundaries

| File | Owns | Must not |
|---|---|---|
| `bin/cgh_cdp.py` | WebSocket transport, generic page ops | know anything about ChatGPT |
| `bin/cgh_web.py` | ChatGPT semantics: tabs, tiers, injection, progress | own the job ledger |
| `bin/cgh` | Jobs, locks, state machine, parsing, CLI | drive the browser directly |

`cgh_cdp.py` is deliberately not a general DevTools framework. Resist growing it into one.

## Hard rules

Read `AGENTS.md` §6 before changing anything in `bin/`. Summary of what a PR may not do:

- Touch, log, or persist credentials — ever.
- Act on a page whose host isn't `chatgpt.com` / `chat.openai.com`.
- Silently fall back to a lower reasoning tier.
- Auto-resend after an unconfirmed send.
- Rewrite, summarize, or "clean up" ChatGPT's output.
- Add a third-party dependency. Standard library only, Python ≥ 3.9. CI enforces this.

## Out of scope

Multi-account, batch runs, concurrency scheduling, a hosted service, a browser extension,
a ChatGPT API replacement. This is a personal, local, low-frequency tool and stays one.

## Commits and PRs

Format: `<type>: <short summary>` where type ∈ `feat` / `fix` / `docs` / `chore` / `design`.

Say *why* in the body, not just what — the commit log is the only place the reasoning
behind a selector or a threshold survives. Before pushing, run `git status --short` and
confirm no credentials, no `.env`, no `.chatgpt/web-handoff/` artifacts.
