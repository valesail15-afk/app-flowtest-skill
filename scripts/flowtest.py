# -*- coding: utf-8 -*-
"""统一入口：按目标类型自动分派到 Web / Android 脚本。

用法：
  python flowtest.py doctor --url http://127.0.0.1:8787/ --out <run>
  python flowtest.py map    --url http://127.0.0.1:8787/ --out <run>/feature-map.yaml
  python flowtest.py step   --url http://127.0.0.1:8787/ --root <run> --step r01 --label 首页
  python flowtest.py report --run <run> --issues <run>/work/issues.json --out <run>/outputs/issues-report.html
  python flowtest.py coverage --map <run>/feature-map.yaml --out <run>/work/coverage.json

Android：把 --url 换成 --apk <apk路径>（step 用 --tap/--key 等参数）。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.join(HERE, "android")


def run(script, args):
    cmd = [sys.executable, script] + args
    print(">>", " ".join(cmd), file=sys.stderr)
    raise SystemExit(subprocess.call(cmd))


def make_coverage(args):
    """从功能地图生成覆盖台账骨架；重复执行时保留已有状态与备注。"""
    import json

    import yaml

    ap = argparse.ArgumentParser(description="生成/更新覆盖台账")
    ap.add_argument("--map", required=True, help="feature-map.yaml 路径")
    ap.add_argument("--out", required=True, help="coverage.json 输出路径")
    a, _ = ap.parse_known_args(args)

    try:
        data = yaml.safe_load(open(a.map, encoding="utf-8")) or {}
    except FileNotFoundError:
        raise SystemExit(f"找不到功能地图：{a.map}")
    features = data.get("features") or []
    if not features:
        raise SystemExit(f"功能地图为空：{a.map}")

    existing = {}
    if os.path.isfile(a.out):
        try:
            old = json.load(open(a.out, encoding="utf-8"))
            existing = {i.get("name"): i for i in old.get("items", [])}
        except Exception:
            existing = {}

    items = []
    for f in features:
        name = f.get("name", "")
        items.append(existing.get(name) or {"name": name, "status": "untested", "note": ""})

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fp:
        json.dump({"total": len(items), "items": items}, fp, ensure_ascii=False, indent=2)

    tested = sum(1 for i in items if i.get("status") == "tested")
    print(f"覆盖台账已写入：{a.out}（{tested}/{len(items)} 已测）")
    if tested < len(items):
        print("请逐条执行后把 status 改为 tested；受阻写 blocked 并注明原因。")


def main():
    parser = argparse.ArgumentParser(description="通用功能流程测试（Web / Android）")
    parser.add_argument("action", choices=["doctor", "map", "step", "flow", "report", "coverage"])
    parser.add_argument("--url", help="Web 目标地址；缺省则走 Android")
    args, rest = parser.parse_known_args()

    if args.action == "coverage":
        make_coverage(rest)
    elif args.action == "report":
        run(os.path.join(HERE, "build_report.py"), rest)
    elif args.url:
        script = {"doctor": "web_probe.py", "map": "web_crawl.py", "step": "web_capture.py",
                  "flow": "web_flow.py"}[args.action]
        run(os.path.join(HERE, script), ["--url", args.url] + rest)
    else:
        script = {"doctor": "env_check.py", "map": "feature_map.py", "step": "capture.py"}[args.action]
        run(os.path.join(ANDROID, script), rest)


if __name__ == "__main__":
    main()
