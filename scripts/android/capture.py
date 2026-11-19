# -*- coding: utf-8 -*-
"""Stage 2: capture one test step (optional action -> wait -> screenshot + UI tree + activity).

Example:
  python capture.py --root <run> --step r03 --label "首页-发现" --note "冷启动后等待6秒" \
      --expect "进入发现首页" --wait 6
  python capture.py --root <run> --step r04 --label "搜索页" --tap 360 200 --wait 2
  python capture.py --root <run> --step r05 --label "返回首页" --key KEYCODE_BACK --wait 2
"""
import argparse
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import pick_device, run, slugify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--expect", default="")
    ap.add_argument("--serial")
    ap.add_argument("--tap", nargs=2, type=int, metavar=("X", "Y"))
    ap.add_argument("--swipe", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    ap.add_argument("--key", help="如 KEYCODE_BACK")
    ap.add_argument("--wait", type=float, default=0, help="动作后等待秒数")
    ap.add_argument("--no-ui", action="store_true", help="跳过 UI 树抓取（视频播放等动画页面）")
    ap.add_argument("--quiet", action="store_true", help="只打印一行摘要")
    a = ap.parse_args()

    serial = pick_device(a.serial)
    root = os.path.abspath(a.root)
    shots = os.path.join(root, "outputs", "screenshots")
    ui = os.path.join(root, "work", "ui")
    rec_path = os.path.join(root, "work", "steps.jsonl")
    os.makedirs(shots, exist_ok=True)
    os.makedirs(ui, exist_ok=True)

    run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serial=serial)
    if a.tap:
        run(["shell", "input", "tap", str(a.tap[0]), str(a.tap[1])], serial=serial)
    if a.swipe:
        run(["shell", "input", "swipe", *[str(v) for v in a.swipe]], serial=serial)
    if a.key:
        run(["shell", "input", "keyevent", a.key], serial=serial)
    if a.wait:
        time.sleep(a.wait)

    png = run(["exec-out", "screencap", "-p"], serial=serial, binary=True, timeout=120)
    shot = os.path.join(shots, f"{a.step}_{slugify(a.label)}.png")
    with open(shot, "wb") as f:
        f.write(png)

    xmlpath = os.path.join(ui, f"{a.step}.xml")
    ui_ok = False
    xml = ""
    if not a.no_ui:
        # 先删远端旧文件，避免 dump 失败时读到上一次的陈旧 UI 树
        run(["shell", "rm", "-f", "/sdcard/ui.xml"], serial=serial, timeout=30)
        for attempt in range(3):
            try:
                out = run(["shell", "uiautomator", "dump", "/sdcard/ui.xml"], serial=serial, timeout=60)
                if "dumped to" in out:
                    xml = run(["exec-out", "cat", "/sdcard/ui.xml"], serial=serial, timeout=60)
                    ui_ok = "<hierarchy" in xml
                    if ui_ok:
                        break
            except Exception:
                pass
            time.sleep(1)
    if not ui_ok:
        xml = "<error>ui dump failed (device busy/animated or --no-ui)</error>"
    with io.open(xmlpath, "w", encoding="utf-8") as f:
        f.write(xml)

    focus = run(["shell", "dumpsys", "window"], serial=serial, timeout=60)
    m = re.search(r"mCurrentFocus=([^\r\n]+)", focus)
    acts = run(["shell", "dumpsys", "activity", "activities"], serial=serial, timeout=60)
    m2 = re.search(r"mResumedActivity[^\r\n]*?([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)", acts)

    texts = [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]
    descs = [d for d in re.findall(r'content-desc="([^"]*)"', xml) if d.strip()]
    clickables = []
    for tag in re.findall(r"<node[^>]*>", xml):
        if 'clickable="true"' not in tag:
            continue
        def attr(name):
            m = re.search(rf'{name}="([^"]*)"', tag)
            return m.group(1) if m else ""
        bounds = attr("bounds")
        if bounds in ("", "[0,0][0,0]"):
            continue
        clickables.append({
            "text": attr("text"), "desc": attr("content-desc"),
            "id": attr("resource-id"), "class": attr("class"), "bounds": bounds,
        })

    rec = {
        "step": a.step,
        "label": a.label,
        "note": a.note,
        "expect": a.expect,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "serial": serial,
        "current_focus": m.group(1).strip() if m else "",
        "resumed_activity": m2.group(1) if m2 else "",
        "screenshot": os.path.relpath(shot, root),
        "ui_xml": os.path.relpath(xmlpath, root),
        "ui_ok": ui_ok,
        "texts": texts[:200],
        "descs": descs[:100],
        "clickables": clickables[:80],
        "size": len(png),
    }
    with io.open(rec_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if a.quiet:
        print(f'{a.step} | ui_ok={ui_ok} | {rec["resumed_activity"]} | {rec["screenshot"]}')
        for c in clickables[:40]:
            print(f'  [{c["text"] or c["desc"] or c["id"]}] {c["bounds"]}')
    else:
        print(json.dumps({k: rec[k] for k in ["step", "label", "current_focus", "resumed_activity",
                                              "ui_ok", "texts", "descs", "clickables", "screenshot"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
