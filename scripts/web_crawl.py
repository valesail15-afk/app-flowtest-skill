# -*- coding: utf-8 -*-
"""阶段 1（Web）：自动遍历导航/链接，抓入口、按钮、表单，生成 feature-map.yaml 草稿。

不假设站点使用任何特定 class/id：
  - 导航优先从 nav/aside/header/[role=navigation] 等语义容器发现，找不到再全页兜底；
  - 无 href 的导航按钮按索引点击（SPA），有 href 的按链接访问（多页站点）；
  - 每次进入后抓当前可见页面容器、标题、按钮、输入框。

自动产出只是候选；`how` 需要按实测点击路径回填后才能作为最终地图。
"""
import argparse
import io
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_common import ITEMS_JS, NAV_JS, WebSession, parse_viewport

NOISE = {
    "×", "x", "关闭", "收起", "展开", "返回", "上一步", "下一步", "下载", "上传", "删除", "清空",
    "处理中", "加载中", "确定", "取消", "保存", "提交", "登录", "退出", "更多", "复制", "重试",
}
# 引导/营销/工具条类文案，不是功能入口（各站点通用，不绑定具体站点）
GUIDE_RE = re.compile(
    r"(拖动.*书签|书签栏|去安装|关闭引导|打开更便捷|扫码|下载.*(APP|App|app|客户端)"
    r"|^跳过$|^返回顶部$|^收起$|^展开$|收起侧栏|展开侧栏|切换深色|切换浅色|切换深浅色"
    r"|时间轴.*滚动|^回到今天$|^上个月$|^下个月$|拖动排序|^放大$|^缩小$|^全屏$)"
)
PUNCT_RE = re.compile(r"[，。～…；！？]")


def is_feature_text(text):
    """判断一段可见文字是否值得作为地图条目。"""
    if not text or len(text) > 20:
        return False
    if text.lower() in NOISE or GUIDE_RE.search(text) or PUNCT_RE.search(text):
        return False
    return True



def same_origin(base, href):
    a, b = urlparse(base), urlparse(href)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def wait_idle(sess, seconds=0.8):
    try:
        sess.page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass
    time.sleep(seconds)


def capture(sess, base, step, label, nav_item):
    shot = sess.screenshot(step, label, full_page=True)
    obs = sess.observe()
    items = sess.page.evaluate(ITEMS_JS)
    return {
        "step": step,
        "nav": nav_item,
        "url": obs.get("url"),
        "title": obs.get("title"),
        "screens": obs.get("screens"),
        "headings": obs.get("headings"),
        "toast": obs.get("toast"),
        "modal": obs.get("modal"),
        "items": items.get("items", []),
        "scope": items.get("scope", ""),
        "screenshot": os.path.relpath(shot, base),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True, help="feature-map.yaml 草稿输出路径")
    ap.add_argument("--root", help="测试产物根目录（默认取 yaml 所在目录）")
    ap.add_argument("--viewport", default="1440x960")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--max", type=int, default=30, help="最多遍历多少个入口")
    ap.add_argument("--max-links", type=int, default=10, help="无导航时最多跟随多少个同源链接")
    ap.add_argument("--max-per-screen", type=int, default=15, help="每屏最多收录多少个功能候选（按面积优先）")
    ap.add_argument("--max-features", type=int, default=120, help="地图总条目上限")
    a = ap.parse_args()

    out_yaml = os.path.abspath(a.out)
    root = os.path.abspath(a.root or os.path.dirname(out_yaml))
    for d in ["work/ui", "outputs/screenshots"]:
        os.makedirs(os.path.join(root, d), exist_ok=True)

    screens = []
    with WebSession(root, a.url, parse_viewport(a.viewport), headless=not a.headed) as sess:
        sess.goto("", wait=1.0)
        nav = sess.page.evaluate(NAV_JS)
        all_entries = nav.get("items", [])
        # 只把真正的导航项逐屏遍历；主题切换、收起侧栏这类工具按钮不算导航
        navs = [x for x in all_entries if x.get("area") == "导航"]
        tools = [x for x in all_entries if x.get("area") != "导航"]

        # 没有可用导航时跟随同源链接（多页站点/文档站）
        follow_links = not navs
        links = []
        if follow_links:
            links = sess.page.evaluate(r"""
            () => {
              const out = [], seen = new Set();
              for (const el of document.querySelectorAll('a[href]')) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                if (r.width <= 2 || r.height <= 2 || s.display === 'none' || s.visibility === 'hidden') continue;
                const text = (el.innerText || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
                const href = el.href || '';
                if (!text || text.length > 40 || seen.has(href)) continue;
                seen.add(href);
                out.push({text, href});
              }
              return out;
            }
            """)
            links = [x for x in links if same_origin(a.url, x["href"])][: a.max_links]
            for i, link in enumerate(links, 1):
                navs.append({"index": -i, "text": link["text"], "href": link["href"],
                             "go": "", "region": "链接", "tag": "a"})

        def click_by_text(item):
            """重新收集一次导航（页面可能已刷新），按文字+data 定位后点击。"""
            if sess.page.url.split("#")[0] != sess.url("").split("#")[0]:
                sess.goto("", wait=0.6)
            fresh = sess.page.evaluate(NAV_JS).get("items", [])
            hit = next((x for x in fresh if x["text"] == item["text"] and x.get("go") == item.get("go")), None)
            if not hit:
                raise RuntimeError("未找到导航入口")
            sess.page.evaluate("i => document.querySelectorAll('[data-flowtest-nav]')[i].click()", hit["index"])

        navs = navs[: a.max]
        for i, item in enumerate(navs, 1):
            step = f"c{i:02d}"
            try:
                target = item["href"]
                if target:
                    if not re.match(r"^https?://", target):
                        target = urljoin(sess.url(""), target)
                    if same_origin(a.url, target) and target.split("#")[0] != sess.url("").split("#")[0]:
                        sess.page.goto(target, wait_until="domcontentloaded", timeout=45000)
                    else:
                        click_by_text(item)
                else:
                    click_by_text(item)
                wait_idle(sess, 0.8)
            except Exception as e:
                print(f"跳过 {item['text']}：{e}", file=sys.stderr)
                continue
            screens.append(capture(sess, root, step, item["text"], item))

    # 生成草稿条目
    features, seen = [], set()

    def add(name, where, how, aliases=None):
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        if not is_feature_text(name):
            return
        # 同名只保留一条：优先导航，其次首次出现，避免同一功能在每页重复
        if name in seen or len(features) >= a.max_features:
            return
        seen.add(name)
        row = {"name": name, "where": where, "how": how}
        if aliases:
            row["aliases"] = aliases
        features.append(row)

    # 先收录导航页（层级最稳定），再补侧栏工具，最后补每屏的功能候选
    for s in screens:
        item = s["nav"]
        label = item["text"]
        region = item.get("region", "导航")
        where_base = f"{region}导航 > {label}" if region != "链接" else f"页面链接 > {label}"
        how = f"点击{region}导航「{label}」" if region != "链接" else f"打开链接「{label}」"
        add(label, where_base, how)

    for t in tools:
        region = t.get("region", "侧栏")
        # 顶栏多为安装/引导类工具，不进入功能地图；侧栏工具才是功能入口
        if region == "顶部" and GUIDE_RE.search(t["text"]):
            continue
        add(t["text"], f"{region}工具 > {t['text']}",
            f"点击{region}工具按钮「{t['text']}」")

    for s in screens:
        label = s["nav"]["text"]
        # 按面积从大到小取每屏最显眼的候选，避免把整页按钮都收进来
        cand = []
        for it in s["items"]:
            text = re.sub(r"\s+", " ", it["text"]).strip()
            if it["tag"] in ("input", "textarea", "select"):
                name = it["placeholder"] or it.get("data", {}).get("title") or ""
                if not is_feature_text(name):
                    continue
                cand.append((0, name, f"{label} > 表单", f"进入「{label}」> 填写「{name}」"))
                continue
            if not is_feature_text(text):
                continue
            box = it.get("box") or [0, 0, 0, 0]
            area = max(0, box[2]) * max(0, box[3])
            cand.append((area, text, f"{label} > {text}", f"进入「{label}」> 点击「{text}」"))
        cand.sort(key=lambda x: x[0], reverse=True)
        for _, name, where, how in cand[: a.max_per_screen]:
            add(name, where, how)

    data = {
        "site": a.url,
        "features": features,
    }
    try:
        import yaml
        with io.open(out_yaml, "w", encoding="utf-8") as f:
            f.write("# 由 app-flowtest web_crawl 自动遍历生成，where/how 需按实测回填\n")
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except ImportError:
        with io.open(out_yaml, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    with io.open(os.path.join(root, "work", "crawl.json"), "w", encoding="utf-8") as f:
        json.dump({"url": a.url, "nav": nav, "screens": screens}, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "url": a.url,
        "fallback": follow_links,
        "screens": [{"step": s["step"], "nav": s["nav"]["text"], "url": s["url"],
                     "headings": s["headings"], "items": len(s["items"]),
                     "screenshot": s["screenshot"]} for s in screens],
        "features": len(features),
        "yaml": out_yaml,
        "crawl": os.path.join(root, "work", "crawl.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
