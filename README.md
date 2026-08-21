# chatgpt-web-handoff (`cgh`)

**Hand your coding agent's current context to the ChatGPT Web session already logged in
in your everyday Chrome — and pull a structured verdict back into your repo.**

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

No browser extension. No Native Messaging. No broker service. No second Chrome profile.
No credentials touched, stored, or moved — it drives the session you're already in.

---

## Quick start

```bash
# 1. Chrome must expose the DevTools port. If it isn't already:
#    (quit Chrome first, then)
open -a "Google Chrome" --args --remote-debugging-port=9222     # macOS
# google-chrome --remote-debugging-port=9222                    # Linux

# 2. Log into chatgpt.com in that Chrome, as you normally would.

# 3. Install
git clone https://github.com/sologuy/chatgpt-web-handoff.git
cd chatgpt-web-handoff
./scripts/install.sh

# 4. Check
./bin/cgh doctor
```

`install.sh` symlinks the skill into `~/.claude/skills/`, `~/.agents/skills/` and
`~/.codex/skills/` — so Claude Code, Codex and DSH all pick up the same copy.
Requires **Python ≥ 3.9, stdlib only**. No pip install, no build step, no daemon.

## Use it

The intended entry point is the skill — in Claude Code, Codex or DSH just say:

```
/chatgpt-handoff  review whether the retry logic in the uploader can double-charge
```

Or drive the CLI yourself:

```bash
CGH=./bin/cgh

$CGH new --action review -- "review whether the retry logic can double-charge"
$EDITOR .chatgpt/web-handoff/<job_id>/request.md    # fill in the context
$CGH submit --id <job_id>                            # returns immediately
$CGH wait   --id <job_id>                            # blocks until the answer lands
$CGH outcome --id <job_id> --status adopted --note "which advice was gold, which was a trap"
```

`wait` polls for you — you don't sit there asking "is it done yet".

| Command | What it does |
|---|---|
| `new` / `continue` | Create a job / follow up in the *same* ChatGPT conversation |
| `submit` | Pick the reasoning tier, inject the body, send, capture the conversation URL |
| `poll` / `wait` | Read progress once / block until the verdict is parsed |
| `outcome` | Record whether the advice was adopted — the only signal that lets this improve |
| `stats` | Cross-repo stats: tier cost/benefit, who initiated, adoption rate |
| `doctor` | Preflight: port reachable, logged in, tab found, tier readable |
| `list` / `state` / `abort` / `confirm` / `parse` | Ledger and manual recovery |

## What comes back

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
Your agent (Claude Code / Codex / DSH)
   └─ skill: writes request.md — that's all it does
        └─ cgh  (deterministic: job ledger, locks, tier control, parsing)
             └─ raw CDP → 127.0.0.1:9222
                  └─ your everyday Chrome, already logged into ChatGPT
                       └─ artifacts land in <your repo>/.chatgpt/web-handoff/<job_id>/
```

The browser choreography lives in **code, not in the prompt**. That's deliberate: a
twenty-step flow with state transitions and branches is a state machine, and a prompt
version of it can't be asserted, diffed, or regression-tested — it just quietly drifts.
The reasoning behind each step lives in the code comments of `bin/cgh_web.py`.

## Guarantees it actually enforces

These are checked in code, not promised in a doc:

- **No silent tier downgrade.** If the requested reasoning tier isn't in the UI, the job
  stops as `effort_not_found` and lists what *is* available. It never quietly runs a
  cheaper tier and hands you the result.
- **Tier is read back** from the UI after being set, and re-verified immediately before
  send — the tier is an account-level preference that another tab can change under you.
- **The model is verified**, not assumed (`CGH_EXPECTED_MODEL` to pin your own).
- **Page allowlist.** Nothing is clicked unless the tab's host is `chatgpt.com`.
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
  of this that lives in a browser. Ship changes by re-running an actual low-tier job.
- **Single active job per repo**, enforced by a lockfile. Different repos run in parallel;
  a machine-wide lock guards only the one-second `set tier → send` window.
- **This is a personal, local, low-frequency tool.** It is not a ChatGPT API replacement,
  not a shared service, not for batch work. Automating a web session may sit awkwardly
  with your provider's terms — that call, and its consequences, are yours.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — start there if a ChatGPT UI change broke
something, or if you want to add your UI language.

## License

MIT — see [LICENSE](LICENSE).
