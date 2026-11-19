# -*- coding: utf-8 -*-
"""统一入口：按目标类型自动分派到 Web / Android 脚本。

用法：
  python flowtest.py doctor --url http://127.0.0.1:8787/ --out <run>
  python flowtest.py map    --url http://127.0.0.1:8787/ --out <run>/feature-map.yaml
  python flowtest.py step   --url http://127.0.0.1:8787/ --root <run> --step r01 --label 首页
  python flowtest.py report --run <run> --issues <run>/work/issues.json --out <run>/outputs/issues-report.html

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


def main():
    parser = argparse.ArgumentParser(description="通用功能流程测试（Web / Android）")
    parser.add_argument("action", choices=["doctor", "map", "step", "flow", "report"])
    parser.add_argument("--url", help="Web 目标地址；缺省则走 Android")
    args, rest = parser.parse_known_args()

    if args.action == "report":
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
