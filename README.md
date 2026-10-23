# chatgpt-web-handoff (`cgh` + `cgimg`)

**Use your existing ChatGPT Web session in your everyday Chrome for independent reviews
and image generation, with results saved locally.**

[简体中文](README.zh-CN.md)

[![CI](https://github.com/sologuy/chatgpt-web-handoff/actions/workflows/ci.yml/badge.svg)](https://github.com/sologuy/chatgpt-web-handoff/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%E2%89%A5%203.9-blue)](#quick-start)
[![deps](https://img.shields.io/badge/dependencies-none-brightgreen)](#quick-start)
[![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)](#limits--read-these)

Your local agent (Claude Code, Codex, DSH…) is good at *doing*. When you hit a root-cause
call, an architecture trade-off, or a change you can't afford to get wrong, you want an
**independent second opinion** — from a different model, with a different bias, that has no
stake in the code it's reviewing.

`cgh` packages the current task into a `request.md`, drives your **already-logged-in**
ChatGPT tab over the Chrome DevTools Protocol, and parses the reply back into a
`result.md` with `verdict` / `findings` / `recommended_actions`.

`cgimg` uses the same browser connection to generate images, optionally from reference
images, and saves the generated files locally. The two skills can be installed separately;
both CLIs and their shared modules live in this repository.

No browser extension. No Native Messaging. No broker service. No second Chrome profile.
No credentials touched, stored, or moved — it drives the session you're already in.

---

## v0.7.0 · 2026-10-23

- **Two optional skills:** install `chatgpt-handoff`, `chatgpt-image-gen`, or both from one checkout. Image generation does not require the handoff skill to be installed.
- **Shared browser code:** both CLIs use the same ChatGPT UI checks, raw CDP transport, origin/ledger helpers, and short browser lock around tier selection and sending.
- **Image generation at xhigh:** `cgimg` supports style, aspect ratio and reference images, waits for generation, then saves the images and returns JSON paths.
- **Preserved failure context:** image failures retain their own tab and report the page ID and conversation URL when known. An unconfirmed send is never automatically repeated.

## v0.6.0 · 2026-10-23

`main` is the delivery branch: verified changes are merged and pushed there. Use a
release tag when you need a fixed version.

- **Follow-ups can attach new files** with `continue --from … --attach …`, while keeping the same ChatGPT conversation.
- **UI compatibility and page recovery:** model readback, Chinese/English tier labels, visible controls, and verified unsent-draft recovery. Deep preflight cleans up its own empty tab. The 2026-10-23 live run read back **GPT-6 / Instant**; Chinese tier names remain supported aliases.
- **Review history:** jobs record their originating agent/session when available; `outcome` records adoption decisions and retains updates in the append-only ledger.
- **Correct statistics and safe repair:** `stats --json` emits only JSON and counts completed jobs without an outcome by set difference. `backfill --dry-run` previews missing events; `--id` and `--event` limit what is repaired. Ledger write failures are reported without resending a handoff.

The release code passed the **25-check dry run and a real browser submission**, including
a deliberately unwritable ledger followed by repair in an isolated ledger.

## Quick start

```bash
# 1. Install either skill, or both. Installation does not need Chrome or Node.
git clone https://github.com/sologuy/chatgpt-web-handoff.git
cd chatgpt-web-handoff
./scripts/install.sh                    # handoff only (backward-compatible default)
# ./scripts/install.sh --skills image   # image generation only
# ./scripts/install.sh --skills all     # both skills

# 2. Before running either CLI, Chrome must expose the DevTools port:
#    (quit Chrome first, then)
open -a "Google Chrome" --args --remote-debugging-port=9222     # macOS
# google-chrome --remote-debugging-port=9222                    # Linux

# 3. Log into chatgpt.com in that Chrome, as you normally would.

# 4. Check
./bin/cgh doctor
```

`install.sh --skills handoff|image|all` symlinks the selected skills into
`~/.claude/skills/`, `~/.agents/skills/` and `~/.codex/skills/`, plus
`~/.hermes/skills/` when `~/.hermes` already exists. Each harness reads the same source.
It checks all selected targets before writing, refuses to overwrite real files or
directories, and leaves unselected skills alone. For an isolated installation, set
`CGH_INSTALL_HOME=/path/to/install-root`; this changes only the installation root.
Requires **Python ≥ 3.9, stdlib only**. No pip install, no build step, no daemon.
The optional `--register-mcp` flag requires Node, npx and Claude Code; that MCP is for
diagnostics, and neither CLI needs it for normal use.

## Use handoff

The intended entry point is the skill — in Claude Code, Codex or DSH just say:

```
/chatgpt-handoff  review whether the retry logic in the uploader can double-charge
```

Or drive the CLI yourself:

```bash
CGH=./bin/cgh

$CGH new --action review -- "review whether the retry logic can double-charge"
$CGH new --action review --attach ./bug.png --attach ./trace.log -- "..."   # with images/files
$EDITOR .chatgpt/web-handoff/<job_id>/request.md    # fill in the context
$CGH submit --id <job_id>                            # returns immediately
$CGH wait   --id <job_id>                            # blocks until the answer lands
$CGH outcome --id <job_id> --status adopted --note "which advice was gold, which was a trap"
```

`wait` polls for you — you don't sit there asking "is it done yet".

Follow up with another file, or inspect and repair the ledger:

```bash
$CGH continue --from <previous_job_id> --attach ./supplement.pdf -- "Review the new evidence"
# Fill the new request.md, then submit and wait using the returned child job_id.
$CGH stats --json
$CGH backfill --dry-run --id <job_id> --event completed
# After checking the preview:
$CGH backfill --id <job_id> --event completed
```

Backfill preserves original event times and does not modify job/result files or infer
outcomes. A completion needs a valid result block; when the raw reply exists, its parsed
result must agree. Repeating the same repair adds no duplicate event.

| Command | What it does |
|---|---|
| `new` / `continue` | Create a job / follow up in the *same* ChatGPT conversation, with optional new attachments |
| `submit` | Upload attachments, pick the reasoning tier, inject the body, send, capture the conversation URL |
| `poll` / `wait` | Read progress once / block until the verdict is parsed |
| `outcome` | Record whether the advice was adopted — the only signal that lets this improve |
| `stats` | Cross-repo ledger statistics; `--json` emits a machine-readable summary and detail |
| `backfill` | Preview or append missing created/completed events; supports `--dry-run`, `--id`, and `--event` |
| `doctor` | Preflight: port reachable, logged in, tab found, tier readable |
| `list` / `state` / `abort` / `confirm` / `parse` | Ledger and manual recovery |

## Generate images

After installing with `--skills image` or `--skills all`, invoke the skill:

```
/chatgpt-image-gen  an orange cat on a wooden ladder in an old bookshop, afternoon light
```

Or use the CLI directly:

```bash
./bin/cgimg "An orange cat on a wooden ladder in an old bookshop" \
  --style "photorealistic, shallow depth of field" --aspect 3:2 --out ./images

./bin/cgimg "Paint this scene in watercolor" --ref ./reference.png --out ./images
```

`cgimg` uses **xhigh only** and waits in the foreground for generation and saving.
The returned JSON lists saved files in `images[].path`. `--ref` is repeatable;
`--note` appends an instruction, `--max` limits saved images, and `--timeout` / `--interval`
control waiting. Use `--keep-tab` to retain the successful conversation. Model readback
is checked; `--allow-model-drift` explicitly permits a model outside the expected list, without lowering
the reasoning tier. See `./bin/cgimg --help` for the full parameter list.

Failure keeps the tab created by that run and reports its page ID and conversation URL
when available. **Do not blindly rerun after `send_unknown`, a generation timeout, or a
download/save failure:** the original request may already be generating or complete.
Inspect that conversation first. Only a successful run closes its own tab by default;
other tabs are left alone. Check per-image errors as well as saved paths when downloads
are incomplete.

## What handoff returns

`result.md` holds the **raw reply, unmodified**, plus a parsed block:

```
verdict: pass | revise | reject
confidence: 0.0-1.0
summary: <one line>
findings: […]
recommended_actions: […]
missing_information: […]
```

Nothing is summarized away, no dissenting point is dropped, no uncertain claim is
promoted to a certain one. If ChatGPT doesn't close with the required block, you get
`no_sentinel` and the raw text — never a model-invented field.

## How it works

```
Your agent (Claude Code / Codex / DSH / Hermes)
   ├─ chatgpt-handoff → cgh → request.md / result.md in your repo
   └─ chatgpt-image-gen → cgimg → image files in --out
        Both CLIs share:
        cgh_common.py (origin, ledger, browser lock)
        cgh_web.py (ChatGPT UI) → cgh_cdp.py (raw CDP)
             → 127.0.0.1:9222 → your logged-in Chrome
```

The browser choreography lives in **code, not in the prompt**. That's deliberate: a
twenty-step flow with state transitions and branches is a state machine, and a prompt
version of it can't be asserted, diffed, or regression-tested — it just quietly drifts.
The reasoning behind each step lives in the code comments of `bin/cgh_web.py`.
Handoff artifacts remain in `<your repo>/.chatgpt/web-handoff/<job_id>/`.

## Handoff guarantees

These are checked in code, not promised in a doc:

- **No silent tier downgrade.** If the requested reasoning tier isn't in the UI, the job
  stops as `effort_not_found` and lists what *is* available. It never quietly runs a
  cheaper tier and hands you the result.
- **Tier is read back** from the UI after being set, and re-verified immediately before
  send — the tier is an account-level preference that another tab can change under you.
- **The model is verified**, not assumed (`CGH_EXPECTED_MODEL` to pin your own).
- **Page allowlist.** Nothing is clicked unless the tab's host is `chatgpt.com` or `chat.openai.com`.
- **Send is idempotent.** If the send fired but the conversation URL never appeared, you
  get `send_unknown` — a non-terminal state that refuses to auto-resend.
- **Your instruction is frozen** with a sha256 and cross-checked, so an agent can't
  paraphrase what you asked or swap the tier you named.
- **Artifacts are gitignored** in your repo on creation — `request.md` carries your code.

## Limits — read these

- **macOS-developed.** Linux should work; nothing macOS-specific is in the code path, but
  it hasn't been exercised there.
- **UI-coupled.** ChatGPT ships UI changes. When one breaks a selector you get
  `ui_changed` with a saved snapshot, not a wrong answer. Fixing it means editing
  `bin/cgh_web.py` — the code comments explain what each anchor is and why.
- **Tier labels are matched in Chinese and English only.** Another UI language will fail
  loudly at `effort_not_found`, listing the labels it actually saw — add yours to
  `EFFORT_LABELS`.
- **No unit tests.** Verification here is real runs; a dry run cannot exercise the half
  of this that lives in a browser. Changes to `bin/` require a real low-tier handoff and
  image generation, including a reference-image run.
- **Single active handoff job per repo**, enforced by a lockfile. Both CLIs share
  `~/.cgh/browser.lock` only for tier selection, model/tier verification, sending and
  confirmation. Uploads, generation and downloads are outside that lock. It does not
  provide batch or concurrency scheduling.
- **This is a personal, local, low-frequency tool.** It is not a ChatGPT API replacement,
  not a shared service, not for batch work. Automating a web session may sit awkwardly
  with your provider's terms — that call, and its consequences, are yours.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — start there if a ChatGPT UI change broke
something, or if you want to add your UI language.

## License

MIT — see [LICENSE](LICENSE).
