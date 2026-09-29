"""Offline checks against a local mock of /v1/systemone. Run: python test_all.py
The mock proves the logic and wire shape, not OpenJev's accuracy; run `python jevlib.py` for a live smoke test."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="jevtest-"))


class Mock(BaseHTTPRequestHandler):
    responder = None
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.calls.append(body)
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
