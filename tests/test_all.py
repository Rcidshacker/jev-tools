"""Offline checks against a local mock of /v1/systemone. Run: python test_all.py
The mock proves the logic and wire shape, not OpenJev's accuracy; run `python jevlib.py` for a live smoke test."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "installer"))
TMP = Path(tempfile.mkdtemp(prefix="jevtest-"))


class Mock(BaseHTTPRequestHandler):
    responder = None
    calls = []
    auth = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.calls.append(body)
        Mock.auth.append(self.headers.get("Authorization"))
        try:
            data = json.dumps({"model": "mock", "answers": Mock.responder(body), "usage": {}}).encode()
        except Exception:
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def noul_a(p):
    return {"type": "noul", "noul": p}


def choice_a(pick, p=0.95):
    return {"type": "choice", "choice": pick, "probabilities": {pick: p}, "confidence": p}


def score_a(x):
    return {"type": "score", "score": x, "legend": {}, "probabilities": {}, "confidence": 1.0}


def setUpModule():
    srv = HTTPServer(("127.0.0.1", 0), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ.update(OPENJEV_BASE_URL=f"http://127.0.0.1:{srv.server_port}", OPENJEV_API_KEY="test-key",
                      JEV_LOG=str(TMP / "log.jsonl"), HOME=str(TMP / "home"), USERPROFILE=str(TMP / "home"),
                      PYTHONIOENCODING="utf-8")
    os.environ["JEV_MODE"] = "active"
    os.environ["JEV_SKILL_PICKER"] = "1"


def run(script, *args, stdin="", cwd=None, **env):
    return subprocess.run([sys.executable, str(HERE / script), *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", cwd=cwd, env={**os.environ, **env})


def reset(responder):
    Mock.responder, Mock.calls = staticmethod(responder), []


class Client(unittest.TestCase):
    def test_returns_answers_and_fails_open(self):
        import jevlib
        reset(lambda b: {"q": noul_a(0.7)})
        self.assertEqual(jevlib.ask("s", {"q": jevlib.noul("x")})["q"]["noul"], 0.7)
        reset(lambda b: 1 / 0)
        self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))

    def test_refuses_foreign_host(self):
        import jevlib
        reset(lambda b: {"q": noul_a(0.7)})
        old = os.environ["OPENJEV_BASE_URL"]
        os.environ["OPENJEV_BASE_URL"] = "https://evil.example"
        try:
            self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))
        finally:
            os.environ["OPENJEV_BASE_URL"] = old
        self.assertEqual(Mock.calls, [])


class Privacy(unittest.TestCase):
    def test_secrets_are_redacted_before_sending(self):
        import jevlib
        reset(lambda b: {"q": noul_a(0.1)})
        jevlib.ask('key = "sk-abcdefghijklmnopqrstuvwxyz" and password = "hunter2hunter2"', {"q": jevlib.noul("x")})
        sent = json.dumps(Mock.calls[-1])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", sent)
        self.assertNotIn("hunter2hunter2", sent)
        self.assertIn("[REDACTED]", sent)

    def test_common_secret_shapes_are_redacted_and_ordinary_code_survives(self):
        import jevlib
        leaks = {  # every value below is fabricated; split literals keep GitHub push protection from mistaking them for real keys
            "use sk_" "live_4eC39HqLyjWDarjtT1zdp7dc now": "4eC39HqLyjWDarjtT1zdp7dc",
            "DATABASE_URL=postgres://admin:S3cretPassw0rd@db.internal:5432/app": "S3cretPassw0rd",
            "mongodb+srv://user:hunter2hunter2@cluster0.abc.mongodb.net/test": "hunter2hunter2",
            "API_KEY=abcd1234efgh5678ijkl9012": "abcd1234efgh5678ijkl9012",
            "CLIENT_SECRET=Zm9vYmFyYmF6cXV4MTIzNDU2": "Zm9vYmFyYmF6cXV4MTIzNDU2",
            "Authorization: Bearer abcDEF123456ghiJKL789012mnoPQR": "abcDEF123456ghiJKL789012mnoPQR",
            "key=AIza" "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q": "AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q",
            "aws_secret_access_key = " "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "here is the token 9f8e7d6c5b4a39281706f5e4d3c2b1a098765432 ok": "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432",
            "//registry.npmjs.org/:_authToken=npm" "_abcdefghijklmnopqrstuvwxyz0123456789": "npm_abcdefghijklmnopqrstuvwxyz0123456789",
            "OPENJEV_API_KEY=sk-" "codiv-AbCdEfGhIjKlMnOpQrStUvWxYz012345": "AbCdEfGhIjKlMnOpQrStUvWxYz012345",
            "https://hooks.slack.com/" "services/T01234567/B01234567/abcdefghijklmnopqrstuvwx": "abcdefghijklmnopqrstuvwx",
            '{"db_password": "correct-horse-battery"}': "correct-horse-battery",
        }
        for text, secret in leaks.items():
            self.assertNotIn(secret, jevlib.scrub(text), text)
        for code in ("def total(items): return sum(i.price for i in items)", "class AuthTokenRefresher: pass",
                     "const url = config.apiHost + '/users'; // token refresh handled elsewhere", "max_tokens = 256"):
            self.assertEqual(jevlib.scrub(code), code)

    def test_sensitive_paths_and_normal_code(self):
        import jevlib
        for p in (r"C:\proj\.env", "/a/.env.local", "~/.ssh/id_rsa", "certs/server.pem", "config/credentials.json"):
            self.assertTrue(jevlib.sensitive_path(p), p)
        for p in (r"C:\proj\srcpp.py", "src/environment.ts", "docs/keyboard.md"):
            self.assertFalse(jevlib.sensitive_path(p), p)

    def test_missing_key_is_logged_not_silent(self):
        import jevlib
        keys = {k: os.environ.pop(k) for k in ("OPENJEV_API_KEY", "TYPESAFE_API_KEY") if k in os.environ}
        try:
            self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))
        finally:
            os.environ.update(keys)
        self.assertIn('"no_key"', Path(os.environ["JEV_LOG"]).read_text(encoding="utf-8"))

    def test_status_reports_key_and_mode(self):
        r = run("status.py")
        self.assertIn("api key     found via OPENJEV_API_KEY", r.stdout)
        self.assertIn("mode        active", r.stdout)


class Backends(unittest.TestCase):
    """config.json + credentials file written by `jev-tools-setup`, read by jevlib."""
    def setUp(self):
        import jevlib
        self.home = jevlib.home()
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir(parents=True)
        self.env = {k: os.environ.pop(k) for k in ("OPENJEV_API_KEY", "TYPESAFE_API_KEY") if k in os.environ}
        self.base = os.environ["OPENJEV_BASE_URL"]
        Mock.auth = []

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        os.environ.update(self.env)

    def test_key_file_is_the_last_resort(self):
        import jevlib
        self.assertEqual(jevlib.find_key(), (None, None))
        (self.home / "credentials").write_text("file-key\n")
        self.assertEqual(jevlib.find_key(), ("file-key", "credentials file"))
        os.environ["OPENJEV_API_KEY"] = "env-key"
        try:
            self.assertEqual(jevlib.find_key(), ("env-key", "OPENJEV_API_KEY"))  # env still wins
        finally:
            del os.environ["OPENJEV_API_KEY"]

    def test_offline_never_calls(self):
        import jevlib
        (self.home / "config.json").write_text(json.dumps({"backend": "offline"}))
        os.environ["OPENJEV_API_KEY"] = "k"
        reset(lambda b: {"q": noul_a(0.9)})
        try:
            self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))
        finally:
            del os.environ["OPENJEV_API_KEY"]
        self.assertEqual(Mock.calls, [])

    def test_local_works_without_a_key_and_api_does_not(self):
        import jevlib
        (self.home / "config.json").write_text(json.dumps({"backend": "local"}))
        reset(lambda b: {"q": noul_a(0.8)})
        self.assertEqual(jevlib.ask("s", {"q": jevlib.noul("x")})["q"]["noul"], 0.8)
        self.assertEqual(Mock.auth, [None])  # nothing to send, nothing sent
        (self.home / "config.json").write_text(json.dumps({"backend": "api"}))
        self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))  # api backend still needs a key

    def test_config_cannot_point_the_key_at_another_host(self):
        import jevlib
        (self.home / "config.json").write_text(json.dumps({"backend": "local", "base_url": "https://evil.example"}))
        (self.home / "credentials").write_text("file-key\n")
        reset(lambda b: {"q": noul_a(0.8)})
        old = os.environ.pop("OPENJEV_BASE_URL")  # the env var would otherwise take precedence over the config
        try:
            self.assertIsNone(jevlib.ask("s", {"q": jevlib.noul("x")}))
        finally:
            os.environ["OPENJEV_BASE_URL"] = old
        self.assertEqual(Mock.calls, [])

    def test_mode_from_config_but_env_wins(self):
        import jevlib
        (self.home / "config.json").write_text(json.dumps({"mode": "off"}))
        old = os.environ.pop("JEV_MODE")
        try:
            self.assertEqual(jevlib.mode(), "off")
            os.environ["JEV_MODE"] = "active"
            self.assertEqual(jevlib.mode(), "active")
        finally:
            os.environ["JEV_MODE"] = old

    def test_status_names_backend_and_key_source_not_the_key(self):
        (self.home / "credentials").write_text("super-secret-file-key\n")
        r = run("status.py", OPENJEV_API_KEY="")
        self.assertIn("api key     found via credentials file", r.stdout)
        self.assertIn("backend     api", r.stdout)
        self.assertNotIn("super-secret-file-key", r.stdout)


class SmallModels(unittest.TestCase):
    """Local Verdict/Laya: model name in the request, state trimmed to the context window, option caps."""
    def setUp(self):
        import jevlib
        self.jl = jevlib
        self.home = jevlib.home()
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir(parents=True)
        self.base = os.environ["OPENJEV_BASE_URL"]

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def use(self, model, backend="local"):
        (self.home / "config.json").write_text(json.dumps({"backend": backend, "model": model}))

    def test_model_selection(self):
        self.assertEqual(self.jl.model(), "openjev-latest")
        self.use("verdict-1.4")
        self.assertEqual(self.jl.model(), "verdict-1.4")
        self.use("verdict-1.4", backend="api")
        self.assertEqual(self.jl.model(), "openjev-latest")  # a model choice only applies to the local backend
        self.use("not-a-model")
        self.assertEqual(self.jl.model(), "openjev-latest")

    def test_request_names_the_model_and_trims_the_state_head_first(self):
        self.use("verdict-1.4")
        reset(lambda b: {"q": noul_a(0.5)})
        self.jl.ask("HEAD" + "x" * 6000, {"q": self.jl.noul("Is this fine")})
        body = Mock.calls[-1]
        self.assertEqual(body["model"], "verdict-1.4")
        self.assertTrue(body["state"].startswith("HEAD"))
        self.assertLess(len(body["state"]), 1500)  # 512 tokens x 3 chars, minus the question
        self.use("laya-1.0")
        self.jl.ask("y" * 6000, {"q": self.jl.noul("Is this fine")})
        self.assertGreater(len(Mock.calls[-1]["state"]), 1500)  # Laya has twice the room
        self.assertLess(len(Mock.calls[-1]["state"]), 3000)

    def test_openjev_state_is_never_trimmed(self):
        reset(lambda b: {"q": noul_a(0.5)})
        self.jl.ask("z" * 6000, {"q": self.jl.noul("Is this fine")})
        self.assertEqual(len(Mock.calls[-1]["state"]), 6000)
        self.assertEqual(Mock.calls[-1]["model"], "openjev-latest")

    def test_dict_state_keeps_its_shape(self):
        out = self.jl.fit({"goal": "g", "files": {"a": "x" * 4000, "b": "y" * 4000}}, 1000)
        self.assertEqual(sorted(out["files"]), ["a", "b"])
        self.assertLess(len(json.dumps(out)), 1300)
        small = {"a": "short"}
        self.assertIs(self.jl.fit(small, 1000), small)

    def test_too_many_options_declines_instead_of_cutting(self):
        self.use("verdict-1.4")
        reset(lambda b: {"q": choice_a("o0")})
        many = self.jl.choice("Which", {f"o{i}": None for i in range(30)})
        self.assertIsNone(self.jl.ask("s", {"q": many}))
        self.assertEqual(Mock.calls, [])
        ok = self.jl.choice("Which", {f"o{i}": None for i in range(20)})
        self.assertIsNotNone(self.jl.ask("s", {"q": ok}))

    def test_max_options_per_model(self):
        self.assertEqual(self.jl.max_options(), 255)
        self.use("verdict-1.4")
        self.assertEqual(self.jl.max_options(), 23)
        self.use("laya-1.0")
        self.assertEqual(self.jl.max_options(), 19)

    def test_status_names_the_small_model(self):
        self.use("laya-1.0")
        r = run("status.py", OPENJEV_API_KEY="")
        self.assertIn("model       laya-1.0", r.stdout)
        self.assertIn("rule-calibrate", r.stdout)


class Trust(unittest.TestCase):
    """verdict-1.4 only routes skills; everything it measurably cannot judge uses the pattern fallbacks."""
    def setUp(self):
        import jevlib
        self.jl, self.home = jevlib, jevlib.home()
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir(parents=True)
        self.proj = TMP / "trustproj"
        shutil.rmtree(self.proj, ignore_errors=True)
        (self.proj / "src").mkdir(parents=True)
        (self.proj / "CLAUDE.md").write_text("# Rules\n- Never use console.log in source files\n")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def use(self, model, backend="local"):
        (self.home / "config.json").write_text(json.dumps({"backend": backend, "model": model}))

    def test_no_model_and_workers(self):
        self.assertFalse(self.jl.no_model("rules"))  # api / OpenJev: trusted for everything
        self.assertEqual(self.jl.workers(), 5)
        feats = ("skills", "nav", "rules", "precheck", "files")
        self.use("verdict-1.4")
        self.assertEqual([self.jl.no_model(f) for f in feats], [False, True, True, True, True])
        self.assertEqual((self.jl.workers(), self.jl.workers(4)), (1, 1))  # one thread against a local server
        self.use("laya-1.0")
        self.assertEqual([self.jl.no_model(f) for f in feats], [True, False, True, True, True])
        self.use("openjev-latest")
        self.assertEqual([self.jl.no_model(f) for f in feats], [False] * 5)
        self.use("x", backend="offline")
        self.assertTrue(self.jl.no_model("skills"))

    def test_verdict_rule_hook_uses_the_literal_check_and_makes_no_call(self):
        self.use("verdict-1.4")
        reset(lambda b: {})
        ti = {"file_path": str(self.proj / "src/a.js"), "old_string": "return 1", "new_string": "console.log(1); return 1"}
        out = json.loads(run("rule_enforcer.py", stdin=json.dumps({"tool_name": "Edit", "tool_input": ti, "cwd": str(self.proj)}), JEV_MODE="active").stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(Mock.calls, [])

    def test_verdict_still_routes_skills_with_the_model(self):
        self.use("verdict-1.4")
        d = self.proj / ".claude" / "skills" / "pdf-tool"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: pdf-tool\ndescription: Merge, split and rotate PDF files\n---\nbody\n")
        reset(lambda b: {"skill": choice_a("pdf-tool", 0.9)} if "skill" in b["questions"] else {"needed": noul_a(0.9), "right": noul_a(0.9)})
        out = run("skill_picker.py", stdin=json.dumps({"prompt": "please merge these two pdf files into one", "cwd": str(self.proj)}), JEV_MODE="active", JEV_SKILL_PICKER="1")
        self.assertIn("pdf-tool", out.stdout)
        self.assertTrue(Mock.calls and Mock.calls[0]["model"] == "verdict-1.4")

    def test_verdict_precheck_and_nav_use_patterns(self):
        self.use("verdict-1.4")
        reset(lambda b: {})
        els = [{"ref": "ref_1", "role": "link", "name": "Home"}, {"ref": "ref_2", "role": "button", "name": "Settings"}]
        out = json.loads(run("pick_next.py", stdin=json.dumps({"goal": "open the settings", "elements": els})).stdout)
        self.assertEqual((out["action"], out["ref"]), ("unsure", "ref_2"))
        self.assertEqual(Mock.calls, [])

    def test_secret_rule_without_a_literal_token_is_caught_by_shape(self):
        self.use("verdict-1.4")
        reset(lambda b: {})
        (self.proj / "CLAUDE.md").write_text("# Rules\n- Never commit secrets or API keys\n")
        ti = {"file_path": str(self.proj / "src/a.js"), "old_string": "const a = 1", "new_string": "const apiKey = 'sk-live-9f8e7d6c5b4a'; const a = 1"}
        out = json.loads(run("rule_enforcer.py", stdin=json.dumps({"tool_name": "Edit", "tool_input": ti, "cwd": str(self.proj)}), JEV_MODE="active").stdout)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        ti["new_string"] = "const sum = 1"
        self.assertEqual(run("rule_enforcer.py", stdin=json.dumps({"tool_name": "Edit", "tool_input": ti, "cwd": str(self.proj)}), JEV_MODE="active").stdout.strip(), "")
        self.assertEqual(Mock.calls, [])

    def test_laya_skill_hook_uses_keywords_and_makes_no_call(self):
        self.use("laya-1.0")
        d = self.proj / ".claude" / "skills" / "pdf-tool"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: pdf-tool\ndescription: Merge, split and rotate PDF files\n---\nbody\n")
        reset(lambda b: {})
        out = run("skill_picker.py", stdin=json.dumps({"prompt": "please merge these two pdf files into one", "cwd": str(self.proj)}), JEV_MODE="active", JEV_SKILL_PICKER="1")
        self.assertIn("pdf-tool", out.stdout)
        self.assertEqual(Mock.calls, [])

    def test_laya_still_drives_browser_nav_with_the_model(self):
        self.use("laya-1.0")
        reset(lambda b: {"next": choice_a("ref_2", 0.9), "goal_met": noul_a(0.05), "stuck": noul_a(0.05)})
        els = [{"ref": "ref_1", "role": "link", "name": "Home"}, {"ref": "ref_2", "role": "button", "name": "Settings"}]
        out = json.loads(run("pick_next.py", stdin=json.dumps({"goal": "open the settings", "elements": els})).stdout)
        self.assertEqual((out["action"], out["ref"]), ("click", "ref_2"))
        self.assertEqual(Mock.calls[0]["model"], "laya-1.0")


class Installer(unittest.TestCase):
    KEY = "sk-" "codiv-TestKeyTestKeyTestKey0123456789"

    def setUp(self):
        import jev_tools_cli
        self.cli, self.home = jev_tools_cli, jev_tools_cli.home()
        shutil.rmtree(self.home, ignore_errors=True)
        self.out = io.StringIO()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def nothing_saved(self):  # a failed attempt may leave log.jsonl and LOG.md behind, but never a key or a config
        self.assertFalse((self.home / "credentials").exists())
        self.assertFalse((self.home / "config.json").exists())

    def setup(self, *args, stdin=""):
        with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(self.out):
            return self.cli.main(["setup", "--skip-plugin", *args])

    def test_api_setup_validates_then_stores_key_without_printing_it(self):
        reset(lambda b: {"ok": noul_a(0.99)})
        self.assertEqual(self.setup("--backend", "api", "--key-stdin", stdin=self.KEY + "\n"), 0)
        self.assertEqual((self.home / "credentials").read_text().strip(), self.KEY)
        cfg = json.loads((self.home / "config.json").read_text())
        self.assertEqual((cfg["backend"], cfg["mode"]), ("api", "shadow"))
        self.assertNotIn(self.KEY, self.out.getvalue())
        self.assertNotIn(self.KEY, json.dumps(cfg))
        self.assertEqual(Mock.auth[-1], f"Bearer {self.KEY}")
        if os.name != "nt":
            self.assertEqual((self.home / "credentials").stat().st_mode & 0o777, 0o600)

    def test_rejected_key_saves_nothing(self):
        reset(lambda b: 1 / 0)  # mock answers 500
        self.assertEqual(self.setup("--backend", "api", "--key-stdin", stdin=self.KEY + "\n"), 1)
        self.nothing_saved()
        self.assertNotIn(self.KEY, self.out.getvalue())

    def test_empty_key_saves_nothing(self):
        self.assertEqual(self.setup("--backend", "api", "--key-stdin", stdin="\n"), 1)
        self.nothing_saved()

    def test_offline_writes_config_and_explains(self):
        self.assertEqual(self.setup("--backend", "offline", "--mode", "off"), 0)
        self.assertEqual(json.loads((self.home / "config.json").read_text()), {"backend": "offline", "mode": "off"})
        self.assertFalse((self.home / "credentials").exists())
        self.assertIn("no model", self.out.getvalue())

    def test_local_refuses_without_blackwell_gpu(self):
        with mock.patch.object(self.cli, "gpu", return_value=("NVIDIA GeForce RTX 4050 Laptop GPU", False)):
            self.assertEqual(self.setup("--backend", "local", "--model", "openjev-latest"), 1)
        self.nothing_saved()
        self.assertIn("Blackwell", self.out.getvalue())

    def test_local_with_gpu_and_docker_saves_loopback_url(self):
        reset(lambda b: {"ok": noul_a(0.99)})
        url = os.environ["OPENJEV_BASE_URL"]
        with mock.patch.object(self.cli, "gpu", return_value=("RTX PRO 6000 Blackwell", True)), \
                mock.patch.object(self.cli.shutil, "which", return_value="docker"):
            self.assertEqual(self.setup("--backend", "local", "--model", "openjev-latest", "--base-url", url), 0)
        self.assertEqual(json.loads((self.home / "config.json").read_text())["base_url"], url)
        self.assertIn("server answers", self.out.getvalue())

    def test_probe_asks_with_the_configured_model(self):
        reset(lambda b: {"ok": noul_a(0.99)})
        self.assertIsNone(self.cli.probe(os.environ["OPENJEV_BASE_URL"], None, "verdict-1.4"))
        self.assertEqual(Mock.calls[-1]["model"], "verdict-1.4")
        self.assertIsNone(self.cli.probe(os.environ["OPENJEV_BASE_URL"], None))
        self.assertEqual(Mock.calls[-1]["model"], "openjev-latest")

    def test_probe_refuses_foreign_hosts(self):
        reset(lambda b: {"ok": noul_a(0.99)})
        self.assertIn("refusing", self.cli.probe("https://evil.example", "k"))
        self.assertEqual(Mock.calls, [])

    def test_missing_claude_cli_prints_manual_commands(self):
        with mock.patch.object(self.cli.shutil, "which", return_value=None), contextlib.redirect_stdout(self.out):
            self.assertFalse(self.cli.install_plugin())
        self.assertIn("/plugin install jev-tools@jev-tools", self.out.getvalue())

    def test_gpu_parsing(self):
        for out, want in (("NVIDIA RTX PRO 6000 Blackwell, 12.0\n", True), ("NVIDIA B200, 10.0\n", True),
                          ("NVIDIA GeForce RTX 4050 Laptop GPU, 8.9\n", False), ("garbage, n/a\n", False)):
            r = subprocess.CompletedProcess([], 0, out, "")
            with mock.patch.object(self.cli.shutil, "which", return_value="x"), mock.patch.object(self.cli.subprocess, "run", return_value=r):
                self.assertEqual(self.cli.gpu()[1], want, out)

    def test_small_model_install_runs_clone_venv_pip_then_saves_config(self):
        calls = []
        with mock.patch.object(self.cli.subprocess, "call", side_effect=lambda cmd, **k: calls.append(cmd) or 0), \
                mock.patch.object(self.cli.shutil, "which", return_value="git"):
            self.assertEqual(self.setup("--backend", "local", "--model", "verdict-1.4", "--yes"), 0)
        self.assertEqual([c[0] for c in calls][:1], ["git"])
        self.assertIn("clone", calls[0])
        self.assertIn("venv", calls[1])
        self.assertEqual(calls[2][-3:-1], ["install", "-e"])
        self.assertTrue(calls[2][-1].endswith("[verdict]"))
        cfg = json.loads((self.home / "config.json").read_text())
        self.assertEqual((cfg["backend"], cfg["model"], cfg["base_url"]), ("local", "verdict-1.4", self.cli.LOCAL_URL))
        self.assertIn("serve", self.out.getvalue())

    def test_small_model_install_declined_or_failed_saves_nothing(self):
        with mock.patch.object(self.cli.subprocess, "call", return_value=0) as call, mock.patch("builtins.input", return_value="n"):
            self.assertEqual(self.setup("--backend", "local", "--model", "laya-1.0"), 1)
        call.assert_not_called()
        self.nothing_saved()
        with mock.patch.object(self.cli.subprocess, "call", return_value=1), mock.patch.object(self.cli.shutil, "which", return_value="git"):
            self.assertEqual(self.setup("--backend", "local", "--model", "laya-1.0", "--yes"), 1)
        self.nothing_saved()

    def test_serve_sets_backend_env_and_needs_setup_first(self):
        with contextlib.redirect_stdout(self.out):
            self.assertEqual(self.cli.main(["serve"]), 1)  # nothing configured yet
        self.home.mkdir(parents=True)
        (self.home / "config.json").write_text(json.dumps({"backend": "local", "model": "laya-1.0", "base_url": "http://127.0.0.1:8123"}))
        py = self.cli.venv_python()
        py.parent.mkdir(parents=True)
        py.write_text("")
        with mock.patch.object(self.cli.subprocess, "call", return_value=0) as call, contextlib.redirect_stdout(self.out):
            self.assertEqual(self.cli.main(["serve", "--device", "cpu"]), 0)
        cmd, env = call.call_args[0][0], call.call_args[1]["env"]
        self.assertEqual(cmd[-2:], ["-m", "openjev"])
        self.assertEqual((env["OPENJEV_BACKEND"], env["OPENJEV_PORT"], env["OPENJEV_DEVICE"]), ("laya", "8123", "cpu"))

    def test_check_reports_a_down_local_server(self):
        self.home.mkdir(parents=True)
        (self.home / "config.json").write_text(json.dumps({"backend": "local", "model": "verdict-1.4", "base_url": self.cli.LOCAL_URL}))
        with mock.patch.object(self.cli, "probe", return_value="refused"), mock.patch.object(self.cli.shutil, "which", return_value=None), \
                mock.patch.object(self.cli.socket, "create_connection", side_effect=OSError("x")):
            rows = {n: (lvl, h) for lvl, n, _, h in self.cli.checks()}
        self.assertEqual(rows["local server"][0], "warn")
        self.assertIn("serve", rows["local server"][1])

    def test_uninstall_removes_everything(self):
        self.home.mkdir()
        (self.home / "credentials").write_text("k")
        with contextlib.redirect_stdout(self.out):
            self.assertEqual(self.cli.main(["uninstall"]), 0)
        self.assertFalse(self.home.exists())


class Offline(unittest.TestCase):
    """backend=offline: no model and no network, but every piece still does what it can and says what it cannot."""
    def setUp(self):
        import jevlib
        self.home = jevlib.home()
        shutil.rmtree(self.home, ignore_errors=True)
        self.home.mkdir(parents=True)
        (self.home / "config.json").write_text(json.dumps({"backend": "offline"}))
        reset(lambda b: {})
        self.proj = TMP / "offproj"
        shutil.rmtree(self.proj, ignore_errors=True)
        (self.proj / "src").mkdir(parents=True)
        (self.proj / "CLAUDE.md").write_text("# Rules\n- Never use console.log in source files\n- Always add type hints\n")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def log_events(self):
        p = Path(os.environ["JEV_LOG"])
        return [json.loads(l)["event"] for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    # rule hook
    def edit(self, new, path="src/a.js"):
        ti = {"file_path": str(self.proj / path), "old_string": "return 1", "new_string": new}
        return json.dumps({"tool_name": "Edit", "tool_input": ti, "cwd": str(self.proj)})

    def test_edit_diff_keeps_removed_and_added_lines_apart(self):
        import rule_enforcer
        d = rule_enforcer.diff_of("Edit", {"file_path": "a.js", "old_string": "return 1", "new_string": "console.log(1); return 1"})
        self.assertIn("\n-return 1\n+console.log(1); return 1\n", d)  # was glued: "-return 1+console.log(1)..."

    def test_literal_tokens(self):
        from rule_enforcer import literal_tokens as lt
        self.assertEqual(lt("Never use console.log in source files"), ["console.log"])
        self.assertEqual(lt("Avoid `eval` in request handlers"), ["eval"])
        self.assertEqual(lt("Don't use eval() anywhere"), ["eval()"])
        for vague in ("Always add type hints", "Never use tabs", "No print statements", "Do not write long functions"):
            self.assertEqual(lt(vague), [], vague)

    def test_rule_hook_blocks_a_literal_match_without_calling_anything(self):
        out = json.loads(run("rule_enforcer.py", stdin=self.edit("console.log(1); return 1"), JEV_MODE="active").stdout)
        h = out["hookSpecificOutput"]
        self.assertEqual(h["permissionDecision"], "deny")
        self.assertIn("console.log", h["permissionDecisionReason"])
        self.assertIn("no model", h["permissionDecisionReason"])
        self.assertEqual(Mock.calls, [])
        self.assertIn("offline", self.log_events())  # `status` can see the hook ran

    def test_rule_hook_allows_clean_edits_and_never_blocks_in_shadow(self):
        self.assertEqual(run("rule_enforcer.py", stdin=self.edit("x(2); return 1"), JEV_MODE="active").stdout, "")
        self.assertEqual(run("rule_enforcer.py", stdin=self.edit("console.log(1)"), JEV_MODE="shadow").stdout, "")
        self.assertIn("rule_check", self.log_events())

    # skill hook
    def test_skill_hook_uses_its_keyword_shortlist(self):
        d = self.proj / ".claude" / "skills" / "pdf-tool"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: pdf-tool\ndescription: Merge, split and rotate PDF files\n---\nbody\n")
        ev = lambda t: json.dumps({"prompt": t, "cwd": str(self.proj)})
        out = json.loads(run("skill_picker.py", stdin=ev("please merge these two pdf files into one"), JEV_MODE="active").stdout)
        self.assertIn("pdf-tool", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(run("skill_picker.py", stdin=ev("please merge these two pdf files into one"), JEV_MODE="shadow").stdout, "")
        self.assertEqual(run("skill_picker.py", stdin=ev("something about weather forecasts today"), JEV_MODE="active").stdout, "")
        self.assertEqual(Mock.calls, [])

    # browser-nav
    def test_browser_nav_suggests_by_name_but_stays_unsure(self):
        els = [{"ref": "ref_1", "role": "link", "name": "Home"}, {"ref": "ref_2", "role": "button", "name": "Settings"}]
        r = run("pick_next.py", stdin=json.dumps({"goal": "open the settings page", "elements": els}))
        out = json.loads(r.stdout)
        self.assertEqual((r.returncode, out["action"], out["ref"]), (0, "unsure", "ref_2"))
        r = run("pick_next.py", stdin=json.dumps({"goal": "open the settings page", "elements": els, "history": ["clicked ref_2"]}))
        self.assertEqual(json.loads(r.stdout)["action"], "error")  # the only match was already used
        r = run("pick_next.py", stdin=json.dumps({"goal": "upload avatar", "elements": els}))
        self.assertEqual((r.returncode, json.loads(r.stdout)["action"]), (1, "error"))

    # review pre-check
    def repo(self, files):
        repo = Path(tempfile.mkdtemp(prefix="offrepo-", dir=TMP))  # fresh each time: Windows cannot delete a read-only .git
        g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        g("init", "-q")
        (repo / "f.py").write_text("x = 1\n")
        g("add", "."); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text)
            g("add", "-N", name)
        return repo

    def precheck(self, files):
        r = run("review_precheck.py", cwd=self.repo(files))
        return r.returncode, json.loads(r.stdout)

    def test_precheck_flags_what_patterns_can_see(self):
        code, out = self.precheck({"f.py": 'key = "sk-abcdefghijklmnopqrstuvwxyz"\ntry:\n    go()\nexcept Exception:\n    pass\n', "package.json": "{}"})
        self.assertEqual((code, out["route"]), (10, "full"))
        text = " ".join(out["flags"])
        for expect in ("secrets", "errors", "dependencies"):
            self.assertIn(expect, text)

    def test_precheck_fast_only_for_a_small_clean_diff(self):
        self.assertEqual(self.precheck({"f.py": "x = 2\n"})[0], 0)
        code, out = self.precheck({"f.py": "".join(f"y{i} = {i}\n" for i in range(40))})
        self.assertEqual((code, out["route"]), (10, "full"))
        self.assertIn("risk", " ".join(out["flags"]))
        self.assertEqual(Mock.calls, [])

    def test_precheck_flags_test_weakening_and_migrations(self):
        code, out = self.precheck({"tests/test_a.py": "import pytest\n@pytest.mark.skip\ndef test_a():\n    pass\n",
                                   "db/migrations/001_add.sql": "ALTER TABLE users ADD COLUMN x int;\n"})
        text = " ".join(out["flags"])
        self.assertIn("tests", text)
        self.assertIn("schema", text)

    def test_precheck_outage_stays_full_but_still_reports_patterns(self):
        (self.home / "config.json").write_text(json.dumps({"backend": "api"}))
        reset(lambda b: 1 / 0)
        repo = self.repo({"package.json": "{}"})
        r = run("review_precheck.py", cwd=repo)
        out = json.loads(r.stdout)
        self.assertEqual((r.returncode, out["route"]), (10, "full"))
        self.assertIn("Jev unavailable", out["flags"])
        self.assertIn("dependencies", " ".join(out["flags"]))

    # calibrate + find-files
    def test_calibrate_refuses_clearly(self):
        r = run("rule_calibrate.py", cwd=self.proj)
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs a model", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_find_files_scores_are_percent_of_best(self):
        for i, n in enumerate((3, 1)):
            (self.proj / f"auth_{i}.py").write_text("login token\n" * n)
        r = run("find_files.py", "login token", "--root", str(self.proj), "--top", "2")
        self.assertEqual(r.returncode, 0)
        self.assertEqual([l.split()[0] for l in r.stdout.splitlines()], ["100", "33"])
        self.assertIn("no model", r.stderr)


class Report(unittest.TestCase):
    """LOG.md: the plain-English report a user can read or attach to an issue."""
    REPORT = HERE.parent / "installer" / "jev_report.py"

    def make(self, events=(), plugin_events=(), config=None, **env):
        home = Path(tempfile.mkdtemp(prefix="rep-", dir=TMP))
        (home / ".jev-tools").mkdir()
        if config is not None:
            (home / ".jev-tools" / "config.json").write_text(json.dumps(config))
        write = lambda path, evs: (path.parent.mkdir(parents=True, exist_ok=True),
                                   path.write_text("".join(json.dumps(e) + "\n" for e in evs), encoding="utf-8"))
        if events:
            write(home / ".jev-tools" / "log.jsonl", events)
        if plugin_events:
            write(home / ".claude" / "plugins" / "data" / "jev-tools-jev-tools" / "log.jsonl", plugin_events)
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPENJEV", "TYPESAFE", "JEV_", "CLAUDE_PLUGIN"))}
        r = subprocess.run([sys.executable, str(self.REPORT)], capture_output=True, text=True, encoding="utf-8",
                           env={**clean, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8", **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        return (home / ".jev-tools" / "LOG.md").read_text(encoding="utf-8"), r.stdout, home

    @staticmethod
    def ev(event, ago=60, **kw):
        import time
        return {"t": int(time.time()) - ago, "event": event, **kw}

    def test_empty_log_says_what_to_check(self):
        md, out, _ = self.make()
        self.assertIn("No events recorded yet", md)
        self.assertIn("Restart Claude Code", md)
        self.assertIn("⚠️", md)
        self.assertIn("notes", out)

    def test_problems_are_named_with_fixes_and_secrets_are_redacted(self):
        key = "sk-" "codiv-AbCdEfGhIjKlMnOpQrStUvWx0123"
        md, out, home = self.make(events=[
            self.ev("no_key"), self.ev("no_key"),
            self.ev("ask_error", err="HTTPError", msg=f"HTTP Error 401: Unauthorized for {key}"),
            self.ev("hook_error", hook="rule_enforcer", err="KeyError('x')")])
        self.assertIn("❌", md)
        self.assertIn("PROBLEMS", out)
        for want in ("API key missing (2 skipped calls", "key rejected", "rule_enforcer hook crashed", "Fix:", "codiv.ai/dashboard"):
            self.assertIn(want, md)
        self.assertNotIn(key, md)
        self.assertIn("[REDACTED]", md)
        self.assertNotIn(str(home), md)
        self.assertIn("~", md)  # the log path is shown with the home directory shortened

    def test_healthy_when_calls_succeed(self):
        md, out, _ = self.make(events=[self.ev("ask", n=1, ms=900, tok=100), self.ev("ask", n=2, ms=1100, tok=200),
                                       self.ev("rule_check", file="a.py", rules=3, top=0.1, enforce=False)],
                               config={"backend": "api", "mode": "shadow"}, OPENJEV_API_KEY="k")
        self.assertIn("✅ Healthy", md)
        self.assertIn("median 1000 ms", md)
        self.assertIn("rule check on a.py", md)
        self.assertIn("OPENJEV_API_KEY", md)  # the NAME of where the key was found
        self.assertNotIn("| k |", md)

    def test_mode_off_is_called_out(self):
        md, _, _ = self.make(events=[self.ev("ask", n=1, ms=5, tok=1)], JEV_MODE="off")
        self.assertIn("Mode is OFF", md)
        self.assertIn("⚠️", md)

    def test_merges_both_log_locations_without_double_counting(self):
        shared = self.ev("ask", n=1, ms=10, tok=1)
        md, _, _ = self.make(events=[shared, self.ev("ask", ago=5, n=1, ms=20, tok=1)], plugin_events=[shared, self.ev("precheck", route="full", flags=2)])
        self.assertIn("3 event(s) in total", md)
        self.assertIn("review pre-check: full review, 2 flag(s)", md)

    def test_offline_and_small_model_notes(self):
        md, _, _ = self.make(events=[self.ev("offline"), self.ev("state_cut", model="verdict-1.4", chars=9000)], config={"backend": "offline"})
        self.assertIn("Offline backend: 1 model call(s) skipped", md)
        self.assertIn("small local model is trimming", md)

    def test_setup_writes_a_log_even_when_it_fails(self):
        import jev_tools_cli
        home = jev_tools_cli.home()
        shutil.rmtree(home, ignore_errors=True)
        reset(lambda b: 1 / 0)  # the mock answers 500, so the key check fails
        with mock.patch("sys.stdin", io.StringIO("sk-" "codiv-AbCdEfGhIjKlMnOpQrStUvWx0123\n")), contextlib.redirect_stdout(io.StringIO()) as out:
            rc = jev_tools_cli.main(["setup", "--skip-plugin", "--backend", "api", "--key-stdin"])
        self.assertEqual(rc, 1)
        md = (home / "LOG.md").read_text(encoding="utf-8")
        self.assertIn("setup started", md)
        self.assertIn("key/server check failed", md)
        self.assertIn("setup finished with exit code 1", md)
        self.assertNotIn("AbCdEfGhIjKlMnOpQrStUvWx0123", md)
        self.assertIn("LOG.md", out.getvalue())
        shutil.rmtree(home, ignore_errors=True)

    def test_report_command_and_skill(self):
        import jev_tools_cli
        home = jev_tools_cli.home()
        shutil.rmtree(home, ignore_errors=True)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(jev_tools_cli.main(["report"]), 0)
        self.assertIn("LOG.md", out.getvalue())
        self.assertTrue((home / "LOG.md").is_file())
        shutil.rmtree(home, ignore_errors=True)
        skill = (HERE.parent / "skills" / "report" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: report", skill)
        self.assertTrue((HERE.parent / "skills" / "report" / ".." / ".." / "installer" / "jev_report.py").resolve().is_file())


class Check(unittest.TestCase):
    """`jev-tools-setup check`: read-only prerequisite report."""
    def setUp(self):
        import jev_tools_cli
        self.cli = jev_tools_cli

    def report(self, py="3.13", claude="/bin/claude", plugin="jev-tools 0.3.0"):
        def run_out(cmd, timeout=20):
            if "--version" in cmd:
                return 0, "2.1.0 (Claude Code)"
            if cmd[-2:] == ["plugin", "list"]:
                return 0, plugin
            if "nvidia-smi" in cmd[0]:
                return 1, ""
            return 0, py
        which = lambda n, path=None: {"python": "/bin/python", "claude": claude, "git": "/bin/git"}.get(n)
        with mock.patch.object(self.cli, "run_out", run_out), mock.patch.object(self.cli.shutil, "which", which), \
                mock.patch.object(self.cli.socket, "create_connection", return_value=mock.Mock()):
            return {name: (level, detail) for level, name, detail, _ in self.cli.checks()}

    def test_all_good(self):
        rows = self.report()
        self.assertNotIn("fail", [lvl for lvl, _ in rows.values()])
        self.assertEqual(rows["jev-tools plugin"][0], "ok")
        self.assertEqual(rows["GPU for local mode"][0], "info")  # absent GPU never blocks api/offline

    def test_old_python_fails(self):
        self.assertEqual(self.report(py="3.9")["python on PATH"][0], "fail")

    def test_missing_claude_fails_but_missing_git_only_warns(self):
        self.assertEqual(self.report(claude=None)["claude CLI"][0], "fail")
        with mock.patch.object(self.cli.shutil, "which", lambda n, path=None: None), \
                mock.patch.object(self.cli.socket, "create_connection", side_effect=OSError("down")):
            rows = {n: lvl for lvl, n, _, _ in self.cli.checks()}
        self.assertEqual((rows["git"], rows["network to api.codiv.ai"]), ("warn", "warn"))

    def test_plugin_not_installed_is_not_a_failure(self):
        self.assertIn("not installed", self.report(plugin="other-plugin")["jev-tools plugin"][1])

    def test_exit_code_and_hint(self):
        out = io.StringIO()
        fail = [("fail", "claude CLI", "not found", "install Claude Code")]
        with mock.patch.object(self.cli, "checks", return_value=fail), contextlib.redirect_stdout(out):
            self.assertEqual(self.cli.check(None), 1)
        self.assertIn("install Claude Code", out.getvalue())
        with mock.patch.object(self.cli, "checks", return_value=[("ok", "x", "y", "")]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cli.check(None), 0)

    def test_python_lookup_skips_the_tools_own_venv(self):
        venv_bin, system_bin = "/uvtool/venv/bin", "/usr/bin"
        seen = {}

        def which(name, path=None):
            seen["path"] = path
            return "/usr/bin/python"
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([venv_bin, system_bin])}),                 mock.patch.object(self.cli.sys, "prefix", "/uvtool/venv"), mock.patch.object(self.cli.sys, "base_prefix", "/usr"),                 mock.patch.object(self.cli.Path, "resolve", lambda self_: self_), mock.patch.object(self.cli.shutil, "which", which):
            self.assertEqual(self.cli.system_python(), "/usr/bin/python")
        self.assertEqual(seen["path"], system_bin)

    def test_jev_mode_env_is_flagged(self):
        with mock.patch.dict(os.environ, {"JEV_MODE": "off"}):
            rows = self.report()
        self.assertEqual(rows["JEV_MODE env var"][0], "warn")


class RuleEnforcer(unittest.TestCase):
    def setUp(self):
        self.proj = TMP / "proj"
        (self.proj / "src").mkdir(parents=True, exist_ok=True)
        (self.proj / "CLAUDE.md").write_text("# Rules\n- Never use console.log in source files\n- Always add type hints\n")

    def event(self, new, path="src/a.js", tool="Edit"):
        ti = {"file_path": str(self.proj / path), "old_string": "x()", "new_string": new}
        return json.dumps({"tool_name": tool, "tool_input": ti, "cwd": str(self.proj)})

    @staticmethod
    def judge(b):  # flags the console.log rule only when the diff contains console.log
        bad = "console.log" in b["state"]
        return {k: noul_a(0.93 if bad and "console.log" in q["instructions"] else 0.05)
                for k, q in b["questions"].items()}

    def test_denies_violation(self):
        reset(self.judge)
        out = json.loads(run("rule_enforcer.py", stdin=self.event("console.log(x())")).stdout)
        h = out["hookSpecificOutput"]
        self.assertEqual(h["permissionDecision"], "deny")
        self.assertIn("Never use console.log", h["permissionDecisionReason"])

    def test_second_look_can_veto(self):
        def judge(b):  # the wide check says violation, the strict confirmation says no
            return {k: noul_a(0.1 if k == "c" else 0.93) for k in b["questions"]}
        reset(judge)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())")).stdout, "")
        self.assertIn("c", Mock.calls[-1]["questions"])  # the confirmation was actually asked

    def test_allows_clean_edit_and_fails_open(self):
        reset(self.judge)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("x(1)")).stdout, "")
        reset(lambda b: 1 / 0)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())")).stdout, "")

    def test_secret_named_files_are_never_sent(self):
        reset(self.judge)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())", path=".env")).stdout, "")
        self.assertEqual(Mock.calls, [])

    def test_off_mode_makes_no_call(self):
        reset(self.judge)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())"), JEV_MODE="off").stdout, "")
        self.assertEqual(Mock.calls, [])

    def test_shadow_mode_and_skips(self):
        reset(self.judge)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())"), JEV_MODE="shadow").stdout, "")
        before = len(Mock.calls)
        self.assertEqual(run("rule_enforcer.py", stdin=self.event("console.log(x())", path="notes.md")).stdout, "")
        self.assertEqual(len(Mock.calls), before)  # docs are not checked, no API call


class ReviewPrecheck(unittest.TestCase):
    def test_routing(self):
        import review_precheck as rp
        pol = {"a": "A", "b": "B"}
        self.assertEqual(rp.route({"a": noul_a(0.02), "b": noul_a(0.1)}, pol)[0], "fast")
        self.assertEqual(rp.route({"a": noul_a(0.02), "b": noul_a(0.6)}, pol)[0], "full")
        self.assertEqual(rp.route(None, pol)[0], "full")  # Jev down -> full review
        self.assertEqual(rp.route({"a": noul_a(0.0)}, pol)[0], "full")  # missing answer
        self.assertEqual(rp.route({"a": noul_a(0.0), "b": noul_a(0.0)}, pol, truncated=True)[0], "full")

    def test_cli_on_real_diff(self):
        repo = TMP / "repo"
        repo.mkdir(exist_ok=True)
        g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        g("init", "-q")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "init")
        (repo / "f.py").write_text("x = 1\n")
        g("add", "f.py")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "f")
        (repo / "f.py").write_text("x = 2\n")
        reset(lambda b: {k: noul_a(0.01) for k in b["questions"]})
        r = run("review_precheck.py", cwd=repo)
        self.assertEqual((r.returncode, json.loads(r.stdout)["route"]), (0, "fast"))
        self.assertEqual(len(Mock.calls[0]["questions"]), 7)
        reset(lambda b: {k: noul_a(0.9 if k == "secrets" else 0.01) for k in b["questions"]})
        r = run("review_precheck.py", cwd=repo)
        self.assertEqual((r.returncode, json.loads(r.stdout)["route"]), (10, "full"))
        g("checkout", "--", "f.py")
        (repo / "README.md").write_text("docs\n")
        g("add", "-N", "README.md")
        reset(lambda b: 1 / 0)
        r = run("review_precheck.py", cwd=repo)
        self.assertEqual((r.returncode, json.loads(r.stdout)["note"], Mock.calls), (0, "docs only", []))


class Calibrate(unittest.TestCase):
    def test_verdicts(self):
        from rule_calibrate import verdict
        self.assertEqual(verdict([0.9] * 3), "skipped")                        # too few hunks
        self.assertEqual(verdict([0.95, 0.9, 0.85, 0.9, 0.2, 0.9]), "noisy")   # fires on most
        self.assertEqual(verdict([0.02, 0.1, 0.05, 0.0, 0.03]), "quiet")
        self.assertEqual(verdict([0.3, 0.55, 0.4, 0.6, 0.35]), "weak")
        self.assertEqual(verdict([0.02, 0.95, 0.03, 0.9, 0.05]), "decisive")


class FindFiles(unittest.TestCase):
    def setUp(self):
        self.root = TMP / "ff"
        self.root.mkdir(exist_ok=True)
        for i in range(45):
            (self.root / f"auth_{i}.py").write_text("def login(token):\n    return token\n")
        (self.root / "unrelated.py").write_text("print('hello')\n")

    def test_two_stage_ranking(self):
        def judge(b):  # "How relevant is file F3 ..." -> look the file up in the state
            return {k: score_a(3.8 if "auth_7.py" in b["state"]["files"][q["instructions"].split()[4]] else 0.8)
                    for k, q in b["questions"].items()}
        reset(judge)
        r = run("find_files.py", "login token handling", "--root", str(self.root), "--top", "3")
        first = r.stdout.splitlines()[0]
        self.assertIn("auth_7.py", first)
        self.assertEqual(first.split()[0], "95")
        # 45 candidates -> stage 1 in requests of 20 + 20 + 5, then the 10 best re-judged; unrelated.py never sent
        self.assertEqual(sorted(len(c["questions"]) for c in Mock.calls), [5, 10, 20, 20])

    def test_small_local_models_do_not_rank_files(self):
        home = Path(os.environ["HOME"]) / ".jev-tools"
        home.mkdir(parents=True, exist_ok=True)
        try:
            for model in ("verdict-1.4", "laya-1.0"):  # both scored below plain keywords on a labelled set, so neither is asked
                (home / "config.json").write_text(json.dumps({"backend": "local", "model": model}))
                reset(lambda b: {k: score_a(2.0) for k in b["questions"]})
                r = run("find_files.py", "login token handling", "--root", str(self.root), "--top", "2")
                self.assertEqual((r.returncode, len(r.stdout.splitlines()), Mock.calls), (0, 2, []), model)
                self.assertIn("no better than keywords", r.stderr)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_falls_back_to_keyword_order(self):
        reset(lambda b: 1 / 0)
        r = run("find_files.py", "login token handling", "--root", str(self.root), "--top", "2")
        self.assertEqual((r.returncode, len(r.stdout.splitlines())), (0, 2))
        self.assertIn("unavailable", r.stderr)


class PickNext(unittest.TestCase):
    ELS = [{"ref": "ref_1", "role": "link", "name": "Home"}, {"ref": "ref_2", "role": "textbox", "name": "Email"},
           {"ref": "ref_3", "role": "button", "name": "Admin"}]

    def ask(self, nxt, met=0.05, stuck=0.05, p=0.95):
        reset(lambda b: {"next": choice_a(nxt, p), "goal_met": noul_a(met), "stuck": noul_a(stuck)})
        r = run("pick_next.py", stdin=json.dumps({"goal": "open admin", "url": "/", "elements": self.ELS, "history": []}))
        return r.returncode, json.loads(r.stdout)

    def test_actions(self):
        self.assertEqual(self.ask("ref_3")[1]["action"], "click")
        self.assertEqual(self.ask("ref_2")[1]["action"], "type")
        self.assertEqual(self.ask("ref_3", met=0.9)[1], {"action": "done"})
        self.assertEqual(self.ask("none")[1], {"action": "blocked"})
        self.assertEqual(self.ask("none", met=0.6)[1], {"action": "done"})
        self.assertEqual(self.ask("ref_3", p=0.5)[1]["action"], "unsure")  # below the confidence floor
        self.assertEqual(self.ask("ref_3", stuck=0.9)[1], {"action": "blocked"})

    def test_error_when_jev_down(self):
        reset(lambda b: 1 / 0)
        r = run("pick_next.py", stdin=json.dumps({"goal": "g", "elements": self.ELS}))
        self.assertEqual((r.returncode, json.loads(r.stdout)["action"]), (1, "error"))


class SkillPicker(unittest.TestCase):
    def setUp(self):
        self.proj = TMP / "sp"
        d = self.proj / ".claude" / "skills" / "pdf-tool"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text("---\nname: pdf-tool\ndescription: Merge, split and rotate PDF files\n---\nbody\n")

    def prompt(self, text):
        return json.dumps({"prompt": text, "cwd": str(self.proj)})

    @staticmethod
    def picker(pick="pdf-tool", p=0.9, needed=0.9, right=0.9):
        return lambda b: ({"skill": choice_a(pick, p)} if "skill" in b["questions"]
                          else {"needed": noul_a(needed), "right": noul_a(right)})

    def test_opt_in_only(self):
        reset(self.picker())
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("please merge these two pdf files into one"),
                             JEV_SKILL_PICKER="0").stdout, "")
        self.assertEqual(Mock.calls, [])  # not opted in: the prompt is never sent

    def test_stage_two_can_veto(self):
        reset(self.picker(right=0.2))
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("please merge these two pdf files into one")).stdout, "")

    def test_injects_pick(self):
        reset(self.picker())
        out = json.loads(run("skill_picker.py", stdin=self.prompt("please merge these two pdf files into one")).stdout)
        self.assertIn("pdf-tool", out["hookSpecificOutput"]["additionalContext"])

    def test_silent_cases(self):
        reset(lambda b: {"skill": choice_a("none", 0.9)})
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("please merge these two pdf files into one")).stdout, "")
        reset(self.picker())
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("please merge these two pdf files into one"),
                             JEV_MODE="shadow").stdout, "")
        n = len(Mock.calls)
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("thanks")).stdout, "")
        self.assertEqual(run("skill_picker.py", stdin=self.prompt("something about weather forecasts today")).stdout, "")
        self.assertEqual(len(Mock.calls), n)  # short prompt / no shortlist -> no API call


if __name__ == "__main__":
    unittest.main(verbosity=1)
