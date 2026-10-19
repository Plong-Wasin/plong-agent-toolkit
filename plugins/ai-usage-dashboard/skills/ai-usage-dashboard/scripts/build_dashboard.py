#!/usr/bin/env python3
"""Collect token usage with ccusage and render one standalone HTML dashboard.

Usage:
  build_dashboard.py --out dash.html \
      [--source "เครื่องหลัก="] \
      [--source "devcontainer=/path/to/.devcontainer/.claude"]

--source LABEL=CLAUDE_CONFIG_DIR   (repeatable; empty dir = ccusage default,
    which also includes Codex and other agents it detects on this machine).
    Every extra source contributes only Claude models, so a Codex history that
    lives on the host is never counted twice.
"""
import argparse, datetime, json, os, re, subprocess, sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template.html"


def agent_of(model):
    if model.startswith("claude"):
        return "claude"
    if model.startswith(("gpt", "o1", "o3", "o4", "codex")):
        return "codex"
    return "other"


def run_ccusage(config_dir):
    env = dict(os.environ)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    cmd = ["npx", "-y", "ccusage@latest", "daily", "--json", "--breakdown"]
    out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        sys.exit(f"ccusage failed for {config_dir or 'default'}:\n{out.stderr[-800:]}")
    return json.loads(out.stdout)["daily"]


def collect(sources):
    """Return (rows, labels). Source 0 keeps every model; later sources keep Claude only."""
    rows, labels = [], {}
    for n, spec in enumerate(sources):
        label, _, path = spec.partition("=")
        key = "s%d" % n
        labels[key] = label
        if path and not Path(path).expanduser().is_dir():
            sys.exit(f"Not a directory: {path}")
        for day in run_ccusage(str(Path(path).expanduser()) if path else ""):
            for b in day["modelBreakdowns"]:
                m = b["modelName"]
                if n > 0 and agent_of(m) != "claude":
                    continue
                rows.append({"d": day.get("period") or day.get("date"), "s": key,
                             "a": agent_of(m), "m": m, "c": round(b["cost"], 4),
                             "i": b["inputTokens"], "o": b["outputTokens"],
                             "cr": b["cacheReadTokens"], "cw": b["cacheCreationTokens"]})
    return rows, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", action="append", default=[], help="LABEL=CONFIG_DIR")
    a = ap.parse_args()
    sources = a.source or ["เครื่องหลัก="]
    rows, labels = collect(sources)
    if not rows:
        sys.exit("ccusage returned no usage rows")
    note = " · ".join(f"{v} = <code>{(sources[int(k[1:])].partition('=')[2] or 'ค่าเริ่มต้นของ ccusage (รวม Codex)')}</code>" for k, v in labels.items())
    note += " — แต่ละแหล่งนับแยกกันและไม่ซ้อนกัน"
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", json.dumps(rows, separators=(",", ":")))
            .replace("__LABELS__", json.dumps(labels, ensure_ascii=False))
            .replace("__NOTE__", note)
            .replace("__GEN__", datetime.date.today().isoformat()))
    Path(a.out).write_text(html, encoding="utf-8")
    total = sum(r["c"] for r in rows)
    print(f"wrote {a.out}: {len(rows)} rows, {len({r['d'] for r in rows})} days, ~${total:,.2f}")
    for k, v in labels.items():
        print(f"  {v}: ~${sum(r['c'] for r in rows if r['s'] == k):,.2f}")


if __name__ == "__main__":
    main()
