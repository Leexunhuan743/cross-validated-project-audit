# 平台、语言与运行时模式

仅在风险地图命中对应 OS、编码、语言、构建模式或第三方库语义时读取本文件。每项都要求目标平台、锁定版本或对应版本权威契约；模型记忆或其他平台模拟只能作为 Hypothesis/context，不能冒充目标平台的决定性 Evidence。

## Windows 路径与 rename 语义

- 尾点、尾空格、保留名、大小写折叠和路径规范化可能让记录名与真实目录分歧。
- 覆盖已有目标、跨卷移动、打开文件 rename 和文件/目录行为可能与 POSIX 不同。
- 使用目标 Windows 版本上的真实生产文件函数和代表性路径验证。
- Linux 上的字符串比较或模拟只能形成 Hypothesis/辅助线索，不能单独支持 Windows 文件系统 Finding 的 `CONFIRMED` Decision。

## Unicode、字节和规范化边界

- 区分 Unicode code point、grapheme cluster、UTF 字节、显示宽度和存储长度。
- 覆盖组合字符、不同规范化形式、CJK、emoji、大小写折叠和非法字节处理。
- 让真实生产函数处理输入，并分别核对显示、序列化、存储和比较结果。
- 若系统契约明确只接受 ASCII 或已在边界强制规范化，不把无关 Unicode 场景列为缺陷。

## PowerShell 匹配与管道语义

- `-match/-notmatch`、通配符、相等比较、数组广播、管道输出和退出码并不等价。
- 版本子串、正则转义和自动类型转换容易产生误报。
- 在目标 PowerShell 版本中复现原运算符、输入形状和错误偏好；不要用其他语言 equality 模拟。
- 区分脚本返回值、进程退出码和写入错误流，避免只检查屏幕文本。

## Rust overflow、shift 与构建模式

- 区分整数 overflow、shift amount 越界、被移出位、debug/release 行为和显式 wrapping/checked 操作。
- 锁定 toolchain、profile 和目标类型，调用真实表达式或生产函数。
- 不把 defensive-only、被类型系统排除或真实输入不可达的情况升级为运行时缺陷。
- 构建模式差异无法验证时记录验证缺口与缺失条件，不在本模块直接作 Decision。

## Node.js、npm 与包发布语义

- 区分 ESM/CJS 解析（`type` 字段、扩展名、default/named export 互操作）与 `require` 缓存行为；在目标 Node 版本复现，不用记忆替代。
- `child_process` 在 Windows 的 `.bat/.cmd` 执行、shell 差异与路径空格需要显式 `shell`/`windowsHide` 决策；退出码与信号跨平台不等价。
- 包发布内容由 `files`/`.npmignore`/`exports` 决定，安装产物可能与源码树不同；审计发布面时以 `npm pack --dry-run` 的实际清单为准。
- 未捕获异常、unhandled rejection、`process.exitCode` 的默认行为随版本变化；涉及进程生命周期时锁定目标 Node 版本契约。

## 第三方库、协议和 release/debug 差异

- 锁定实际版本、feature、平台、编译选项和调用方式；不要用最新文档替代当前版本契约。
- 优先调用真实 API 的最小公共路径；不能运行时引用对应版本的官方文档、源码或发布说明。
- 检查默认值、错误类型、线程安全、编码、持久化、兼容窗口和弃用行为。
- 包名相同、代理共识或过去版本行为都不能独立确认当前语义。

## 结论规则

| 证据 | 典型质量/裁决影响 |
|---|---|
| 目标平台/版本真实公共路径可重复复现 | 通常 `ES4`；可支持较高 Confidence，但最终 Decision 仍由主代理结合 disconfirmation 与影响评估作出 |
| 对应版本权威契约明确且代码路径完整 | 通常 `ES2`；可确认纯静态契约事实，若 Finding 仍依赖真实状态/集成行为则不能冒充运行时复现 |
| 其他平台模拟、不同版本试验 | 作为 context/较弱支持，不能单独确认目标平台语义 |
| 模型记忆或无可定位来源的说法 | 不是 Evidence，只能作为 Hypothesis/reasoning 线索 |
| 无法获得目标环境或版本证据 | 披露验证缺口及其影响，不在本模块推测 Decision 或门禁 |
