#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""routecall: the strong model thinks, cheap and local models work - without losing the remote.

Run it through the plugin's launcher (skills/routecall/SKILL.md says how):

  routecall.py advisor [--mix advisor|opusplan|subagents|all] [--write] [--project DIR]
      Strong-thinks, cheap-works inside Claude itself: the advisor tool, opusplan, subagents on a
      cheaper model. --write puts the choice into the project's own .claude/ files.
  routecall.py crew list | check MEMBER [--row ID] | run MEMBER --task TEXT [--cwd DIR] [--dry-run]
      Other vendors' own command-line agents for scripted work - only on a price-table row whose
      use is 'automated' (an API key), never on a person's plan.
  routecall.py profile NAME [--project DIR] [--model M] [--url U] [--window] [--dry-run]
      NAME: glm, kimi, deepseek, qwen, minimax, mimo, local, local-red. A second, cheap window
      for this project: .routecall/NAME/settings.json and a launcher that reads the key from the
      system keychain. Never touches ~/.claude/settings.json.
  routecall.py key NAME
      How to put the vendor's key into the system keychain (the key never passes through Claude).
  routecall.py window NAME [--project DIR]
      A git worktree with sparse checkout that leaves the company's red folders out - the folder a
      cloud model's window works in.
  routecall.py local [--ram-gb N]
      Which local model to run as the lead and which on call, for this machine's memory.
  routecall.py local load [--url U] [--model M] [--n 4] [--tokens 128]
      Measures a local model server: tokens a second for one request and for N at once, and how
      many people that holds.
  routecall.py gateway --profiles a,b [--for scripts|people] [--out DIR] [--check-installed]
      A LiteLLM config for scripts and CI (daily budget from the company policy, PII masked by
      Presidio), and the comparison of gateways. Never for people.
  routecall.py server --lead NAME=FILE.gguf [--on-call NAME=FILE.gguf ...] [--out DIR]
      A llama-swap config: one lead model kept loaded, the rest loaded when called.
  routecall.py doctor [--project DIR] [--json]
      Which address Claude Code talks to and who set it, which rules bind this computer, and
      whether Remote Control and the advisor work in this setup.

Standard library only. routecall never goes to the network itself: the only requests it makes are
to a model server on this computer (local, local load), through curl, and only when asked. It buys
nothing. Exit 0: fine. 1: refused - the line says why. 2: the input cannot be used. 3: nothing to
measure here (no local server). Never a traceback.
"""
import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DATA = os.path.join(ROOT, "data")
LANG_DIR = os.path.join(ROOT, "lang")
POLICY_NAME = "company-ai-policy.json"
MANAGED_DIRS = {
    "darwin": "/Library/Application Support/ClaudeCode",
    "linux": "/etc/claude-code",
    "win32": "C:\\Program Files\\ClaudeCode",
}
MDM_PLIST = "/Library/Managed Preferences/com.anthropic.claudecode.plist"
KEYCHAIN_SERVICE = "routecall"
ANTHROPIC_HOSTS = ("api.anthropic.com",)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")
LOCAL_SERVERS = (("ollama", "http://localhost:11434", "/api/tags"),
                 ("lmstudio", "http://localhost:1234", "/v1/models"),
                 ("llama-swap", "http://localhost:8080", "/v1/models"))
CLOUD_PROFILES = ("glm", "kimi", "deepseek", "qwen", "minimax", "mimo")
PROFILES = CLOUD_PROFILES + ("local", "local-red")
# The company-policy profiles that deny vendors, the same words gatecall's profiles.json uses.
POLICY_PROFILE_DENY = {
    "us-federal-contractor": ("deepseek",),
    "us-dod-strict": ("deepseek", "qwen", "qwq", "kimi", "moonshot", "glm", "chatglm", "zhipu", "z.ai", "zai",
                      "minimax", "abab", "mimo", "xiaomi", "alibaba", "dashscope", "doubao", "seed-",
                      "hunyuan", "ernie", "baichuan"),
}
# Variables that make Remote Control unavailable, from code.claude.com/docs/en/remote-control (02.10.2026).
REMOTE_OFF_VARS = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK")
REMOTE_PROVIDER_VARS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
REMOTE_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
TRUSTED_DEVICE_VARS = ("DISABLE_TELEMETRY", "DO_NOT_TRACK")
# Variables that stop the feature-flag fetch the advisor needs (code.claude.com/docs/en/advisor).
ADVISOR_OFF_VARS = ("DISABLE_TELEMETRY", "DO_NOT_TRACK", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                    "DISABLE_GROWTHBOOK", "CLAUDE_CODE_DISABLE_ADVISOR_TOOL")
MODEL_ENV = {"main": "ANTHROPIC_MODEL", "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
             "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL", "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
             "fable": "ANTHROPIC_DEFAULT_FABLE_MODEL", "subagent": "CLAUDE_CODE_SUBAGENT_MODEL"}
# The red window's mark. gatecall's hook reads it: only a session on this computer that carries it opens the
# red folders; every other session, a local one included, is kept out of them.
WINDOW_VAR = "ROUTECALL_WINDOW"
# What the red window does without, so nothing in it reaches the web: the web tools (here), every MCP server
# (--strict-mcp-config on its launcher), and a network program to an outside host (gatecall's hook).
RED_WINDOW_DENY = ("WebFetch", "WebSearch")


class Problem(Exception):
    """Input routecall cannot use. Printed as one line; exit 2."""


class Refused(Exception):
    """A rule says no. Printed as one line; exit 1."""


# ---------------------------------------------------------------- files and words -------------

def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise Problem("cannot read %s %s (%s)" % (what, path, exc.strerror))
    except ValueError as exc:
        raise Problem("%s %s is not valid JSON (%s)" % (what, path, exc))


def data(name):
    return load_json(os.path.join(DATA, name), "routecall's data file")


def lang_words(code):
    words = load_json(os.path.join(LANG_DIR, "en.json"), "the dictionary")
    path = os.path.join(LANG_DIR, "%s.json" % code)
    if code != "en" and os.path.isfile(path):
        words.update(load_json(path, "the dictionary"))
    return words


def pick_lang(explicit=None, policy=None, env=None):
    env = os.environ if env is None else env
    for code in (explicit, (policy or {}).get("language"), (env.get("LANG") or "")[:2]):
        if code and os.path.isfile(os.path.join(LANG_DIR, "%s.json" % code.lower())):
            return code.lower()
    return "en"


def say(words, key, **values):
    text = words.get(key) or lang_words("en").get(key, key)
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def write_text(path, text, mode=None):
    guard_global(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def guard_global(path):
    """routecall never writes the person's own Claude Code settings: a global ANTHROPIC_BASE_URL would
    take Remote Control and the organisation's rules away from every window, not only the cheap one."""
    real = os.path.realpath(path)
    home_claude = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude"))
    if real == os.path.join(home_claude, "settings.json") or real.startswith(home_claude + os.sep):
        raise Refused("routecall writes only into the project folder, never into %s" % home_claude)


# ---------------------------------------------------------------- the company policy file -----

def managed_dir():
    return os.environ.get("ROUTECALL_MANAGED_DIR") or MANAGED_DIRS.get(sys.platform)


def policy_paths(cwd=None):
    """Where company-ai-policy.json is looked for, the binding one first: the managed copy an
    administrator installed, then $COMPANY_AI_POLICY, then the project, then the person's own."""
    out = []
    managed = managed_dir()
    if managed:
        out.append(os.path.join(managed, POLICY_NAME))
    env = os.environ.get("COMPANY_AI_POLICY")
    if env:
        out.append(env)
    base = cwd or os.getcwd()
    out.append(os.path.join(base, POLICY_NAME))
    out.append(os.path.join(base, ".claude", POLICY_NAME))
    out.append(os.path.join(os.path.expanduser("~"), ".claude", POLICY_NAME))
    return out


def read_policy(explicit=None, cwd=None):
    """-> (policy dict, path) or ({}, None). A file that does not parse is a Problem, not silence."""
    for path in ([explicit] if explicit else policy_paths(cwd)):
        if path and os.path.isfile(path):
            value = load_json(path, "the company policy")
            if not isinstance(value, dict):
                raise Problem("%s must hold one JSON object" % path)
            return value, path
    if explicit:
        raise Problem("no company policy at %s" % explicit)
    return {}, None


def words_of(policy, key):
    value = (policy or {}).get(key) or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise Problem("%s in the company policy must be a list" % key)
    return [str(v).strip().lower() for v in value if isinstance(v, str) and v.strip()]


def policy_denial(vendor, names, policy):
    """Why the company policy does not allow this vendor or these model names, or None.

    vendor: the vendor's name; names: provider words and model names that identify it."""
    if not policy:
        return None
    hay = [str(vendor or "").lower()] + [str(n).lower() for n in names if n]
    allowed = words_of(policy, "allowed_providers")
    if allowed and str(vendor or "").lower() not in ("this computer", "this computer, nothing leaves") \
            and not any(a in h for a in allowed for h in hay):
        return "allowed_providers names only %s" % ", ".join(allowed)
    for d in words_of(policy, "deny_providers"):
        if any(d in h for h in hay):
            return "deny_providers names %s" % d
    for profile in words_of(policy, "profiles"):
        for d in POLICY_PROFILE_DENY.get(profile, ()):
            if any(d in h for h in hay):
                return "the policy's profile %s denies %s" % (profile, d)
    return None


def red_paths(policy, home=None):
    """The policy's red folders as absolute paths (case kept: a path is not a vendor name)."""
    home = home or os.path.expanduser("~")
    value = (policy or {}).get("red_paths") or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise Problem("red_paths in the company policy must be a list of folders")
    out = []
    for p in value:
        if not isinstance(p, str) or not p.strip():
            continue
        p = p.strip()
        if p == "~" or p.startswith("~/"):
            p = os.path.join(home, p[2:])
        out.append(os.path.abspath(p))
    return out


# ---------------------------------------------------------------- billcall's price table ------

def price_table_paths(explicit=None):
    out = []
    if explicit:
        return [explicit]
    if os.environ.get("BILLCALL_PRICES"):
        out.append(os.environ["BILLCALL_PRICES"])
    parent = os.path.dirname(ROOT)
    out.append(os.path.join(parent, "billcall", "data", "prices.json"))        # side by side (a checkout)
    grand = os.path.dirname(parent)                                            # plugin cache: <plugin>/<version>/
    cached = os.path.join(grand, "billcall")
    if os.path.isdir(cached):
        for version in sorted(os.listdir(cached), reverse=True):
            out.append(os.path.join(cached, version, "data", "prices.json"))
    return out


def price_rows(explicit=None):
    """-> ({row id: row}, path) from billcall's price table, or ({}, None) when it is not here."""
    for path in price_table_paths(explicit):
        if path and os.path.isfile(path):
            table = load_json(path, "billcall's price table")
            return dict((r["id"], r) for r in table.get("rows", []) if isinstance(r, dict) and "id" in r), path
    if explicit:
        raise Problem("no price table at %s" % explicit)
    return {}, None


# ---------------------------------------------------------------- where the rules come from ---

def settings_files(project):
    """Claude Code's settings files that can carry env and rules, the binding one first."""
    out = []
    managed = managed_dir()
    if managed:
        out.append(("managed", os.path.join(managed, "managed-settings.json")))
        drop = os.path.join(managed, "managed-settings.d")
        if os.path.isdir(drop):
            for name in sorted(os.listdir(drop)):
                if name.endswith(".json") and not name.startswith("."):
                    out.append(("managed", os.path.join(drop, name)))
    out.append(("project-local", os.path.join(project, ".claude", "settings.local.json")))
    out.append(("project", os.path.join(project, ".claude", "settings.json")))
    out.append(("user", os.path.join(os.path.expanduser("~"), ".claude", "settings.json")))
    return [(kind, path) for kind, path in out if os.path.isfile(path)]


def env_sources(project, env=None):
    """-> {variable: [(where, value), ...]} from the shell and every settings file's env block."""
    env = os.environ if env is None else env
    found = {}
    for kind, path in settings_files(project):
        try:
            value = load_json(path, "a settings file")
        except Problem:
            found.setdefault("_unreadable", []).append((kind, path))
            continue
        block = value.get("env") if isinstance(value, dict) else None
        if isinstance(block, dict):
            for k, v in block.items():
                found.setdefault(k, []).append(("%s %s" % (kind, path), str(v)))
    for k, v in env.items():
        found.setdefault(k, []).append(("the shell", v))
    return found


def host_of(url):
    m = re.match(r"^[a-z]+://([^/:?#]+|\[[^\]]+\])", str(url or ""), re.I)
    return m.group(1).lower() if m else ""


def is_anthropic(url):
    return not url or host_of(url) in ANTHROPIC_HOSTS


def is_local(url):
    return host_of(url) in LOCAL_HOSTS


def rule_sources(project, base_url, extra=None):
    out = []
    if not base_url or is_anthropic(base_url):
        out.append("server-managed settings from claude.ai, if the organisation sets them")
    if os.path.isfile(MDM_PLIST):
        out.append(MDM_PLIST)
    for kind, path in settings_files(project):
        if kind == "managed":
            out.append(path)
    if extra:
        out.append(extra)
    for kind, path in settings_files(project):
        if kind != "managed":
            out.append(path)
    return out or ["no rules file on this computer"]


# ---------------------------------------------------------------- profiles -------------------

def endpoint(name):
    profiles = data("endpoints.json")["profiles"]
    if name not in profiles:
        raise Problem("no profile %r - the profiles are %s" % (name, ", ".join(PROFILES)))
    return profiles[name]


def curl(args, timeout=10, stdin=None):
    """-> (exit code, stdout). routecall reaches only a server on this computer, through curl."""
    if not shutil.which("curl"):
        return 127, ""
    try:
        done = subprocess.run(["curl", "-s", "-m", str(timeout)] + list(args), input=stdin,
                              capture_output=True, text=True, timeout=timeout + 5)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, done.stdout


def local_server(url=None):
    """-> (kind, url, [model names]) of the first local model server that answers, or None."""
    tries = [(None, url, None)] if url else LOCAL_SERVERS
    for kind, base, path in tries:
        if not is_local(base):
            raise Refused("%s is not this computer - a local profile talks to localhost only" % base)
        for probe in ([path] if path else ["/api/tags", "/v1/models"]):
            code, out = curl([base.rstrip("/") + probe], timeout=3)
            if code != 0 or not out.strip():
                continue
            try:
                body = json.loads(out)
            except ValueError:
                continue
            names = [m.get("name") or m.get("model") for m in body.get("models", [])] if "models" in body \
                else [m.get("id") for m in body.get("data", [])]
            return kind or ("ollama" if probe == "/api/tags" else "local"), base, [n for n in names if n]
    return None


def keychain_read_sh(account):
    """The launcher's lines that read the key from the system store - the pattern of mailcall."""
    return ('if command -v security >/dev/null 2>&1; then\n'
            '  key=$(security find-generic-password -s %(s)s -a %(a)s -w 2>/dev/null) || key=\n'
            'elif command -v secret-tool >/dev/null 2>&1; then\n'
            '  key=$(secret-tool lookup service %(s)s account %(a)s 2>/dev/null) || key=\n'
            'else\n  key=\nfi\n'
            'if [ -z "$key" ]; then\n'
            '  echo "routecall: no key for %(a)s in the system keychain yet - ask Claude: routecall key %(a)s"\n'
            '  exit 1\nfi\n') % {"s": KEYCHAIN_SERVICE, "a": account}


def ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def keychain_read_ps(account):
    """PowerShell: the key from Windows' credential store (PasswordVault, read through Windows
    PowerShell 5.1, which has the WinRT types that PowerShell 7 lacks)."""
    inner = ("[void][Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]; "
             "try { $c = (New-Object Windows.Security.Credentials.PasswordVault).Retrieve('%s','%s'); "
             "$c.RetrievePassword(); $c.Password } catch { '' }" % (KEYCHAIN_SERVICE, account))
    return "$key = (& powershell.exe -NoProfile -Command %s | Out-String).Trim()" % ps_quote(inner)


def key_help(name):
    if name not in CLOUD_PROFILES:
        raise Problem("%s needs no key: it runs on this computer" % name)
    return {
        "mac": "security add-generic-password -U -s %s -a %s -w" % (KEYCHAIN_SERVICE, name),
        "linux": "secret-tool store --label='routecall %s' service %s account %s" % (name, KEYCHAIN_SERVICE, name),
        "windows": ("powershell -NoProfile -Command \"[void][Windows.Security.Credentials.PasswordVault,"
                    "Windows.Security.Credentials,ContentType=WindowsRuntime]; $k = Read-Host -AsSecureString 'key'; "
                    "$p = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::"
                    "SecureStringToBSTR($k)); (New-Object Windows.Security.Credentials.PasswordVault).Add((New-Object "
                    "Windows.Security.Credentials.PasswordCredential('%s','%s',$p)))\"" % (KEYCHAIN_SERVICE, name)),
        "say": "Type this line yourself in a terminal (not in the chat): it asks for the key without showing it, "
               "and the key goes straight into the system keychain. Claude never sees it.",
    }


def deny_rules(paths):
    """permissions.deny rules for red folders, with absolute //paths (Claude Code's form for an
    absolute path in a permission rule)."""
    out = []
    for p in paths:
        p = p.replace("\\", "/").rstrip("/")
        p = "//" + p.lstrip("/")
        for tool in ("Read", "Edit", "Write"):
            out.append("%s(%s/**)" % (tool, p))
    return out


def build_profile(name, project, policy, model=None, url=None, workdir=None, server=None):
    """-> dict with settings, launcher text and banner facts for one profile. Raises Refused when
    the company policy forbids it."""
    ep = endpoint(name)
    # The server that answered (LM Studio on :1234, llama-swap on :8080) is the one the window talks to.
    base = url or (server[1] if server and server[1] else None) or ep["base_url"]
    local = name in ("local", "local-red")
    if local and not is_local(base):
        raise Refused("%s talks to this computer only, and %s is not it" % (name, base))
    if not local and is_local(base):
        raise Problem("%s is a vendor's address, not this computer" % name)
    models = dict(ep.get("models") or {})
    if model:
        models = {"main": model, "opus": model, "sonnet": model, "haiku": model}
    if local and not models:
        names = (server or (None, None, []))[2]
        if not names:
            raise Problem("no model name: start the local server and pull a model, or give --model")
        models = {"main": names[0], "opus": names[0], "sonnet": names[0], "haiku": names[0]}
    why = policy_denial(ep.get("vendor"), list(ep.get("provider_words") or []) + list(models.values()), policy)
    if why:
        raise Refused("%s: %s" % (ep.get("vendor"), why))
    env = {"ANTHROPIC_BASE_URL": base}
    for role, value in models.items():
        if role in MODEL_ENV:
            env[MODEL_ENV[role]] = value
    env.update(ep.get("extra_env") or {})
    env.update(ep.get("window_env") or {})
    reds = red_paths(policy)
    red_window = bool(ep.get("red"))
    if red_window:
        # The one window that opens the red folders. A deny rule for them would win here over everything (a
        # deny at any level cannot be lifted), so this window carries none: the red folders become its working
        # folders, and the mark tells gatecall's hook that this session may read them.
        env[WINDOW_VAR] = name
        perms = {"deny": list(RED_WINDOW_DENY)}
        if reds:
            perms["additionalDirectories"] = list(reds)
        settings = {"env": env, "permissions": perms}
    else:
        settings = {"env": env, "permissions": {"deny": deny_rules(reds)}}
    out_dir = os.path.join(project, ".routecall", name)
    settings_path = os.path.join(out_dir, "settings.json")
    launch_env = dict(ep.get("launcher_env") or {})
    lines = ["#!/bin/sh",
             "# routecall profile %s - written by routecall; start it with: sh %s" % (
                 name, shlex.quote(os.path.join(out_dir, "claude.sh"))),
             "# The key is read from the system keychain here, when the window opens; it is in no file."
             if not local else "# A model on this computer: no key, and nothing in this window leaves it.",
             "set -u"]
    if local:
        lines.append("unset ANTHROPIC_API_KEY")
        lines.append("export %s=%s" % (ep["auth_var"], shlex.quote(ep.get("local_token") or "local")))
    else:
        lines.append(keychain_read_sh(name).rstrip("\n"))
        lines.append("unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN")
        lines.append('export %s="$key"' % ep["auth_var"])
    for k, v in sorted(launch_env.items()):
        lines.append("export %s=%s" % (k, shlex.quote(v)))
    lines.append("cd %s || exit 1" % shlex.quote(workdir or project))
    # --strict-mcp-config with no --mcp-config: the red window starts with no MCP server at all.
    no_mcp = " --strict-mcp-config" if red_window else ""
    lines.append('exec claude --settings %s%s "$@"' % (shlex.quote(settings_path), no_mcp))
    ps = ["# routecall profile %s - written by routecall; start it with: powershell -File %s" % (
              name, os.path.join(out_dir, "claude.ps1")),
          "# The key is read from Windows' credential store here, when the window opens; it is in no file."
          if not local else "# A model on this computer: no key, and nothing in this window leaves it."]
    if local:
        ps.append("Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue")
        ps.append("$env:%s = %s" % (ep["auth_var"], ps_quote(ep.get("local_token") or "local")))
    else:
        ps.append(keychain_read_ps(name))
        ps.append("if (-not $key) { Write-Output 'routecall: no key for %s in the credential store yet - "
                  "ask Claude: routecall key %s'; exit 1 }" % (name, name))
        ps.append("Remove-Item Env:ANTHROPIC_API_KEY, Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue")
        ps.append("$env:%s = $key" % ep["auth_var"])
    for k, v in sorted(launch_env.items()):
        ps.append("$env:%s = %s" % (k, ps_quote(v)))
    ps.append("Set-Location -LiteralPath %s" % ps_quote(workdir or project))
    ps.append("& claude --settings %s%s @args" % (ps_quote(settings_path), no_mcp))
    ps.append("exit $LASTEXITCODE")
    return {"name": name, "vendor": ep.get("vendor"), "base_url": base, "models": models, "settings": settings,
            "settings_path": settings_path, "launcher_path": os.path.join(out_dir, "claude.sh"),
            "launcher": "\n".join(lines) + "\n", "launcher_ps1": "\r\n".join(ps) + "\r\n",
            "launcher_ps1_path": os.path.join(out_dir, "claude.ps1"), "red": bool(ep.get("red")), "red_paths": reds,
            "workdir": workdir or project, "notes": ep.get("notes") or [], "url": ep.get("url"),
            "checked": ep.get("checked"), "price_rows": ep.get("price_rows") or []}


def banner(profile, project, words):
    out = [say(words, "banner_base_url", host=host_of(profile["base_url"]) or profile["base_url"])]
    if profile["red"]:
        out.append(say(words, "red_window"))
    out.append(say(words, "banner_rules", sources="; ".join(rule_sources(project, profile["base_url"],
                                                                          profile["settings_path"]))))
    if profile["name"] in CLOUD_PROFILES:
        out.append(say(words, "banner_key"))
    return out


# ---------------------------------------------------------------- window (worktree) ----------

def git(args, cwd):
    try:
        done = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Problem("git did not run (%s)" % exc)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def make_window(name, project, policy):
    code, top, err = git(["rev-parse", "--show-toplevel"], project)
    if code != 0:
        raise Problem("%s is not a git repository - a window is a git worktree (git init first)" % project)
    top = os.path.realpath(top)
    inside = []
    for p in red_paths(policy):
        real = os.path.realpath(p)
        if real == top or real.startswith(top + os.sep):
            inside.append(os.path.relpath(real, top).replace(os.sep, "/"))
    if "." in inside:
        raise Refused("the whole repository is a red folder: no cloud window can be made of it")
    dest = os.path.join(os.path.dirname(top), "%s-routecall-%s" % (os.path.basename(top), name))
    patterns = ["/*"] + ["!/%s/" % rel for rel in sorted(inside)]
    if os.path.isdir(dest):
        return {"path": dest, "left_out": inside, "created": False}
    code, _, err = git(["worktree", "add", "--no-checkout", "-B", "routecall/%s" % name, dest, "HEAD"], top)
    if code != 0:
        raise Problem("git worktree add failed: %s" % err)
    for args in (["sparse-checkout", "init", "--no-cone"], ["sparse-checkout", "set", "--no-cone"] + patterns,
                 ["checkout"]):
        code, _, err = git(args, dest)
        if code != 0:
            raise Problem("git %s failed in %s: %s" % (" ".join(args[:2]), dest, err))
    return {"path": dest, "left_out": inside, "created": True}


# ---------------------------------------------------------------- local ----------------------

def ram_gb():
    try:
        if sys.platform == "darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()) / 2 ** 30
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / 2 ** 20
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = Status()
            s.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return s.ullTotalPhys / 2 ** 30
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None
    return None


def local_pick(ram):
    tiers = [t for t in data("local-models.json")["tiers"] if "min_gb" in t]
    if ram is None:
        raise Problem("cannot read this machine's memory - give --ram-gb")
    ram = round(ram)
    if ram < tiers[0]["min_gb"]:
        return {"ram": ram, "lead": None, "on_call": tiers[0]["on_call"][:2], "hardware_rows": tiers[0]["hardware_rows"],
                "note": "below 16 GB a local model is a small helper only (embeddings, sorting), not an agent"}
    for t in tiers:
        if t["min_gb"] <= ram <= t["max_gb"]:
            return {"ram": ram, "lead": t["lead"], "on_call": t["on_call"], "hardware_rows": t["hardware_rows"], "note": ""}
    return {"ram": ram, "lead": tiers[-1]["lead"], "on_call": tiers[-1]["on_call"],
            "hardware_rows": tiers[-1]["hardware_rows"], "note": ""}


def one_request(base, model, tokens, kind):
    """Starts one generation request on the local server (curl), -> Popen."""
    if kind == "ollama" or kind == "anthropic":
        url = base.rstrip("/") + "/v1/messages"
        body = {"model": model, "max_tokens": tokens,
                "messages": [{"role": "user", "content": "Write a short paragraph about the sea."}]}
        head = ["-H", "x-api-key: local", "-H", "anthropic-version: 2023-06-01"]
    else:
        url = base.rstrip("/") + "/v1/chat/completions"
        body = {"model": model, "max_tokens": tokens,
                "messages": [{"role": "user", "content": "Write a short paragraph about the sea."}]}
        head = []
    args = ["curl", "-s", "-m", "300", "-X", "POST", url, "-H", "content-type: application/json"] + head + \
        ["--data-binary", "@-"]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    p.stdin.write(json.dumps(body))
    p.stdin.close()
    return p


def output_tokens(text):
    try:
        body = json.loads(text)
    except ValueError:
        return 0
    usage = body.get("usage") or {}
    return int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)


def measure(base, model, kind, n=4, tokens=128):
    t0 = time.time()
    p = one_request(base, model, tokens, kind)
    single_out = output_tokens(p.stdout.read())
    p.wait()
    single = single_out / max(time.time() - t0, 1e-6)
    t0 = time.time()
    procs = [one_request(base, model, tokens, kind) for _ in range(n)]
    total_out = 0
    for p in procs:
        total_out += output_tokens(p.stdout.read())
        p.wait()
    total = total_out / max(time.time() - t0, 1e-6)
    return {"model": model, "single_tps": round(single, 1), "total_tps": round(total, 1), "n": n,
            "single_tokens": single_out, "total_tokens": total_out}


def people_held(total_tps, need_tps=None, active_share=None):
    load = data("local-models.json")["load"]
    need = need_tps or load["need_tps"]
    share = active_share or load["active_share"]
    return int(total_tps // (need * share)) if total_tps > 0 else 0


# ---------------------------------------------------------------- gateway and server ---------

def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def litellm_ok(version):
    rule = data("gateways.json")["minimum"]["litellm"]
    if str(version).strip() in rule["never"]:
        return False
    return version_tuple(version) >= version_tuple(rule["at_least"])


def gateway_config(names, policy):
    lines = ["# routecall gateway - LiteLLM proxy for scripts, CI and night jobs. Not for people:",
             "# behind ANTHROPIC_BASE_URL a person loses Remote Control, cloud sessions, the advisor and",
             "# the organisation's server-managed settings (code.claude.com/docs/en/remote-control).",
             "# Start: litellm --config litellm-config.yaml --port 4000   (litellm >= 1.83.0, never 1.82.7/1.82.8)",
             "# A job then uses ANTHROPIC_BASE_URL=http://localhost:4000 and the proxy key as its token.",
             "# Keys come from the environment of the proxy (ROUTECALL_<NAME>_KEY), never from this file.",
             "model_list:"]
    for name in names:
        ep = endpoint(name)
        if name not in CLOUD_PROFILES:
            raise Problem("%s is not a vendor profile; the gateway routes the cloud profiles %s"
                          % (name, ", ".join(CLOUD_PROFILES)))
        why = policy_denial(ep.get("vendor"), list(ep.get("provider_words") or []) + list(ep["models"].values()), policy)
        if why:
            raise Refused("%s: %s" % (ep.get("vendor"), why))
        for model in sorted(set(ep["models"].values())):
            lines += ['  - model_name: "%s/%s"' % (name, model),
                      "    litellm_params:",
                      '      model: "anthropic/%s"' % model,
                      '      api_base: "%s"' % ep["base_url"],
                      '      api_key: "os.environ/ROUTECALL_%s_KEY"' % name.upper()]
    lines += ["guardrails:",
              '  - guardrail_name: "presidio-pii"',
              "    litellm_params:",
              "      guardrail: presidio",
              '      mode: "pre_call"']
    budget = (policy or {}).get("max_usd_per_day")
    lines.append("litellm_settings:")
    lines.append("  drop_params: true")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        lines += ["  max_budget: %s" % budget, '  budget_duration: "1d"']
    return "\n".join(lines) + "\n"


def parse_named(items, what):
    out = []
    for item in items or []:
        if "=" not in item:
            raise Problem("%s must be NAME=FILE.gguf, got %r" % (what, item))
        name, path = item.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", name):
            raise Problem("model name %r: letters, digits, . _ : - only" % name)
        out.append((name, os.path.abspath(os.path.expanduser(path))))
    return out


def server_config(lead, on_call, ctx=65536, ttl=600):
    lines = ["# routecall server - llama-swap: one lead model kept loaded, the rest loaded when called.",
             "# Start: llama-swap --config config.yaml --listen localhost:8080",
             "# Then: routecall profile local --url http://localhost:8080 (or local-red for red work).",
             "healthCheckTimeout: 300", "models:"]
    for name, path in lead + on_call:
        keep = 0 if (name, path) in lead else ttl
        lines += ['  "%s":' % name,
                  '    cmd: llama-server --port ${PORT} -m "%s" -c %d --jinja' % (path, ctx),
                  "    ttl: %d" % keep]
    lines += ["groups:", '  "lead":', "    swap: false", "    exclusive: false", "    persistent: true",
              "    members: [%s]" % ", ".join('"%s"' % n for n, _ in lead)]
    if on_call:
        lines += ['  "on-call":', "    swap: true", "    exclusive: false",
                  "    members: [%s]" % ", ".join('"%s"' % n for n, _ in on_call)]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- crew -----------------------

def crew_member(member, row_id=None, prices=None, policy=None):
    """-> (member dict, row id, list of reasons it may not run)."""
    members = data("crew.json")["members"]
    if member not in members:
        raise Refused("%s is not a crew member - only the vendors' own agents are: %s"
                      % (member, ", ".join(sorted(members))))
    m = members[member]
    row_id = row_id or m["row"]
    rows, where = price_rows(prices)
    row = rows.get(row_id)
    if row is None and where:
        raise Problem("no row %r in billcall's price table %s" % (row_id, where))
    use = (row or {}).get("use") if row is not None else (m.get("use") if row_id == m["row"] else None)
    vendor = (row or {}).get("vendor") or m.get("vendor")
    reasons = []
    if use != "automated":
        reasons.append("the row %s is for people (use: %s); scripted work runs only on a row with use: "
                       "automated - a pay-as-you-go API key, never a person's plan" % (row_id, use))
    why = policy_denial(vendor, [member, row_id], policy)
    if why:
        reasons.append("the company policy: %s" % why)
    return m, row_id, reasons


# ---------------------------------------------------------------- doctor ---------------------

def doctor(project, env=None):
    env = os.environ if env is None else env
    found = env_sources(project, env)
    order = ("managed", "project-local", "project", "user", "the shell")

    def first(var):
        items = found.get(var) or []
        for kind in order:
            for where, value in items:
                if where.startswith(kind):
                    return where, value
        return None

    base = first("ANTHROPIC_BASE_URL")
    base_url = base[1] if base else ""
    remote = []
    if base_url and not is_anthropic(base_url):
        remote.append("ANTHROPIC_BASE_URL points at %s (%s)" % (host_of(base_url) or base_url, base[0]))
    for var in REMOTE_PROVIDER_VARS + REMOTE_OFF_VARS:
        hit = first(var)
        if hit and hit[1] not in ("", "0", "false"):
            remote.append("%s is set (%s)" % (var, hit[0]))
    for var in REMOTE_KEY_VARS:
        hit = first(var)
        if hit and hit[1]:
            remote.append("%s is set (%s): Remote Control needs the claude.ai sign-in, not a key" % (var, hit[0]))
    trusted = [v for v in TRUSTED_DEVICE_VARS if first(v)]
    advisor = []
    if base_url and not is_anthropic(base_url):
        advisor.append("the advisor needs the Anthropic API")
    for var in ADVISOR_OFF_VARS:
        hit = first(var)
        if hit and hit[1] not in ("", "0", "false"):
            advisor.append("%s is set (%s)" % (var, hit[0]))
    warnings = []
    for where, value in found.get("ANTHROPIC_BASE_URL", []):
        if where.startswith("user") and not is_anthropic(value):
            warnings.append("ANTHROPIC_BASE_URL in your own settings (%s) moves EVERY window away from Anthropic: "
                            "remove it there and use a routecall profile for the cheap window" % where)
    policy, policy_path = read_policy(cwd=project)
    profiles_here = sorted(os.listdir(os.path.join(project, ".routecall"))) \
        if os.path.isdir(os.path.join(project, ".routecall")) else []
    return {"base_url": base_url or "https://api.anthropic.com (default)",
            "base_url_from": base[0] if base else "nobody set it",
            "remote_control": "unavailable" if remote else "available",
            "remote_why": remote, "trusted_devices_note": trusted,
            "advisor": "off" if advisor else "possible", "advisor_why": advisor,
            "rules": rule_sources(project, base_url), "policy": policy_path,
            "unreadable_settings": [p for _, p in found.get("_unreadable", [])],
            "profiles_here": profiles_here, "warnings": warnings}


# ---------------------------------------------------------------- advisor ---------------------

ADVISOR_TEXT = {
    "advisor": ["Advisor: a cheaper main model does the work and consults a stronger one at decision points.",
                "  claude --model sonnet --advisor opus      (or /advisor opus inside a session)",
                "  The advisor reads the whole conversation at its own rates; it needs the Anthropic API and is off",
                "  when DISABLE_TELEMETRY or another flag-fetch switch is set (code.claude.com/docs/en/advisor)."],
    "opusplan": ["opusplan: Opus while planning (plan mode), Sonnet while doing.",
                 "  /model opusplan   (code.claude.com/docs/en/model-config)"],
    "subagents": ["Subagents on a cheaper model: routine searches and edits go to Haiku, the main window keeps Opus.",
                  "  .claude/agents/routecall-worker.md with  model: haiku   (or CLAUDE_CODE_SUBAGENT_MODEL=haiku)"],
}
WORKER_AGENT = """---
name: routecall-worker
description: Routine work - searching the code, reading files, small mechanical edits, running tests - done on a cheaper model while the main conversation keeps the strong one. Use it for any step that needs no judgement.
model: haiku
---

You do one routine step of a larger task and report back briefly: what you found or changed, file and line,
and anything that looked wrong. Do not plan the whole task and do not make design decisions - say what you
would decide and leave it to the main conversation.
"""


def merge_settings(path, values):
    current = {}
    if os.path.isfile(path):
        current = load_json(path, "the project's settings")
        if not isinstance(current, dict):
            raise Problem("%s must hold one JSON object" % path)
    current.update(values)
    write_json(path, current)


# ---------------------------------------------------------------- main ----------------------

def parser():
    top = argparse.ArgumentParser(prog="routecall.py", description="Strong thinks, cheap and local work. Buys nothing.")
    top.add_argument("--lang")
    top.add_argument("--policy", help="company-ai-policy.json (default: looked for where firmcall puts it)")
    sub = top.add_subparsers(dest="command")

    one = sub.add_parser("advisor")
    one.add_argument("--mix", choices=("advisor", "opusplan", "subagents", "all"), default="all")
    one.add_argument("--write", action="store_true")
    one.add_argument("--project", default=".")

    one = sub.add_parser("crew")
    one.add_argument("action", choices=("list", "check", "run"))
    one.add_argument("member", nargs="?")
    one.add_argument("--row", help="price-table row the member is billed on (default: its own)")
    one.add_argument("--prices", help="billcall's data/prices.json")
    one.add_argument("--task")
    one.add_argument("--cwd", default=".")
    one.add_argument("--dry-run", action="store_true")

    one = sub.add_parser("profile")
    one.add_argument("name", choices=PROFILES)
    one.add_argument("--project", default=".")
    one.add_argument("--model")
    one.add_argument("--url")
    one.add_argument("--window", action="store_true", help="work in the sparse worktree without red folders")
    one.add_argument("--dry-run", action="store_true")
    one.add_argument("--json", action="store_true")

    one = sub.add_parser("key")
    one.add_argument("name", choices=CLOUD_PROFILES)

    one = sub.add_parser("window")
    one.add_argument("name")
    one.add_argument("--project", default=".")

    one = sub.add_parser("local")
    one.add_argument("action", nargs="?", choices=("load",))
    one.add_argument("--ram-gb", type=float)
    one.add_argument("--url")
    one.add_argument("--model")
    one.add_argument("--n", type=int, default=4)
    one.add_argument("--tokens", type=int, default=128)
    one.add_argument("--need-tps", type=float)
    one.add_argument("--active-share", type=float)
    one.add_argument("--json", action="store_true")

    one = sub.add_parser("gateway")
    one.add_argument("--profiles", default="")
    one.add_argument("--for", dest="purpose", choices=("scripts", "people"), default="scripts")
    one.add_argument("--out", default=os.path.join(".routecall", "gateway"))
    one.add_argument("--check-installed", action="store_true")
    one.add_argument("--version", help="check this LiteLLM version string instead of the installed one")

    one = sub.add_parser("server")
    one.add_argument("--lead", action="append", required=True)
    one.add_argument("--on-call", action="append", default=[])
    one.add_argument("--out", default=os.path.join(".routecall", "server"))
    one.add_argument("--ctx", type=int, default=65536)

    one = sub.add_parser("doctor")
    one.add_argument("--project", default=".")
    one.add_argument("--json", action="store_true")
    return top


def run(argv):
    args = parser().parse_args(argv)
    if not args.command:
        parser().print_help()
        return 2
    project = os.path.abspath(getattr(args, "project", ".") or ".")
    policy, _ = read_policy(args.policy, cwd=project)
    words = lang_words(pick_lang(args.lang, policy))

    if args.command == "advisor":
        mixes = ("advisor", "opusplan", "subagents") if args.mix == "all" else (args.mix,)
        for mix in mixes:
            print("\n".join(ADVISOR_TEXT[mix]))
        if args.write:
            local_settings = os.path.join(project, ".claude", "settings.local.json")
            if "advisor" in mixes and args.mix != "all":
                merge_settings(local_settings, {"advisorModel": "opus", "model": "sonnet"})
                print("written: %s (advisorModel opus, model sonnet)" % local_settings)
            if args.mix == "opusplan":
                merge_settings(local_settings, {"model": "opusplan"})
                print("written: %s (model opusplan)" % local_settings)
            if "subagents" in mixes:
                path = os.path.join(project, ".claude", "agents", "routecall-worker.md")
                write_text(path, WORKER_AGENT)
                print("written: %s" % path)
        return 0

    if args.command == "crew":
        members = data("crew.json")["members"]
        if args.action == "list":
            for name in sorted(members):
                m, row, reasons = crew_member(name, prices=args.prices, policy=policy)
                print("%-7s %-8s row %-32s %s" % (name, m["program"], row, "ready" if not reasons else reasons[0]))
                print("        login: %s" % m["login"])
            return 0
        if not args.member:
            raise Problem("name a member: %s" % ", ".join(sorted(members)))
        m, row, reasons = crew_member(args.member, args.row, args.prices, policy)
        if reasons:
            for r in reasons:
                print(say(words, "crew_refused", member=args.member, why=r))
            return 1
        if args.action == "check":
            print("%s may run on %s (use: automated). Its own login: %s" % (args.member, row, m["login"]))
            return 0
        if not args.task:
            raise Problem("crew run needs --task")
        cmd = [part.replace("{task}", args.task) for part in m["run"]]
        if args.dry_run:
            print(" ".join(shlex.quote(c) for c in cmd))
            return 0
        if not shutil.which(m["program"]):
            raise Problem("%s is not installed on this computer" % m["program"])
        return subprocess.call(cmd, cwd=os.path.abspath(args.cwd))

    if args.command == "key":
        h = key_help(args.name)
        print(h["say"])
        for system in ("mac", "linux", "windows"):
            print("  %s: %s" % (system, h[system]))
        return 0

    if args.command == "window":
        w = make_window(args.name, project, policy)
        print("window: %s%s" % (w["path"], "" if w["created"] else " (already there)"))
        print("left out (red folders): %s" % (", ".join(w["left_out"]) or "none inside this repository"))
        return 0

    if args.command == "profile":
        server = None
        if args.name in ("local", "local-red") and not args.model:
            server = local_server(args.url)
            if server is None:
                print(say(words, "local_none", tried=", ".join(b for _, b, _ in LOCAL_SERVERS)))
                return 3
        workdir = None
        if args.window:
            if args.name in ("local", "local-red"):
                raise Problem("a local window needs no worktree: nothing leaves this computer")
            workdir = make_window(args.name, project, policy)["path"]
        prof = build_profile(args.name, project, policy, args.model, args.url, workdir, server)
        lines = banner(prof, project, words)
        if args.json:
            print(json.dumps(dict(prof, banner=lines), ensure_ascii=False, indent=2))
        else:
            print("\n".join(lines))
        if not args.dry_run:
            write_json(prof["settings_path"], prof["settings"])
            write_text(prof["launcher_path"], prof["launcher"], 0o755)
            write_text(prof["launcher_ps1_path"], prof["launcher_ps1"])
            if not args.json:
                print("written: %s" % prof["settings_path"])
                print("start the window: sh %s   (Windows: powershell -File %s)" % (
                    shlex.quote(prof["launcher_path"]), prof["launcher_ps1_path"]))
                if args.name in CLOUD_PROFILES:
                    print("the key, once: routecall key %s" % args.name)
        return 0

    if args.command == "local":
        if args.action == "load":
            server = local_server(args.url)
            if server is None:
                print(say(words, "local_none", tried=", ".join(b for _, b, _ in LOCAL_SERVERS)))
                return 3
            kind, base, names = server
            model = args.model or (names[0] if names else None)
            if not model:
                raise Problem("the server at %s lists no model - pull one or give --model" % base)
            result = measure(base, model, kind, max(1, args.n), max(16, args.tokens))
            result["people"] = people_held(result["total_tps"], args.need_tps, args.active_share)
            result["server"] = base
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(say(words, "local_load", model=model, single=result["single_tps"], total=result["total_tps"],
                          n=result["n"], people=result["people"]))
            return 0 if result["total_tokens"] else 1
        pick = local_pick(args.ram_gb if args.ram_gb else ram_gb())
        info = data("local-models.json")
        print("memory: %d GB" % pick["ram"])
        print("lead model: %s" % (pick["lead"] or "none - " + pick["note"]))
        print("on call: %s" % ", ".join(pick["on_call"]))
        print("machines of this size in billcall's price table: %s" % ", ".join(pick["hardware_rows"]))
        for k, v in info["connect"].items():
            print("  %s: %s" % (k, v))
        server = local_server()
        print("running here now: %s" % ("%s at %s (%s)" % (server[0], server[1], ", ".join(server[2][:5]) or "no model")
                                        if server else "no local model server"))
        return 0

    if args.command == "gateway":
        if args.purpose == "people":
            print(say(words, "gateway_people"))
            return 1
        if args.check_installed or args.version:
            version = args.version
            if not version:
                try:
                    version = subprocess.check_output([sys.executable, "-c", "import importlib.metadata as m; "
                                                       "print(m.version('litellm'))"], text=True,
                                                      stderr=subprocess.DEVNULL).strip()
                except (OSError, subprocess.SubprocessError):
                    version = None
            if not version:
                print("litellm is not installed for %s" % sys.executable)
                return 1
            ok = litellm_ok(version)
            rule = data("gateways.json")["minimum"]["litellm"]
            print("litellm %s: %s" % (version, "fine" if ok else "NOT fine - %s" % rule["why"]))
            return 0 if ok else 1
        names = [n.strip() for n in args.profiles.split(",") if n.strip()]
        if not names:
            for g in data("gateways.json")["compared"]:
                print("%-18s %-28s %-36s %s" % (g["name"], g["repo"], g["license"], g["fits"]))
            return 0
        text = gateway_config(names, policy)
        out = os.path.abspath(args.out)
        write_text(os.path.join(out, "litellm-config.yaml"), text)
        write_text(os.path.join(out, "requirements.txt"), "litellm[proxy]>=1.83.0,!=1.82.7,!=1.82.8\n")
        print(say(words, "gateway_people"))
        print("written: %s" % os.path.join(out, "litellm-config.yaml"))
        return 0

    if args.command == "server":
        lead = parse_named(args.lead, "--lead")
        on_call = parse_named(args.on_call, "--on-call")
        out = os.path.abspath(args.out)
        write_text(os.path.join(out, "config.yaml"), server_config(lead, on_call, args.ctx))
        print("written: %s" % os.path.join(out, "config.yaml"))
        print("start: llama-swap --config %s --listen localhost:8080" % shlex.quote(os.path.join(out, "config.yaml")))
        return 0

    if args.command == "doctor":
        d = doctor(project)
        if args.json:
            print(json.dumps(d, ensure_ascii=False, indent=2))
            return 0
        print(say(words, "doctor_base", where="%s (%s)" % (d["base_url"], d["base_url_from"])))
        if d["remote_control"] == "available":
            print(say(words, "doctor_remote_ok"))
        else:
            print(say(words, "doctor_remote_off", why="; ".join(d["remote_why"])))
        if d["trusted_devices_note"]:
            print("  %s set: Remote Control still works unless the organisation requires Trusted Devices"
                  % ", ".join(d["trusted_devices_note"]))
        if d["advisor"] == "off":
            print(say(words, "doctor_advisor_off", why="; ".join(d["advisor_why"])))
        print(say(words, "doctor_rules", sources="; ".join(d["rules"])))
        print("company policy: %s" % (d["policy"] or "none found"))
        if d["profiles_here"]:
            print("routecall windows in this project: %s" % ", ".join(d["profiles_here"]))
        for w in d["warnings"] + ["cannot read %s" % p for p in d["unreadable_settings"]]:
            print("  ! %s" % w)
        return 0
    return 2


def main(argv=None):
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Refused as exc:
        print("routecall: %s" % exc)
        return 1
    except Problem as exc:
        print("routecall: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
