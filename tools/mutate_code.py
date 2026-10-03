#!/usr/bin/env python3
"""Break routecall's own rules on purpose, in a copy, and watch the tests redden.

Each mutation copies the plugin folder to a temporary place, changes one exact text in one file of the
copy (the text must be there exactly once, or the mutation itself is reported as broken), runs the named
tests in the copy, and expects them red. The control mutation changes a comment and expects green. After
every run the sha256 of every original file is compared with the one taken at the start: the plugin itself
is never touched. The last line counts the mutations that misbehaved; anything but 0 is a failure.

  python3 tools/mutate_code.py            (about a minute; needs pytest, like the tests themselves)

Most mutations change the code; two change routecall's own data (data/endpoints.json), because the
rules of a profile live there.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = "skills/routecall/scripts/routecall.py"
TESTS = "tests/test_routecall.py"
ENDPOINTS = "data/endpoints.json"
SKIP = (".git", "__pycache__", ".pytest_cache", "dist")

# (what is broken, file, exact text, replacement, tests to run, expected outcome)
MUTATIONS = (
    ("control: a comment reworded", SCRIPT,
     "# The company-policy profiles that deny vendors", "# The company-policy profiles which deny vendors",
     TESTS + "::Policy", "green"),
    ("profile writes the person's own ~/.claude/settings.json", SCRIPT,
     'settings_path = os.path.join(out_dir, "settings.json")',
     'settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")',
     TESTS + "::Profiles", "red"),
    ("the refusal to write the global settings is gone", SCRIPT,
     'if real == os.path.join(home_claude, "settings.json") or real.startswith(home_claude + os.sep):', "if False:",
     TESTS + "::Profiles", "red"),
    ("a network module in the code", SCRIPT,
     "import time\n", "import time\nimport urllib.request\n",
     TESTS + "::NoNetwork", "red"),
    ("crew runs on a person's plan", SCRIPT,
     'if use != "automated":', "if False:",
     TESTS + "::Crew", "red"),
    ("the red window leaves Ollama's cloud on", ENDPOINTS,
     '"launcher_env": {"OLLAMA_NO_CLOUD": "1"}', '"launcher_env": {}',
     TESTS + "::Profiles", "red"),
    ("the red window leaves non-essential traffic on", ENDPOINTS,
     '"window_env": {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}', '"window_env": {}',
     TESTS + "::Profiles", "red"),
    ("the banner no longer says what stops working", SCRIPT,
     'out = [say(words, "banner_base_url", host=', 'out = [] and [say(words, "banner_base_url", host=',
     TESTS + "::Profiles", "red"),
    ("a defence contractor gets DeepSeek", SCRIPT,
     '"us-federal-contractor": ("deepseek",),', '"us-federal-contractor": (),',
     TESTS + "::Policy", "red"),
    ("any LiteLLM version passes", SCRIPT,
     'return version_tuple(version) >= version_tuple(rule["at_least"])', "return True",
     TESTS + "::Gateway", "red"),
    ("a gateway is written for people", SCRIPT,
     'if args.purpose == "people":', "if False:",
     TESTS + "::Gateway", "red"),
    ("doctor forgets that DISABLE_GROWTHBOOK switches the remote off", SCRIPT,
     'REMOTE_OFF_VARS = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK")',
     'REMOTE_OFF_VARS = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",)',
     TESTS + "::Doctor", "red"),
    ("a stray ANTHROPIC_API_KEY stays set in the window", SCRIPT,
     'lines.append("unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN")', "pass",
     TESTS + "::Profiles", "red"),
    ("the window's settings keep the red folders readable", SCRIPT,
     'settings = {"env": env, "permissions": {"deny": deny_rules(reds)}}',
     'settings = {"env": env, "permissions": {"deny": []}}',
     TESTS + "::Profiles", "red"),
    ("the red window denies its own red folders again", SCRIPT,
     'perms = {"deny": list(RED_WINDOW_DENY)}',
     'perms = {"deny": list(RED_WINDOW_DENY) + deny_rules(reds)}',
     TESTS + "::Profiles", "red"),
    ("the found local server's address is lost", SCRIPT,
     'base = url or (server[1] if server and server[1] else None) or ep["base_url"]',
     'base = url or ep["base_url"]',
     TESTS + "::Local", "red"),
)


def digest(root):
    """sha256 of every file under root (junk folders left out), keyed by relative path."""
    out = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, root)] = hashlib.sha256(handle.read()).hexdigest()
    return out


def run_one(tmp, n, mutation):
    """-> ("red" | "green" | "error", detail)."""
    _name, rel, old, new, tests, _expect = mutation
    copy = os.path.join(tmp, "m%02d" % n)
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(*SKIP))
    target = os.path.join(copy, rel)
    with open(target, encoding="utf-8") as handle:
        text = handle.read()
    if text.count(old) != 1:
        return "error", "%r is in %s %d times, not once" % (old, rel, text.count(old))
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text.replace(old, new, 1))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", tests],
                              cwd=copy, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", repr(exc)
    last = (done.stdout.strip().splitlines() or [""])[-1]
    if done.returncode == 0:
        return "green", last
    if done.returncode == 1:
        return "red", last
    return "error", "pytest exit %d: %s" % (done.returncode, (done.stdout + done.stderr).strip()[-300:])


def main():
    before = digest(ROOT)
    bad = 0
    tmp = tempfile.mkdtemp(prefix="routecall-mutate-")
    try:
        for n, mutation in enumerate(MUTATIONS):
            name, expect = mutation[0], mutation[5]
            outcome, detail = run_one(tmp, n, mutation)
            if outcome == expect:
                print("ok   %s: %s as expected (%s)" % (name, expect, detail))
            else:
                print("BAD  %s: expected %s, got %s (%s)" % (name, expect, outcome, detail))
                bad += 1
            after = digest(ROOT)
            if after != before:
                print("BAD  the plugin's own files changed during '%s'" % name)
                bad += 1
                before = after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("misbehaving: %d" % bad)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
