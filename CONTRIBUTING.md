# Contributing

[简体中文](CONTRIBUTING.zh-CN.md)

The single most likely reason you're here: **ChatGPT shipped a UI change and something
broke.** That case is first.

## Fixing a broken selector

When a UI change breaks something, `cgh` fails loudly — `ui_changed`, `effort_not_found`
or `attachment_state` — and saves the scene. It does **not** return a wrong answer.
That's the design; keep it that way when you patch things.

1. Reproduce: `./bin/cgh doctor`, then a real low-tier `submit` or `cgimg` run for the affected flow.
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
./scripts/dryrun.sh          # CLI/ledger checks without a browser
./scripts/install-check.sh   # isolated installation matrix, no Chrome or Node required
```

`dryrun.sh` covers the ledger, locks, state machine, tier resolution, sentinel parsing and
content gates. It does **not** cover opening tabs, setting the tier, injecting the body,
sending, or completion detection.
`install-check.sh` exercises default, handoff-only, image-only and combined installation,
repeat installation, target conflicts and paths with spaces. It uses `CGH_INSTALL_HOME`
to keep the real skill directories untouched; installing only the image skill must still
resolve its CLI and shared modules from the same checkout.

After these pass, run both flows in a temporary git repository, using the absolute paths
to this checkout's CLIs and an isolated `CGH_LEDGER`:

```bash
CGH=/path/to/checkout/bin/cgh
CGIMG=/path/to/checkout/bin/cgimg
export CGH_LEDGER="$PWD/ledger.jsonl"
"$CGH" doctor
"$CGH" new --action review --effort instant -- "<something small, in your own words>"
# fill request.md
"$CGH" submit --id <job_id> && "$CGH" wait --id <job_id>
# Also follow up with a new attachment in the same conversation.
"$CGH" continue --from <job_id> --attach ./supplement.txt -- "Review the new evidence"
# Fill the child request.md, submit and wait.

"$CGIMG" "A blue ceramic mug on a plain table" --out ./images
"$CGIMG" "Paint the reference scene in watercolor" --ref ./reference.png --out ./images-ref
```

Replace the checkout paths above with your own. Check the returned files by opening
them: reference uploads must not be mistaken for generated output.
Verify requested/actual effort, failure tab retention, successful cleanup of only the
owned tab, and both CLIs' use of the same browser lock. Record any gaps in the PR along
with the actual tiers and results. A PR touching `bin/` that was only dry-run tested is
not verified.

## Layer boundaries

| File | Owns | Must not |
|---|---|---|
| `bin/cgh_cdp.py` | WebSocket transport, generic page ops | know anything about ChatGPT |
| `bin/cgh_web.py` | ChatGPT semantics: tabs, tiers, attachments, injection, progress, image candidates | own the job ledger or save image files |
| `bin/cgh_common.py` | Time/origin helpers, ledger append, shared browser lock | import a CLI or add ChatGPT UI logic |
| `bin/cgh` | Handoff jobs, per-repo lock, state machine, parsing, CLI | drive the browser directly |
| `bin/cgimg` | Image generation flow, output files, JSON result, CLI | duplicate ChatGPT UI logic or load another installed skill |

`cgh_cdp.py` is deliberately not a general DevTools framework. Resist growing it into one.
Both CLIs import the shared modules directly. Their shared browser lock covers tier
selection, model/tier verification, sending and confirmation; uploads, generation and
downloads stay outside it. This is not a queue or a concurrency scheduler.

## Hard rules

Read `AGENTS.md` §6 before changing anything in `bin/`. Summary of what a PR may not do:

- Touch, log, or persist credentials — ever.
- Act on a page whose host isn't `chatgpt.com` / `chat.openai.com`.
- Silently fall back to a lower reasoning tier.
- Auto-resend after an unconfirmed send.
- Treat an image generation timeout or download/save failure as proof that sending failed.
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
