# -*- coding: utf-8 -*-
"""Stage 2: capture one test step (optional action -> wait -> screenshot + UI tree + activity).

Example:
  python capture.py --root <run> --step r03 --label "首页-发现" --note "冷启动后等待6秒" \
      --expect "进入发现首页" --launch com.example.app --cold
  python capture.py --root <run> --step r04 --label "搜索页" --tap-text "搜索" --wait-for "text:搜索"
  python capture.py --root <run> --step r05 --label "转换结果" --tap 360 1200 \
      --wait-for "text:处理完成" --verdict fail --note "输出体积与源文件一致"
  python capture.py --root <run> --step r06 --label "回到首页" --key KEYCODE_BACK \
      --wait-for "activity:.MainActivity"
  python capture.py --root <run> --step r07 --label "进入GIF工具" --scroll-to "text:GIF工具" \
      --tap-text "GIF工具" --verdict partial
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

VERDICTS = ("pass", "fail", "partial", "unverified")


def current_activity(serial):
    acts = run(["shell", "dumpsys", "activity", "activities"], serial=serial, timeout=60)
    m = re.search(r"mResumedActivity[^\r\n]*?([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)", acts)
    return m.group(1) if m else ""


def current_pkg(serial):
    raw = run(["shell", "dumpsys", "window"], serial=serial, timeout=30)
    line = next((ln for ln in raw.splitlines() if "mCurrentFocus" in ln), "")
    m = re.search(r"\s([a-zA-Z0-9_.]+)/[A-Za-z0-9_.$]+", line)
    return m.group(1) if m else ""


def dump_ui(serial, retries=2):
    """返回 (xml, ok)；先删远端旧文件，避免读到上一次的陈旧 UI 树。"""
    run(["shell", "rm", "-f", "/sdcard/ui.xml"], serial=serial, timeout=30)
    for _ in range(retries):
        try:
            out = run(["shell", "uiautomator", "dump", "/sdcard/ui.xml"], serial=serial, timeout=60)
            if "dumped to" in out:
                xml = run(["exec-out", "cat", "/sdcard/ui.xml"], serial=serial, timeout=60)
                if "<hierarchy" in xml:
                    return xml, True
        except Exception:
            pass
        time.sleep(1)
    return "", False


def parse_rect(bounds):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def find_text_node(xml, target):
    """按 text/content-desc 精确优先、包含兜底找中心点，返回 (cx, cy, 文本, bounds)。

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
    return (x1 + x2) // 2, (y1 + y2) // 2, text, f"[{x1},{y1}][{x2},{y2}]"


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


def dismiss_overlays(serial, rounds=8):
    """启动后自动关闭开屏广告/促销弹窗；优先点关闭按钮，找不到再对广告页回退。"""
    for _ in range(rounds):
        raw = run(["shell", "dumpsys", "window"], serial=serial, timeout=30)
        focus = next((ln for ln in raw.splitlines() if "mCurrentFocus" in ln), "")
        xml, ok = dump_ui(serial)
        if not ok:
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
            x, y, label = hit[0], hit[1], hit[2]
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


def wait_for(serial, spec, timeout, interval):
    """轮询直到界面满足条件。spec: text:|desc:|id:|activity:|package:值"""
    kind, _, val = spec.partition(":")
    kind, val = kind.strip().lower(), val.strip()
    if kind not in ("text", "desc", "id", "activity", "package") or not val:
        raise SystemExit("--wait-for 格式错误，支持 text:关键字 | desc:关键字 | id:资源ID | activity:Activity | package:包名")
    deadline = time.time() + timeout
    tries = 0
    last_xml = ""
    while True:
        tries += 1
        if kind in ("activity", "package"):
            got = current_activity(serial)
            if val.lower() in got.lower():
                return True, tries, last_xml
        else:
            xml, ok = dump_ui(serial, retries=1)
            if ok:
                last_xml = xml
                if kind == "text":
                    hit = any(val in t for t in re.findall(r'text="([^"]*)"', xml))
                elif kind == "desc":
                    hit = any(val in d for d in re.findall(r'content-desc="([^"]*)"', xml))
                else:
                    hit = any(val in i for i in re.findall(r'resource-id="([^"]*)"', xml))
                if hit:
                    return True, tries, last_xml
        if time.time() >= deadline:
            return False, tries, last_xml
        time.sleep(interval)


def screen_size(serial):
    out = run(["shell", "wm", "size"], serial=serial, timeout=30)
    m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 720, 1600


def scroll_to(serial, spec, max_times):
    """向下滚动直到界面出现目标文本（列表项在屏幕外时 uiautomator 拿不到）。spec: text:xx|desc:xx"""
    kind, _, val = spec.partition(":")
    kind, val = kind.strip().lower(), val.strip()
    if kind not in ("text", "desc") or not val:
        raise SystemExit("--scroll-to 格式错误，支持 text:关键字 | desc:关键字")
    w, h = screen_size(serial)
    x, y1, y2 = w // 2, int(h * 0.79), int(h * 0.33)
    for i in range(max_times):
        xml, ok = dump_ui(serial, retries=1)
        if ok:
            pat = r'text="([^"]*)"' if kind == "text" else r'content-desc="([^"]*)"'
            if any(val in t for t in re.findall(pat, xml)):
                return True, i, xml
        run(["shell", "input", "swipe", str(x), str(y1), str(x), str(y2), "320"], serial=serial)
        time.sleep(0.8)
    xml, ok = dump_ui(serial, retries=2)
    if ok:
        pat = r'text="([^"]*)"' if kind == "text" else r'content-desc="([^"]*)"'
        # Flutter 滚动过程中的语义树可能暂时缺文本，滚动结束后再判一次，避免误报未找到
        if any(val in t for t in re.findall(pat, xml)):
            return True, max_times, xml
        return False, max_times, xml
    return False, max_times, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--step", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--expect", default="")
    ap.add_argument("--serial")
    ap.add_argument("--tap", nargs=2, type=int, metavar=("X", "Y"))
    ap.add_argument("--tap-text", help="按界面文本点击（自动找节点中心，比坐标稳）")
    ap.add_argument("--tap-desc", help="按 content-desc 点击")
    ap.add_argument("--swipe", nargs=4, type=int, metavar=("X1", "Y1", "X2", "Y2"))
    ap.add_argument("--key", help="如 KEYCODE_BACK")
    ap.add_argument("--clear", action="store_true", help="先把光标移到末尾并删空当前输入框（配合 --tap 点输入框后使用）")
    ap.add_argument("--input-text", help="输入文本（ASCII；空格自动转义为 %s），中文请用输入法")
    ap.add_argument("--launch", help="启动包名（会先等启动完成，并自动关闭广告/弹窗）")
    ap.add_argument("--cold", action="store_true", help="配合 --launch 先 force-stop，保证冷启动")
    ap.add_argument("--dismiss-rounds", type=int, default=8, help="自动关闭广告的最大轮数")
    ap.add_argument("--wait", type=float, default=0, help="动作后固定等待秒数")
    ap.add_argument("--wait-for", default="", help="轮询等待条件：text:xx | desc:xx | id:xx | activity:xx | package:xx")
    ap.add_argument("--wait-for-timeout", type=float, default=15, help="--wait-for 超时秒数，默认 15")
    ap.add_argument("--wait-interval", type=float, default=0.6, help="--wait-for 轮询间隔，默认 0.6")
    ap.add_argument("--scroll-to", default="", help="向下滚动直到出现：text:xx | desc:xx")
    ap.add_argument("--scroll-max", type=int, default=8, help="--scroll-to 最多滚动次数，默认 8")
    ap.add_argument("--verdict", choices=VERDICTS, default="", help="本步判定：pass/fail/partial/unverified")
    ap.add_argument("--burst", type=int, default=1, help="连拍张数，用于捕捉 Toast/一闪而过的提示（默认 1）")
    ap.add_argument("--burst-interval", type=float, default=0.4, help="连拍间隔秒数，默认 0.4")
    ap.add_argument("--settle", type=float, default=0.6, help="动作后截图前的稳定等待秒数，避免截到上一帧（0 关闭）")
    ap.add_argument("--no-ui", action="store_true", help="跳过 UI 树抓取（视频播放等动画页面）")
    ap.add_argument("--log-grep", help="动作后抓取 logcat 最近匹配行（正则），用于接口参数/返回值的证据留存")
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

    tap_hit = None
    if a.tap_text or a.tap_desc:
        tx, ok = dump_ui(serial, retries=2)
        if not ok:
            raise SystemExit("无法抓取 UI 树，--tap-text/--tap-desc 不可用，请改用 --tap 坐标")
        target = a.tap_text or a.tap_desc
        found = find_text_node(tx, target)
        if not found:
            texts = [t for t in re.findall(r'text="([^"]*)"', tx) if t.strip()][:15]
            descs = [d for d in re.findall(r'content-desc="([^"]*)"', tx) if d.strip()][:15]
            raise SystemExit(f'界面未找到「{target}」，先截图确认当前页面\n当前文本: {texts}\n当前描述: {descs}')
        cx, cy, hit_text, hit_bounds = found
        press(serial, cx, cy)
        tap_hit = {"by": target, "hit": hit_text, "x": cx, "y": cy, "bounds": hit_bounds}
    if a.tap:
        press(serial, a.tap[0], a.tap[1])
    if a.clear:
        run(["shell", "input", "keyevent", "KEYCODE_MOVE_END"], serial=serial)
        for _ in range(40):
            run(["shell", "input", "keyevent", "KEYCODE_DEL"], serial=serial)
    if a.input_text:
        run(["shell", "input", "text", a.input_text.replace(" ", "%s")], serial=serial)
    if a.swipe:
        run(["shell", "input", "swipe", *[str(v) for v in a.swipe]], serial=serial)
    if a.key:
        run(["shell", "input", "keyevent", a.key], serial=serial)
    if a.wait:
        time.sleep(a.wait)

    polled_xml = ""
    scroll_ok, scroll_tries = None, 0
    if a.scroll_to:
        scroll_ok, scroll_tries, sx = scroll_to(serial, a.scroll_to, a.scroll_max)
        if sx:
            polled_xml = sx

    wait_ok, wait_tries = None, 0
    if a.wait_for:
        wait_ok, wait_tries, wx = wait_for(serial, a.wait_for, a.wait_for_timeout, a.wait_interval)
        if wx:
            polled_xml = wx

    # vivo/Flutter 上页面切换后立即 screencap 容易拿到上一帧（截图还是旧页面、UI 树已是新页面）。
    # 有动作且未显式 --wait 时补一个短稳定期；仍在动画的页面可用 --no-ui + --settle 0 跳过。
    if a.settle > 0 and (a.tap or a.tap_text or a.tap_desc or a.swipe or a.key or a.clear or a.input_text) and not a.wait:
        time.sleep(a.settle)

    png = run(["exec-out", "screencap", "-p"], serial=serial, binary=True, timeout=120)
    shot = os.path.join(shots, f"{step_slug}_{slugify(a.label)}.png")
    with open(shot, "wb") as f:
        f.write(png)
    burst_files = []
    for i in range(2, a.burst + 1):
        time.sleep(a.burst_interval)
        extra = run(["exec-out", "screencap", "-p"], serial=serial, binary=True, timeout=120)
        p = os.path.join(shots, f"{step_slug}_{slugify(a.label)}_b{i}.png")
        with open(p, "wb") as f:
            f.write(extra)
        burst_files.append(os.path.relpath(p, root))

    xmlpath = os.path.join(ui, f"{step_slug}.xml")
    ui_ok = False
    xml = ""
    if not a.no_ui:
        if polled_xml:
            xml, ui_ok = polled_xml, True
        else:
            xml, ui_ok = dump_ui(serial, retries=3)
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
            mm = re.search(rf'{name}="([^"]*)"', tag)
            return mm.group(1) if mm else ""
        bounds = attr("bounds")
        if bounds in ("", "[0,0][0,0]"):
            continue
        clickables.append({
            "text": attr("text"), "desc": attr("content-desc"),
            "id": attr("resource-id"), "class": attr("class"), "bounds": bounds,
        })

    log_lines = []
    if a.log_grep:
        try:
            log_out = run(["logcat", "-d", "-t", "4000"], serial=serial, timeout=90)
            rx = re.compile(a.log_grep)
            log_lines = [ln for ln in log_out.splitlines() if rx.search(ln)][-20:]
        except Exception as e:
            log_lines = [f"<logcat 抓取失败: {e}>"]

    rec = {
        "step": a.step,
        "label": a.label,
        "note": a.note,
        "expect": a.expect,
        "verdict": a.verdict,
        "settle": a.settle,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "serial": serial,
        "current_focus": m.group(1).strip() if m else "",
        "resumed_activity": m2.group(1) if m2 else "",
        "screenshot": os.path.relpath(shot, root),
        "burst": burst_files,
        "ui_xml": os.path.relpath(xmlpath, root),
        "ui_ok": ui_ok,
        "wait_for": a.wait_for,
        "wait_for_ok": wait_ok,
        "wait_for_tries": wait_tries,
        "tap_by_text": a.tap_text or a.tap_desc or "",
        "input_text": a.input_text or "",
        "tap_hit": tap_hit,
        "scroll_to": a.scroll_to,
        "scroll_ok": scroll_ok,
        "scroll_tries": scroll_tries,
        "texts": texts[:200],
        "descs": descs[:100],
        "clickables": clickables[:80],
        "log_grep": a.log_grep or "",
        "log_lines": log_lines,
        "size": len(png),
    }
    with io.open(rec_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    warn = ""
    if wait_ok is False:
        warn += f"  ! wait-for 超时({a.wait_for_timeout}s, {wait_tries} 次): {a.wait_for}"
    if scroll_ok is False:
        warn += f"  ! scroll-to 未找到({scroll_tries} 次滚动): {a.scroll_to}"
    if a.quiet:
        print(f'{a.step} | verdict={a.verdict or "-"} | ui_ok={ui_ok} | {rec["resumed_activity"]} | {rec["screenshot"]}{warn}')
        if tap_hit:
            print(f'  tap「{tap_hit["by"]}」-> ({tap_hit["x"]},{tap_hit["y"]}) {tap_hit["bounds"]}')
        for c in clickables[:40]:
            print(f'  [{c["text"] or c["desc"] or c["id"]}] {c["bounds"]}')
        for ln in log_lines[-5:]:
            print(f'  log> {ln.strip()[:200]}')
    else:
        print(json.dumps({k: rec[k] for k in ["step", "label", "verdict", "current_focus", "resumed_activity",
                                              "ui_ok", "wait_for", "wait_for_ok", "texts", "descs",
                                              "clickables", "screenshot"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
