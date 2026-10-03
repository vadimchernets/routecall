"""routecall: profiles, the company policy, the crew rule, local servers, the gateway, doctor.

Every command runs as a subprocess with HOME set to a temporary folder, so nothing here can touch the
person's own Claude Code settings, and a test proves it."""
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "routecall", "scripts", "routecall.py")
sys.path.insert(0, os.path.dirname(SCRIPT))
import routecall  # noqa: E402

DATA = os.path.join(ROOT, "data")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        self.managed = os.path.join(self.tmp, "managed")
        for d in (self.home, self.project, self.managed):
            os.makedirs(d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_rc(self, *args, env=None, cwd=None):
        e = {"PATH": os.environ.get("PATH", ""), "HOME": self.home, "ROUTECALL_MANAGED_DIR": self.managed,
             "LANG": "en_US.UTF-8"}
        e.update(env or {})
        p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True,
                           env=e, cwd=cwd or self.project, timeout=120)
        self.assertNotIn("Traceback", p.stderr + p.stdout)
        return p.returncode, p.stdout

    def policy(self, **fields):
        path = os.path.join(self.project, "company-ai-policy.json")
        with open(path, "w") as fh:
            json.dump(dict({"schema": 1}, **fields), fh)
        return path


class Profiles(Base):
    def test_every_cloud_profile_writes_its_window_into_the_project_only(self):
        for name in routecall.CLOUD_PROFILES:
            code, out = self.run_rc("profile", name, "--project", self.project)
            self.assertEqual(code, 0, out)
            folder = os.path.join(self.project, ".routecall", name)
            settings = json.load(open(os.path.join(folder, "settings.json")))
            ep = json.load(open(os.path.join(DATA, "endpoints.json")))["profiles"][name]
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], ep["base_url"])
            self.assertEqual(settings["env"]["ANTHROPIC_MODEL"], ep["models"]["main"])
            launcher = open(os.path.join(folder, "claude.sh")).read()
            self.assertIn("security find-generic-password -s routecall -a %s -w" % name, launcher)
            self.assertIn('export %s="$key"' % ep["auth_var"], launcher)
            self.assertIn("exec claude --settings", launcher)
            ps1 = open(os.path.join(folder, "claude.ps1")).read()
            self.assertIn("PasswordVault", ps1)
            self.assertIn("& claude --settings", ps1)
        # nothing was written into the person's own settings, and no key is in any file
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "settings.json")))
        self.assertEqual(os.listdir(self.home), [])

    def test_launcher_is_valid_shell(self):
        self.run_rc("profile", "glm", "--project", self.project)
        p = subprocess.run(["/bin/sh", "-n", os.path.join(self.project, ".routecall", "glm", "claude.sh")])
        self.assertEqual(p.returncode, 0)

    def test_launcher_without_a_key_says_so_and_never_starts_claude(self):
        self.run_rc("profile", "deepseek", "--project", self.project)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        for name, body in (("security", "exit 44"), ("claude", "echo CLAUDE STARTED")):
            path = os.path.join(bin_dir, name)
            open(path, "w").write("#!/bin/sh\n%s\n" % body)
            os.chmod(path, 0o755)
        p = subprocess.run(["/bin/sh", os.path.join(self.project, ".routecall", "deepseek", "claude.sh")],
                           capture_output=True, text=True, env={"PATH": bin_dir + ":/usr/bin:/bin", "HOME": self.home})
        self.assertEqual(p.returncode, 1)
        self.assertIn("routecall key deepseek", p.stdout)
        self.assertNotIn("CLAUDE STARTED", p.stdout)

    def test_launcher_with_a_key_hands_it_over_in_the_environment_only(self):
        self.run_rc("profile", "kimi", "--project", self.project)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        for name, body in (("security", "echo sk-test-123"),
                           ("claude", 'echo "token=$ANTHROPIC_AUTH_TOKEN apikey=${ANTHROPIC_API_KEY:-unset} args=$*"')):
            path = os.path.join(bin_dir, name)
            open(path, "w").write("#!/bin/sh\n%s\n" % body)
            os.chmod(path, 0o755)
        p = subprocess.run(["/bin/sh", os.path.join(self.project, ".routecall", "kimi", "claude.sh"), "-p", "hi"],
                           capture_output=True, text=True,
                           env={"PATH": bin_dir + ":/usr/bin:/bin", "HOME": self.home, "ANTHROPIC_API_KEY": "stray"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("token=sk-test-123 apikey=unset", p.stdout)   # a stray key would bill Anthropic instead
        self.assertIn("args=--settings", p.stdout)
        for folder, _, files in os.walk(self.project):
            for f in files:
                self.assertNotIn("sk-test-123", open(os.path.join(folder, f), errors="replace").read())

    def test_banner_names_what_does_not_work_and_where_the_rules_come_from(self):
        code, out = self.run_rc("profile", "minimax", "--project", self.project)
        self.assertIn("Remote Control", out)
        self.assertIn("server-managed settings do not work here", out)
        self.assertIn("api.minimax.io", out)
        self.assertIn("Rules in this window come from:", out)
        self.assertIn(os.path.join(".routecall", "minimax", "settings.json"), out)
        # under a vendor's address the claude.ai settings are not fetched, so they are not named as a source
        self.assertNotIn("server-managed settings from claude.ai", out.split("Rules in this window come from:")[1])

    def test_banner_in_the_company_language(self):
        self.policy(language="es")
        code, out = self.run_rc("profile", "glm", "--project", self.project)
        self.assertIn("En esta ventana Claude Code habla con api.z.ai", out)

    def test_a_managed_rules_file_is_named_first(self):
        open(os.path.join(self.managed, "managed-settings.json"), "w").write("{}")
        os.makedirs(os.path.join(self.managed, "managed-settings.d"))
        open(os.path.join(self.managed, "managed-settings.d", "50-company.json"), "w").write("{}")
        code, out = self.run_rc("profile", "qwen", "--project", self.project)
        rules = out.split("Rules in this window come from:")[1]
        self.assertLess(rules.index("managed-settings.json"), rules.index(".routecall"))
        self.assertIn("50-company.json", rules)

    def test_red_folders_are_denied_in_the_window(self):
        red = os.path.join(self.home, "Company", "Clients")
        self.policy(red_paths=["~/Company/Clients"])
        self.run_rc("profile", "glm", "--project", self.project)
        deny = json.load(open(os.path.join(self.project, ".routecall", "glm", "settings.json")))["permissions"]["deny"]
        self.assertIn("Read(//%s/**)" % red.lstrip("/"), deny)
        self.assertIn("Edit(//%s/**)" % red.lstrip("/"), deny)

    def test_the_red_window_opens_the_red_folders_and_every_other_window_keeps_them_shut(self):
        red = os.path.join(self.home, "Company", "Clients")
        self.policy(red_paths=["~/Company/Clients"])
        rule = "Read(//%s/**)" % red.lstrip("/")
        code, out = self.run_rc("profile", "local-red", "--project", self.project, "--model", "qwen3.6:35b")
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.project, ".routecall", "local-red")
        settings = json.load(open(os.path.join(folder, "settings.json")))
        perms = settings["permissions"]
        # a deny rule wins over everything in Claude Code: the red window carries none for its red folders
        self.assertNotIn(rule, perms["deny"])
        self.assertEqual(perms["additionalDirectories"], [red])
        self.assertIn("WebFetch", perms["deny"])
        self.assertIn("WebSearch", perms["deny"])
        self.assertEqual(settings["env"]["ROUTECALL_WINDOW"], "local-red")
        self.assertIn("--strict-mcp-config", open(os.path.join(folder, "claude.sh")).read())
        self.assertIn("--strict-mcp-config", open(os.path.join(folder, "claude.ps1")).read())
        # the control: a cloud window and the ordinary local one keep the red folders shut and carry no mark
        for name, extra in (("glm", ()), ("local", ("--model", "gpt-oss:20b"))):
            code, out = self.run_rc("profile", name, "--project", self.project, *extra)
            self.assertEqual(code, 0, out)
            other = json.load(open(os.path.join(self.project, ".routecall", name, "settings.json")))
            self.assertIn(rule, other["permissions"]["deny"], name)
            self.assertNotIn("additionalDirectories", other["permissions"], name)
            self.assertNotIn("ROUTECALL_WINDOW", other["env"], name)
            launcher = open(os.path.join(self.project, ".routecall", name, "claude.sh")).read()
            self.assertNotIn("--strict-mcp-config", launcher, name)

    def test_local_red_keeps_everything_on_this_computer(self):
        code, out = self.run_rc("profile", "local-red", "--project", self.project, "--model", "qwen3.6:35b")
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.project, ".routecall", "local-red")
        env = json.load(open(os.path.join(folder, "settings.json")))["env"]
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        self.assertTrue(routecall.is_local(env["ANTHROPIC_BASE_URL"]))
        launcher = open(os.path.join(folder, "claude.sh")).read()
        self.assertIn("export OLLAMA_NO_CLOUD=1", launcher)
        self.assertNotIn("security", launcher)
        self.assertIn("Red window", out)

    def test_the_privacy_switch_stays_out_of_the_ordinary_local_window(self):
        self.run_rc("profile", "local", "--project", self.project, "--model", "gpt-oss:20b")
        env = json.load(open(os.path.join(self.project, ".routecall", "local", "settings.json")))["env"]
        self.assertNotIn("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", env)

    def test_a_local_profile_refuses_a_remote_address(self):
        code, out = self.run_rc("profile", "local-red", "--project", self.project, "--model", "x",
                                "--url", "https://api.example.com")
        self.assertEqual(code, 1)
        self.assertIn("this computer only", out)

    def test_local_without_a_server_or_a_model_says_so(self):
        code, out = self.run_rc("profile", "local", "--project", self.project, "--url", "http://127.0.0.1:9")
        self.assertIn(code, (2, 3))

    def test_the_global_settings_are_refused_even_when_asked(self):
        with self.assertRaises(routecall.Refused):
            routecall.guard_global(os.path.join(os.path.expanduser("~"), ".claude", "settings.json"))
        routecall.guard_global(os.path.join(self.project, ".routecall", "x", "settings.json"))


class Policy(Base):
    def test_deny_providers_stops_a_profile(self):
        self.policy(deny_providers=["moonshot"])
        code, out = self.run_rc("profile", "kimi", "--project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("deny_providers", out)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".routecall", "kimi")))

    def test_allowed_providers_lets_only_those(self):
        self.policy(allowed_providers=["z.ai"])
        self.assertEqual(self.run_rc("profile", "glm", "--project", self.project)[0], 0)
        self.assertEqual(self.run_rc("profile", "mimo", "--project", self.project)[0], 1)
        # a model on this computer is not a provider: allowed_providers does not stop it
        self.assertEqual(self.run_rc("profile", "local", "--project", self.project, "--model", "gpt-oss:20b")[0], 0)

    def test_a_defence_contractor_gets_no_deepseek_not_even_on_its_own_machine(self):
        self.policy(profiles=["default", "us-federal-contractor"])
        self.assertEqual(self.run_rc("profile", "deepseek", "--project", self.project)[0], 1)
        code, out = self.run_rc("profile", "local-red", "--project", self.project, "--model", "deepseek-v4-flash")
        self.assertEqual(code, 1, out)
        self.assertIn("us-federal-contractor", out)
        self.assertEqual(self.run_rc("profile", "glm", "--project", self.project)[0], 0)

    def test_dod_strict_also_stops_the_other_chinese_vendors(self):
        self.policy(profiles=["us-dod-strict"])
        for name in routecall.CLOUD_PROFILES:
            self.assertEqual(self.run_rc("profile", name, "--project", self.project)[0], 1, name)

    def test_the_lists_agree_with_gatecall(self):
        gate = os.path.join(os.path.dirname(ROOT), "gatecall", "data", "profiles.json")
        if not os.path.isfile(gate):
            self.skipTest("gatecall is not beside routecall here")
        profiles = json.load(open(gate))["profiles"]
        for name, words in routecall.POLICY_PROFILE_DENY.items():
            for w in profiles[name].get("deny_models", []):
                self.assertIn(w, words, "%s: gatecall denies %s" % (name, w))


class Crew(Base):
    def test_each_member_runs_only_on_an_automated_row(self):
        for name in json.load(open(os.path.join(DATA, "crew.json")))["members"]:
            code, out = self.run_rc("crew", "check", name)
            self.assertEqual(code, 0, out)

    def test_a_personal_plan_is_refused(self):
        code, out = self.run_rc("crew", "check", "codex", "--row", "anthropic-claude-pro")
        self.assertEqual(code, 1)
        self.assertIn("use: personal", out)
        code, out = self.run_rc("crew", "run", "kimi", "--row", "moonshot-kimi-code-membership", "--task", "x")
        self.assertEqual(code, 1)

    def test_a_team_seat_is_refused_too(self):
        code, out = self.run_rc("crew", "check", "qwen", "--row", "alibaba-token-plan-team")
        self.assertEqual(code, 1)
        self.assertIn("team-interactive", out)

    def test_only_the_vendors_own_programs(self):
        code, out = self.run_rc("crew", "check", "claude-in-opencode")
        self.assertEqual(code, 1)
        self.assertIn("only the vendors' own agents", out)

    def test_the_policy_stops_a_member(self):
        self.policy(deny_providers=["moonshot"])
        self.assertEqual(self.run_rc("crew", "check", "kimi")[0], 1)

    def test_run_names_the_vendor_command(self):
        code, out = self.run_rc("crew", "run", "codex", "--task", "sort the inbox", "--dry-run")
        self.assertEqual((code, out.strip()), (0, "codex exec 'sort the inbox'"))

    def test_without_billcall_the_snapshot_of_the_row_is_used(self):
        rows, where = routecall.price_rows()
        if where:
            for name, m in json.load(open(os.path.join(DATA, "crew.json")))["members"].items():
                self.assertEqual(rows[m["row"]]["use"], m["use"], "%s: snapshot differs from billcall" % name)


class FakeServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "fake-model:7b"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._send({"type": "message", "content": [{"type": "text", "text": "sea"}],
                    "usage": {"input_tokens": 10, "output_tokens": body.get("max_tokens", 1)}})


class Local(Base):
    def setUp(self):
        super().setUp()
        self.server = FakeServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def test_load_measures_and_counts_people(self):
        code, out = self.run_rc("local", "load", "--url", self.url, "--n", "3", "--tokens", "64", "--json")
        self.assertEqual(code, 0, out)
        r = json.loads(out)
        self.assertEqual((r["model"], r["n"], r["total_tokens"]), ("fake-model:7b", 3, 192))
        self.assertGreater(r["single_tps"], 0)
        self.assertEqual(r["people"], routecall.people_held(r["total_tps"]))

    def test_the_profile_takes_the_model_the_server_lists(self):
        code, out = self.run_rc("profile", "local", "--project", self.project, "--url", self.url)
        self.assertEqual(code, 0, out)
        env = json.load(open(os.path.join(self.project, ".routecall", "local", "settings.json")))["env"]
        self.assertEqual(env["ANTHROPIC_MODEL"], "fake-model:7b")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], self.url)

    def test_the_window_talks_to_the_server_that_answered(self):
        # LM Studio answered on :1234 and nothing on Ollama's :11434: the window must point where the model is
        prof = routecall.build_profile("local", self.project, {}, server=("lmstudio", "http://localhost:1234", ["qwen"]))
        self.assertEqual(prof["settings"]["env"]["ANTHROPIC_BASE_URL"], "http://localhost:1234")
        self.assertEqual(prof["settings"]["env"]["ANTHROPIC_MODEL"], "qwen")

    def test_people_formula(self):
        self.assertEqual(routecall.people_held(100, 20, 0.25), 20)
        self.assertEqual(routecall.people_held(0), 0)

    def test_tiers_by_memory(self):
        self.assertEqual(routecall.local_pick(16)["lead"], "gpt-oss-20b")
        self.assertIn("Qwen3.6-35B-A3B", routecall.local_pick(32)["lead"])
        self.assertIn("Qwen3-Coder-Next", routecall.local_pick(128)["lead"])
        self.assertEqual(routecall.local_pick(512)["lead"], "DeepSeek-V4-Flash")
        self.assertIsNone(routecall.local_pick(8)["lead"])


class Gateway(Base):
    def test_never_for_people(self):
        code, out = self.run_rc("gateway", "--for", "people", "--profiles", "glm")
        self.assertEqual(code, 1)
        self.assertIn("scripts and CI only", out)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".routecall", "gateway")))

    def test_config_for_scripts_with_budget_and_pii_guard(self):
        self.policy(max_usd_per_day=40)
        code, out = self.run_rc("gateway", "--profiles", "glm,deepseek")
        self.assertEqual(code, 0, out)
        text = open(os.path.join(self.project, ".routecall", "gateway", "litellm-config.yaml")).read()
        self.assertIn('api_base: "https://api.z.ai/api/anthropic"', text)
        self.assertIn('api_key: "os.environ/ROUTECALL_DEEPSEEK_KEY"', text)
        self.assertIn("guardrail: presidio", text)
        self.assertIn("max_budget: 40", text)
        self.assertIn('budget_duration: "1d"', text)
        req = open(os.path.join(self.project, ".routecall", "gateway", "requirements.txt")).read()
        self.assertIn(">=1.83.0,!=1.82.7,!=1.82.8", req)

    def test_policy_applies_to_the_gateway(self):
        self.policy(profiles=["us-federal-contractor"])
        self.assertEqual(self.run_rc("gateway", "--profiles", "deepseek")[0], 1)

    def test_litellm_versions(self):
        for v, ok in (("1.82.7", False), ("1.82.8", False), ("1.82.6", False), ("1.83.0", True), ("1.103.2", True)):
            self.assertEqual(routecall.litellm_ok(v), ok, v)
        self.assertEqual(self.run_rc("gateway", "--version", "1.82.7")[0], 1)
        self.assertEqual(self.run_rc("gateway", "--version", "1.83.0")[0], 0)

    def test_comparison_names_every_candidate_with_a_licence(self):
        code, out = self.run_rc("gateway")
        for name in ("LiteLLM", "Bifrost", "Higress", "RouteLLM", "claude-code-router", "llama-swap",
                     "cc-proxy-plugin", "opencodex"):
            self.assertIn(name, out)
        for g in json.load(open(os.path.join(DATA, "gateways.json")))["compared"]:
            self.assertTrue(g["license"] and g["repo"].count("/") == 1, g)


class Server(Base):
    def test_lead_stays_loaded_on_call_swaps(self):
        code, out = self.run_rc("server", "--lead", "qwen36=/m/qwen.gguf", "--on-call", "emb=/m/emb.gguf",
                                "--out", os.path.join(self.project, "srv"))
        self.assertEqual(code, 0, out)
        text = open(os.path.join(self.project, "srv", "config.yaml")).read()
        self.assertIn('"qwen36":', text)
        self.assertIn("--port ${PORT}", text)
        self.assertRegex(text, r'"lead":\n    swap: false\n    exclusive: false\n    persistent: true\n    members: \["qwen36"\]')
        self.assertIn('members: ["emb"]', text)

    def test_bad_names_are_refused(self):
        self.assertEqual(self.run_rc("server", "--lead", "bad name=/x.gguf")[0], 2)


class Doctor(Base):
    def test_a_vendor_address_in_the_shell_is_named_and_remote_is_off(self):
        code, out = self.run_rc("doctor", "--project", self.project, "--json",
                                env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"})
        d = json.loads(out)
        self.assertEqual(d["base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(d["base_url_from"], "the shell")
        self.assertEqual(d["remote_control"], "unavailable")
        self.assertEqual(d["advisor"], "off")
        self.assertNotIn("server-managed settings from claude.ai, if the organisation sets them", d["rules"])

    def test_privacy_switches_turn_remote_off_and_say_which(self):
        for var in ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK"):
            d = json.loads(self.run_rc("doctor", "--project", self.project, "--json", env={var: "1"})[1])
            self.assertEqual(d["remote_control"], "unavailable", var)
            self.assertTrue(any(var in w for w in d["remote_why"]))

    def test_telemetry_off_keeps_remote_but_stops_the_advisor(self):
        d = json.loads(self.run_rc("doctor", "--project", self.project, "--json", env={"DISABLE_TELEMETRY": "1"})[1])
        self.assertEqual(d["remote_control"], "available")
        self.assertEqual(d["trusted_devices_note"], ["DISABLE_TELEMETRY"])
        self.assertEqual(d["advisor"], "off")

    def test_an_api_key_turns_remote_off(self):
        d = json.loads(self.run_rc("doctor", "--project", self.project, "--json", env={"ANTHROPIC_API_KEY": "x"})[1])
        self.assertEqual(d["remote_control"], "unavailable")

    def test_settings_files_are_read_and_a_global_address_is_warned(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        json.dump({"env": {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic"}},
                  open(os.path.join(self.home, ".claude", "settings.json"), "w"))
        json.dump({"permissions": {}}, open(os.path.join(self.managed, "managed-settings.json"), "w"))
        code, out = self.run_rc("doctor", "--project", self.project)
        self.assertIn("api.z.ai", out)
        self.assertIn("EVERY window", out)
        self.assertIn("managed-settings.json", out)
        self.assertIn("Remote Control: unavailable", out)

    def test_clean_machine_is_all_available(self):
        d = json.loads(self.run_rc("doctor", "--project", self.project, "--json")[1])
        self.assertEqual((d["remote_control"], d["advisor"]), ("available", "possible"))


class Window(Base):
    def test_sparse_worktree_leaves_red_folders_out(self):
        if not shutil.which("git"):
            self.skipTest("no git here")
        repo = os.path.join(self.project, "repo")
        os.makedirs(os.path.join(repo, "clients"))
        os.makedirs(os.path.join(repo, "src"))
        open(os.path.join(repo, "clients", "list.csv"), "w").write("secret\n")
        open(os.path.join(repo, "src", "a.py"), "w").write("x = 1\n")
        g = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "HOME": self.home, "PATH": os.environ["PATH"]}
        for args in (["init", "-q"], ["add", "."], ["commit", "-qm", "x"]):
            subprocess.run(["git"] + args, cwd=repo, env=g, check=True, capture_output=True)
        json.dump({"red_paths": [os.path.join(repo, "clients")]}, open(os.path.join(repo, "company-ai-policy.json"), "w"))
        code, out = self.run_rc("window", "glm", "--project", repo, env={"GIT_AUTHOR_NAME": "t"}, cwd=repo)
        self.assertEqual(code, 0, out)
        dest = os.path.join(self.project, "repo-routecall-glm")
        self.assertTrue(os.path.isfile(os.path.join(dest, "src", "a.py")))
        self.assertFalse(os.path.exists(os.path.join(dest, "clients")))
        self.assertIn("clients", out)

    def test_no_repository_is_a_plain_problem(self):
        self.assertEqual(self.run_rc("window", "glm", "--project", self.project)[0], 2)


class Advisor(Base):
    def test_write_puts_choices_into_the_project_only(self):
        code, out = self.run_rc("advisor", "--mix", "advisor", "--write", "--project", self.project)
        self.assertEqual(code, 0, out)
        s = json.load(open(os.path.join(self.project, ".claude", "settings.local.json")))
        self.assertEqual((s["advisorModel"], s["model"]), ("opus", "sonnet"))
        self.run_rc("advisor", "--mix", "subagents", "--write", "--project", self.project)
        agent = open(os.path.join(self.project, ".claude", "agents", "routecall-worker.md")).read()
        self.assertIn("\nmodel: haiku\n", agent)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))

    def test_existing_settings_are_kept(self):
        os.makedirs(os.path.join(self.project, ".claude"))
        json.dump({"permissions": {"deny": ["Read(./x)"]}}, open(os.path.join(self.project, ".claude", "settings.local.json"), "w"))
        self.run_rc("advisor", "--mix", "opusplan", "--write", "--project", self.project)
        s = json.load(open(os.path.join(self.project, ".claude", "settings.local.json")))
        self.assertEqual(s["model"], "opusplan")
        self.assertEqual(s["permissions"]["deny"], ["Read(./x)"])


class DataFiles(unittest.TestCase):
    def test_every_endpoint_names_its_page_and_day(self):
        eps = json.load(open(os.path.join(DATA, "endpoints.json")))["profiles"]
        self.assertEqual(sorted(eps), sorted(routecall.PROFILES))
        for name, ep in eps.items():
            self.assertTrue(ep["url"].startswith("https://"), name)
            self.assertRegex(ep["checked"], r"^2026-\d\d-\d\d$")
            self.assertIn(ep["auth_var"], ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
            if name in routecall.CLOUD_PROFILES:
                self.assertTrue(ep["base_url"].startswith("https://") and ep["models"]["main"], name)

    def test_price_rows_named_by_profiles_exist_in_billcall(self):
        rows, where = routecall.price_rows()
        if not where:
            self.skipTest("billcall's price table is not beside routecall here")
        for name, ep in json.load(open(os.path.join(DATA, "endpoints.json")))["profiles"].items():
            for row in ep["price_rows"]:
                self.assertIn(row, rows, name)
                self.assertEqual(rows[row]["use"], "automated", row)
        for t in json.load(open(os.path.join(DATA, "local-models.json")))["tiers"]:
            for row in t["hardware_rows"]:
                self.assertIn(row, rows)

    def test_dictionaries_have_every_key(self):
        en = json.load(open(os.path.join(ROOT, "lang", "en.json")))
        keys = set(en) - {"_purpose", "name"}
        for code in ("es", "pt", "ru", "uk"):
            other = json.load(open(os.path.join(ROOT, "lang", "%s.json" % code)))
            self.assertEqual(set(other) - {"name"}, keys, code)
            for k in keys:
                self.assertEqual(sorted(re.findall(r"{(\w+)}", en[k])), sorted(re.findall(r"{(\w+)}", other[k])), (code, k))


class NoNetwork(unittest.TestCase):
    def test_no_network_module_in_the_plugin_code(self):
        bad = re.compile(r"^\s*(?:import|from)\s+(urllib|http\.client|http\b|socket|requests|httpx|ftplib|smtplib)\b", re.M)
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "tests", ".pytest_cache")]
            for f in files:
                if f.endswith(".py"):
                    text = open(os.path.join(folder, f), encoding="utf-8").read()
                    self.assertIsNone(bad.search(text), os.path.join(folder, f))

    def test_curl_is_asked_only_for_this_computer(self):
        with self.assertRaises(routecall.Refused):
            routecall.local_server("https://api.example.com")


if __name__ == "__main__":
    unittest.main()
