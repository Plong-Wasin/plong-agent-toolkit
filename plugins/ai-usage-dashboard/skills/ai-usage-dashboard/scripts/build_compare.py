#!/usr/bin/env python3
"""Render a "real credit vs subscription" comparison page from ccusage data.

Usage:
  build_compare.py --out compare.html \
      --source "เครื่องหลัก=" --source "devcontainer=/path/.devcontainer/.claude" \
      --plan "claude|Claude Team (1 seat)|Claude|150|หมายเหตุ" \
      --plan "codex|ChatGPT Plus (Codex)|Codex|20|หมายเหตุ"

--plan KEY|LABEL|SHORT|MONTHLY_USD|NOTE|PAYER (PAYER: "company" or "self", optional) where KEY is the agent (claude or codex).
The page lets the reader edit each monthly price; the script value is the default.
Sources behave as in build_dashboard.py (extra sources count Claude models only).
"""
import argparse, datetime, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dashboard as bd

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "compare-template.html"
NOTES = [
    "Credit จริง คือค่า token ที่ ccusage ประมาณตามอัตรา API จึงเป็นตัวเลขสมมติว่าจ่ายตามการใช้ ไม่ใช่ใบแจ้งหนี้",
    "Subscription คิดตามสัดส่วนจำนวนวันที่มีข้อมูลของเครื่องมือนั้น (ราคาต่อเดือน × วัน ÷ 30.44)",
    "แพ็กเกจรายเดือนมีลิมิตการใช้ (รอบ 5 ชั่วโมง/รายสัปดาห์) การ pay-per-token ไม่มีลิมิตนี้ จึงเปรียบเทียบได้เฉพาะด้านราคา",
    "หากเปิด extra usage ไว้ ส่วนที่เกินลิมิตอาจถูกคิดเงินเพิ่ม ซึ่ง ccusage ไม่เห็น ยอดจริงจึงอาจสูงกว่าค่าสมาชิกที่แสดง",
    "ราคาเริ่มต้นของแพ็กเกจเป็นค่าสมมติ ตรวจกับใบเสร็จหรือหน้า billing ก่อนนำตัวเลขไปใช้",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--plan", action="append", required=True)
    a = ap.parse_args()
    rows, _ = bd.collect(a.source or ["เครื่องหลัก="])
    plans = []
    for spec in a.plan:
        key, label, short, price, note, payer = (spec.split("|") + ["", ""])[:6]
        plans.append({"key": key, "label": label, "short": short, "price": float(price), "note": note, "payer": payer})
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", json.dumps(rows, separators=(",", ":")))
            .replace("__PLANS__", json.dumps(plans, ensure_ascii=False))
            .replace("__NOTES__", json.dumps(NOTES, ensure_ascii=False))
            .replace("__GEN__", datetime.date.today().isoformat()))
    Path(a.out).write_text(html, encoding="utf-8")
    for p in plans:
        r = [x for x in rows if x["a"] == p["key"]]
        print(f"{p['label']}: API ~${sum(x['c'] for x in r):,.2f} over {len({x['d'] for x in r})} days")


if __name__ == "__main__":
    main()
