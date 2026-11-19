# -*- coding: utf-8 -*-
"""Web 平台公共能力：浏览器启动、持久会话、截图、页面快照、步骤记录。

浏览器优先级：本机 Chrome > 本机 Edge > Playwright 自带 Chromium。
所有步骤共用 run/work/browser-profile，localStorage 里的作品/配置会跨步骤保留。
"""
import io
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# 通用观察器：不依赖任何具体站点的 class/id，只按语义与可见性判断
COMMON_PRELUDE = r"""
  const norm = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const vis = el => {
    if (!el || el.nodeType !== 1) return false;
    if (!el.isConnected) return false;
    if (typeof el.checkVisibility === 'function') {
      try { if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false; } catch (e) {}
    }
    const r = el.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    return true;
  };
  const txt = el => norm(el.innerText || el.textContent || el.value || '');
  const label = el => norm(el.getAttribute('aria-label') || el.getAttribute('title') || txt(el));
  const pick = el => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      text: label(el).slice(0, 90),
      id: el.id || '',
      cls: norm(String(el.className || '')).slice(0, 80),
      placeholder: el.getAttribute('placeholder') || '',
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      href: el.getAttribute('href') || '',
      data: Object.fromEntries(Object.entries(el.dataset || {}).slice(0, 10)),
      box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
    };
  };
  // 页面容器：语义优先，找不到就按「可见且带标题」兜底
  const SCREEN_SEL = '[data-screen], [data-page], [role=tabpanel], .screen, .page, .view, .tab-pane, .tabpanel, main > section, #app > section';
  const screenRoots = () => {
    const cand = [...document.querySelectorAll(SCREEN_SEL)].filter(el => {
      if (!vis(el)) return false;
      const r = el.getBoundingClientRect();
      if (r.height < 100) return false;
      const role = el.getAttribute('role');
      const titled = [...el.querySelectorAll('h1, h2')].some(h => vis(h) && txt(h));
      return role === 'tabpanel' || titled || /screen|page|view|pane/i.test(el.id || '');
    });
    // 去掉被其它候选包含的子容器，避免同一屏被算多次
    return cand.filter(el => !cand.some(o => o !== el && o.contains(el)));
  };
  const CLICK_SEL = 'button, a[href], [role=button], [role=tab], [role=menuitem], input[type=submit], input[type=button], [data-go], [data-action], [data-tool], [data-open], [onclick], summary';
  const toastText = () => {
    const sel = '#toast, .toast, [class*="toast"], [class*="snack"], [role=status], [aria-live="polite"], [aria-live="assertive"]';
    const el = [...document.querySelectorAll(sel)].filter(e => vis(e) && txt(e) && txt(e).length < 400).pop();
    return el ? txt(el).slice(0, 300) : '';
  };
  const modalText = () => {
    const sel = 'dialog, [role=dialog], [role=alertdialog], [class*="modal"], [class*="dialog"]';
    const el = [...document.querySelectorAll(sel)]
      .filter(e => vis(e) && txt(e).length > 2)
      .sort((a, b) => txt(b).length - txt(a).length)[0];
    return el ? txt(el).slice(0, 1500) : '';
  };
"""

OBSERVE_JS = r"""
() => {
""" + COMMON_PRELUDE + r"""
  const roots = screenRoots();
  const screens = roots.map(el => el.id || el.dataset.screen || el.dataset.page || txt(el.querySelector('h1,h2') || el).slice(0, 20));
  if (!screens.length) screens.push(location.pathname || '/');
  const head = roots.flatMap(el => [...el.querySelectorAll('h1, h2, h3')].filter(vis).map(txt)).filter(Boolean);
  if (!head.length) head.push(...[...document.querySelectorAll('h1, h2')].filter(vis).map(txt).filter(Boolean).slice(0, 6));
  const buttons = [...document.querySelectorAll(CLICK_SEL)].filter(vis).map(pick);
  const inputs = [...document.querySelectorAll('input:not([type=file]):not([type=hidden]), textarea, select, [contenteditable=true]')].filter(vis).map(pick);
  return {
    url: location.href,
    title: document.title,
    screens,
    headings: head.slice(0, 12),
    toast: toastText(),
    modal: modalText(),
    buttons: buttons.slice(0, 150),
    inputs: inputs.slice(0, 80),
    bodyText: (document.body.innerText || '').replace(/\n{2,}/g, '\n').slice(0, 8000)
  };
}
"""

# 导航入口发现：语义容器（nav/aside/header）优先，找不到再全页兜底
NAV_JS = r"""
() => {
""" + COMMON_PRELUDE + r"""
  const scopeSel = 'nav, aside, header, [role=navigation], [class*="sidebar"], [class*="side"], [class*="menu"], [class*="nav"]';
  let scopes = [...document.querySelectorAll(scopeSel)].filter(vis);
  let fallback = false;
  if (!scopes.length) { scopes = [document.body]; fallback = true; }
  const seen = new Set();
  const items = [];
  for (const scope of scopes) {
    for (const el of scope.querySelectorAll('a, button, [role=button], [role=tab], [data-go], [data-screen]')) {
      if (!vis(el)) continue;
      if (!fallback && !scope.contains(el)) continue;
      const text = label(el);
      if (!text || text.length > 40) continue;
      const href = el.getAttribute('href') || '';
      const key = text + '|' + (el.dataset.go || el.dataset.screen || href);
      if (seen.has(key)) continue;
      seen.add(key);
      const r = el.getBoundingClientRect();
      const area = el.closest('nav, [role=navigation]') ? '导航'
        : (el.closest('header') ? '顶栏' : '工具');
      el.setAttribute('data-flowtest-nav', String(items.length));
      items.push({
        index: items.length, text, href,
        go: el.dataset.go || el.dataset.screen || '',
        area,
        region: r.x < window.innerWidth * 0.3 ? '侧栏' : '顶部',
        tag: el.tagName.toLowerCase()
      });
    }
  }
  return {items, fallback, scopes: scopes.length};
}
"""

# 当前屏可见的交互元素（用于功能地图的二级入口候选）
ITEMS_JS = r"""
() => {
""" + COMMON_PRELUDE + r"""
  const roots = screenRoots();
  const scope = roots[0] || document.querySelector('main') || document.body;
  const items = [];
  const seen = new Set();
  for (const el of scope.querySelectorAll(CLICK_SEL + ', input, textarea, select, [data-cat], [data-sample], [data-plan], [data-cycle]')) {
    if (!vis(el)) continue;
    const p = pick(el);
    const key = p.tag + '|' + p.text + '|' + p.placeholder + '|' + p.box.join(',');
    if (seen.has(key)) continue;
    seen.add(key);
    items.push(p);
  }
  return {scope: scope.id || scope.tagName.toLowerCase(), items: items.slice(0, 200)};
}
"""


def slugify(text):
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", str(text)).strip("-")
    return s[:40] or "step"


def pick_browser():
    for p in BROWSER_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def parse_viewport(text):
    if not text:
        return 1440, 960
    m = re.match(r"^(\d+)\s*[xX*]\s*(\d+)$", text.strip())
    if not m:
        raise SystemExit(f"视口格式应为 1440x960：{text}")
    return int(m.group(1)), int(m.group(2))


class WebSession:
    def __init__(self, root, base_url, viewport=(1440, 960), headless=True):
        self.root = os.path.abspath(root)
        self.base_url = base_url.rstrip("/") + "/" if base_url else ""
        self.viewport = viewport
        self.headless = headless
        self.profile = os.path.join(self.root, "work", "browser-profile")
        self.shots = os.path.join(self.root, "outputs", "screenshots")
        self.ui_dir = os.path.join(self.root, "work", "ui")
        self.steps_path = os.path.join(self.root, "work", "steps.jsonl")
        self.console_errors = []
        self.dialogs = []
        self._pw = None
        self.context = None
        self.page = None

    def __enter__(self):
        for d in (self.profile, self.shots, self.ui_dir, os.path.dirname(self.steps_path)):
            os.makedirs(d, exist_ok=True)
        self._pw = sync_playwright().start()
        exe = pick_browser()
        kwargs = dict(headless=self.headless, viewport={"width": self.viewport[0], "height": self.viewport[1]},
                      locale="zh-CN", device_scale_factor=1)
        if exe:
            kwargs["executable_path"] = exe
        try:
            self.context = self._pw.chromium.launch_persistent_context(self.profile, **kwargs)
        except Exception as e:
            raise SystemExit(f"浏览器启动失败：{e}\n可执行 python -m playwright install chromium 后重试")
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.on("console", self._on_console)
        self.page.on("dialog", self._on_dialog)
        return self

    def _on_console(self, msg):
        if msg.type == "error":
            self.console_errors.append(msg.text[:500])

    def _on_dialog(self, dialog):
        """确认框默认同意，并记录文案作为证据。"""
        self.dialogs.append(dialog.message)
        dialog.accept()

    def __exit__(self, exc_type, exc, tb):
        try:
            self.context.close()
        finally:
            self._pw.stop()

    def url(self, path=""):
        if not path:
            return self.base_url
        if re.match(r"^https?://", path):
            return path
        return self.base_url + path.lstrip("/")

    def goto(self, path="", wait=0.6):
        self.page.goto(self.url(path), wait_until="domcontentloaded", timeout=45000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        time.sleep(wait)

    def click(self, spec, timeout=8000):
        """spec: 以 css=/text= 开头显式指定；# . [ 开头按选择器；其他按可见文字。"""
        page = self.page
        if spec.startswith("text="):
            loc = page.get_by_text(spec[5:], exact=False).first
        elif spec.startswith("css="):
            loc = page.locator(spec[4:]).first
        elif spec[:1] in ("#", ".", "[", "("):
            loc = page.locator(spec).first
        else:
            loc = page.get_by_text(spec, exact=False).first
        loc.click(timeout=timeout)

    def fill(self, selector, value):
        page = self.page
        loc = page.locator(selector).first
        loc.fill(value, timeout=8000)

    def select(self, selector, value):
        self.page.locator(selector).first.select_option(value, timeout=8000)

    def press(self, key):
        self.page.keyboard.press(key)

    def observe(self):
        return self.page.evaluate(OBSERVE_JS)

    def screenshot(self, step, label, full_page=False):
        path = os.path.join(self.shots, f"{step}_{slugify(label)}.png")
        self.page.screenshot(path=path, full_page=full_page)
        return path

    def dump_dom(self, step):
        html_path = os.path.join(self.ui_dir, f"{step}.html")
        text_path = os.path.join(self.ui_dir, f"{step}.txt")
        with io.open(html_path, "w", encoding="utf-8") as f:
            f.write(self.page.content())
        with io.open(text_path, "w", encoding="utf-8") as f:
            obs = self.observe()
            f.write(obs.get("bodyText", ""))
        return html_path, text_path

    def record(self, rec):
        with io.open(self.steps_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_actions(sess, actions, delay=0.5):
    """按脚本顺序执行动作，支持 click / fill / select / upload / press / js / wait 混排。"""
    for act in actions:
        if not isinstance(act, dict):
            raise SystemExit(f"actions 每项应为对象：{act}")
        if "click" in act:
            specs = act["click"] if isinstance(act["click"], list) else [act["click"]]
            for spec in specs:
                sess.click(spec)
                time.sleep(act.get("delay", delay))
        elif "fill" in act:
            for selector, value in (act["fill"] or {}).items():
                sess.fill(selector, value)
                time.sleep(0.15)
        elif "select" in act:
            for selector, value in (act["select"] or {}).items():
                sess.select(selector, value)
                time.sleep(0.15)
        elif "upload" in act:
            for selector, value in (act["upload"] or {}).items():
                # 多文件用分号分隔，或直接传列表
                if isinstance(value, str):
                    paths = [p for p in value.split(";") if p] if ";" in value else value
                else:
                    paths = value
                sess.page.locator(selector).first.set_input_files(paths)
                time.sleep(0.3)
        elif "press" in act:
            keys = act["press"] if isinstance(act["press"], list) else [act["press"]]
            for key in keys:
                sess.press(key)
                time.sleep(delay)
        elif "js" in act:
            sess.page.evaluate(act["js"])
            time.sleep(delay)
        elif "wait" in act:
            time.sleep(float(act["wait"]))
        else:
            raise SystemExit(f"actions 里不认识的字段：{list(act)}")


def run_step(sess, step, label, note="", expect="", goto=None, clicks=(), fills=(), selects=(),
             uploads=(), presses=(), js="", delay=0.5, wait=0.4, full_page=False, no_dom=False,
             actions=None):
    """执行一组动作并取证，返回记录 dict。

    actions 若提供，按给定顺序执行（可混排 click/fill/select/upload/press/js/wait）；
    否则按 click → fill → select → upload → press → js 的固定顺序执行。
    """
    if goto is not None:
        sess.goto(goto, wait=wait)
    if actions:
        run_actions(sess, actions, delay=delay)
    else:
        for spec in clicks:
            sess.click(spec)
            time.sleep(delay)
        for item in fills:
            if "=" not in item:
                raise SystemExit(f"--fill 需要 selector=value 格式：{item}")
            selector, value = item.split("=", 1)
            sess.fill(selector, value)
            time.sleep(0.15)
        for item in selects:
            if "=" not in item:
                raise SystemExit(f"--select 需要 selector=value 格式：{item}")
            selector, value = item.split("=", 1)
            sess.select(selector, value)
            time.sleep(0.15)
        for item in uploads:
            if "=" not in item:
                raise SystemExit(f"--upload 需要 selector=文件路径 格式：{item}")
            selector, value = item.split("=", 1)
            sess.page.locator(selector).first.set_input_files(value)
            time.sleep(0.3)
        for key in presses:
            sess.press(key)
            time.sleep(delay)
        if js:
            sess.page.evaluate(js)
            time.sleep(delay)
    if wait:
        time.sleep(wait)

    shot = sess.screenshot(step, label, full_page=full_page)
    obs = sess.observe()
    html_path = text_path = ""
    if not no_dom:
        html_path, text_path = sess.dump_dom(step)

    rec = {
        "step": step,
        "label": label,
        "note": note,
        "expect": expect,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": obs.get("url", ""),
        "title": obs.get("title", ""),
        "screen": ",".join(obs.get("screens", [])),
        "headings": obs.get("headings", []),
        "toast": obs.get("toast", ""),
        "modal": obs.get("modal", ""),
        "body_text": obs.get("bodyText", ""),
        "screenshot": os.path.relpath(shot, sess.root),
        "ui_html": os.path.relpath(html_path, sess.root) if html_path else "",
        "ui_text": os.path.relpath(text_path, sess.root) if text_path else "",
        "buttons": obs.get("buttons", []),
        "inputs": obs.get("inputs", []),
        "console_errors": sess.console_errors[-10:],
        "dialogs": sess.dialogs[-10:],
        "size": os.path.getsize(shot),
    }
    sess.record(rec)
    return rec


def print_record(rec, quiet=False):
    if quiet:
        print(f'{rec["step"]} | {rec["screen"] or "-"} | {rec["toast"] or "-"} | {rec["screenshot"]}')
        for b in rec["buttons"][:40]:
            if b["text"]:
                print(f'  [{b["text"]}] {b["box"]}')
        for e in rec.get("console_errors", []):
            print(f'  [console] {e}')
        return
    slim = {k: rec[k] for k in ("step", "label", "url", "screen", "headings", "toast", "modal",
                                "buttons", "inputs", "console_errors", "screenshot")}
    print(json.dumps(slim, ensure_ascii=False, indent=2))
