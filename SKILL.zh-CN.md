---
name: universal-audit-review
description: "对任意项目工件(功能分支、commit、已实现功能、实施计划)运行多子代理审计/审查:4-15 个只读子代理覆盖安全/逻辑/UI/CLI/测试/i18n/并发/git/回归等维度,然后主代理亲自复核每个 finding 并显式裁决 ADOPT/DECIDE/REJECT。用户要求 审计/审核/审查/审阅 分支/commit/PR/计划/已实现功能 全面/多角度/从各个方面,或问 修复得对不对/commit 是否合理 时使用;也覆盖要求分批修复+验证的修复-验证循环。"
---

# 通用审计与审查 — 多子代理、亲自复核

用只读子代理审计任意项目工件,然后**亲自复核每个 finding**。核心循环 —— 基线 → 派发 → 复核 → 裁决 → 修复 → 验证 —— 对每种工件都一样;只有范围裁剪不同。

## 何时使用(选工件类型)

| 工件 | 范围界定 | 派发规模 |
|---|---|---|
| **功能分支 / PR** | `git log --oneline base..head` + `git diff --stat base head` | 8-10 个代理 |
| **修复 commit**(审计后的整改) | 前次审计报告 + 修复 diff,建立 finding→fix 映射 | 10-15 个代理 |
| **已实现功能**(交付成果) | 计划文件 + 分支状态 | 8-10 个代理 |
| **实施计划**(执行前) | 计划文件 + 其关键主张 | 4 个代理 |

## 基线(内联,派发前)

1. **拓扑预检**:`git log --oneline <base>..<head>` 和 `git diff --stat <base> <head>`。squash-merge 会让 `base..head` 为空,而分支内容其实就是 base 的树 —— 审计框架完全改变。用 `git log -1 <squash-commit>` + `git diff --stat origin/master <branch-head>` 验证。
2. **建立基线**:build / vet / 全量测试跑绿;记录**既有失败清单**(环境相关的测试、依赖语料的 vendor 测试),子代理绝不重复报告。
3. **亲自读完整 diff** 再派发。你对每个子系统的个人了解,是写出每个代理 scope 并事后裁决的前提。
4. **写 verified-facts 表**:API 签名、预算、先例、硬规则(panic=abort、clippy 零告警、i18n 对齐、patch 标记)—— 代理不重复推导你已验证过的事实。

## 派发(一次 `task` 调用,全部 READ-ONLY)

维度模板 —— 每维度一个代理,按工件裁剪:

- **security-reviewer**:脱敏/消毒边界(真正的 P1 藏在这里)、凭据处理、vendored crate 崩溃面
- **reviewer**:核心逻辑 / UI 对话框状态机(索引数学!)/ CLI 契约(错误文本、退出码)/ 测试判别力 / 并发-内存(有界等待、RAII 释放、线程生命周期)/ 回归真相
- **scout**:文档一致性(过度声称检测)/ git 交付完整性(杂散文件、标记、导出)/ 互操作-发布证据

每个代理拿到:精确路径、diff(或其路径)、verified-facts 表、既有失败清单、严重度分级(P0 运行破坏/数据丢失/泄漏;P1 正常路径 bug/回归;P2 边界/健壮性;P3 风格/文档)、"verified by reading vs inferred" 标注要求,以及 **verified-correct 清单**(给你正面对照)。按子系统把 diff 预导出到共享文件(如 `.audit-share/<name>-diff.txt`)—— scout 常常无法跑 git/bash。不要传 `"outputSchema": false`(预检会拒绝;省略该字段)。

## 复核每个 P0/P1/P2(不可协商)

- 读实际代码现场;追交错;自己跑逻辑。代理会误读 —— 最强的单源 finding 也需要你的眼睛。
- **交叉验证规则**:2+ 独立代理报告的同一 finding = 近乎确定;单源 finding 需要最强证据。
- **实证探针是杀手锏**:临时程序(用后删除)调用**真实函数** —— 给消毒器喂 CJK/西里尔输入、计算新旧标题、对 Windows FS 主张实际跑 `os.Mkdir`/`os.Rename`。平台主张在宿主机 OS 上验证。
- 当 finding 质疑 patch 动机时,用 `git show <base>:<file>` 看修复**前**的代码。

## 显式裁决

最终报告里每个 finding 都有裁决:**ADOPT**(附修复)/ **DECIDE**(需用户)/ **REJECT**(附理由)。拒绝是合法的 —— 例如代理用 Node 的相等比较重实现了 PowerShell 子串 gate,会误报。诚实区分既有问题 vs patch 引入(`git show base:file` 看旧侧)—— 早于分支就存在的问题仍要报告,但分级不同。

## 修复-验证循环(仅当用户要求修复时)

1. **按严重度分批**:P0/P1(数据/下载行为、生命周期/安全)优先;每批 3-5 个修复,验证才可审阅。每批一个 todo 清单。
2. **每批:停下,验证,再进下一批。** build + 定向测试跑绿 → 派 3-4 个只读 scout,每人负责一个被触动的子系统,带上:精确修复清单、验收标准、严重度分级、证据格式(file:line + verified/inferred),以及"追查**新**回归和测试判别力,不只是确认修复"的指令。
3. **亲自裁决他们的输出**:确认的缺陷 → 立即修,重跑受影响测试;被驳斥的主张 → 记录理由;验证者发现的新 P1/P2 → 先修再继续。
4. **全部批次后的第二轮**:修剩余 P2/P3(便宜的),更新 CHANGELOG,只 gofmt 你动过的文件。
5. **清理放最后**:删 `.audit-share/`、临时探针、worktree;`git status --porcelain` 只显示预期改动;仓库用 lat.md 则跑 `lat check`。

## 完成标准

- 每个被接受的 finding 在最终报告里有代码级复核记录
- 每个代理的裁决表(维度 / finding / 你的证据 / 裁决)+ verified-correct 清单
- 诚实列出残留缺口:仅 release-build 可测的风险、未测的 UI 交互、仅临时目录的互操作探针
- 报告:严重度表(file:line + 证据)+ 按优先级排序的修复清单

## 已知陷阱(实战得来 —— 接受前逐一验证)

- **测试判别力**:每个新测试在修复被回退时是否**会失败**?在修复前代码上通过的测试是假信心(一个在两条路径上都触发同一 SQL 触发器的排序测试)。
- **文档过度声称**:CHANGELOG/API/lat.md 声称超过代码 —— "并发改名 → 409" 当进程内锁序列化时只是跨进程现象;"URL userinfo 不记日志" 可能根本没有对应代码路径。
- **修复破坏它声称迁移的旧数据**:加了校验规则后在改名路径上校验**旧**名字,会卡死既有记录(下载每次报错;恢复只能直接改库)。旧名字豁免新规则,或比较前先归一化,并加旧记录迁移测试。
- **遗留死代码**:修复的新 helper 替换了 full-row writer,而后者还活在测试里 —— 旧隐患在纯测试代码中复活。
- **新激活路径暴露潜伏 bug**:接通一个之前死掉的端点,激活了潜伏的时区往返缺陷(存 UTC、显示墙钟、再按浏览器本地解析 → 每次编辑都偏移)。
- **关停加固中的无界等待**:`activeMutations.Wait()` / `<-startupDone` 无超时,在卡住的 handler 上永远挂起;无超时的阻塞 session.Open 会击穿 startupDone 握手。
- **gate 语义**:PowerShell `-notmatch` + 正则转义子串对 4 段版本扩展("1.4.1" ⊂ "1.4.1.0")**通过**;用相等比较复现会误报。验证实际匹配语义。
- **Rust 移位语义**:`<<` 只在移位量 >= 位宽时 panic;被移出的**值位**在 debug 和 release 下都静默丢弃。对小的有界字面量的"debug overflow panic"主张是错的 → 属于 DEFENSIVE-ONLY,不是 panic 修复。
- **Windows 路径语义**:尾点/尾空格通过校验但 Win32 会剥掉 → 记录/目录分歧;`os.Rename` 到已存在的**空**目录在 Windows 上失败(不会静默替换)。
- **空洞测试**:用本地镜像 helper 而非生产函数;`if success { assert }` 吞掉失败分支。钉住生产函数(必要时 make pub)并断言具体错误文本。
- **squash-merged master**:`base..head` 空 ≠ 分支空 —— 始终拿 base 与分支头 diff。
- **全行写丢失更新**:`UPDATE ... SET a=?,b=?,c=?` 从 T0 快照写入,会静默回退并发的单调写。
