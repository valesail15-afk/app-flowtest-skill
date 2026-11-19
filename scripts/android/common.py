# -*- coding: utf-8 -*-
"""Shared helpers: locate adb, pick a device, run commands, slugify."""
import os
import re
import shutil
import subprocess

CANDIDATES = [
    os.environ.get("ADB", ""),
    os.path.join(os.environ.get("ANDROID_HOME", ""), "platform-tools", "adb.exe"),
    os.path.join(os.environ.get("ANDROID_SDK_ROOT", ""), "platform-tools", "adb.exe"),
    r"C:\Users\dianq\AppData\Local\Microsoft\WinGet\Packages\Genymobile.scrcpy_Microsoft.Winget.Source_8wekyb3d8bbwe\scrcpy-win64-v5.0.1\adb.exe",
]


def find_adb():
    for p in CANDIDATES:
        if p and os.path.isfile(p):
            return p
    found = shutil.which("adb")
    if found:
        return found
    raise SystemExit("未找到 adb，请设置环境变量 ADB 指向 adb.exe")


ADB = find_adb()


def run(args, serial=None, binary=False, timeout=90, cwd=None):
    cmd = [ADB] + (["-s", serial] if serial else []) + args
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd)
    if binary:
        return p.stdout
    return p.stdout.decode("utf-8", "ignore").strip()


def list_devices():
    out = run(["devices", "-l"])
    devices = []
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+device\b(.*)$", line.strip())
        if not m:
            continue
        info = dict(re.findall(r"(\w+):(\S+)", m.group(2)))
        devices.append({"serial": m.group(1), **info})
    return devices


def pick_device(serial=None):
    devices = list_devices()
    if serial:
        matched = [d for d in devices if d["serial"] == serial]
        if not matched:
            raise SystemExit(f"设备 {serial} 不在线，当前：{[d['serial'] for d in devices]}")
        return serial
    if not devices:
        raise SystemExit("没有在线设备，请连接手机并开启 USB 调试后重试")
    if len(devices) == 1:
        return devices[0]["serial"]
    raise SystemExit("检测到多台设备，请用 --serial 指定：" + ", ".join(d["serial"] for d in devices))


def slugify(text):
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", text).strip("-")
    return s[:40] or "step"
