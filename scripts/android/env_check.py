# -*- coding: utf-8 -*-
"""Stage 0: check adb/device/deps, create run dirs, write work/env.json."""
import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ADB, pick_device, run

try:  # androguard 4.x 默认 DEBUG 级日志，测试脚本里静音
    from loguru import logger
    logger.remove()
except Exception:
    pass


def sh(serial, cmd):
    try:
        return run(["shell", cmd], serial=serial, timeout=30)
    except Exception as e:
        return f"<error: {e}>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="测试产物根目录")
    ap.add_argument("--serial")
    ap.add_argument("--apk", help="可选，记录包信息")
    a = ap.parse_args()

    serial = pick_device(a.serial)
    root = os.path.abspath(a.out)
    for d in ["work/ui", "outputs/screenshots"]:
        os.makedirs(os.path.join(root, d), exist_ok=True)

    props = {
        "brand": sh(serial, "getprop ro.product.brand"),
        "model": sh(serial, "getprop ro.product.model"),
        "release": sh(serial, "getprop ro.build.version.release"),
        "sdk": sh(serial, "getprop ro.build.version.sdk"),
        "abi": sh(serial, "getprop ro.product.cpu.abi"),
        "size": sh(serial, "wm size").replace("Physical size: ", "").strip(),
        "density": sh(serial, "wm density").replace("Physical density: ", "").strip(),
    }

    deps = {"python": sys.version.split()[0]}
    for mod in ["yaml", "androguard"]:
        try:
            __import__(mod)
            deps[mod] = True
        except ImportError:
            deps[mod] = False

    app = {}
    if a.apk:
        try:
            from androguard.core.apk import APK
            obj = APK(a.apk)
            app = {
                "apk": os.path.abspath(a.apk),
                "size": os.path.getsize(a.apk),
                "package": obj.get_package(),
                "version_name": obj.get_androidversion_name(),
                "version_code": obj.get_androidversion_code(),
            }
        except Exception as e:
            app = {"apk": os.path.abspath(a.apk), "error": str(e)}

    env = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "serial": serial,
           "adb": ADB, "device": props, "deps": deps, "app": app}
    path = os.path.join(root, "work", "env.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    print(json.dumps(env, ensure_ascii=False, indent=2))
    if not deps.get("androguard"):
        print("提示：未安装 androguard，功能地图静态提取能力受限（python -m pip install androguard）")
    print(f"\n产物目录已就绪：{root}")


if __name__ == "__main__":
    main()
