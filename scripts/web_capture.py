# -*- coding: utf-8 -*-
"""阶段 2（Web）：执行一步操作并取证（截图 + 页面快照 + 交互元素清单 + toast/弹窗）。

示例：
  python web_capture.py --root <run> --url http://127.0.0.1:8787/ --step r01 \
      --label "首页" --expect "展示创作页" --wait 1
  python web_capture.py --root <run> --url http://127.0.0.1:8787/ --step r02 \
      --label "生成大纲" --fill "#topic=周末爬山要带什么" --click "#sendBtn" --wait 1
  python web_capture.py --root <run> --url http://127.0.0.1:8787/ --step r03 \
      --label "作品库" --click "[data-go=library]" --wait 1
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_common import WebSession, parse_viewport, print_record, run_step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--url", required=True, help="站点根地址")
    ap.add_argument("--step", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--expect", default="")
    ap.add_argument("--goto", help="先跳转到某个路径（相对根地址）或完整 URL")
    ap.add_argument("--click", action="append", default=[], help="可重复：text=文字 / css=选择器 / #id")
    ap.add_argument("--fill", action="append", default=[], help="可重复：selector=value")
    ap.add_argument("--select", action="append", default=[], help="可重复：selector=value")
    ap.add_argument("--upload", action="append", default=[], help="可重复：selector=文件路径")
    ap.add_argument("--press", action="append", default=[], help="可重复：Enter / Control+Enter")
    ap.add_argument("--js", default="", help="附加执行 JS")
    ap.add_argument("--wait", type=float, default=0.6, help="动作后等待秒数")
    ap.add_argument("--delay", type=float, default=0.5, help="连续动作之间的间隔")
    ap.add_argument("--viewport", default="1440x960")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--no-dom", action="store_true", help="跳过 DOM 快照")
    ap.add_argument("--quiet", action="store_true", help="只打印一行摘要")
    a = ap.parse_args()

    with WebSession(a.root, a.url, parse_viewport(a.viewport), headless=not a.headed) as sess:
        # 默认先打开站点首页，--goto 可再跳转
        sess.goto(a.goto or "", wait=min(a.wait, 1.0))
        rec = run_step(sess, a.step, a.label, a.note, a.expect, goto=None,
                       clicks=a.click, fills=a.fill, selects=a.select, uploads=a.upload, presses=a.press,
                       js=a.js, delay=a.delay, wait=a.wait, full_page=a.full_page, no_dom=a.no_dom)

    print_record(rec, quiet=a.quiet)


if __name__ == "__main__":
    main()
