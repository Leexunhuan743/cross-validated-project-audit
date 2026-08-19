# 审计账本与断点恢复

审计主代理在**派发任何子代理之前**读取本文件并初始化审计状态；之后在自然里程碑落盘（派发完成、发现到达、复核定稿、模式范围定稿、门禁输出）。目标：会话中断后无需重跑任何子代理即可续审；跨轮审计可查询上一轮裁决与反证。盘上即真相——子代理的"完成"声明、返回文本的长度与顺序都不是权威。

审计状态一律用 **Markdown 作为唯一作者格式**：人机皆可直接读写，无转义与机器格式维护负担。机器格式（如 JSONL）不在纯 skill 阶段手写；平台具备会话/事件日志读取能力时，由配套插件以确定性 reducer 投影生成。

## 1. 状态目录（工作目录 `.audits/`）

审计状态写在**工作目录**下的 `.audits/`。初始化时主代理按顺序处理忽略规则：

1. 工作目录是 Git 仓库：运行 `git check-ignore .audits/`——已被忽略则什么都不写；
2. 未忽略时，运行 `git rev-parse --git-path info/exclude` 取得真实排除文件路径（linked worktree 中 `.git` 可能是文件而非目录，不能假设 `.git/info/exclude` 可直接写），把 `.audits/` 追加进该路径（Git 本地排除文件，不产生 `git status`/diff，不属于交付内容）；该路径不可写但 `.audits/` 可写：披露并继续（`.audits/` 会出现在 `git status`，不得提交其中内容）；
3. 用户明确要求忽略规则随仓库提交时，才写项目 `.gitignore`，并在报告中披露这行项目修改；
4. 工作目录不是 Git 仓库：直接使用 `.audits/`，无需忽略规则；
5. `.audits/` 不可写时改用会话内账本（用同样的 Markdown 表格在对话中维护）并披露。

其余项目文件仍遵守只读契约。

```text
<工作目录>/.audits/<auditId>/
├── audit.md            # 审计定义、范围、基线、假设、门禁目标
├── coverage.md         # 覆盖矩阵（含每单元状态）
├── ledger.md           # 候选账本（当前状态表 + 变更记录）
├── fix-map.md          # 可选：修复映射与批次依赖图（fix 模式，见 references/fix-verification.md）
├── findings/           # 各子代理发现产物
│   └── <axis>-<agent>.md
├── verification/       # 可选：主代理实证档案（探针/契约/测试证据），verification/<账本ID>.md
└── probes/             # 主代理批准的隔离探针（结束时清理）
```

- `auditId`：先 `sanitizeKey(审计名)`（只保留字母、数字、`-`、`_`，其余折叠为 `-`；禁止路径分隔符、`..` 与空 id）得到 slug；`auditId = <slug 前 23 字符>-<8 位短摘要>`，空 slug 时使用 `audit-<8 位短摘要>`。`<8 位短摘要>` 的算法固定为：对审计名先做 NFKC 规范化并去除首尾空白，取 UTF-8 字节计算 SHA-256，取小写十六进制摘要的前 8 位（如 `a1b2c3d4`）；同一审计名稳定得到同一摘要；短摘要用于降低规范化名称冲突概率，不保证绝对无碰撞。
- 主代理在审计开始时解析工作目录的**绝对路径**并记录到 `audit.md` 的 `stateDir`；检查、恢复与归档一律按该绝对路径定位，不得引用环境变量（受限环境可能重定向环境变量，导致真实目录被判缺失）。报告中必须附该路径。

## 2. 文件模板

### 2.1 `audit.md`（审计定义）

```markdown
| 键 | 值 |
|---|---|
| id | lep-2026-08 |
| name | LEPTON 交叉审计 v1.5 |
| ownerKey | <平台会话 id 或等价标识；拿不到时写 startedAt 紧凑时间戳（格式见下）> |
| stateDir | <工作目录绝对路径>\.audits\lep-2026-08（解析后的绝对路径，不写环境变量） |
| artifact | branch；base: 4943fb2；head: …；path: … |
| mode | audit-only / audit-and-fix / fix-verification |
| gate | 最终报告前填写：READY / READY-WITH-CONDITIONS / BLOCKED / INCOMPLETE |
| assumptions | 每行一条 |
| excluded | 每行一条（明确排除的范围与理由） |
| knownFacts | 每行一条（已确认事实与既有失败） |
| openClaims | 每行一条（待验证主张 / 未知项） |
| startedAt / updatedAt | ISO8601 |
```

- `ownerKey` 必须**唯一标识主会话/主代理**：优先取平台会话 id 或等价标识；该 id 用于路径前必须按与 `auditId` 相同的文件名安全规则清洗，禁止路径分隔符及 Windows 非法文件名字符。禁止通用占位符（如 `dsh-session`、`default`、`main`、`unknown`、空串、审计名本身）；确实拿不到时直接写 `startedAt` 的时间戳值，不得写占位符。时间戳值用**紧凑格式** `20260815T215947+08`（无冒号、无空格，保留时区后缀）——冒号在 Windows 文件名中非法，且避免归档键过长。**秒级时间戳仍可能同秒撞键**：兜底值追加至少 4 位随机后缀以降低冲突概率；创建目标目录前必须检查是否已存在，存在则重新生成后缀，直到取得未占用路径。
- `id`、`ownerKey`、`stateDir` 初始化后不再改动；写错时在报告中披露并按断点恢复重建。

### 2.2 `ledger.md`（候选账本）

账本只存主代理的**裁决状态与修复状态**（两套正交：问题是否成立 vs 是否仍待处理/已修复），不复制 findings 的内容字段：位置、严重度、归因、证据（DIRECT/INFERRED）以 findings 为唯一真相，账本用 `发现引用` 指回。

当前状态表（每候选一行，原地编辑该行）：

```markdown
| ID | 证据轴 | 来源 | 发现引用 | 验证方式 | 裁决 | 修复状态 | 模式范围 | 反证/备注 | 主代理修正 |
|---|---|---|---|---|---|---|---|---|---|
| C1 | engineering | SA-fix | SA-fix-3 | code-trace | CONFIRMED | OPEN | ISOLATED | — | 严重度 High/P1 → Medium/P2（依据：…） |
```

列取值：

- `验证方式`：`code-trace` / `runtime-probe` / `contract` / `test-discrimination` / `minimal-probe` / `unknown`（对应 `SKILL.md` §4 的验证步骤与 `behavioral-verification.md` 的验证方式；尚未验证写 `unknown`）。需要保留实证档案（探针输出、契约摘录、判别性测试记录）时，写入 `verification/<账本ID>.md` 并在该列写枚举值 + `（见 verification/<账本ID>.md）`；无需保留时只写枚举值。
- `裁决`：四种最终裁决值 `CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`；**新候选可直接写最终裁决值**。`待复核` / `已复核` 是可选中间态，仅在主代理暂缓裁决时使用，不是必经阶梯。最终裁决值确定后修改必须同时在变更记录说明理由。
- `修复状态`（与 `裁决` 正交，只表示"是否仍待处理/已修复"，不表示问题是否成立）：`OPEN`（默认；待处理或待修复）/`FIX-IN-PROGRESS`（修复实施或验证中）/`FIXED-VERIFIED`（修复已实施并有直接证据确认原候选消失，不再阻断）/`ACCEPTED-RISK`（用户或决策明确接受该风险，不再阻断）；`REJECTED` 裁决的候选无需修复，写 `—`。`NEEDS-DECISION` 裁决后：决定必须修复→`OPEN`，决定接受→`ACCEPTED-RISK`；`CONDITIONAL` 在补齐证据前保持 `OPEN`。门禁仅把 `OPEN` / `FIX-IN-PROGRESS` 视为仍阻断（见 `references/reporting.md` §4）。
- `发现引用`：对应 findings 条目 id；主代理直接发现的候选同样写入主代理专用 findings 文件（`findings/main.md`，子代理不得写）并在此引用，不允许用 `—` 跳过内容落盘。
- `模式范围`：`ISOLATED` / `SYSTEMIC` / `UNKNOWN`，仅模式搜索后填写。
- `反证/备注`：`REJECTED` 必填反证；`CONDITIONAL` 必填缺失条件；`NEEDS-DECISION` 必填选项与影响。
- `主代理修正`：只记录与 findings 不一致的裁决输出（位置/严重度/归因/证据/验证结论等），并附依据；一致写 `—`。账本其余列不得出现与 findings 不一致的内容。
- **聚合对照**：每条候选入账时，仅对账本**实际存储**的字段与 findings 逐条核对——`发现引用` 是否指向正确的 findings 条目；`证据轴`/`来源`/`验证方式`/`裁决`/`修复状态`/`模式范围`/`反证/备注` 是否与主代理裁决一致；`主代理修正` 非空时是否与 findings 的 位置/严重度/归因/证据 形成明确且附依据的偏差记录。位置、严重度、归因、描述、原始证据等**内容字段以 findings 为唯一真相，不得在账本中复制**；账本只在 `主代理修正` 列记录与 findings 的偏差（且不得与 findings 之外的其它列冲突）。不一致立即修正并记变更记录，Low 项同样执行。

变更记录表（只追加、不删旧行）：

```markdown
| 时间 | 对象 | 变更 |
|---|---|---|
| ISO8601 | C1 | 裁决 待复核 → CONFIRMED；复核方式 code-trace |
```

修订规则：当前状态以状态表该行内容为准；修订历史只存在于变更记录表（Markdown 账本没有 rev 编号机制）。出现以下任一**修正事件**时，必须更新该行并追加一条变更记录：

1. 裁决推翻（如 `REJECTED → CONFIRMED`、`CONFIRMED → REJECTED`）；
2. 位置 / 严重度 / 归因 / 证据更正（只记在 `主代理修正` 列并附依据，不得把这些内容字段复制进账本其它列；内容真相仍在 findings）；
3. 模式范围变化（如 `ISOLATED → SYSTEMIC`）。

一次成型的候选不产生修订历史；只有修正事件才留下历史链。

### 2.3 `coverage.md`（覆盖矩阵）

```markdown
| 单元 | 代理 | 证据轴 | 主责维度 | 路径/子系统 | 重叠不变量 | 发现条目 | 证据方式 | 状态 | 核对 |
|---|---|---|---|---|---|---|---|---|---|
| SA-fix\|engineering\|正确性\|vendor/lepton_jpeg | SA-fix | engineering | 正确性与不变量 | vendor/lepton_jpeg | get_block 下溢 | SA-fix-3, SB-7 | code-trace | verified | SA-fix-3→C1 CONFIRMED；SB-7→C2 REJECTED |
```

- `状态` 单向逐级推进：`planned → dispatched → reported → verified`（`dispatched` 后先到 `reported` 才能到 `verified`）；随里程碑同步：派发完成→`dispatched`，子代理发现文件写入/内联报告到达→`reported`，逐条复核定稿→`verified`。无法判定的单元留在当前状态并在报告"残留缺口"披露；`verified` 只在逐条复核定稿后标记。
- `发现条目` 显式链接本单元产出的 findings id。`verified` 判据：非空时每条都已聚合入 `ledger.md`（`发现引用` 引回）且对应候选全部到达终态；无候选问题（写 `无`）时，仍需主代理直接复核后才可标 `verified`。
- `核对`：标 `verified` 前，主代理必须逐条写下"发现条目 → 账本行 → 终态裁决"映射；无候选问题时写"主代理直接复核：无候选"。没有 `核对` 记录的 `verified` 视为未完成。
- 最高风险不变量必须有至少两个单元覆盖，且都达到 `verified`，才允许使用"未发现已确认缺陷"措辞（`reporting.md` §6）。

### 2.4 `findings/<axis>-<agent>.md`（子代理发现产物）

每个子代理只写自己这一个文件，按以下顺序组织：

1. **候选问题**：每条一个小节（模板如下）；
2. **已核验正确的高风险行为**：位置与直接证据，没有写"无"；
3. **覆盖与缺口**：实际检查了什么、未检查什么；
4. **缺陷模式与同类搜索建议**：可概括时写模式描述、搜索建议与范围假设；没有写"无"。

```markdown
## <finding-id> <位置>（<严重度>，置信度 <high/medium/low>，<DIRECT/INFERRED>）

- 归因：<本次引入 / 扩大或激活既有 / 纯既有 / 未知>
- 原始证据：<实际读取或运行所得>
- 原因→影响：<…>
- 触发条件：<…>
- 建议验证：<…>
```

- 置信度只用于主代理复核排序，不入 ledger、不进最终报告；报告定稿以裁决与严重度为准。
- 没有候选问题时写"无候选问题"，并附覆盖与缺口说明。
- 子代理只写自己的文件，不得读、写账本或其他代理的文件；主代理直接发现写入 `findings/main.md`，与子代理文件隔离；`<finding-id>` 在本次审计内唯一。

## 3. 落盘纪律

- 按自然里程碑批量落盘，不要求每个微步骤写盘，但**每个里程碑必须同步对应状态**：派发完成（`audit.md` + `coverage.md` 初始化、忽略规则已处理，状态→`dispatched`）、子代理报告到达（findings 落盘，状态→`reported`，随后聚合入账）、每候选复核定稿（实证档案写入 `verification/`、`coverage.md` 写 `核对` 映射后标 `verified`）、模式范围定稿、门禁输出（回填 `gate`）。禁止收尾时一次性把 `planned` 补写为 `verified`。
- 每次写盘后核对盘面与当前结论一致；盘上内容与最终报告不一致视为缺陷。
- 子代理无法写盘：全文内联返回，主代理代写入对应 findings 文件并注明"主代理代写"；这属于已披露降级，不改变"盘上即真相"的要求。
- 工作目录不可写：改用会话内账本（用同样的 Markdown 表格在对话中维护）并披露。
- 凭据、令牌、真实用户数据不回显：脱敏后入账，原文只保留给用户指定的安全位置或直接丢弃。

## 4. 断点恢复

1. 读取 `.audits/<auditId>/` 下的 `audit.md` 与 `coverage.md`，还原工件、基线、假设与矩阵状态。
2. 裁决尚未确定的候选继续复核/裁决；在 `audit-and-fix` / `fix-verification` 模式下，同时恢复 `修复状态 ∈ {OPEN, FIX-IN-PROGRESS}` 的候选，并恢复 `fix-map.md` 中尚未达到 `PASSED` 的批次；变更记录用于还原过程与理由。
3. 以 coverage `发现条目` 与 ledger `发现引用` 的差集为准，把"已报告、未聚合"的条目补聚合进账本。
4. 在报告"范围与基线"注明"恢复自 `<状态目录路径>`，中断点为 X，恢复后续审 N 项"。
5. 先在 `.audits/<auditId>/` 找（当前未归档状态），再查 `.audits/archive/` 下匹配 `*--<auditId>` 的目录（归档键为 `<ownerKey>--<auditId>`，见 §5）；命中多个时读取各 `audit.md` 的 base/head/scope 字段判定正确实例，不凭目录名猜测；都没有匹配才视为新审计，并在报告中披露"历史状态未找到，从零开始"。

## 5. 归档与跨轮复盘

- 审计结束：清理 `probes/` 与一切临时探针；随后把状态目录移入 `.audits/archive/<ownerKey>--<auditId>/`，报告附归档路径。
- 归档路径整体必须唯一；`ownerKey` 区分运行实例，`auditId` 稳定标识审计名称，不要求 `auditId` 本身唯一。
- 移入前检查目标归档路径；已存在时只在 `ownerKey` 一侧追加消歧值，例如 `<ownerKey>-<startedAt>--<auditId>` 或 `<ownerKey>-2--<auditId>`，不得在 `auditId` 后追加后缀；禁止覆盖或静默丢弃。
- 归档保留而非删除：下一轮审计先检索同工件/同范围的归档账本，上一轮裁决、反证、模式范围与未覆盖范围直接作为输入，而不是重跑一遍再比。
- 归档内容含敏感信息时，按与证据包相同的脱敏纪律处理后再保留。

## 6. 降级与披露

- 无法写盘（无文件能力、只读沙箱、平台限制）：继续审计，但改为会话内账本（用同样的 Markdown 表格在对话中维护）；报告"范围与基线"注明"审计状态未持久化"，且 `reporting.md` 完成清单对应项不得打勾。
- 单代理、窄范围且用户明确要快速结果：可最小化账本（至少 `audit.md` + `ledger.md`），但降级必须披露。
- 降级不改变其他纪律：子代理只读、DIRECT/INFERRED 标注、证据轴独立照常执行。

## 7. 账本与会话日志的分工

- 平台会话/事件日志是**过程事件源**（可重放）：记录过程而非当前状态，会话/审计边界不一致、含未脱敏原文、只读不可写。
- 账本是**归约后的当前状态**，由主代理按本文件维护；二者职责分离：日志=过程可重放，账本=结果真相。
