# Security

## What routecall touches

- **The project folder it is pointed at**: it writes `.routecall/<name>/settings.json` and a launcher
  (`claude.sh`, `claude.ps1`) there, and with `advisor --write` the project's own `.claude/settings.local.json` and
  `.claude/agents/routecall-worker.md`. With `window` it adds a git worktree beside the repository.
- **Claude Code's settings files**, read-only, for `doctor`: the managed file and `managed-settings.d/`, the
  project's and the person's settings. It reports variable names and addresses, never a key's value.
- **The company policy file** `company-ai-policy.json`, read-only.
- **billcall's price table** `data/prices.json`, read-only, for the crew rule.
- **A model server on this computer** (localhost only), through curl, for `local` and `local load`.

## What it never does

- Never writes `~/.claude/settings.json` or anything under `~/.claude/`: a refusal in the code stops it, and a test
  proves the person's home stays untouched.
- Never stores, prints or asks for an API key. The launcher reads it from the system keychain (macOS Keychain,
  libsecret on Linux, Windows' credential store) at the moment the window opens; the person puts it there with a
  line they type themselves.
- Never goes to the network: Python's standard library only and no network module (a test fails the build if one
  appears); curl is called only for an address on this computer.
- Never buys, subscribes or asks for a card.

## Reporting

Open an issue on github.com/vadimchernets/routecall, or write to the author through the Poly A1 support address.
