#!/usr/bin/env python3
"""Generate Codex/Claude metadata for packages whose files live in plugins/."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys


ROOT = Path(__file__).resolve().parents[1]
INDEX = "plugins/generated-files.json"
CLIENTS = {"claude", "codex"}
IGNORED = {".claude-plugin", ".codex-plugin", "__pycache__", ".git"}


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def inside(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Expected a repository-relative path: {relative}")
    result = root / path
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes repository: {relative}")
    return result


def source_files(root, relative):
    path = inside(root, relative)
    if not path.exists():
        raise ValueError(f"Missing source: {relative}")
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    result = {}
    for file in paths:
        if any(part in IGNORED for part in file.relative_to(path.parent).parts):
            continue
        if file.is_symlink():
            raise ValueError(f"Bundle sources must be physical files: {file}")
        if file.is_file():
            mode = 0o755 if file.stat().st_mode & 0o111 else 0o644
            result[file.relative_to(root).as_posix()] = (file.read_bytes(), mode)
    return result


def render(root):
    registry = json.loads((root / "plugin-sources.json").read_text())
    name = registry["name"]
    owner = registry["owner"]
    catalogs = {
        "claude": {"name": name, "owner": owner, "metadata": registry["metadata"], "plugins": []},
        "codex": {"name": name, "interface": {"displayName": "Plong Agent Toolkit"}, "plugins": []},
    }
    outputs = {}
    seen = set()
    for plugin in registry["plugins"]:
        plugin_name = plugin["name"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", plugin_name) or plugin_name in seen:
            raise ValueError(f"Invalid or duplicate plugin name: {plugin_name}")
        seen.add(plugin_name)
        clients = plugin["clients"]
        if not clients or not set(clients) <= CLIENTS or len(set(clients)) != len(clients):
            raise ValueError(f"Invalid clients for {plugin_name}")
        if "source" in plugin:
            # Externally hosted plugin: reference it in the catalogs and generate nothing.
            for client in clients:
                entry = {"name": plugin_name, "source": plugin["source"]}
                if client == "claude":
                    entry["description"] = plugin["description"]
                    # Extra marketplace fields, e.g. strict=false with a skills subset of the upstream repo.
                    entry.update(plugin.get("marketplace", {}))
                else:
                    entry.update({
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Productivity",
                    })
                catalogs[client]["plugins"].append(entry)
            continue
        plugin_root = f"plugins/{plugin_name}"
        folder = inside(root, plugin_root)
        skills = plugin.get("skills", [])
        sources = {}
        for skill in skills:
            if Path(skill).parts[:1] != ("skills",):
                raise ValueError(f"Skill must live inside its package's skills/ directory: {skill}")
            if not (inside(folder, skill) / "SKILL.md").is_file():
                raise ValueError(f"Missing SKILL.md: {skill}")
            skill_files = source_files(folder, skill)
            sources.update(skill_files)
        for resource in plugin.get("files", []):
            resource_files = source_files(folder, resource)
            sources.update(resource_files)

        # Skills and hook resources are editable files already inside the
        # installable package. Generation owns metadata only, never their content.
        manifest = {"name": plugin_name, "description": plugin["description"], "author": owner}
        if plugin.get("hooks"):
            manifest["hooks"] = plugin["hooks"]
            for groups in manifest["hooks"].values():
                for group in groups:
                    for hook in group["hooks"]:
                        for token in shlex.split(hook["command"]):
                            prefix = "${CLAUDE_PLUGIN_ROOT}/"
                            if token.startswith(prefix):
                                path = token[len(prefix):]
                                if not inside(folder, path).is_file() or path not in sources:
                                    raise ValueError(f"Hook resource is missing or undeclared: {plugin_name}/{path}")
        if not sources:
            raise ValueError(f"Plugin has no bundled resources: {plugin_name}")

        # Change the installed version when source content changes so clients do
        # not reuse a stale cache under the old version number.
        digest = hashlib.sha256(b"codex-compatibility-manifest-v1\n" + json_bytes(manifest))
        for path, (content, mode) in sorted(sources.items()):
            digest.update(json_bytes([path, mode, len(content)]))
            digest.update(content)
        manifest["version"] = registry["metadata"]["version"] + "+" + digest.hexdigest()[:12]

        for client in clients:
            client_manifest = dict(manifest)
            if client == "codex":
                client_manifest["interface"] = {
                    "displayName": plugin_name,
                    "shortDescription": plugin["description"][:80],
                    "developerName": owner["name"],
                    "category": "Productivity",
                    "capabilities": [],
                }
                if "hooks" in client_manifest:
                    # Inline hook entries use the complete hooks-file schema.
                    client_manifest["hooks"] = {"hooks": client_manifest["hooks"]}
            manifest_path = f"{plugin_root}/.codex-plugin/plugin.json" if client == "codex" else f"{plugin_root}/.claude-plugin/plugin.json"
            outputs[manifest_path] = (json_bytes(client_manifest), 0o644)
            entry = {"name": plugin_name, "source": "./" + plugin_root}
            if client == "claude":
                entry["description"] = plugin["description"]
            else:
                entry.update({
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                })
            catalogs[client]["plugins"].append(entry)

    for client, catalog in catalogs.items():
        path = ".claude-plugin/marketplace.json" if client == "claude" else ".agents/plugins/marketplace.json"
        outputs[path] = (json_bytes(catalog), 0o644)
    outputs[INDEX] = (json_bytes(sorted(outputs)), 0o644)
    return outputs


def sync(root, check=False):
    outputs = render(root)
    index = root / INDEX
    previous = json.loads(index.read_text()) if index.exists() else []
    # Old indexes also listed generated copies of skills/scripts. Those paths
    # are now editable sources; even a legacy/stale index must never delete them.
    stale = {path for path in set(previous) - set(outputs) if generated_metadata(path)}
    differences = []
    for relative, (content, mode) in outputs.items():
        path = inside(root, relative)
        if not path.is_file() or path.read_bytes() != content or (path.stat().st_mode & 0o111) != (mode & 0o111):
            differences.append(relative)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(mode)
    for relative in sorted(stale):
        path = inside(root, relative)
        if path.exists():
            differences.append(relative)
            if not check:
                path.unlink()
    return differences


def generated_metadata(path):
    return path in (INDEX, ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json") or bool(
        re.fullmatch(r"plugins/[a-z0-9]+(?:-[a-z0-9]+)*/(?:plugin\.json|\.(?:claude|codex)-plugin/plugin\.json)", path)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated files need updating")
    args = parser.parse_args()
    try:
        differences = sync(ROOT, args.check)
    except (ValueError, KeyError, OSError) as error:
        print(f"Plugin generation failed: {error}", file=sys.stderr)
        return 1
    if args.check and differences:
        print("Run python3 scripts/sync-plugins.py to update:\n" + "\n".join(differences), file=sys.stderr)
        return 1
    print(f"Plugin files {'verified' if args.check else 'updated'} ({len(differences)} changes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
