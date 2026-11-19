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


def dump_ui(serial):
    """抓取当前 UI 树；先删远端旧文件，避免读到上一次的陈旧结果。"""
    run(["shell", "rm", "-f", "/sdcard/ui.xml"], serial=serial, timeout=30)
    for _ in range(3):
        try:
            out = run(["shell", "uiautomator", "dump", "/sdcard/ui.xml"], serial=serial, timeout=60)
            if "dumped to" in out:
                xml = run(["exec-out", "cat", "/sdcard/ui.xml"], serial=serial, timeout=60)
                if "<hierarchy" in xml:
                    return xml
        except Exception:
            pass
        time.sleep(1)
    return ""


def parse_rect(bounds):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def find_text_node(xml, target):
    """按 text/content-desc 精确优先、包含兜底找中心点。

    底部 Tab 的文字节点常是 0 尺寸，此时回溯到最近的有尺寸祖先（Tab 容器）取中心，
    避免「文字能找到但点不到」。
    """
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
    except Exception:
        return None
    items = []

    def walk(el, ancestors):
        text = (el.get("text") or el.get("content-desc") or "").strip()
        items.append((text, el.get("bounds"), ancestors))
        for child in el:
            walk(child, ancestors + [el])

    walk(root, [])
    areas = [r for r in (parse_rect(b) for _, b, _ in items) if r]
    screen_area = max(((r[2] - r[0]) * (r[3] - r[1]) for r in areas), default=0) or 1

    def resolve(rect, ancestors):
        if rect and rect[2] - rect[0] > 2 and rect[3] - rect[1] > 2:
            return rect
        for anc in reversed(ancestors):
            r = parse_rect(anc.get("bounds"))
            if not r:
                continue
            if (r[2] - r[0]) * (r[3] - r[1]) > screen_area * 0.8:
                continue
            return r
        return None

    cands = []
    for text, bounds, ancestors in items:
        if not text:
            continue
        score = 0
        if text == target:
            score = 2
        elif target in text or text in target:
            score = 1
        if not score:
            continue
        rect = resolve(parse_rect(bounds), ancestors)
        if rect:
            cands.append((score, len(text), rect, text))
    if not cands:
        return None
    cands.sort(key=lambda c: (-c[0], c[1]))
    _, _, (x1, y1, x2, y2), text = cands[0]
    return (x1 + x2) // 2, (y1 + y2) // 2, text


def press(serial, x, y):
    """用 120ms 的同点按压代替 tap：自绘 UI（Flutter/游戏化）对瞬时 tap 可能不响应。"""
    run(["shell", "input", "swipe", str(x), str(y), str(x), str(y), "120"], serial=serial)


AD_CLOSE_TEXTS = ["跳过", "跳过广告", "关闭广告", "关闭", "×", "X", "我知道了", "稍后再说", "以后再说",
                  "稍后更新", "以后更新", "暂不更新", "暂不升级", "稍后升级"]
AD_CLOSE_IDS = ("iv_close", "img_close", "btn_close", "dialog_close", "close", "dismiss", "skip")


def find_close_node(xml):
    """按 resource-id 找无文字的关闭按钮，优先 iv_close/btn_close 这类明确命名，再按面积取最小。"""
    best = None
    for tag in re.findall(r"<node[^>]*>", xml):
        rid = re.search(r'resource-id="([^"]*)"', tag)
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not rid or not bounds:
            continue
        rid_v = rid.group(1).lower()
        if not any(k in rid_v for k in AD_CLOSE_IDS):
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0 or w > 240 or h > 240:
            continue
        strong = 0 if any(k in rid_v for k in ("iv_close", "img_close", "btn_close", "dialog_close")) else 1
        key = (strong, w * h)
        if best is None or key < best[0]:
            best = (key, (x1 + x2) // 2, (y1 + y2) // 2, rid.group(1))
    return (best[1], best[2], best[3]) if best else None


def current_pkg(serial):
    raw = run(["shell", "dumpsys", "window"], serial=serial, timeout=30)
    line = next((ln for ln in raw.splitlines() if "mCurrentFocus" in ln), "")
    m = re.search(r"\s([a-zA-Z0-9_.]+)/[a-zA-Z0-9_.$]+", line)
    return m.group(1) if m else ""


def dismiss_overlays(serial, rounds=8):
    """启动后自动关闭开屏广告/促销弹窗；优先点关闭按钮，找不到再对广告页回退。"""
    for _ in range(rounds):
        raw = run(["shell", "dumpsys", "window"], serial=serial, timeout=30)
        focus = next((ln for ln in raw.splitlines() if "mCurrentFocus" in ln), "")
        xml = dump_ui(serial)
        if "<hierarchy" not in xml:
            time.sleep(1.5)
            continue
        hit = None
        for txt in AD_CLOSE_TEXTS:
            hit = find_text_node(xml, txt)
            if hit:
                break
        if not hit:
            hit = find_close_node(xml)
        if hit:
            x, y, label = hit
            print(f"关闭弹层：{label} -> ({x},{y})")
            press(serial, x, y)
            time.sleep(3)
            continue
        if any(k in focus for k in ("AdActivity", "InterstitialAd", "SplashAd", "Advert")):
            run(["shell", "input", "keyevent", "4"], serial=serial)
            time.sleep(2)
            continue
        if "SplashActivity" in focus:
            # 开屏页尚未结束，等它自己进主页，不要按返回（会退出应用）
            time.sleep(3)
            continue
        break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--expect", default="")
    ap.add_argument("--serial")
    ap.add_argument("--tap", nargs=2, type=int, metavar=("X", "Y"))
    ap.add_argument("--tap-text", help="按界面文字点击（自动找节点中心，比坐标稳）")
    ap.add_argument("--swipe", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    ap.add_argument("--key", help="如 KEYCODE_BACK")
    ap.add_argument("--launch", help="启动包名（会先等启动完成，并自动关闭广告/弹窗）")
    ap.add_argument("--cold", action="store_true", help="配合 --launch 先 force-stop，保证冷启动")
    ap.add_argument("--dismiss-rounds", type=int, default=8, help="自动关闭广告的最大轮数")
    ap.add_argument("--wait", type=float, default=0, help="动作后等待秒数")
    ap.add_argument("--no-ui", action="store_true", help="跳过 UI 树抓取（视频播放等动画页面）")
    ap.add_argument("--quiet", action="store_true", help="只打印一行摘要")
    a = ap.parse_args()

    serial = pick_device(a.serial)
    root = os.path.abspath(a.root)
    step_slug = slugify(a.step)
    shots = os.path.join(root, "outputs", "screenshots")
    ui = os.path.join(root, "work", "ui")
    rec_path = os.path.join(root, "work", "steps.jsonl")
    os.makedirs(shots, exist_ok=True)
    os.makedirs(ui, exist_ok=True)

    run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serial=serial)
    if a.launch:
        if a.cold:
            run(["shell", "am", "force-stop", a.launch], serial=serial, timeout=30)
            time.sleep(1)
        run(["shell", "monkey", "-p", a.launch, "-c", "android.intent.category.LAUNCHER", "1"], serial=serial, timeout=60)
        time.sleep(5)
        dismiss_overlays(serial, a.dismiss_rounds)
        if current_pkg(serial) != a.launch and current_pkg(serial) not in ("", "com.android.systemui"):
            # 广告把页面带到站外（应用商店/落地页）时，回退重启一次
            run(["shell", "am", "force-stop", a.launch], serial=serial, timeout=30)
            time.sleep(1)
            run(["shell", "monkey", "-p", a.launch, "-c", "android.intent.category.LAUNCHER", "1"], serial=serial, timeout=60)
            time.sleep(5)
            dismiss_overlays(serial, a.dismiss_rounds)
    if a.tap_text:
        before = dump_ui(serial)
        hit = find_text_node(before, a.tap_text)
        if not hit:
            texts = [t for t in re.findall(r'text="([^"]*)"', before) if t.strip()]
            print(f"未找到文字节点：{a.tap_text}", file=sys.stderr)
            print("当前可点文字：" + " / ".join(texts[:40]), file=sys.stderr)
            sys.exit(1)
        x, y, hit_text = hit
        print(f"tap-text 命中「{hit_text}」-> ({x},{y})")
        press(serial, x, y)
    if a.tap:
        press(serial, a.tap[0], a.tap[1])
    if a.swipe:
        run(["shell", "input", "swipe", *[str(v) for v in a.swipe]], serial=serial)
    if a.key:
        run(["shell", "input", "keyevent", a.key], serial=serial)
    if a.wait:
        time.sleep(a.wait)

    png = run(["exec-out", "screencap", "-p"], serial=serial, binary=True, timeout=120)
    shot = os.path.join(shots, f"{step_slug}_{slugify(a.label)}.png")
    with open(shot, "wb") as f:
        f.write(png)

    xmlpath = os.path.join(ui, f"{step_slug}.xml")
    ui_ok = False
    xml = ""
    if not a.no_ui:
        xml = dump_ui(serial)
        ui_ok = "<hierarchy" in xml
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
