# Changelog

## 0.1.2 — 2026-10-03

- README: the Zenodo DOI badge (the concept DOI always points to the latest version).

## 0.1.1 — 2026-10-03

- Zenodo DOI: the repository is archived on Zenodo; this release is the first one it records (same content as 0.1.0).

## 0.1.0 — 2026-10-02

- First release: `advisor`, `profile` (glm, kimi, deepseek, qwen, minimax, mimo, local, local-red), `key`, `window`,
  `crew`, `local`, `local load`, `gateway`, `server` and `doctor`; one skill, no hooks.
- `data/endpoints.json`: each vendor's Anthropic-compatible address, key variable and model names, with page and day.
- `data/crew.json`, `data/gateways.json` (LiteLLM at least 1.83.0, never 1.82.7 or 1.82.8), `data/local-models.json`.
- Reads the shared `company-ai-policy.json`: `allowed_providers`, `deny_providers`, `profiles`
  (`us-federal-contractor`, `us-dod-strict`), `red_paths`, `max_usd_per_day`, `language`.
- `profile local-red` is the one window that opens the red folders: no deny rule for them (it would win over
  every level), the folders as `additionalDirectories`, no web tools, `--strict-mcp-config`, and the mark
  `ROUTECALL_WINDOW=local-red` for gatecall's hook. Every other window keeps them denied.
- A local window talks to the server that answered (LM Studio on 1234, llama-swap on 8080), not always to Ollama's port.
