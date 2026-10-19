"""Check packaging boundaries, generated output drift, and relocated hook behavior."""

import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = runpy.run_path(str(ROOT / "scripts/sync-plugins.py"))
CLIENT_CHECK = runpy.run_path(str(ROOT / "scripts/check-plugin-clients.py"))


class PluginPackages(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is required for runtime discovery")
    def test_codex_loads_installed_hook_plugins_and_requires_trust(self):
        with tempfile.TemporaryDirectory(prefix="codex hook regression ") as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
            names = {"laravel-test-lock", "php-test-parallel-hook"}
            catalog["plugins"] = [entry for entry in catalog["plugins"] if entry["name"] in names]
            marketplace = root / ".agents/plugins/marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps(catalog))
            for name in names:
                shutil.copytree(ROOT / "plugins" / name, root / "plugins" / name)
            env = dict(os.environ, CODEX_HOME=str(Path(directory) / "codex"))
            Path(env["CODEX_HOME"]).mkdir()
            CLIENT_CHECK["run"](["codex", "plugin", "marketplace", "add", str(root)], root, env)
            for name in names:
                CLIENT_CHECK["run"](["codex", "plugin", "add", f"{name}@plong-agent-toolkit"], root, env)
            _, inventory = CLIENT_CHECK["codex_inventory"](root, env)
            hooks = []
            for entry in inventory["data"]:
                self.assertEqual(entry["errors"], [])
                self.assertEqual(entry["warnings"], [])
                hooks.extend(hook for hook in entry["hooks"] if hook["source"] == "plugin")
            self.assertCountEqual([hook["pluginId"] for hook in hooks], [f"{name}@plong-agent-toolkit" for name in names])
            for hook in hooks:
                self.assertTrue(hook["enabled"])
                self.assertEqual(hook["trustStatus"], "untrusted")
                self.assertEqual(hook["eventName"], "preToolUse")
                self.assertEqual(hook["matcher"], "Bash")
                self.assertTrue(hook["statusMessage"], "Hook browser needs a readable label")
                self.assertIn(hook["pluginId"].split("@")[0], hook["statusMessage"])
                self.assertNotIn("${", hook["command"])
                for command, blocked in [("php artisan test", True), ("git status", False)]:
                    result = subprocess.run(
                        hook["command"], shell=True, cwd=directory, env=env,
                        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}),
                        text=True, capture_output=True, timeout=10,
                    )
                    denied = result.returncode == 2 or '"permissionDecision": "deny"' in result.stdout
                    self.assertEqual(denied, blocked, (hook["pluginId"], result.stdout, result.stderr))

    def test_generated_files_are_current(self):
        self.assertEqual(GENERATOR["sync"](ROOT, check=True), [])

    def test_each_catalog_exposes_only_its_supported_plugins(self):
        registry = json.loads((ROOT / "plugin-sources.json").read_text())
        for client, path in [("claude", ".claude-plugin/marketplace.json"), ("codex", ".agents/plugins/marketplace.json")]:
            catalog = json.loads((ROOT / path).read_text())
            self.assertEqual(catalog["name"], "plong-agent-toolkit")
            self.assertEqual(
                {plugin["name"] for plugin in catalog["plugins"]},
                {plugin["name"] for plugin in registry["plugins"] if client in plugin["clients"]},
            )
            for entry in catalog["plugins"]:
                with self.subTest(client=client, name=entry["name"]):
                    if isinstance(entry["source"], dict):
                        continue  # externally hosted plugin, nothing local to inspect
                    folder = (ROOT / entry["source"]).resolve()
                    self.assertTrue(folder.is_relative_to(ROOT))
                    manifest_path = folder / f".{client}-plugin/plugin.json"
                    manifest = json.loads(manifest_path.read_text())
                    if client == "codex":
                        self.assertFalse((folder / "plugin.json").exists(), "Root manifests hide compatibility hooks in Codex 0.162.1")
                    self.assertEqual(manifest["name"], entry["name"])
                    self.assertTrue(manifest["version"].startswith("1.0.0+"))
                    source = next(plugin for plugin in registry["plugins"] if plugin["name"] == entry["name"])
                    for skill in source.get("skills", []):
                        self.assertTrue((folder / "skills" / Path(skill).name / "SKILL.md").is_file())
                    hooks = manifest.get("hooks", {}).get("hooks", {}) if client == "codex" else manifest.get("hooks", {})
                    for groups in hooks.values():
                        for group in groups:
                            for hook in group["hooks"]:
                                for token in shlex.split(hook["command"]):
                                    prefix = "${CLAUDE_PLUGIN_ROOT}/"
                                    if token.startswith(prefix):
                                        self.assertTrue((folder / token[len(prefix):]).is_file(), token)

    def test_packages_contain_only_their_declared_skills(self):
        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        entries = {plugin["name"]: plugin for plugin in catalog["plugins"]}
        for name in ["client-html", "api-flow-prototype"]:
            folder = ROOT / entries[name]["source"]
            self.assertEqual([file.parent.name for file in folder.rglob("SKILL.md")], [name])
        self.assertNotIn("plong-statusline", entries)
        self.assertNotIn("usage-guard-hook", entries)

    def test_hook_packages_work_when_relocated_without_the_repo(self):
        for name in ["laravel-test-lock", "php-test-parallel-hook"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="relocated plugin ") as directory:
                folder = Path(directory) / name
                shutil.copytree(ROOT / "plugins" / name, folder)
                for client in ["claude", "codex"]:
                    manifest_path = folder / f".{client}-plugin/plugin.json"
                    manifest = json.loads(manifest_path.read_text())
                    hooks = manifest["hooks"]["hooks"] if client == "codex" else manifest["hooks"]
                    command = hooks["PreToolUse"][0]["hooks"][0]["command"]
                    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(folder), PLUGIN_ROOT=str(folder))
                    for test_command in ["php artisan test", ["bash", "-lc", "docker compose exec app php artisan test"]]:
                        result = subprocess.run(
                            command, shell=True, cwd=directory, env=env, text=True, capture_output=True,
                            input=json.dumps({"tool_input": {"command": test_command}}),
                        )
                        self.assertTrue(result.returncode == 2 or '"permissionDecision": "deny"' in result.stdout,
                                        (client, name, result.stdout, result.stderr))
                    result = subprocess.run(
                        command, shell=True, cwd=directory, env=env, text=True, capture_output=True,
                        input=json.dumps({"tool_input": {"command": "git status"}}),
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(result.stdout.strip())

    def test_generator_detects_modified_resources_and_refuses_external_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "plugins/probe/skills/probe"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: probe\ndescription: Probe\n---\nHello.\n")
            source = {"name": "probe", "owner": {"name": "test"}, "metadata": {"version": "1.0.0"}, "plugins": [
                {"name": "probe", "description": "Probe", "skills": ["./skills/probe"], "clients": ["claude", "codex"]},
            ]}
            (root / "plugin-sources.json").write_text(json.dumps(source))
            GENERATOR["sync"](root)
            self.assertEqual(GENERATOR["sync"](root, check=True), [])
            (skill / "SKILL.md").write_text("Changed source")
            self.assertTrue(GENERATOR["sync"](root, check=True))
            # Removing a client removes its generated manifest without touching
            # the editable source or the other client's plugin package.
            source["plugins"][0]["clients"] = ["claude"]
            (root / "plugin-sources.json").write_text(json.dumps(source))
            GENERATOR["sync"](root)
            self.assertFalse((root / "plugins/probe/plugin.json").exists())
            self.assertFalse((root / "plugins/probe/.codex-plugin/plugin.json").exists())
            self.assertTrue((root / "plugins/probe/.claude-plugin/plugin.json").exists())
            self.assertEqual((skill / "SKILL.md").read_text(), "Changed source")
            source["plugins"][0]["skills"] = ["../outside"]
            (root / "plugin-sources.json").write_text(json.dumps(source))
            with self.assertRaises(ValueError):
                GENERATOR["sync"](root)

    def test_generation_owns_only_metadata_and_preserves_legacy_indexed_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "plugins/probe/skills/probe"
            skill.mkdir(parents=True)
            text = "---\nname: probe\ndescription: Probe\n---\nEditable source.\n"
            (skill / "SKILL.md").write_text(text)
            registry = {"name": "probe", "owner": {"name": "test"}, "metadata": {"version": "1.0.0"}, "plugins": [
                {"name": "probe", "description": "Probe", "skills": ["./skills/probe"], "clients": ["claude"]},
            ]}
            (root / "plugin-sources.json").write_text(json.dumps(registry))
            # Simulate the pre-migration index, which used to own source copies.
            (root / "plugins/generated-files.json").write_text(json.dumps(["plugins/probe/skills/probe/SKILL.md"]))
            GENERATOR["sync"](root)
            self.assertEqual((skill / "SKILL.md").read_text(), text)
            self.assertTrue(all(GENERATOR["generated_metadata"](p) for p in GENERATOR["render"](root)))
            registry["plugins"] = []
            (root / "plugin-sources.json").write_text(json.dumps(registry))
            GENERATOR["sync"](root)
            self.assertFalse((root / "plugins/probe/.claude-plugin/plugin.json").exists())
            self.assertEqual((skill / "SKILL.md").read_text(), text)

    def test_skills_have_one_physical_source(self):
        self.assertFalse((ROOT / "skill-defs").exists())
        self.assertFalse((ROOT / "skills").exists())
        skills = list((ROOT / "plugins").rglob("SKILL.md"))
        names = [path.parent.name for path in skills]
        self.assertEqual(len(names), len(set(names)))
        index = json.loads((ROOT / "plugins/generated-files.json").read_text())
        self.assertTrue(all(GENERATOR["generated_metadata"](path) for path in index))


if __name__ == "__main__":
    unittest.main()
