import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import uvicorn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bridge.account_manager import AccountManager
from bridge.antigravity_client import AntigravityClient
from bridge.config import DATA_DIR, DEFAULT_HOST, DEFAULT_PORT, KNOWN_MODELS, resolve_model
from bridge.quota_router import QuotaRouter

PID_FILE = DATA_DIR / "bridge.pid"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("antigravity-bridge.cli")


def get_saved_server_info():
    """Retrieve saved PID and port from PID_FILE if present."""
    if PID_FILE.exists():
        try:
            content = PID_FILE.read_text(encoding="utf-8").strip()
            if ":" in content:
                parts = content.split(":", 1)
                return int(parts[0]), int(parts[1])
            return int(content), DEFAULT_PORT
        except Exception:
            pass
    return None, DEFAULT_PORT


def is_server_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if the bridge server is responding to socket connection or health checks."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        pass

    try:
        url = f"http://{host}:{port}/api/accounts"
        req = urllib.request.Request(url, headers={"User-Agent": "apx-cli"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def cmd_run(args):
    """Run the bridge server in the foreground."""
    host = getattr(args, "host", None) or DEFAULT_HOST
    port = getattr(args, "port", None) or DEFAULT_PORT

    # Save current PID and Port
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(f"{os.getpid()}:{port}", encoding="utf-8")

    print(f"\n========================================================")
    print(f"  Antigravity Multi-Account Bridge")
    print(f"========================================================")
    print(f"  Web Dashboard:      http://{host}:{port}/")
    print(f"  OpenAI Base URL:    http://{host}:{port}/v1")
    print(f"  Anthropic Base URL: http://{host}:{port}")
    print(f"  Process PID:        {os.getpid()}")
    print(f"========================================================\n")
    print("Press Ctrl+C to stop.\n")

    try:
        uvicorn.run("bridge.server:app", host=host, port=port, log_level="info")
    finally:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except Exception:
                pass


def cmd_start(args):
    """Start the bridge server (foreground or background)."""
    host = getattr(args, "host", None) or DEFAULT_HOST
    port = getattr(args, "port", None) or DEFAULT_PORT
    detach = getattr(args, "detach", False)

    if is_server_running(host, port):
        print(f"\n[INFO] Antigravity Bridge is already running on http://{host}:{port}/")
        print(f"Dashboard: http://{host}:{port}/\n")
        return

    if detach:
        bridge_script = Path(__file__).resolve()
        # Use direct pythoncore if available to avoid WindowsApps detached process DLL issues
        python_exe = sys.executable
        if "WindowsApps" in python_exe or not python_exe:
            cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Python" / "pythoncore-3.14-64" / "python.exe"
            if cand.exists():
                python_exe = str(cand)
            else:
                cand2 = Path(os.environ.get("LOCALAPPDATA", "")) / "Python" / "bin" / "python.exe"
                if cand2.exists():
                    python_exe = str(cand2)

        log_path = DATA_DIR / "bridge.log"

        project_root = Path(__file__).resolve().parent.parent
        bridge_py = project_root / "bridge.py"

        if bridge_py.is_file():
            cmd_args = [python_exe, str(bridge_py), "run", "--host", host, "--port", str(port)]
            cmd_str = f'"{python_exe}" "{bridge_py}" run --host {host} --port {port}'
            spawn_cwd = str(project_root)
        else:
            cmd_args = [python_exe, "-m", "bridge", "run", "--host", host, "--port", str(port)]
            cmd_str = f'"{python_exe}" -m bridge run --host {host} --port {port}'
            spawn_cwd = str(Path.home())

        if sys.platform == "win32":
            # On Windows, spawn via WMI to cleanly break away from any console or Job Object
            ps_script = (
                f"$res = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                f"-Arguments @{{CommandLine = '{cmd_str}'}}; $res.ProcessId"
            )
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    text=True,
                    cwd=spawn_cwd,
                ).strip()
                pid = int(out.split()[-1])
            except Exception as e:
                logger.debug("WMI spawn fallback: %s", e)
                with open(log_path, "a", encoding="utf-8") as out_f:
                    proc = subprocess.Popen(
                        cmd_args,
                        stdin=subprocess.DEVNULL,
                        stdout=out_f,
                        stderr=out_f,
                        cwd=spawn_cwd,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                        close_fds=False,
                    )
                    pid = proc.pid
        else:
            with open(log_path, "a", encoding="utf-8") as out_f:
                proc = subprocess.Popen(
                    cmd_args,
                    stdin=subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=out_f,
                    cwd=spawn_cwd,
                    start_new_session=True,
                )
                pid = proc.pid

        PID_FILE.write_text(f"{pid}:{port}", encoding="utf-8")
        print(f"\n[OK] Started Antigravity Bridge in background (PID: {pid})")
        print(f"Port:      {port}")
        print(f"Dashboard: http://{host}:{port}/")
        print(f"Log file:  {log_path}")
        print("Run 'apx status' to check status, or 'apx stop' to terminate.\n")
    else:
        cmd_run(args)


def cmd_stop(args):
    """Stop running bridge server."""
    stopped = False
    saved_pid, saved_port = get_saved_server_info()
    if saved_pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(saved_pid)], capture_output=True)
            else:
                os.kill(saved_pid, 15)
            stopped = True
            print(f"[OK] Stopped Antigravity Bridge process (PID: {saved_pid}).")
        except Exception as e:
            logger.debug("Could not kill via pid file: %s", e)
        finally:
            PID_FILE.unlink(missing_ok=True)

    port = getattr(args, "port", None) or saved_port or DEFAULT_PORT
    if is_server_running(DEFAULT_HOST, port):
        # On Windows find process on port and kill
        if sys.platform == "win32":
            try:
                cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
                out = subprocess.check_output(["powershell", "-Command", cmd], text=True).strip()
                pids = set(out.split())
                for p in pids:
                    subprocess.run(["taskkill", "/F", "/PID", p], capture_output=True)
                stopped = True
                print(f"[OK] Stopped process on port {port}.")
            except Exception:
                pass

    if not stopped:
        print("[INFO] No running Antigravity Bridge server found.")


def cmd_status(args):
    """Check whether the bridge is currently running."""
    host = getattr(args, "host", None) or DEFAULT_HOST
    saved_pid, saved_port = get_saved_server_info()
    port = getattr(args, "port", None)
    # Check explicitly passed port, or saved port, or default port
    check_port = port or saved_port or DEFAULT_PORT

    if is_server_running(host, check_port):
        mgr = AccountManager()
        accs = mgr.list_accounts()
        print(f"\n[ONLINE] Antigravity Bridge is RUNNING on http://{host}:{check_port}/")
        if saved_pid:
            print(f"Process PID:        {saved_pid}")
        print(f"Active Accounts:    {len(accs)}")
        print(f"OpenAI Endpoint:    http://{host}:{check_port}/v1/chat/completions")
        print(f"Anthropic Endpoint: http://{host}:{check_port}/v1/messages")
        print(f"Web Dashboard:      http://{host}:{check_port}/\n")
    else:
        print(f"\n[OFFLINE] Antigravity Bridge is NOT running on port {check_port}.")
        print("Run 'apx start' or 'bridge start' to launch it.\n")


def cmd_accounts(args):
    """List all accounts and quota statuses."""
    mgr = AccountManager()
    accs = mgr.list_accounts()
    if not accs:
        print("No accounts found. Use 'apx add' or 'apx import' to add one.")
        return

    print(f"\nFound {len(accs)} configured Google Account(s):\n")
    print(f"{'Email':<35} {'Status':<12} {'Tier':<18} {'Gemini Quota':<14} {'3P Quota':<12}")
    print("-" * 95)

    client = AntigravityClient()
    router = QuotaRouter(mgr, client)

    for acc in accs:
        g_frac, _ = router.get_account_quota_fraction(acc, "gemini")
        p3_frac, _ = router.get_account_quota_fraction(acc, "3p")
        g_str = f"{int(g_frac * 100)}%"
        p3_str = f"{int(p3_frac * 100)}%"
        print(f"{acc.email:<35} {acc.status:<12} {acc.tier:<18} {g_str:<14} {p3_str:<12}")
    print()


def cmd_import_local(args):
    """Import local Windows Credential Manager account."""
    mgr = AccountManager()
    acc = mgr.auto_import_local_account()
    if acc:
        print(f"[OK] Successfully imported local Antigravity account: {acc.email}")
    else:
        print("[ERROR] Could not find local Antigravity credentials in Windows Credential Manager.")


def cmd_add_account(args):
    """Start local webserver or open browser to add a new account."""
    port = getattr(args, "port", None) or DEFAULT_PORT
    login_url = f"http://127.0.0.1:{port}/auth/login"
    print(f"\nOpening browser for Google Account authentication: {login_url}")
    print("If your browser doesn't open automatically, please visit the URL above.")
    print("Make sure the bridge server is running ('apx start').\n")
    webbrowser.open(login_url)


def cmd_test(args):
    """Run an end-to-end test prompt."""
    async def _test():
        mgr = AccountManager()
        client = AntigravityClient()
        router = QuotaRouter(mgr, client)

        model = getattr(args, "model", None) or "gemini-3.8-flash-high"
        prompt = getattr(args, "prompt", None) or "Explain quantum computing in 10 words."

        print(f"\nSending test prompt to model '{model}':")
        print(f"Prompt: {prompt}\n")
        print("Response: ", end="", flush=True)

        try:
            async for chunk in router.stream_with_failover(
                model=model,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
            ):
                candidates = chunk.get("response", {}).get("candidates", [])
                for c in candidates:
                    for p in c.get("content", {}).get("parts", []):
                        text = p.get("text")
                        if text:
                            print(text, end="", flush=True)
            print("\n\n[SUCCESS] Test completed successfully!")
        except Exception as e:
            print(f"\n\n[ERROR] Test failed: {e}")

    asyncio.run(_test())


def cmd_setup(args):
    """Auto-configure agents (Claude Code, Hermes, Aider, Windows Env) to use the bridge."""
    from bridge.setup_manager import SetupManager
    _, saved_port = get_saved_server_info()
    port = getattr(args, "port", None) or saved_port or DEFAULT_PORT
    mgr = SetupManager(port=port)

    if getattr(args, "revert", False):
        target = getattr(args, "target", "all") or "all"
        print(f"\n[REVERT] Reverting configuration for: {target}...")
        if target == "all":
            res = mgr.revert_all()
        elif target == "claude":
            res = mgr.revert_claude()
        elif target == "hermes":
            res = mgr.revert_hermes()
        elif target == "aider":
            res = mgr.revert_aider()
        elif target == "cursor":
            res = mgr.revert_cursor()
        elif target in ("env", "system"):
            res = mgr.revert_env()
        print(json.dumps(res, indent=2))
        print("[OK] Revert complete.\n")
        return

    target = getattr(args, "target", "all") or "all"
    model = getattr(args, "model", None)
    print(f"\n========================================================")
    print(f"  Antigravity Agent Auto-Setup (Target: {target})")
    print(f"  Bridge URL: http://127.0.0.1:{port}")
    if model:
        print(f"  Target Model: {model}")
    print(f"========================================================")

    if target == "all":
        res = mgr.configure_all(model=model)
    elif target == "claude":
        res = {"claude": mgr.configure_claude(model=model)}
    elif target == "hermes":
        res = {"hermes": mgr.configure_hermes(model=model)}
    elif target == "aider":
        res = {"aider": mgr.configure_aider(model=model)}
    elif target == "cursor":
        res = {"cursor": mgr.configure_cursor(model=model)}
    elif target in ("env", "system"):
        res = {"env": mgr.configure_env()}
    else:
        print(f"[ERROR] Unknown target '{target}'. Available: all, claude, hermes, aider, cursor, env")
        return

    print("\nResults:")
    for k, v in res.items():
        st = v.get("status", "ok")
        print(f"  ✓ {k:<10}: {st.upper()}")
        if "model" in v:
            print(f"    Model: {v['model']}")
        if "path" in v:
            print(f"    File:  {v['path']}")
        if "paths" in v:
            for p in v["paths"]:
                print(f"    File:  {p}")
        if "base_url" in v:
            print(f"    URL:   {v['base_url']}")
        if "variables" in v:
            for var_k, var_v in v["variables"].items():
                print(f"    Env:   {var_k}={var_v}")

    print("\n[SUCCESS] Configured! Your agents can now run immediately without manual exports:")
    print("  - Claude Code:  claude")
    print("  - Hermes:       hermes chat")
    print("  - Aider:        aider\n")
    if target in ("claude", "all"):
        print("💡 Note: In Claude Code, you can also switch models at any time with '/model':")
        print("   /model haiku      -> Gemini 3.8 Flash (native, clean)")
        print("   /model sonnet     -> Claude Sonnet 4.6")
        print("   /model opus       -> Claude Opus 4.6 Thinking")
        print("   /model gemini-pro -> Gemini 3.1 Pro\n")


def cmd_model(args):
    """View or switch active model for an agent."""
    from bridge.setup_manager import SetupManager
    _, saved_port = get_saved_server_info()
    port = getattr(args, "port", None) or saved_port or DEFAULT_PORT
    mgr = SetupManager(port=port)

    agent = getattr(args, "agent", None)
    model_name = getattr(args, "model_name", None)

    # Support shorthand: 'apx model gemini' -> switches claude to gemini
    if agent and not model_name and agent in ("gemini", "sonnet", "opus", "gemini-pro", "flash", "pro", "haiku"):
        model_name = agent
        agent = "claude"

    if not agent and not model_name:
        detected = mgr.detect_agents()
        print("\n========================================================")
        print("  Antigravity Bridge: Active Agent Models")
        print("========================================================")
        for name, info in detected.items():
            if name == "env":
                continue
            cur_model = info.get("current_model") or "Not configured"
            status = "✓ Configured" if info.get("configured") else ("Detected" if info.get("detected") else "Not found")
            print(f"  {info['name']:<20}: {cur_model:<25} ({status})")

        print("\nQuick Model Switch Commands:")
        print("  apx model claude gemini       -> Switch Claude Code to Gemini 3.8 Flash")
        print("  apx model claude gemini-pro   -> Switch Claude Code to Gemini 3.1 Pro")
        print("  apx model claude sonnet       -> Switch Claude Code to Claude Sonnet 4.6")
        print("  apx model claude opus         -> Switch Claude Code to Claude Opus 4.6")
        print("  apx model cursor gemini       -> Switch Cursor to Gemini 3.8 Flash")
        print("  apx model hermes gemini       -> Switch Hermes to Gemini 3.8 Flash")
        print("\nInside Claude Code, you can also use /model anytime:")
        print("  /model haiku        -> Uses Gemini 3.8 Flash (native, clean)")
        print("  /model sonnet       -> Uses Claude Sonnet 4.6")
        print("  /model opus         -> Uses Claude Opus 4.6 Thinking")
        print("  /model gemini       -> Uses Gemini 3.8 Flash directly\n")
        return

    if not agent:
        agent = "claude"

    if not model_name:
        detected = mgr.detect_agents()
        info = detected.get(agent, {})
        cur_model = info.get("current_model", "gemini-3.8-flash-high")
        print(f"\n{agent.capitalize()} is currently configured to use: {cur_model}")
        print(f"To change it: apx model {agent} <model_name>")
        print("Available models: gemini, gemini-pro, sonnet, opus\n")
        return

    print(f"\nConfiguring {agent} model -> {model_name}...")
    if agent == "claude":
        res = mgr.configure_claude(model=model_name)
    elif agent == "cursor":
        res = mgr.configure_cursor(model=model_name)
    elif agent == "hermes":
        res = mgr.configure_hermes(model=model_name)
    elif agent == "aider":
        res = mgr.configure_aider(model=model_name)
    else:
        print(f"[ERROR] Unknown agent: {agent}")
        return

    print(f"[OK] Successfully configured {agent.capitalize()} with model: {res.get('model', model_name)}")
    if agent == "claude":
        print("💡 Note: You can also switch models at any time inside Claude Code with:")
        print("   /model haiku      (Gemini 3.8 Flash)")
        print("   /model sonnet     (Claude Sonnet 4.6)")
        print("   /model opus       (Claude Opus 4.6 Thinking)")
        print("   /model gemini-pro (Gemini 3.1 Pro)\n")


def cmd_restart(args):
    """Restart running bridge server."""
    print("\n[RESTART] Restarting Antigravity Bridge...")
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_logs(args):
    """View, tail, or clear bridge server logs."""
    from bridge.log_manager import LOG_FILE, clear_logs

    if getattr(args, "clear", False):
        if clear_logs():
            print("\n[OK] Antigravity Bridge logs cleared.\n")
        else:
            print("\n[ERROR] Failed to clear logs.\n")
        return

    if not LOG_FILE.exists():
        print(f"\n[INFO] No log file found at {LOG_FILE}\n")
        return

    lines_count = getattr(args, "lines", 50) or 50
    follow = getattr(args, "follow", False)

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            for line in all_lines[-lines_count:]:
                print(line, end="")

            if not follow:
                return

            print(f"\n--- Following live logs from {LOG_FILE} (Ctrl+C to exit) ---\n")
            while True:
                line = f.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n\nStopped tailing logs.\n")


def main():
    parser = argparse.ArgumentParser(
        prog="apx",
        description="Antigravity Multi-Account Bridge CLI (start server, manage accounts, test models)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start
    start_parser = subparsers.add_parser("start", help="Start the bridge server")
    start_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    start_parser.add_argument("-d", "--detach", action="store_true", help="Run server in the background (detached)")

    # run (alias for start in foreground)
    run_parser = subparsers.add_parser("run", help="Run server in foreground")
    run_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    run_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop running bridge server")
    stop_parser.add_argument("--port", type=int, default=None, help="Port of running server (defaults to saved active port)")

    # status
    status_parser = subparsers.add_parser("status", help="Check server running status")
    status_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to check")
    status_parser.add_argument("--port", type=int, default=None, help="Port to check (defaults to saved active port)")

    # accounts / list
    subparsers.add_parser("accounts", help="List all accounts and quota statuses")
    subparsers.add_parser("list", help="Alias for accounts")

    # import-local / import
    subparsers.add_parser("import-local", help="Import credentials from local Antigravity runtime")
    subparsers.add_parser("import", help="Alias for import-local")

    # add-account / add
    add_parser = subparsers.add_parser("add-account", help="Authenticate a new Google account")
    add_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bridge server port")
    add_alias = subparsers.add_parser("add", help="Alias for add-account")
    add_alias.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bridge server port")

    # setup
    setup_parser = subparsers.add_parser("setup", help="Auto-configure Claude Code, Hermes, Aider, Cursor & Environment")
    setup_parser.add_argument("target", nargs="?", default="all", choices=["all", "claude", "hermes", "aider", "cursor", "env"], help="Target agent to configure (default: all)")
    setup_parser.add_argument("--model", "-m", default=None, help="Model to configure for the agent (e.g. gemini, sonnet, opus, gemini-pro)")
    setup_parser.add_argument("--port", type=int, default=None, help="Bridge server port to target")
    setup_parser.add_argument("--revert", action="store_true", help="Revert configurations from backup")

    # model
    model_parser = subparsers.add_parser("model", help="View or switch active model for an agent (e.g. 'apx model claude gemini')")
    model_parser.add_argument("agent", nargs="?", default=None, help="Agent to configure (claude, cursor, hermes, aider) or model alias")
    model_parser.add_argument("model_name", nargs="?", default=None, help="Model name or alias to switch to (e.g. gemini, sonnet, opus, gemini-pro)")
    model_parser.add_argument("--port", type=int, default=None, help="Bridge server port to target")

    # test
    test_parser = subparsers.add_parser("test", help="Send a test prompt")
    test_parser.add_argument("--model", default="gemini-3.8-flash-high", help="Model to test")
    test_parser.add_argument("--prompt", default="Explain quantum computing in 10 words.", help="Prompt text")

    # restart
    restart_parser = subparsers.add_parser("restart", help="Restart running bridge server")
    restart_parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    restart_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind to")
    restart_parser.add_argument("-d", "--detach", action="store_true", help="Run server in background (detached)")

    # logs
    logs_parser = subparsers.add_parser("logs", help="View or tail bridge logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow / stream logs in real time (tail -f)")
    logs_parser.add_argument("-n", "--lines", type=int, default=50, help="Number of lines to show (default: 50)")
    logs_parser.add_argument("--clear", action="store_true", help="Clear the bridge log file")

    args = parser.parse_args()

    if args.command in ("start",):
        cmd_start(args)
    elif args.command in ("restart",):
        cmd_restart(args)
    elif args.command in ("run",):
        cmd_run(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "logs":
        cmd_logs(args)
    elif args.command in ("accounts", "list"):
        cmd_accounts(args)
    elif args.command in ("import-local", "import"):
        cmd_import_local(args)
    elif args.command in ("add-account", "add"):
        cmd_add_account(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "model":
        cmd_model(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
