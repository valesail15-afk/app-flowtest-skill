# -*- coding: utf-8 -*-
"""Regression helper: turn a previous issues.json into a re-test checklist, then record verdicts.

Usage:
  # 1) 从上一轮问题生成复测清单
  python regression.py init --prev <prev-run>/work/issues.json --out <run>/work/regression.json

  # 2) 查看清单
  python regression.py list --file <run>/work/regression.json

  # 3) 回填结果（可多次）
  python regression.py set --file <run>/work/regression.json --id R03 \
      --status fixed --evidence "r60 输出 312KB < 源图 862KB" --step r60

  # 4) 汇总（打印统计，供报告 notes 引用）
  python regression.py summary --file <run>/work/regression.json

status: still(仍存在) | fixed(已修复) | regressed(修复后复发) | unverified(本轮未覆盖)
"""
import argparse
import io
import json
import os
import sys

STATUS_LABEL = {"still": "仍存在", "fixed": "已修复", "regressed": "复发", "unverified": "未验证", "pending": "待复测"}


def load(path):
    with io.open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def iter_issues(issues):
    for sec in issues.get("sections", []):
        if sec.get("id") not in ("c1", "c2"):
            continue
        for it in sec.get("items", []):
            yield sec.get("id"), it


def cmd_init(a):
    issues = load(a.prev)
    prev_app = issues.get("app", {})
    items = []
    for i, (sid, it) in enumerate(iter_issues(issues), 1):
        rid = it.get("id") or f"R{i:02d}"
        items.append({
            "id": rid,
            "prev_section": "确认问题" if sid == "c1" else "待确认",
            "prev_severity": it.get("severity", ""),
            "prev_path": it.get("path", ""),
            "title": it.get("title", ""),
            "check": it.get("evidence", "") or it.get("desc", ""),
            "prev_images": it.get("images", []),
            "status": "pending",
            "evidence": "",
            "step": "",
            "note": "",
        })
    data = {
        "prev_report": os.path.abspath(a.prev),
        "prev_app": prev_app,
        "items": items,
    }
    save(a.out, data)
    print(json.dumps({"out": os.path.abspath(a.out), "items": len(items)}, ensure_ascii=False))


def cmd_list(a):
    data = load(a.file)
    print(f'{data.get("prev_app", {}).get("version", "")} 共 {len(data["items"])} 条待复测\n')
    for it in data["items"]:
        print(f'{it["id"]:>4} [{STATUS_LABEL.get(it["status"], it["status"])}] {it["title"]}')
        print(f'      复现要点：{str(it["check"])[:110]}')
    print("\n回填：regression.py set --file <file> --id <ID> --status fixed|still|regressed|unverified --evidence \"...\"")


def cmd_set(a):
    data = load(a.file)
    target = None
    for it in data["items"]:
        if it["id"] == a.id:
            target = it
            break
    if not target:
        raise SystemExit(f'没有 {a.id} 这条，用 list 查看可用 ID')
    target["status"] = a.status
    if a.evidence:
        target["evidence"] = a.evidence
    if a.step:
        target["step"] = a.step
    if a.note:
        target["note"] = a.note
    save(a.file, data)
    print(f'{a.id} -> {STATUS_LABEL.get(a.status, a.status)}')


def cmd_summary(a):
    data = load(a.file)
    counts = {"fixed": 0, "still": 0, "regressed": 0, "unverified": 0, "pending": 0}
    for it in data["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    out = {
        "total": len(data["items"]),
        **{STATUS_LABEL[k]: v for k, v in counts.items()},
        "still_list": [f'{it["id"]} {it["title"]}' for it in data["items"] if it["status"] in ("still", "regressed")],
        "pending_list": [it["id"] for it in data["items"] if it["status"] == "pending"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--prev", required=True, help="上一轮 work/issues.json")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("list")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("set")
    p.add_argument("--file", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=["still", "fixed", "regressed", "unverified"])
    p.add_argument("--evidence", default="")
    p.add_argument("--step", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("summary")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_summary)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
