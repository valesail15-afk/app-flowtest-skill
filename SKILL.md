---
name: app-flowtest
description: 通用产品功能流程测试（Web 网页 / 本地项目 URL / 静态页面 / Android APK）。按固定四阶段执行：先用 feature-map 技能获取/校验功能地图（feature-map.yaml）→ 按地图逐功能真机/浏览器测试并逐步截图取证 → 每个被测对象单独生成可勾选确认的 issues-report.html → 交用户确认。用户要求「测这个站点 / 测本地项目 / 测这个 APK / 走一遍功能 / 出问题清单 / 截图留证」时使用。
---

# 通用功能流程测试

固定四阶段，**不允许跳阶段**：功能地图没生成，不开测；每一步没有截图，不算测过。

## 与 feature-map 技能的协作（先取地图，再测）

本 skill 不另造一套功能定义，**阶段 1 优先复用 feature-map 技能的地图**：

1. 先找现成地图：`<项目根>/feature-map.yaml`，或 Web 站点的 `sites/<域名>/feature-map.yaml`（查询时 `fmap.py --site <域名>`）。
2. 用 feature-map 技能读取并校验：

```powershell
python <feature-map skill目录>\scripts\fmap.py --list --data <项目根>\feature-map.yaml
python <feature-map skill目录>\scripts\fmap.py --check --data <项目根>\feature-map.yaml
```

3. 校验通过后，把地图快照复制为 `<run>/feature-map.yaml`，并在 `work/env.json` / `notes` 记录地图来源与取证日期；测试用例按地图条目逐条执行（`name` 就是用例名，`where/how` 就是操作路径）。
4. 没有现成地图时，才用本 skill 的 `map` 命令生成草稿；补全后写回项目根（或 `sites/<域名>/`），并用 `fmap.py --check` 验证，不能只留在 `<run>/`。
5. 实测发现地图里没有的功能，回填到 feature-map（补 `name/aliases/where/how`），保持地图与测试同步。
6. 两份产出分工：feature-map 记录「在哪里、怎么打开」；`issues-report.html` 记录「实际行为、问题与证据」，且**一个被测对象一份报告**。

同一套流程覆盖两类目标：

| 目标 | 识别方式 | 取证方式 |
| --- | --- | --- |
| Web / 本地项目 / 任意站点 | `--url http://...` | Playwright 驱动本机 Chrome/Edge：截图 + DOM 快照 + 控制台错误 |
| Android App | `--apk <路径>` / `--serial` | adb：截图 + UI 树 + 前台 Activity |

统一入口 `scripts/flowtest.py`，参数透传给对应平台脚本。

## 通用适配约定（Web）

脚本**不依赖任何站点专属 class/id**，靠语义与可见性判断，换站点可直接复用：

| 能力 | 识别方式 |
| --- | --- |
| 导航入口 | `nav / aside / header / [role=navigation]` 等容器内的 `a / button / [role=button] / [data-go]`；找不到导航容器时全页兜底或跟随同源链接 |
| 页面容器 | `[data-screen] / [role=tabpanel] / .screen / .page / .view / main > section` 中「可见且带标题」的容器，自动剔除子容器避免重复 |
| toast | `#toast / .toast / [class*=toast] / [class*=snack] / [role=status] / [aria-live]` |
| 弹窗 | `dialog / [role=dialog] / [class*=modal] / [class*=dialog]` 中可见且有文字的最大容器 |
| 可点元素 | `button / a[href] / [role=button] / [role=tab] / [data-go] / [data-action] / [onclick]` |

静态/自动抓取只是候选，**界面实测到的才算数**。遇到没有语义标签的站点，不要改脚本去适配单个站点，先按上面的语义补全页面自身结构；确实无法识别时用 `--js` / `--click css=...` 精确操作并记录到功能地图。

## 产物目录约定

**硬性规则：一个被测对象一份报告。** 一个 App 或一个网站对应一个 `<run>/`、一份 `issues.json`、一份 `issues-report.html`。用户一次给多个包或多个网址时，必须按对象拆成多个 run 分别测试、分别出报告，**禁止把多个 App/网站混进同一份报告**；报告标题和 `app` 字段只写当前对象。

以目标短名建目录（示例 `D:\功能测试\<日期>\<slug>\`）：

```
<run>/
  feature-map.yaml            # 阶段 1 产出（同时复制到项目根，供 feature-map 技能查询）
  work/
    env.json                  # 目标信息（Web：URL/标题/视口/浏览器；Android：设备/包）
    steps.jsonl               # 每步一条记录（capture 追加）
    ui/<step>.html|.txt|.xml  # 每步页面快照（Web 为 DOM/正文，Android 为 UI 树）
    crawl.json                # Web 阶段 1 自动遍历清单
    issues.json               # 阶段 3 输入（问题/待确认/正常 + 速查项）
    browser-profile/          # Web 持久会话（localStorage 跨步骤保留）
    logcat.txt                # Android 测试期间日志
  outputs/
    screenshots/<step>_<标签>.png
    downloads/                # 测试中接收的下载文件（txt/zip/json）
    issues-report.html        # 阶段 3 产出（图片 base64 内嵌，单文件可看）
```

## 阶段 0 · 环境检查

```powershell
# Web
python <skill目录>\scripts\flowtest.py doctor --url http://127.0.0.1:8787/ --out <run>
# Android
python <skill目录>\scripts\flowtest.py doctor --apk <apk> --out <run>
```

Web 依赖：Python + `playwright`；浏览器优先用本机 Chrome/Edge，未安装时回退 Playwright Chromium（`python -m playwright install chromium`）。
Android 依赖：adb 可用、设备在线（多设备用 `--serial`）、`androguard`（静态提取）。

- 需要登录/验证码/第三方授权：先用测试账号或游客入口；不行就 `--headed` 显示浏览器，请用户手动登录（会话保存在 `work/browser-profile`，后续步骤沿用）。
- Android 真机安装/截图/授权可能弹确认框，先自动、失败再请用户点「允许」。

## 阶段 1 · 生成功能地图

**先复用 feature-map 技能的地图**：项目根已有 `feature-map.yaml`（Web 也可用 `sites/<域名>/` 内置地图）时，直接用 `fmap.py --list` / `--check` 读取校验并复制到 `<run>/feature-map.yaml`，不要重复抓一遍。只有没有地图或地图明显过期时，才执行下面的草稿生成：

```powershell
# Web：自动遍历导航/同源链接，抓入口、按钮、表单，产出草稿
python <skill目录>\scripts\flowtest.py map --url http://127.0.0.1:8787/ --out <run>\feature-map.yaml

# Android：静态提取 Activity/路由
python <skill目录>\scripts\flowtest.py map --apk <apk> --out <run>\feature-map.yaml
```

Web 自动遍历默认最多 30 个入口；纯多页站点（无导航容器）会自动跟随同源链接，可用 `--max-links` 调整。
入口是按钮、点击后切换同页视图（SPA）时，脚本会按导航索引点击并逐屏截图；入口是链接时按地址访问。

自动产出只是候选，**必须动态核对后回填**：

1. 逐个页面确认模块真实存在、名称与界面一致（Web 看 `work/crawl.json` 与截图）。
2. 按「进入 → 操作 → 看结果 → 退出」走通主流程，把 `how` 改成真实点击路径（格式 `A > B > C`）。
3. 自动遍历只覆盖导航一级页；二级页面/弹窗（如「开始创作 → 大纲 → 出图」、详情弹窗、上传/下载）需手动进入后补进地图。
4. 地图至少覆盖：首页/启动、每个导航 Tab、每个二级页面/弹窗、工具与设置入口、表单提交、下载/导入导出、退出路径。
5. 最终地图以项目根目录（Web 可放 `sites/<域名>/`）为唯一事实来源，`<run>/feature-map.yaml` 只是本次测试的快照；两份都按 feature-map 格式维护。

字段：`name`（界面上的真实名称）、`where`（功能位置）、`how`（怎么点开）、`aliases`（可选，同义词）。

> 静态/自动抓取有、界面无入口的模块标注「未发现入口」，列为待确认，不要凭代码猜位置。

## 阶段 2 · 逐功能执行与取证

每个功能按「进入 → 操作 → 看结果 → 退出」执行，关键节点逐步取证。

### 覆盖率硬性要求（不得只看页面）

- **功能地图有多少条，就必须执行多少条**；只截图打开页面不算测过，必须实际点一次目标控件并看到结果。
- 表单/录入/设置类功能必须**录入测试数据并保存**：金额用 0.01/12.34 等小额，备注用可识别前缀（如 `autotest-1119`）；保存后回到列表/详情确认写入，再清理测试数据或明确标注保留。
- 需要系统授权的功能（相机、通知栏、后台运行、桌面小组件等）也要点开验证，记录系统权限页/拦截结果，不能跳过。
- 要点到二级页面、弹窗、开关、空状态按钮；入口存在但点不开、点了无反应，记 `failed`，不要写成正常。
- 每个功能在 `work/coverage.json` 留一条台账，**status 只有 `tested` 才算测过**；`blocked` 必须写明具体原因（需登录/需付费/系统限制），`untested` 不允许交付。

```json
{
  "total": 50,
  "items": [
    {"name": "完成记账", "status": "tested", "note": "录入 12.34 并保存，明细中已核对"},
    {"name": "拍照记账", "status": "blocked", "note": "触发系统相机权限弹窗，未授权"}
  ]
}
```

生成报告时把该台账合并进 `issues.json` 的 `coverage` 字段，报告顶部会渲染「覆盖台账」和未测/受阻清单。

### Web

```powershell
python <skill目录>\scripts\flowtest.py step --url http://127.0.0.1:8787/ --root <run> ^
  --step r02 --label "生成大纲" --note "输入主题后点发送" --expect "进入大纲页" ^
  --fill "#topic=周末去近郊爬山要带什么" --click "#sendBtn" --wait 1
```

动作参数（可重复、按命令行顺序执行）：

| 参数 | 说明 |
| --- | --- |
| `--goto` | 先跳转（相对站点根路径或完整 URL；默认打开站点首页） |
| `--click` | `text=文字` / `css=选择器` / `#id` |
| `--fill` | `selector=value` |
| `--select` | `selector=value` |
| `--upload` | `selector=文件路径`（文件选择框） |
| `--press` | `Enter` / `Control+Enter` |
| `--js` | 附加执行 JS |
| `--wait` / `--delay` | 动作后等待 / 连续动作间隔（秒） |
| `--full-page` | 整页截图（长页面用） |
| `--headed` | 显示浏览器（人工介入时） |

多步骤流程（需要跨步骤保留页面状态、每步各截一张图）用批量脚本，避免反复启停浏览器：

```json
[
  {"step":"r01","label":"首屏","goto":"","must_see":["灵感墙"]},
  {"step":"r02","label":"填示例","click":["#pasteDemo"],"eval":"document.querySelector('#topic').value","expect_eval":"周末去近郊爬山要带什么"},
  {"step":"r03","label":"生成大纲","fill":{"#topic":"周末爬山"},"click":["#sendBtn"],"expect_screen":"s-outline"}
]
```

```powershell
python <skill目录>\scripts\flowtest.py flow --url http://127.0.0.1:8787/ --root <run> --script <run>\steps.json
```

步骤字段：`goto/click/fill/select/upload/press/js/wait/delay/full`；断言字段：`expect/must_see/must_not_see/expect_screen/expect_eval/download`。

需要「先填再点」这类顺序敏感的操作时，用 `actions` 数组按书写顺序执行（优先于 click/fill 的固定顺序）：

```json
{"step":"r09","label":"改文案再重画","actions":[
  {"fill":{"#pageDesc":"封面：桌面前后对比"}},
  {"click":"#redoPage"},
  {"wait":0.8}
],"must_see":["整套图"]}
```

`upload` 支持多文件：值用分号分隔（`a.png;b.png`）或直接传数组。
`download:true` 会自动接收下载并存到 `outputs/downloads/`；确认框默认同意并记录文案。

要求：

- **步骤号连续**（r01、r02…），一步一张截图 + 一份 DOM 快照，不合并、不跳号。
- 记录五要素：操作、期望、实际、截图、当前页面/弹窗。
- **toast、弹窗、空状态必须截图**；计数、排序、筛选变化前后各截一张。
- 控制台 error 会自动记入步骤记录，作为问题证据。
- 失败/误触步骤保留在记录里，在 note 标注「操作未生效」，不计入结论。
- 业务规则先与用户确认（免费次数、会员门槛、是否需登录等），**按规则判定，不按直觉判定**；规则写进 `issues.json` 的 `notes` 并展示在报告顶部。

### Android

```powershell
python <skill目录>\scripts\flowtest.py step --root <run> --step r01 --label "启动-首屏" --wait 6
```

支持 `--tap X Y` / `--tap-text 文字` / `--swipe X1 Y1 X2 Y2` / `--key KEYCODE_BACK` / `--no-ui` / `--launch 包名`。

- `--tap` 内部用 120ms 同点按压，兼容 Flutter/游戏化自绘 UI；`--tap-text 我的` 会自动 dump 当前界面、按 text/content-desc 找节点并点中心，比手写坐标稳（同名标题优先点面积更小的节点；底部 Tab 的文字节点若是 0 尺寸，会回溯到 Tab 容器）。
- `--launch 包名` 会启动应用并自动关闭开屏广告/促销弹窗（支持「跳过/关闭/×」文字与 `iv_close`/`btn_close` 类资源 id）；加 `--cold` 先 force-stop 保证冷启动。广告层数多时用 `--dismiss-rounds` 加大轮数。
- `--step` 可带层级（如 `m1\a`），落盘文件名会自动 slug 化，不会因为反斜杠丢截图。
- Toast 短暂提示必须截图；UI 树抓取失败会重试 3 次并记 `ui_ok:false`。

## 阶段 3 · 生成报告

**每个 App / 网站单独生成一份报告**：批量测试时先按对象拆分 run，再逐个生成；不要把多个对象的条目合并到同一个 `issues.json`。报告生成后逐个交付，不打包成一份汇总。

把判定结果写入 `work/issues.json`，然后：

```powershell
python <skill目录>\scripts\flowtest.py report --run <run> --issues <run>\work\issues.json --out <run>\outputs\issues-report.html
```

```json
{
  "title": "应用名 · 功能测试问题清单",
  "subtitle": "一句话说明测试范围与结论",
  "kicker": "功能测试 · 取证清单",
  "app": { "package": "站点或包名", "version": "版本", "device": "设备/浏览器", "os": "系统", "date": "" },
  "notes": ["用户确认的业务规则 1", "规则 2"],
  "sections": [
    { "id": "c1", "title": "确认问题", "items": [
      { "path": "r20 · 壁纸详情", "title": "问题标题", "desc": "实际表现，可用 **加粗** 标关键值",
        "evidence": "日志/接口/控制台证据（可选）", "severity": "P0",
        "tags": ["计数"], "images": ["outputs/screenshots/r20_xx.png"] }
    ]},
    { "id": "c2", "title": "待确认", "items": [] },
    { "id": "c3", "title": "正常功能", "items": [] }
  ],
  "ok": [{ "name": "功能名", "desc": "一句话结论", "image": "outputs/screenshots/r19_xx.png" }]
}
```

报告硬性要求（脚本已实现，不要手改 HTML）：

- 三个分区：确认问题 / 待确认 / 正常功能，外加「正常功能速查」缩略图。
- **每条都有「功能正确」勾选**：问题区勾选 → 移入正常功能；正常区取消勾选 → 移回问题列表；速查项也支持反向标记。
- 勾选状态 localStorage 持久化，计数与导航实时联动。
- 截图 base64 内嵌，报告单文件可直接打开。
- **必须带「覆盖台账」**：`issues.json` 的 `coverage` 字段记录地图条目总数与逐条状态；顶部展示「已测/受阻/失败/未测」。存在 `untested` 条目时不得交付报告，先补测或改成有明确原因的 `blocked`。

## 阶段 4 · 交用户确认

- 输出报告链接并说明：确认问题数 / 待确认数 / 正常数、最严重的 3 条。
- 等用户逐条勾选确认；用户改判后更新 `issues.json` 重新生成，不手改 HTML。
- 用户确认后才进入修复或下一轮回归。

## 判定纪律

| 情况 | 处理 |
|---|---|
| 功能可用但文案/提示不一致 | 部分通过，单独列条 |
| 只能靠真实支付/跨天/第三方验证 | 未验证，写明原因，不计失败 |
| 静态/自动抓取有、界面无入口 | 记「未发现入口」，列为待确认 |
| 一次失败 | 复测一次；仍失败才算失败，并附两次截图 |
| 与业务规则冲突的「异常」 | 按规则撤销，移入正常功能并注明依据 |

## 实测常见坑（跨项目通用）

- **Android 点击坐标**：优先用 `--tap-text 文字` 让脚本自己找节点中心；只能手写坐标时，底部 Tab / 图标区要先 dump 取 `bounds` 中心，不要按截图比例猜。
- **应用会恢复上次页面**：`monkey` 启动可能直接回到上次停留的页面（如反馈页、记账录入页）。取证第一屏必须用 `--launch 包名 --cold`，否则会把「上次页面」当成首页。
- **冷启动可能撞上隐私协议/登录门**：部分应用清进程后会先弹「同意协议」或要求重新登录（如 Z有钱 的「一键登录」）。协议不要默认替用户勾选；登录需要用户提供账号或人工完成，先把这一步记进 run 的 note，再继续已解锁的页面。
- **`--swipe` 只接受 4 个参数**：`X1 Y1 X2 Y2`，没有时长参数；带第 5 个值会直接参数错误。
- **`adb pull` 到含中文的目录可能报 `cannot create file/directory`**：先 pull 到 `%TEMP%` 再移动，或直接用 `capture.py` 落盘。
- **Web 自动草稿要限噪**：默认每屏按面积取前 15、同名只留一条、过滤引导/工具条/弹层确认文案，总量上限 120；站点功能特别多时用 `--max-per-screen` 调整，不要把整页按钮当地图。登录后站点用 `--storage-state auth.json` 复用登录态，避免每次都只能抓到登录页。
- **只认界面实测**：静态提取的类名（如 `ConvertActivity`）不能当功能名；启动引导、会员拦截页要先关掉再取主界面。
- **隐藏的 inert 登录表单**：登录页若 `page.fill` 报 `element is inert`，说明表单是背景副本（`aria-hidden` + `inert`）。先点页面右上角「登录」按钮激活登录面板，再填 `#username`/`#password`；不要直接给背景表单去 inert。
- **自绘 UI（Flutter / 游戏化）**：`uiautomator dump` 只能读到少量原生文字，其余按钮没有节点。此时以截图为准，按设备实际分辨率（如 720×1600）换算坐标；普通 `adb shell input tap` 偶尔不生效，改用同点 120ms 的 `input swipe x y x y 120` 更稳。
- **广告密集的应用**：启动后可能连续出现开屏广告、信息流广告和促销弹窗，且关闭按钮在右上角；先逐个点「× / 跳过」再取主界面。部分广告会直接跳到外部落地页（如应用商店、抖音下载页），发现 `mCurrentFocus` 不是目标包名时先 `am force-stop` 再重启。

