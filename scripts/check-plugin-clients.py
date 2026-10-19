#!/usr/bin/env python3
"""Install and inspect plugins with real CLIs using disposable client settings.

Requires codex and claude on PATH. Does not invoke a model, run installed hooks,
connect MCP services, or modify the user's installed plugins.
"""

import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def run(command, root, env):
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"{' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def codex_inventory(root, env):
    process = subprocess.Popen(
        ["codex", "app-server"], cwd=root, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b""

    def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode())
        process.stdin.flush()

    def reply(request_id):
        nonlocal buffer
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                message = json.loads(line)
                if message.get("id") == request_id:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message["result"]
            if selector.select(timeout=1):
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("Codex app-server exited before replying")
                buffer += chunk
        raise TimeoutError("Codex app-server did not reply")

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "plugin-compatibility-check", "version": "1.0.0"}, "capabilities": {"experimentalApi": True}}})
        reply(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "skills/list", "params": {"cwds": [str(root)], "forceReload": True}})
        skills = reply(2)
        send({"id": 3, "method": "hooks/list", "params": {"cwds": [str(root)]}})
        return skills, reply(3)
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def main():
    run(["python3", "scripts/sync-plugins.py", "--check"], ROOT, os.environ)
    with tempfile.TemporaryDirectory(prefix="dual-client-check-") as directory:
        temporary = Path(directory)
        root = temporary / "repo"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        env = dict(os.environ, CODEX_HOME=str(temporary / "codex"), CLAUDE_CONFIG_DIR=str(temporary / "claude"))
        Path(env["CODEX_HOME"]).mkdir()
        Path(env["CLAUDE_CONFIG_DIR"]).mkdir()

        for client, catalog_path in [("claude", ".claude-plugin/marketplace.json"), ("codex", ".agents/plugins/marketplace.json")]:
            catalog = json.loads((root / catalog_path).read_text())
            if client == "claude":
                run(["claude", "plugin", "validate", str(root)], root, env)
            run([client, "plugin", "marketplace", "add", str(root)], root, env)
            for plugin in catalog["plugins"]:
                if client == "claude":
                    run(["claude", "plugin", "validate", str(root / plugin["source"])], root, env)
                verb = "install" if client == "claude" else "add"
                run([client, "plugin", verb, f"{plugin['name']}@{catalog['name']}", "--json"], root, env)
            print(f"{client}: installed {len(catalog['plugins'])} plugins with disposable settings.", flush=True)

        skills, hooks = codex_inventory(root, env)
        groups = skills["data"]
        errors = [error for group in groups for error in group.get("errors", [])]
        if errors:
            raise RuntimeError(f"Codex skill discovery errors: {errors}")
        discovered = {skill["pluginId"].split("@")[0] for group in groups for skill in group["skills"] if skill.get("pluginId")}
        registry = json.loads((root / "plugin-sources.json").read_text())
        expected = {plugin["name"] for plugin in registry["plugins"] if "codex" in plugin["clients"] and plugin.get("skills")}
        if discovered != expected:
            raise RuntimeError(f"Codex skill discovery mismatch: missing={expected - discovered}, unexpected={discovered - expected}")
        print(f"codex: discovered exactly the {len(expected)} packaged skills.", flush=True)
        expected_hooks = {
            f"{plugin['name']}@{registry['name']}": sum(len(group["hooks"]) for groups in plugin["hooks"].values() for group in groups)
            for plugin in registry["plugins"] if "codex" in plugin["clients"] and plugin.get("hooks")
        }
        discovered_hooks = {}
        for group in hooks["data"]:
            if group["errors"] or group["warnings"]:
                raise RuntimeError(f"Codex hook discovery problems: {group['errors']}, {group['warnings']}")
            for hook in group["hooks"]:
                if hook["source"] != "plugin":
                    continue
                plugin_id = hook["pluginId"]
                discovered_hooks[plugin_id] = discovered_hooks.get(plugin_id, 0) + 1
                if not hook["enabled"] or hook["trustStatus"] != "untrusted":
                    raise RuntimeError(f"Fresh plugin hook should require trust review: {hook}")
                if not hook.get("statusMessage"):
                    raise RuntimeError(f"Plugin hook is missing its display label: {hook}")
                if "${" in hook.get("command", ""):
                    raise RuntimeError(f"Unresolved plugin hook path: {hook}")
        if discovered_hooks != expected_hooks:
            raise RuntimeError(f"Codex hook discovery mismatch: expected={expected_hooks}, actual={discovered_hooks}")
        print(f"codex: discovered all {sum(expected_hooks.values())} plugin hooks; fresh installs require trust review.", flush=True)
        for name in ["client-html", "laravel-test-lock", "usage-guard-hook"]:
            details = run(["claude", "plugin", "details", name], root, env)
            if name == "client-html" and "client-html" not in details:
                raise RuntimeError("Claude did not discover client-html")
        print("claude: inspected skill, shared-hook, and Claude-only plugin inventories.")


if __name__ == "__main__":
    main()
