---
name: routecall
description: Get the strongest AI for the lowest bill by giving each kind of work its own model - the strong model plans, cheap and local models do the routine. Use it when someone from a company wants Claude to cost less without getting weaker, asks about the advisor, opusplan or subagents on Haiku, wants a cheap window with DeepSeek, Kimi, Qwen, GLM, MiniMax or MiMo in Claude Code, wants confidential work done by a model on their own machine, asks which local model fits their computer or how many people one machine holds, wants scripts and CI to run on other vendors' agents, needs a gateway for background jobs, or asks why Remote Control stopped working.
argument-hint: "[advisor | profile NAME | key NAME | window NAME | crew | local | local load | gateway | server | doctor]"
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/routecall.py *) PowerShell(${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1 routecall say skills/routecall/scripts/routecall.py *) Read
---

# routecall: the strong model thinks, cheap and local models work

## Running routecall's scripts (Mac, Linux, Windows)

Every script command on this page is written for the **Bash** tool and starts with
`sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/…`. If your shell tool is
**PowerShell** (Windows without Git Bash), only the start changes: write the launcher's path bare, with no quotes
and no `&` — `${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1 routecall say skills/routecall/scripts/…` — and keep the rest,
on one line; that is the form this skill's permission covers. Only if that path has a space in it, write
`& "${CLAUDE_PLUGIN_ROOT}/hooks/python.ps1" …` instead (the person is then asked once). Never call `python3`,
`python` or `py` yourself: the launcher finds a real Python 3.8+ and never starts the Microsoft Store or Apple stub.
If it answers with one line saying routecall "is paused" because this computer has no working Python 3 yet, tell
the person that in one plain line and stop.

The user said: $ARGUMENTS

Answer in the person's language. Say what each choice gives first; the price comes from billcall (`billcall
estimate`), never from memory. routecall buys nothing and never asks for a card. A vendor's API key is typed by the
person into the system keychain — never into the chat, never into a file.

## The one rule behind everything here

People keep their **claude.ai sign-in** (a Team, Enterprise, Pro or Max seat): that is what gives them Remote
Control from the phone, cloud sessions, the advisor and the organisation's rules from the admin console. A cheap
model reaches Claude Code through `ANTHROPIC_BASE_URL`, and under it those stop. So a cheap model gets **its own
window** for the project (`profile`), never the person's whole Claude Code; scripts and CI get a gateway. Say this
once, plainly, when the person first asks for a cheaper model.

## 1. Cheaper inside Claude itself (start here)

```
sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/routecall.py advisor
```

Three ways, all on the person's own seat: the advisor (Sonnet works, Opus is consulted at decision points),
`opusplan` (Opus plans, Sonnet does), subagents on Haiku for routine steps. With `--mix advisor --write`,
`--mix opusplan --write` or `--mix subagents --write` it writes the choice into this project's `.claude/` files.

## 2. A cheap window with another vendor's model

```
sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/routecall.py profile deepseek --project .
```

Names: `glm`, `kimi`, `deepseek`, `qwen`, `minimax`, `mimo`. It writes `.routecall/<name>/settings.json` and a
launcher `.routecall/<name>/claude.sh` (`claude.ps1` on Windows) in the project, shows the banner — what does not
work in that window and where its rules come from — and stops. Read the banner to the person in their words. Then:

```
sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/routecall.py key deepseek
```

prints the one line **the person types themselves in a terminal** to put the key into the keychain. Never ask them
to paste a key into the chat. They open the window with `sh .routecall/deepseek/claude.sh` in a terminal.

If the company has red folders (`red_paths` in `company-ai-policy.json`), the window's settings deny them, and
`--window` makes the window work in a git worktree that leaves them out entirely (`window <name>` makes it alone).
If the company policy forbids the vendor, routecall says so and writes nothing — tell the person which line of
the policy did it.

## 3. Confidential work on this computer

`profile local` — a model on this machine (Ollama, LM Studio, llama.cpp, llama-swap). `profile local-red` — the
same with Ollama's cloud off and Claude Code's non-essential traffic off, in that window only (Remote Control is
off in it; their usual window keeps it). It is the one window that opens the red folders: they become its working
folders (`additionalDirectories`), it has no web tools and starts with no MCP server (`--strict-mcp-config`), and
it carries the mark `ROUTECALL_WINDOW=local-red` that gatecall's hook reads — every other window, the ordinary
local one included, keeps the red folders shut. Offer the firewall line from the banner (LuLu on a Mac) for the last door.
`local` says which model to run as the lead and which on call for this machine's memory; `local load` measures a
running server and says how many people it holds. If no server runs, say so and offer the install line for Ollama.

## 4. Scripts, CI and night jobs

- `crew list` / `crew check <member>` / `crew run <member> --task "…"` — Codex, Gemini CLI, Qwen Code or Kimi CLI
  with their own API-key login. A member runs only on a price row whose use is `automated`; a person's plan is
  refused, and the line says why.
- `gateway --profiles glm,deepseek` — a LiteLLM config (version 1.83.0 or later, never 1.82.7 or 1.82.8) with the
  company's daily budget and Presidio masking; `gateway` alone compares the gateways; `gateway --check-installed`
  checks the installed LiteLLM. Never for people: `--for people` is refused.
- `server --lead name=file.gguf --on-call name=file.gguf` — a llama-swap config for the company's own machine.

## 5. When something stopped working

```
sh "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" routecall say skills/routecall/scripts/routecall.py doctor --project .
```

It names the address Claude Code talks to and who set it, whether Remote Control and the advisor work, which rules
bind this computer, and warns when `ANTHROPIC_BASE_URL` sits in the person's own settings (it moves every window).
Tell them the one change that brings back what they miss.
