# -*- coding: utf-8 -*-
"""Stage 1 (static half): extract modules/routes/components from an APK -> feature-map.yaml draft.

Dynamic verification still required: open each module and fill `where` / `how`.
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # androguard 4.x 默认 DEBUG 级日志
    from loguru import logger
    logger.remove()
except Exception:
    pass

ROUTE_RE = re.compile(r"^/[a-z][a-z0-9_\-]*(/[a-z0-9_\-:<>]+)*$")
FILE_PREFIXES = ("/system", "/data", "/proc", "/dev", "/sdcard", "/storage", "/assets",
                 "/tmp", "/vendor", "/apex", "/mnt", "/usr", "/etc", "/product", "/odm")
SDK_HINTS = ("com.qq.e", "com.bytedance", "com.umeng", "com.alipay", "com.tencent",
             "com.google", "com.facebook", "com.applovin", "com.unity3d", "com.vungle",
             "com.mintegral", "com.pangle", "com.anythink", "com.sigmob", "com.kwad",
             "com.bykv", "com.bytedance.sdk", "com.beizi", "com.huawei.hms", "com.miui",
             "com.ss.android", "com.taobao", "com.igexin", "com.getui")


def static_scan(apk_path, extra_prefixes=()):
    from androguard.core.apk import APK
    apk = APK(apk_path)
    pkg = apk.get_package()
    info = {
        "apk": os.path.abspath(apk_path),
        "size": os.path.getsize(apk_path),
        "package": pkg,
        "version_name": apk.get_androidversion_name(),
        "version_code": apk.get_androidversion_code(),
        "min_sdk": apk.get_min_sdk_version(),
        "target_sdk": apk.get_target_sdk_version(),
        "main_activity": apk.get_main_activity(),
        "activities": apk.get_activities(),
        "services": apk.get_services(),
        "permissions": apk.get_permissions(),
    }

    # 业务包识别：applicationId 前缀 + 启动 Activity 所在的三段包前缀 + 用户显式指定前缀。
    # 很多壳工程会把主业务放在另一个包（如 com.wnformat.app.*），只认 manifest 包名会漏掉全部主页面。
    main = info.get("main_activity") or ""
    roots = {pkg}
    if main:
        roots.add(".".join(main.split(".")[:3]))
    roots.update(p.strip().rstrip(".") + "." for p in extra_prefixes if p.strip())

    business = []
    for name in info["activities"]:
        if any(name.startswith(h) for h in SDK_HINTS):
            continue
        if any(name.startswith(r) for r in roots):
            business.append(name)
    info["business_activities"] = sorted(set(business))

    routes = set()
    with zipfile.ZipFile(apk_path) as z:
        flutter_libs = [n for n in z.namelist() if n.endswith("libapp.so")]
        info["flutter"] = bool(flutter_libs)
        info["flutter_libs"] = flutter_libs
        for lib in flutter_libs:
            data = z.read(lib)
            for token in re.findall(rb"[\x20-\x7e]{3,80}", data):
                s = token.decode("ascii", "ignore").strip()
                if ROUTE_RE.match(s) and len(s) <= 48 and not s.startswith(FILE_PREFIXES):
                    routes.add(s)
    info["routes"] = sorted(routes)
    return info


ROUTE_KINDS = (
    ("会员/支付", ("vip", "pay", "order", "redeem", "benefit")),
    ("登录/账号", ("auth", "login", "register", "password", "sms", "profile")),
    ("壁纸/内容", ("wallpaper", "category", "categor", "discover", "home", "search", "media", "video")),
    ("收藏/历史", ("favorite", "library", "history")),
    ("设置/反馈", ("setting", "feedback", "report")),
    ("信息/协议", ("legal", "about", "policy", "agreement", "onboarding")),
)


def is_noise_route(route):
    """混淆后的短路由（/a1、/c7、/trk、/w1）不是可用入口，只保留作参考。"""
    name = route.strip("/")
    if "/" in name or not name:
        return False
    if name.endswith("_"):
        return True
    return len(name) <= 4 and not re.search(r"[aeiou]", name)


def flutter_kind(route):
    if is_noise_route(route):
        return "疑似混淆路由"
    low = route.lower()
    for kind, keys in ROUTE_KINDS:
        if any(k in low for k in keys):
            return kind
    return "Flutter 页面"


def build_map(info):
    pkg_short = info["package"].split(".")[-1]
    modules = []
    for cls in info.get("business_activities", []):
        short = cls.split(".")[-1]
        if short == info.get("main_activity", "").split(".")[-1]:
            kind = "启动入口"
        elif any(k in short.lower() for k in ("vip", "recharge", "pay", "order")):
            kind = "会员/支付"
        elif any(k in short.lower() for k in ("login", "user", "account")):
            kind = "登录/账号"
        elif any(k in short.lower() for k in ("about", "policy", "agreement", "web")):
            kind = "信息/协议"
        elif any(k in short.lower() for k in ("convert", "format", "compress", "crop", "rotate",
                                              "trim", "merge", "extract", "watermark", "mute",
                                              "volume", "resize", "record")):
            kind = "转换/编辑"
        elif any(k in short.lower() for k in ("player", "preview", "detail")):
            kind = "预览/播放"
        elif any(k in short.lower() for k in ("pick", "select", "choose", "file", "folder")):
            kind = "选择文件"
        elif "main" in short.lower():
            kind = "主界面"
        else:
            kind = "原生页面"
        modules.append({"name": short, "entry": cls, "type": "activity", "kind": kind})
    for route in info.get("routes", []):
        # Flutter 路由必须保留完整路径做名字，只取首段会把 /pay/plans、/pay/orders 合并丢失
        modules.append({"name": route.strip("/") or route, "entry": route,
                        "type": "flutter_route", "kind": flutter_kind(route)})

    features, seen = [], set()
    for m in modules:
        if m["entry"] in seen:
            continue
        if m.get("kind") == "疑似混淆路由":
            continue
        seen.add(m["entry"])
        features.append({
            "name": m["name"],
            "where": f"{pkg_short} > {m['entry']}",
            "how": "待实测补充",
        })

    return {
        "app": {
            "package": info["package"],
            "version": f"{info.get('version_name')} ({info.get('version_code')})",
            "min_sdk": info.get("min_sdk"),
            "target_sdk": info.get("target_sdk"),
            "flutter": info.get("flutter"),
        },
        "modules": modules,
        "features": features,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", required=True)
    ap.add_argument("--out", required=True, help="feature-map.yaml 输出路径")
    ap.add_argument("--strings", help="静态字符串明细输出路径（默认与 yaml 同目录）")
    ap.add_argument("--include", action="append", default=[],
                    help="额外业务包前缀，可重复，如 --include com.dq.")
    a = ap.parse_args()

    info = static_scan(a.apk, a.include)
    data = build_map(info)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write("# 由 android-app-flowtest 静态提取，where/how 需动态实测后回填\n")
        import yaml
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    detail = a.strings or os.path.join(os.path.dirname(os.path.abspath(a.out)), "work", "static_strings.json")
    os.makedirs(os.path.dirname(os.path.abspath(detail)), exist_ok=True)
    with io.open(detail, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "package": info["package"],
        "version": f"{info.get('version_name')} ({info.get('version_code')})",
        "flutter": info.get("flutter"),
        "business_activities": len(info.get("business_activities", [])),
        "routes": len(info.get("routes", [])),
        "features": len(data["features"]),
        "yaml": os.path.abspath(a.out),
        "strings": os.path.abspath(detail),
    }, ensure_ascii=False, indent=2))
    print("\n下一步：安装启动后逐个确认入口，把 how 改成真实点击路径。")


if __name__ == "__main__":
    main()
