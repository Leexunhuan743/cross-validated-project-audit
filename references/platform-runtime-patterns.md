# 平台、语言与运行时陷阱

**按需读取**：风险地图命中某个具体 OS、编码、shell、语言版本、构建模式或第三方库语义时读本文件；不然不要读。

本文件只是**平台陷阱字典**——告诉你哪些地方会骗人、用什么命令能验出来。它不含任何裁决规则：证据强度定级见 [../SKILL.md](../SKILL.md) §6，探针纪律见 §3 步骤 3。

有一条贯穿全文：**目标平台的真实行为只能由目标平台证明**。模型记忆、其他平台的模拟、不同版本的试验都不是该平台的 DIRECT Evidence，只能写进 `reasoning` 或作 `context`。这条在主文件 §6 里表现为强度上限（扩展装在 Node 测试架里可复现的缺陷是 `ES3`，不是 `ES4`），本文件不再重复。

## Windows 路径与 rename 语义

- 尾点、尾空格、保留名（`CON`、`NUL`、`AUX`）、大小写折叠和路径规范化，都可能让代码里记录的名字与真实目录条目分歧。
- 覆盖已有目标、跨卷移动、打开状态下的 rename、以及文件/目录同名判定，行为可能与 POSIX 不同。
- 用目标 Windows 版本上的**真实生产文件函数**和代表性路径验证，不用字符串比较代替文件系统调用。
- 在 Linux 上做字符串比较或模拟，只能形成 Hypothesis 或辅助线索，撑不起 Windows 文件系统 Finding 的 `CONFIRMED`。

```powershell
# 尾点/尾空格：用 -LiteralPath，不要依赖通配符展开
Get-Item -LiteralPath 'C:\probe\name.' , 'C:\probe\name '
# 大小写折叠：确认两个名字解析到同一条目
(Get-Item -LiteralPath 'C:\probe\Name.txt').FullName
```

## cmd / PowerShell 的调用间失忆

cmd 与 PowerShell 的环境变量、shell 状态**不跨工具调用持久**——一次调用里 `set TDIR=...` 或 `$env:TDIR=...`，在下一次调用里不存在，未加引号或未展开的变量会原样落成字面量目录名（很可能直接在仓库里建出一个名叫 `$TDIR` 的目录）。

因此：隔离实验产物严格放在 `.audits/<auditId>/scratch/<R_ID>-<EXECUTOR>/` 分片目录下（绝不落在被审计目标树，也不放到无从追溯的系统临时目录）；引用路径一律写显式绝对路径，不依赖上一次调用留下的 shell 状态；实验用完即清，收口时清空。主文件 §3 步骤 2 与步骤 3 已把这条列为硬约束，这里只补一句平台侧后果。

## Unicode、字节与规范化边界

- 区分 code point、grapheme cluster、UTF 字节、显示宽度和存储长度——四者可以同时不相等。
- 覆盖组合字符、不同规范化形式（NFC/NFD）、CJK、emoji、大小写折叠和非法字节处理。
- 让真实生产函数处理输入，并**分别核对**显示、序列化、存储和比较四个结果。
- 系统契约明确只接受 ASCII，或已在边界强制规范化时，不把无关 Unicode 场景列为缺陷。

## PowerShell 匹配与管道语义

- `-match` / `-notmatch`、通配符、相等比较、数组广播、管道输出和退出码**互不等价**。
- 版本子串比较、正则转义和自动类型转换是误报重灾区。
- 在目标 PowerShell 版本里复现原运算符、输入形状和错误偏好，不要用其他语言的 equality 去模拟。
- 区分脚本返回值、进程退出码和写入错误流——只检查屏幕文本会漏掉写进 error stream 的失败。

```powershell
# 不要这样：字符串比较版本会得出错误次序
'10.9.0' -gt '10.10.0'          # True，错
# 用 [version] 或目标版本的真实比较路径
[version]'10.9.0' -gt [version]'10.10.0'   # False
```

## Rust overflow、shift 与构建模式

- 区分整数 overflow、shift amount 越界、被移出位、debug/release 行为差异和显式 `wrapping_*`/`checked_*`。
- 锁定 toolchain、profile 和目标类型，调用真实表达式或生产函数，不要凭语义推断。
- defensive-only、被类型系统排除、或真实输入不可达的情况，不升级为运行时缺陷。
- 构建模式差异无法验证时，记录验证缺口与缺失条件，交回主代理裁决。

## Node.js、npm 与包发布语义

- 区分 ESM/CJS 解析（`type` 字段、扩展名、default/named export 互操作）与 `require` 缓存行为；在目标 Node 版本复现。
- `child_process` 在 Windows 上执行 `.bat`/`.cmd` 时，路径里的空格会被吞掉，需要显式 `shell` / `windowsHide` 决策；退出码与信号跨平台不等价。
- 包发布内容由 `files` / `.npmignore` / `exports` 决定，**安装产物可能与源码树不同**；审计发布面时以实际清单为准。

```bash
# 发布物清单核验：以 pack 的实际产物为准，不要按源码树推断
npm pack --dry-run
# Windows 上跑 .bat：路径必须显式引号，否则空格是黑洞
execFile('C:\\Program Files\\tool\\run.bat', { windowsHide: true })
```

- 未捕获异常、unhandled rejection、`process.exitCode` 的默认行为随版本变化；涉及进程生命周期时锁定目标 Node 版本契约。

## 第三方库、协议与 release/debug 差异

- 锁定实际版本、feature、平台、编译选项和调用方式；**不用最新文档代替当前版本契约**。
- 优先调用真实 API 的最小公共路径，不能运行时就引用对应版本的官方文档、源码或发布说明。
- 检查默认值、错误类型、线程安全、编码、持久化、兼容窗口和弃用行为。
- 包名相同、代理共识、或过去版本的行为，都不能单独确认当前语义。

## 取证后怎么落回主文件

本文件只负责把平台语义变成可复核的观察。拿到观察后：

- 在目标平台/版本的真实公共路径上可重复复现 → 按 §6 评 `ES4`；
- 只有对应版本权威契约、且代码路径完整 → `ES2`，但若 Finding 依赖真实状态或集成语义，仍要记目标环境验证缺口；
- 其他平台模拟或不同版本试验 → 作 `context` 或较弱支持，不能单独确认目标平台语义；
- 拿不到目标环境 → 披露缺口及其影响，不推测 Decision、不推 Gate。
