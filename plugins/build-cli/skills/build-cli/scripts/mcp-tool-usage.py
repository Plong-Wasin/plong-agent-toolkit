#!/usr/bin/env python3
"""Count how often an MCP server's tools were called in Claude Code session history.

Usage: mcp-tool-usage.py <server> [--projects-dir DIR] [--shapes N]

<server> is the middle part of the tool name: mcp__<server>__<tool>.
Reads every *.jsonl under the projects dir (subagent transcripts included) and prints,
per tool: call count, the most common argument-key shapes with one example each, and the
projects that call it most. Nothing is sent anywhere.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def tool_calls(path, prefix):
    with path.open(errors="ignore") as handle:
        for line in handle:
            if prefix not in line:  # cheap filter before parsing JSON
                continue
            try:
                message = json.loads(line).get("message", {})
            except json.JSONDecodeError:
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "tool_use" and str(block.get("name", "")).startswith(prefix):
                    yield block["name"][len(prefix):], block.get("input") or {}


def project_of(path, root):
    # <root>/<project-dir>/[<session>/subagents/]<file>.jsonl -> <project-dir>
    return path.relative_to(root).parts[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("server")
    parser.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--shapes", type=int, default=4, help="argument shapes to show per tool")
    args = parser.parse_args()

    root = Path(args.projects_dir)
    prefix = f"mcp__{args.server}__"
    counts = Counter()
    shapes = defaultdict(Counter)
    examples = {}
    projects = defaultdict(Counter)

    for path in root.rglob("*.jsonl"):
        project = project_of(path, root)
        for tool, tool_input in tool_calls(path, prefix):
            counts[tool] += 1
            shape = tuple(sorted(tool_input))
            shapes[tool][shape] += 1
            examples.setdefault((tool, shape), tool_input)
            projects[tool][project] += 1

    if not counts:
        raise SystemExit(f"No calls to {prefix}* under {root}")

    total = sum(counts.values())
    print(f"{total} calls to {prefix}* across {len(counts)} tools\n")
    for tool, count in counts.most_common():
        print(f"{count:6d}  {tool}")
        for shape, n in shapes[tool].most_common(args.shapes):
            example = json.dumps(examples[(tool, shape)], ensure_ascii=False)
            print(f"          {n:5d}x  keys={list(shape)}  e.g. {example[:140]}")
        top = ", ".join(f"{name} ({n})" for name, n in projects[tool].most_common(3))
        print(f"          used in: {top}\n")


if __name__ == "__main__":
    main()
