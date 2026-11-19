# -*- coding: utf-8 -*-
"""阶段 0（Web）：检查目标地址、浏览器与依赖，写入 work/env.json 并留首屏截图。"""
import argparse
import io
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_common import WebSession, parse_viewport, pick_browser, slugify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True, help="测试产物根目录")
    ap.add_argument("--viewport", default="1440x960")
    ap.add_argument("--headed", action="store_true", help="显示浏览器窗口（需要人工登录时）")
    a = ap.parse_args()

    root = os.path.abspath(a.out)
    for d in ["work/ui", "outputs/screenshots"]:
        os.makedirs(os.path.join(root, d), exist_ok=True)

    probe = {"url": a.url, "http": {}}
    try:
        req = urllib.request.Request(a.url, headers={"User-Agent": "app-flowtest"})
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
            probe["http"] = {"status": r.status, "bytes": len(body), "content_type": r.headers.get("content-type", "")}
    except Exception as e:
        probe["http"] = {"error": str(e)}

    deps = {"python": sys.version.split()[0]}
    try:
        import playwright
        deps["playwright"] = True
    except ImportError:
        deps["playwright"] = False
    deps["browser"] = pick_browser() or "playwright-chromium"
    if not deps["playwright"]:
        print("缺少 playwright：python -m pip install playwright", file=sys.stderr)
        sys.exit(2)

    with WebSession(root, a.url, parse_viewport(a.viewport), headless=not a.headed) as sess:
        sess.goto("", wait=1.0)
        obs = sess.observe()
        shot = os.path.join(root, "outputs", "screenshots", f"r00_env_{slugify(obs.get('title') or 'home')}.png")
        sess.page.screenshot(path=shot)
        env = {
            "platform": "web",
            "time": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            "url": obs.get("url", a.url),
            "title": obs.get("title", ""),
            "viewport": a.viewport,
            "headless": not a.headed,
            "screens": obs.get("screens", []),
            "headings": obs.get("headings", []),
            "buttons": len(obs.get("buttons", [])),
            "inputs": len(obs.get("inputs", [])),
            "has_login": any(k in obs.get("bodyText", "") for k in ("登录", "注册", "账号")),
            "http": probe["http"],
            "deps": deps,
            "screenshot": os.path.relpath(shot, root),
        }
        with io.open(os.path.join(root, "work", "env.json"), "w", encoding="utf-8") as f:
            json.dump(env, f, ensure_ascii=False, indent=2)

    print(json.dumps(env, ensure_ascii=False, indent=2))
    print(f"\n产物目录已就绪：{root}")


if __name__ == "__main__":
    main()
