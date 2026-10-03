# routecall

The strong model thinks, cheap and local models work — and nobody loses the remote on their phone. A
[Claude Code](https://claude.com/claude-code) plugin of Poly A1, for the person in a company who sets AI up.
Repository: [github.com/vadimchernets/routecall](https://github.com/vadimchernets/routecall).

**routecall routes and measures; it buys nothing, opens no checkout and never asks for a card or a key in the
chat.** What each route costs comes from billcall's dated price table (`billcall estimate`); the person
responsible for the company's accounts buys, from the vendor's own page.

## The rule it is built on

People work on a claude.ai seat (Team, Enterprise, Pro or Max): that sign-in is what gives them Remote Control from
the phone, cloud sessions, the advisor and the organisation's rules from the admin console. A cheaper vendor's model
reaches Claude Code through `ANTHROPIC_BASE_URL`, and under it all four stop (code.claude.com/docs/en/remote-control,
/managed-settings, /advisor, read 02.10.2026). So routecall never moves the person's Claude Code: a cheap model gets
**its own window per project**, and scripts get a gateway. It refuses to write `~/.claude/settings.json`.

## What it does

| Command | What the company gets |
|---|---|
| `advisor` | Cheaper on the seat itself: the advisor tool (Sonnet works, Opus advises at decision points), `opusplan` (Opus plans, Sonnet does), subagents on Haiku. `--write` puts the choice into the project's `.claude/`. |
| `profile glm\|kimi\|deepseek\|qwen\|minimax\|mimo` | A second window for this project on that vendor's Anthropic-compatible address: `.routecall/<name>/settings.json` and a launcher (`claude.sh`, `claude.ps1`) that reads the key from the system keychain when it opens and removes a stray `ANTHROPIC_API_KEY`. A banner says what does not work there and which files the window's rules come from. Red folders of the company policy are denied in it. |
| `key <name>` | The one line the person types in a terminal to put the key into the keychain (macOS Keychain, libsecret, Windows' credential store) — the key never passes through Claude. |
| `window <name>` / `profile … --window` | A git worktree with sparse checkout that leaves the red folders out: the cloud model's window never has them on disk. |
| `profile local` / `profile local-red` | A window on a model on this computer (Ollama, LM Studio, llama.cpp, llama-swap); the window talks to the server that answered. `local-red` adds `OLLAMA_NO_CLOUD=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` in that window only, names the firewall rule (LuLu: localhost only), and is the one window that opens the red folders: they become its working folders, it has no web tools and no MCP server, and its mark `ROUTECALL_WINDOW=local-red` tells gatecall's hook to open them to this window only. |
| `local` | Which model to run as the lead and which on call for this machine's memory, and which machines of that size the price table has. |
| `local load` | Measures a running local server: tokens a second for one request and for N at once, and how many people working with an agent that holds. |
| `crew list\|check\|run` | Codex, Gemini CLI, Qwen Code or Kimi CLI, each with its own API-key login, for scripted work — only on a price row whose `use` is `automated`. A person's plan or a team seat is refused with the vendor's rule. |
| `gateway` | Compares LiteLLM, Bifrost, Higress, RouteLLM, claude-code-router, llama-swap, cc-proxy-plugin and opencodex (licence and last activity from GitHub, 02.10.2026). `--profiles a,b` writes a LiteLLM config for scripts and CI with the company's daily budget and Presidio masking; LiteLLM at least 1.83.0, never 1.82.7 or 1.82.8. `--for people` is refused. |
| `server` | A llama-swap config for the company's own machine: one lead model kept loaded, the rest loaded when called. |
| `doctor` | The address Claude Code talks to and who set it; whether Remote Control and the advisor work in this setup and why not; the rules that bind this computer; a warning when the address sits in the person's own settings. |

## The company policy file

`company-ai-policy.json` is shared by the company plugins (firmcall writes it; gatecall, routecall and billcall read
it), looked for in the managed folder an administrator installed, then `$COMPANY_AI_POLICY`, the project and its
`.claude/`, then `~/.claude/`. routecall reads `allowed_providers`, `deny_providers`, `profiles`
(`us-federal-contractor` stops DeepSeek, also its weights on an own machine; `us-dod-strict` stops the Chinese
vendors), `red_paths`, `max_usd_per_day` (the gateway's daily budget) and `language`.

## Where the addresses come from

`data/endpoints.json` names, for every profile, the vendor's own page and the day it was read (02.10.2026):
DeepSeek `api.deepseek.com/anthropic`, Z.ai `api.z.ai/api/anthropic`, Moonshot `api.moonshot.ai/anthropic`, Alibaba
Model Studio `dashscope-intl.aliyuncs.com/apps/anthropic` (US and workspace addresses beside it), MiniMax
`api.minimax.io/anthropic`, Xiaomi MiMo `api.xiaomimimo.com/anthropic`, with the model names each page gives.

## Measured on the author's machine (02.10.2026)

- `doctor` on a Mac with no override: requests go to `api.anthropic.com` (nobody set it), Remote Control available,
  rules from claude.ai's server-managed settings (if the organisation sets them) and `~/.claude/settings.json`.
- `local` on an Apple M5 with 16 GB: lead model `gpt-oss-20b`; on call Qwen3.5-4B, Qwen3-Embedding-0.6B, Gemma 4 E4B,
  GLM-4.7-Flash.
- `local load`: no local model server runs on that machine (Ollama, LM Studio and llama-swap ports checked), so there
  is no number from it yet; it answers with exit 3 and says so. The measurement itself is tested against a stand-in
  server in `tests/test_routecall.py`. On a machine with Ollama: `routecall local load` gives the figure.

## What it needs

Python 3.8+ and its standard library — no dependencies, no network module; curl for talking to a local model server.
Skills run their script through `hooks/python.sh` (PowerShell: `hooks/python.ps1`).

## Checks

`python3 -m pytest -q tests` — every profile writes only into the project and its launcher reads the key from the
keychain and drops a stray API key; the banner names what stops and where the rules come from; the red window keeps
everything local; the policy's denials (including a defence contractor's local DeepSeek) stop profiles, the crew and
the gateway; crew refuses a person's plan; `local load` measures a stand-in server; the gateway is never for people
and refuses LiteLLM 1.82.7/1.82.8; doctor names each switch that turns Remote Control or the advisor off; the sparse
worktree leaves red folders out; no network module is present. `python3 tools/mutate_code.py` breaks those rules one
by one in a copy and expects red; its last line counts the mutations that misbehaved.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`.
