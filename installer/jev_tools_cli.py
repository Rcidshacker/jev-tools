"""jev-tools installer: one command to install the Claude Code plugin and choose how Jev runs. Stdlib only.

    uv tool install jev-tools-setup     once (or: pipx install jev-tools-setup; no install: uvx jev-tools-setup)

    jev-tools-setup check        read-only: is this machine ready? (python, claude CLI, git, network, GPU, docker)
    jev-tools-setup              install the plugin and pick api / local / offline
    jev-tools-setup serve        run the small local model you chose (verdict-1.4 / laya-1.0) in the foreground
    jev-tools-setup report       write ~/.jev-tools/LOG.md: what happened, what is wrong, how to fix it
    jev-tools-setup uninstall    remove ~/.jev-tools (key, config, log); the plugin itself: /plugin uninstall

The plugin files (skills, scripts, hooks) are downloaded by the `claude` CLI from the GitHub marketplace, so terminal
and desktop share one install. This tool adds what the plugin cannot do for itself: the backend choice and the key.
Non-interactive flags exist for scripts and tests; the API key is only ever read from a hidden prompt or stdin, never argv.
"""
import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MARKET = "Rcidshacker/jev-tools"
PLUGIN = "jev-tools@jev-tools"
HOST = "api.codiv.ai"
LOCAL_URL = "http://127.0.0.1:8080"  # what OpenJev's docker compose listens on
LOOPBACK = ("localhost", "127.0.0.1", "::1")
SELF_HOST_DOCS = "https://codiv.ai/docs/guides/self-hosting"
OPENJEV_REPO = "https://github.com/razorback16/openjev"
# small encoder models: id -> (OpenJev extra / OPENJEV_BACKEND value, label, fp32 weight size estimate = params x 4 bytes)
SMALL = {"verdict-1.4": ("verdict", "Verdict 151M", "about 0.6 GB"), "laya-1.0": ("laya", "Laya 421M", "about 1.7 GB")}
SELF_HOST_CMD = "git clone https://github.com/razorback16/openjev && cd openjev && docker compose up -d"
OFFLINE_NOTE = ("offline means no model (not no internet). Pattern-based fallbacks still run: find-files ranks by keywords, "
                "review-precheck flags secrets/dependencies/auth/schema/test-weakening/swallowed errors (fast only for a small clean diff), "
                "the skill hook picks by keyword, the rule hook blocks only a literal token a 'never/avoid X' rule forbids, "
                "browser-nav gives an unsure keyword hint. rule-calibrate and any judgment that needs understanding are unavailable.")


def run_out(cmd, timeout=20):
    """(returncode, combined output) without ever raising. UTF-8 with replacement: Windows defaults to cp1252 and crashes on Claude's output."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def home():
    return Path.home() / ".jev-tools"


def note(event, **kw):
    """Append one line to the decision log that LOG.md is built from. Never raises, never takes secrets."""
    try:
        home().mkdir(exist_ok=True)
        with (home() / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(time.time()), "event": event, **kw}) + "\n")
    except OSError:
        pass


def lock_down(path):
    """Owner-only access. icacls on Windows, mode bits elsewhere."""
    if os.name == "nt":
        grant = f"{os.environ.get('USERNAME', '')}:" + ("F" if path.is_file() else "(OI)(CI)F")  # dirs hand it down to new files
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant], capture_output=True, check=False)
    else:
        os.chmod(path, 0o600 if path.is_file() else 0o700)


def save_key(key):
    d = home()
    d.mkdir(exist_ok=True)
    lock_down(d)
    p = d / "credentials"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # created owner-only, no window where it is readable
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key.strip() + "\n")
    lock_down(p)
    return p


def read_config():
    try:
        c = json.loads((home() / "config.json").read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def venv_python():
    return home() / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def save_config(**cfg):
    home().mkdir(exist_ok=True)
    p = home() / "config.json"
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return p


def probe(base, key, model="openjev-latest"):
    """One tiny System One call. Returns None on success or a short reason. Never follows redirects, never prints the key."""
    u = urllib.parse.urlsplit(base)
    if not (u.hostname in LOOPBACK or (u.hostname == HOST and u.scheme == "https")):
        return f"refusing to contact {u.hostname!r}: only {HOST} or loopback"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    body = json.dumps({"model": model, "state": "The build finished and all tests passed.",
                       "questions": {"ok": {"type": "noul", "instructions": "The text reports a successful outcome"}}}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "jev-tools/0.1"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with urllib.request.build_opener(NoRedirect).open(
                urllib.request.Request(base.rstrip("/") + "/v1/systemone", body, headers, method="POST"), timeout=20) as r:
            return None if "answers" in json.load(r) else "unexpected response"
    except urllib.error.HTTPError as e:
        return {401: "key rejected (401)", 403: "key rejected (403)", 429: "quota or rate limit (429)"}.get(e.code, f"HTTP {e.code}")
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:80]}"


def gpu():
    """(name, is_blackwell) from nvidia-smi, or (None, False). Blackwell = compute capability 10.x/12.x. A heuristic, not a promise."""
    if not shutil.which("nvidia-smi"):
        return None, False
    rc, text = run_out(["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader"])
    if rc or not text:
        return None, False
    name, _, cap = text.splitlines()[0].partition(",")
    try:
        return name.strip(), int(cap.strip().split(".")[0]) >= 10
    except ValueError:
        return name.strip(), False


def ask(prompt, options, default=None):
    while True:
        a = input(f"{prompt} [{'/'.join(options)}]{f' ({default})' if default else ''}: ").strip().lower() or default
        if a in options:
            return a
        print(f"  choose one of: {', '.join(options)}")


def install_plugin():
    claude = shutil.which("claude")
    if not claude:
        note("plugin_step", step="install", ok=False, msg="claude CLI not found")
        print("! `claude` CLI not found. Install Claude Code, then run inside it:\n"
              f"    /plugin marketplace add {MARKET}\n    /plugin install {PLUGIN}")
        return False
    for args in (["marketplace", "add", MARKET], ["install", PLUGIN]):
        rc, text = run_out([claude, "plugin", *args], timeout=180)
        # re-running setup must not fail just because the marketplace or plugin is already there
        if rc and "already" not in text.lower():
            print(f"! `claude plugin {' '.join(args)}` failed:\n{text[-400:]}")
            note("plugin_step", step=args[0], ok=False, msg=text[-200:])
            return False
        note("plugin_step", step=args[0], ok=True)
        print(f"  ok  claude plugin {args[0]}")
    return True


def choose_backend(a):
    if a.backend:
        return a.backend
    name, blackwell = gpu()
    print("\nHow should Jev run?\n"
          "  api      hosted OpenJev at api.codiv.ai (free tier, needs your key; sends text off-machine)\n"
          "  local    self-hosted OpenJev on this machine (needs an NVIDIA Blackwell-class GPU and Docker)\n"
          "  offline  no model: keyword and pattern fallbacks only, nothing is sent anywhere")
    if name:
        print(f"  detected GPU: {name} -> {'looks Blackwell-class' if blackwell else 'NOT Blackwell-class, so local will not run the model'}")
    else:
        print("  no NVIDIA GPU detected, so local will not work here")
    return ask("Backend", ("api", "local", "offline"), "api")


def choose_model(a):
    if a.model:
        return a.model
    print("\nWhich local model?\n"
          "  verdict-1.4    Verdict 151M: smallest, 512-token context, up to 24 options, ignores yes/no criteria. CPU or any GPU.\n"
          "  laya-1.0       Laya 421M: 1,024-token context, about 20 options, heavier. CPU or any GPU.\n"
          "  openjev-latest the full OpenJev model: needs an NVIDIA Blackwell-class GPU and Docker.\n"
          "  jev-tools trims long diffs to fit the small models and starts them in shadow mode. They are unmeasured with its thresholds.")
    return ask("Model", ("verdict-1.4", "laya-1.0", "openjev-latest"))


def install_small(model, yes):
    """Clone OpenJev, make a venv, install the model's extra. Streams pip output. True when everything succeeded."""
    extra, label, size = SMALL[model]
    repo, venv = home() / "openjev", home() / "venv"
    print(f"\n{label} runs on the CPU or any GPU. Setup will:\n  1. git clone {OPENJEV_REPO} -> {repo}\n"
          f"  2. create a Python venv -> {venv}\n  3. pip install openjev[{extra}]  (brings PyTorch: can be several GB)\n"
          f"The model weights ({size} as fp32) download from Hugging Face the first time the server starts.")
    if not yes and input("Proceed? [y/N]: ").strip().lower() != "y":
        print("  skipped: nothing was changed")
        return False
    if not shutil.which("git"):
        print("! git not found: install git, then re-run setup")
        return False
    steps = []
    if not repo.exists():
        steps.append(["git", "clone", "--depth", "1", OPENJEV_REPO, str(repo)])
    if not venv_python().exists():
        steps.append([sys.executable, "-m", "venv", str(venv)])
    steps.append([str(venv_python()), "-m", "pip", "install", "-e", f"{repo}[{extra}]"])
    for cmd in steps:
        print(f"  $ {' '.join(cmd)}")
        if subprocess.call(cmd):
            print("! that step failed; fix the error above and re-run setup (finished steps are skipped)")
            return False
    return True


def serve(a):
    """Run the small local model in the foreground. Leave it open while you use Claude Code."""
    cfg = read_config()
    model = cfg.get("model")
    if cfg.get("backend") != "local" or model not in SMALL or not venv_python().exists():
        print("! nothing to serve: run `jev-tools-setup`, choose local, and pick verdict-1.4 or laya-1.0")
        return 1
    url = urllib.parse.urlsplit(cfg.get("base_url") or LOCAL_URL)
    env = {**os.environ, "OPENJEV_BACKEND": SMALL[model][0], "OPENJEV_PORT": str(url.port or 8080), "OPENJEV_HOST": url.hostname or "127.0.0.1"}
    if a.device:
        env["OPENJEV_DEVICE"] = a.device
    note("serve_start", model=model, url=url.geturl())
    print(f"serving {model} on {url.geturl()}  (Ctrl-C stops it; first start downloads the weights)")
    try:
        return subprocess.call([str(venv_python()), "-m", "openjev"], env=env)
    except KeyboardInterrupt:
        return 0


def setup(a):
    """Run setup, then always write LOG.md so a failed attempt leaves something to read and attach."""
    note("setup_start", backend=a.backend)
    rc = 1
    try:
        rc = _setup(a)
        return rc
    finally:
        note("setup_end", rc=rc)
        report(None, quiet=True)
        print(f"\nWhat happened is written to {home() / 'LOG.md'}  (attach it if you report a problem; `jev-tools-setup report` refreshes it)")


def _setup(a):
    print("jev-tools setup")
    if not a.skip_plugin:
        print("\n1. Installing the plugin (skills, scripts, hooks) with the claude CLI")
        install_plugin()
    kind = choose_backend(a)
    cfg = {"backend": kind}
    if kind == "api":
        print(f"\nGet a key at https://codiv.ai/dashboard (starts with sk-codiv-). It is stored only in {home() / 'credentials'}, owner-only.")
        key = (sys.stdin.readline() if a.key_stdin else getpass.getpass("Paste your key (hidden): ")).strip()
        if not key:
            print("! no key given: choose offline, or re-run setup")
            return 1
        err = probe(os.environ.get("OPENJEV_BASE_URL") or f"https://{HOST}", key)
        if err:
            note("probe_failed", err=err)
            print(f"! the key did not work: {err}\n  nothing was saved.")
            return 1
        print(f"  ok  key works, saved to {save_key(key)}")
        note("key_saved")
    elif kind == "local":
        model = choose_model(a)
        cfg["model"], cfg["base_url"] = model, a.base_url or LOCAL_URL
        if model in SMALL:
            ok = install_small(model, a.yes)
            note("local_install", model=model, ok=ok)
            if not ok:
                return 1
            print(f"\n  ok  installed. Start the server in its own terminal and keep it open:\n        jev-tools-setup serve")
        else:
            name, blackwell = gpu()
            if not blackwell:
                print(f"! The full OpenJev model needs an NVIDIA Blackwell-class GPU (NVFP4); {'found ' + name if name else 'none found'}.\n"
                      f"  Pick verdict-1.4 or laya-1.0 instead (they run on CPU), or api / offline. Details: {SELF_HOST_DOCS}")
                return 1
            if not shutil.which("docker"):
                print(f"! Docker not found. Install it, then: {SELF_HOST_CMD}\n  Guide: {SELF_HOST_DOCS}")
                return 1
            print(f"\nStart the server if it is not running:\n  {SELF_HOST_CMD}\nChecking {cfg['base_url']} ...")
            err = probe(cfg["base_url"], None, model)
            print("  ok  server answers" if not err else f"! not answering yet ({err}). Config is saved; start the server, then run the `status` skill.")
    else:
        print(f"\n{OFFLINE_NOTE}")
    if cfg.get("model") in SMALL and a.mode == "active":
        print("! small models are unmeasured with jev-tools' thresholds: run the rule-calibrate skill in shadow mode before trusting active.")
    cfg["mode"] = a.mode or ("shadow" if a.backend else ask("\nMode (shadow = log only, active = block/inject, off = nothing)", ("shadow", "active", "off"), "shadow"))
    print(f"\nconfig saved to {save_config(**cfg)}  (mode: {cfg['mode']}; shadow only logs and never blocks)")
    note("config_saved", backend=cfg["backend"], model=cfg.get("model"), mode=cfg["mode"])
    print("The skill-pick hook stays OFF unless you enable it: it sends every prompt you type to the API.")
    print("\nDone. Restart Claude Code (terminal or desktop), then run the `status` skill to confirm.")
    return 0


def report(a, quiet=False):
    """Write ~/.jev-tools/LOG.md from the decision logs."""
    import jev_report
    out = home() / "LOG.md"
    text, level = jev_report.build()
    home().mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if not quiet:
        print(f"wrote {out}  [{ {'ok': 'healthy', 'warn': 'notes to read', 'error': 'PROBLEMS found'}[level] }]")
    return 0


def uninstall(_):
    shutil.rmtree(home(), ignore_errors=True)
    print(f"removed {home()}. To remove the plugin: /plugin uninstall {PLUGIN}")
    return 0


def system_python():
    """The `python` the hooks will get. Under uvx/pipx the tool's own venv is first on PATH, so skip it."""
    dirs = os.environ.get("PATH", "").split(os.pathsep)
    if sys.prefix != sys.base_prefix:
        own = str(Path(sys.prefix).resolve())
        dirs = [d for d in dirs if d and not str(Path(d).resolve()).startswith(own)]
    return shutil.which("python", path=os.pathsep.join(dirs))


def checks():
    """Read-only prerequisite report: list of (level, name, detail, hint), level in ok|warn|fail|info. Sends and changes nothing."""
    out = []
    add = lambda level, name, detail, hint="": out.append((level, name, detail, hint))
    # the hooks run the literal command `python`, so it must resolve to 3.10+ (on Windows the Store stub resolves but does not run)
    py = system_python()
    rc, ver = run_out([py, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"]) if py else (1, "")
    try:
        ok = rc == 0 and tuple(int(x) for x in ver.split(".")) >= (3, 10)
    except ValueError:
        ok = False
    if ok:
        add("ok", "python on PATH", f"{ver} ({py})")
    else:
        add("fail", "python on PATH", f"{'found ' + py + ' but it does not run 3.10+' if py else 'not found'}",
            "install Python 3.10+ and make sure the command `python` works (the hooks call exactly that)")
    claude = shutil.which("claude")
    if not claude:
        add("fail", "claude CLI", "not found", "install Claude Code, or install the plugin by hand with /plugin inside it")
    else:
        rc, ver = run_out([claude, "--version"])
        add("ok" if rc == 0 else "fail", "claude CLI", ver.splitlines()[0] if ver else claude, "" if rc == 0 else "reinstall Claude Code")
        rc, listing = run_out([claude, "plugin", "list"])
        if rc:
            add("warn", "claude plugin", "`claude plugin` is not available", "update Claude Code, or use /plugin inside it")
        else:
            add("ok", "jev-tools plugin", "installed" if "jev-tools" in listing else "not installed yet (setup installs it)")
    add("ok" if shutil.which("git") else "warn", "git", shutil.which("git") or "not found",
        "" if shutil.which("git") else "review-precheck and rule-calibrate read git history; the other pieces work without it")
    try:
        socket.create_connection((HOST, 443), timeout=5).close()
        add("ok", f"network to {HOST}", "reachable")
    except OSError as e:
        add("warn", f"network to {HOST}", str(e)[:60], "only the api backend needs it")
    name, blackwell = gpu()
    add("ok" if blackwell else "info", "GPU for local mode",
        f"{name} (Blackwell-class)" if blackwell else f"{name} (not Blackwell-class: use api or offline)" if name else "no NVIDIA GPU: use api or offline")
    add("ok" if shutil.which("docker") else "info", "docker for local mode", shutil.which("docker") or "not found (only needed for local)")
    saved = read_config()
    if saved.get("backend") == "local":
        err = probe(saved.get("base_url") or LOCAL_URL, None, saved.get("model") or "openjev-latest")  # a Verdict-only server rejects other model names
        add("ok" if not err else "warn", "local server", f"{saved.get('model')} at {saved.get('base_url')}" + ("" if not err else f": {err}"),
            "" if not err else "start it with `jev-tools-setup serve` (small models) or docker compose (full model)")
    cfg = home() / "config.json"
    add("info", "setup state", f"config {'present' if cfg.exists() else 'absent'}, key file {'present' if (home() / 'credentials').exists() else 'absent'}, "
        f"env key {'set' if os.environ.get('OPENJEV_API_KEY') or os.environ.get('TYPESAFE_API_KEY') else 'unset'}")
    if os.environ.get("JEV_MODE"):
        add("warn", "JEV_MODE env var", f"set to {os.environ['JEV_MODE']!r}", "it overrides the mode saved by setup; unset it to use the saved mode")
    return out


def check(_):
    rows = checks()
    tag = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}
    for level, name, detail, hint in rows:
        print(f"{tag[level]} {name:<22} {detail}" + (f"\n         -> {hint}" if hint and level in ("warn", "fail") else ""))
    bad = sum(r[0] == "fail" for r in rows)
    print(f"\n{'Ready to run: jev-tools-setup' if not bad else str(bad) + ' required check(s) failed: fix them, then run check again'}"
          f" ({sum(r[0] == 'warn' for r in rows)} warning(s))")
    return 1 if bad else 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):  # keep our lines in order with pip's streamed output when stdout is a file or pipe
        sys.stdout.reconfigure(line_buffering=True)
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("setup", "check", "serve", "report", "uninstall", "-h", "--help"):
        argv.insert(0, "setup")  # bare `jev-tools-setup` means setup
    ap = argparse.ArgumentParser(prog="jev-tools-setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="install the plugin and configure the backend")
    s.add_argument("--backend", choices=("api", "local", "offline"), help="skip the backend question")
    s.add_argument("--mode", choices=("shadow", "active", "off"))
    s.add_argument("--base-url", help="local server URL (default %s)" % LOCAL_URL)
    s.add_argument("--model", choices=("verdict-1.4", "laya-1.0", "openjev-latest"), help="local model, skips the question")
    s.add_argument("--yes", action="store_true", help="do not ask before downloading/installing the local model")
    s.add_argument("--key-stdin", action="store_true", help="read the API key from one line of stdin")
    s.add_argument("--skip-plugin", action="store_true", help="do not call the claude CLI")
    s.set_defaults(fn=setup)
    sv = sub.add_parser("serve", help="run the local small model (verdict-1.4 or laya-1.0) in the foreground")
    sv.add_argument("--device", choices=("cpu", "cuda"), help="force the device (default: GPU if PyTorch sees one)")
    sv.set_defaults(fn=serve)
    sub.add_parser("report", help="write ~/.jev-tools/LOG.md: what happened and what is wrong").set_defaults(fn=report)
    sub.add_parser("check", help="read-only check of everything setup needs").set_defaults(fn=check)
    sub.add_parser("uninstall", help="remove ~/.jev-tools").set_defaults(fn=uninstall)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
