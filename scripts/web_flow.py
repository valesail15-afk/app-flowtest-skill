# -*- coding: utf-8 -*-
"""阶段 2（Web）批量流程：在同一浏览器会话里按脚本逐步执行并逐步截图。

脚本是一个 JSON 数组，每项是一个步骤，字段：
  step       必填，步骤号 r01/r02...
  label      必填，截图标签
  goto       先跳转（相对站点根或完整 URL）
  click      数组：text=文字 / css=选择器 / #id
  fill       对象：{"#topic": "内容"}
  select     对象：{"#mode": "product"}
  press      数组：["Enter"]
  js         附加执行 JS
  wait       动作后等待秒数（默认 0.6）
  delay      连续动作间隔（默认 0.5）
  full       是否整页截图
  expect     期望说明（写进报告）
  expect_screen  期望屏幕 id
  must_see   数组：页面正文/弹窗/toast 中必须出现的文字
  must_not_see 数组：不应出现的文字
  download   是否期望触发下载（文件名会记录到 outputs/downloads/）

示例：
  python web_flow.py --root <run> --url http://127.0.0.1:8787/ --script steps.json
"""
import argparse
import io
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_common import WebSession, parse_viewport, run_step, slugify


def evaluate(rec, step):
    """按 must_see / must_not_see / expect_screen 给出通过与否。"""
    blob = "\n".join([rec.get("toast", ""), rec.get("modal", ""), rec.get("body_text", ""),
                      "\n".join(rec.get("headings", []))])
    problems = []
    if step.get("expect_screen"):
        screens = [s for s in rec.get("screen", "").split(",") if s]
        if step["expect_screen"] not in screens:
            problems.append(f"未进入 {step['expect_screen']}（当前 {screens}）")
    for word in step.get("must_see", []):
        if word not in blob:
            problems.append(f"缺少「{word}」")
    for word in step.get("must_not_see", []):
        if word in blob:
            problems.append(f"不应出现「{word}」")
    if "expect_eval" in step:
        got = rec.get("eval")
        if str(got).strip().lower() != str(step["expect_eval"]).strip().lower():
            problems.append(f"取值不符（期望 {step['expect_eval']}，实际 {got}）")
    return ("PASS" if not problems else "FAIL"), "；".join(problems)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--viewport", default="1440x960")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--only", help="只跑指定步骤，逗号分隔，如 r01,r02")
    ap.add_argument("--from", dest="start", help="从某一步开始")
    a = ap.parse_args()

    with io.open(a.script, encoding="utf-8") as f:
        steps = json.load(f)
    only = set(x.strip() for x in a.only.split(",") if x.strip()) if a.only else None
    started = not a.start

    root = os.path.abspath(a.root)
    download_dir = os.path.join(root, "outputs", "downloads")
    os.makedirs(download_dir, exist_ok=True)
    results = []

    with WebSession(root, a.url, parse_viewport(a.viewport), headless=not a.headed) as sess:
        sess.goto("", wait=0.6)
        for step in steps:
            sid = step["step"]
            if only and sid not in only:
                continue
            if not started:
                if sid == a.start:
                    started = True
                else:
                    continue
            label = step.get("label", sid)
            try:
                if step.get("download"):
                    with sess.page.expect_download(timeout=20000) as info:
                        rec = run_step(sess, sid, label, step.get("note", ""), step.get("expect", ""),
                                       goto=step.get("goto"), clicks=step.get("click", []),
                                       fills=[f"{k}={v}" for k, v in step.get("fill", {}).items()],
                                       selects=[f"{k}={v}" for k, v in step.get("select", {}).items()],
                                       uploads=[f"{k}={v}" for k, v in step.get("upload", {}).items()],
                                       presses=step.get("press", []), js=step.get("js", ""),
                                       delay=step.get("delay", 0.5), wait=step.get("wait", 0.6),
                                       full_page=step.get("full", False), actions=step.get("actions"))
                    dl = info.value
                    name = slugify(sid + "-" + dl.suggested_filename)
                    path = os.path.join(download_dir, name)
                    dl.save_as(path)
                    rec["download"] = os.path.relpath(path, root)
                    rec["download_name"] = dl.suggested_filename
                else:
                    rec = run_step(sess, sid, label, step.get("note", ""), step.get("expect", ""),
                                   goto=step.get("goto"), clicks=step.get("click", []),
                                   fills=[f"{k}={v}" for k, v in step.get("fill", {}).items()],
                                   selects=[f"{k}={v}" for k, v in step.get("select", {}).items()],
                                   uploads=[f"{k}={v}" for k, v in step.get("upload", {}).items()],
                                   presses=step.get("press", []), js=step.get("js", ""),
                                   delay=step.get("delay", 0.5), wait=step.get("wait", 0.6),
                                   full_page=step.get("full", False), actions=step.get("actions"))
                if step.get("eval"):
                    rec["eval"] = sess.page.evaluate(step["eval"])
                verdict, reason = evaluate(rec, step)
            except Exception as e:
                rec = {"step": sid, "label": label, "error": str(e), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
                try:
                    shot = sess.screenshot(sid, label + "-异常", full_page=True)
                    rec["screenshot"] = os.path.relpath(shot, root)
                except Exception:
                    pass
                sess.record(rec)
                verdict, reason = "ERROR", str(e).splitlines()[0][:160]
                print(traceback.format_exc(), file=sys.stderr)
            rec["verdict"] = verdict
            rec["reason"] = reason
            results.append(rec)
            print(f'{sid} | {verdict:5} | {label} | {reason or "-"} | {rec.get("screenshot", "")}')

    summary = {
        "url": a.url,
        "steps": len(results),
        "pass": sum(1 for r in results if r.get("verdict") == "PASS"),
        "fail": sum(1 for r in results if r.get("verdict") == "FAIL"),
        "error": sum(1 for r in results if r.get("verdict") == "ERROR"),
        "results": [{"step": r["step"], "label": r.get("label"), "verdict": r.get("verdict"),
                     "reason": r.get("reason"), "screenshot": r.get("screenshot"),
                     "toast": r.get("toast", ""), "download": r.get("download", "")} for r in results],
    }
    with io.open(os.path.join(root, "work", "flow-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
