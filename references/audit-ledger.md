# 审计账本与断点恢复

审计主代理在**派发任何子代理之前**读取本文件并初始化审计状态；之后在自然里程碑更新状态（事实地图完成、风险单元派发、调查结果到达、Finding 定稿、Decision 定稿、模式范围定稿、门禁输出）。优先持久化到安全 `stateRoot`：Git 仓库中可使用已被忽略的 `.audits/`，否则优先仓库外 state root；若没有安全可写位置，则使用同构的会话内 Markdown 状态作为本次运行的**权威审计状态**并披露可恢复性降低。目标：能持久化时，会话中断后无需重跑已经完成的调查即可续审；跨轮审计可查询上一轮事实、Finding、Decision、反证与残留风险。子代理的“完成”声明、返回文本长度与顺序都不是权威。

审计状态仍以 **Markdown 作为唯一作者工件**；仅 `audit.md` 使用一小段 YAML front matter 保存稳定、机器可解析的 root metadata，正文继续承载可读契约与说明，不再维护第二份 JSON/JSONL ledger。平台具备会话/事件日志读取能力时，可由配套插件以确定性 reducer 投影生成机器视图。

## 1. 持久化状态目录与会话降级

持久化可用时，先确定一个**不会默认修改目标 Git repository metadata** 的 `stateRoot`。初始化顺序固定如下；只有用户明确授权 repository-local audit metadata 时才允许修改 `.git/info/exclude` 或项目 `.gitignore`：

1. 工作目录是 Git 仓库：先运行 `git check-ignore -q .audits/`。若仓库已经忽略 `.audits/` 且目录可写，使用 `<工作目录>/.audits` 作为 `stateRoot`，不修改任何 ignore 配置；
2. `.audits/` 未被忽略时，**audit-only 默认不写 `.git/info/exclude`、`.gitignore` 或其它 Git metadata**。优先使用平台提供、用户指定或当前环境明确提供的仓库外可写 state root；不要自行假定 `<workspace-parent>/.audit-state` 等路径安全可写；
3. 用户明确授权 repository-local audit metadata 时，才可运行 `git rev-parse --git-path info/exclude` 获取真实 exclude 路径并追加 `.audits/`，随后用 `git check-ignore -q .audits/` 验证；用户明确要求 ignore 规则随仓库提交时才写项目 `.gitignore`。任何这类修改都在报告中披露；
4. 工作目录不是 Git 仓库：可直接使用工作目录下 `.audits/`，或使用平台/用户指定的外部 state root；
5. 没有安全可写的持久化 `stateRoot` 时，使用会话内同构状态并写 `stateDir=session-only`。

审计状态本身是 Skill 输出；除上述明确授权的 repository-local metadata 外，项目源码、配置和 Git metadata 仍遵守只读契约。

```text
<stateRoot>/<auditId>/
├── audit.md             # 任务契约、基线、停止策略与各 gate target 的最终 Gate
├── project-map.md       # 可选：共享的最小 DIRECT 事实地图；不用独立文件时内嵌到 audit.md
├── coverage.md          # 可选：风险覆盖矩阵；不用独立文件时内嵌到 audit.md
├── ledger.md            # Finding → Decision 当前状态表 + 决策变更记录
├── fix-map.md           # 可选：修复映射与批次依赖图
├── investigations/     # 调查产物：Hypothesis + Evidence
│   └── <unit>-<agent>.md
├── findings/            # 主代理规范化后的 Finding；一项一文件
│   └── F<n>.md
├── verification/       # 主代理实证档案；verification/F<n>.md
└── probes/              # 主代理批准的隔离探针（结束时清理）
```

- `auditId`：生成一个本次审计实例唯一、文件名安全的本地 id 即可。推荐 `<startedAt紧凑时间>-<短slug>`；slug 只保留字母、数字、`-`、`_`，禁止路径分隔符和 `..`。创建目录前同时检查 `<stateRoot>/<auditId>/`、`<stateRoot>/archive/<auditId>/`，以及 `<stateRoot>/archive/<auditId>-*/` 中内部 `audit.md.auditId` 相同的实例；任一占用即追加短随机/递增后缀并重新检查。不要为了确定 id 引入哈希协议或额外外部依赖。
- 持久化可用时，主代理把解析后的持久化根记录为 `stateRoot`、活动状态目录绝对路径记录为 `stateDir`，并按这些路径定位；不可持久化时两者都写 `session-only`。持久化审计归档前计算并写入最终 `archiveDir`，归档后恢复与复盘按 `archiveDir` 或 §5 的实例搜索规则定位。

## 2. 四层语义模型

审计中固定区分四层，不允许混用：

1. **Hypothesis（H）**：可证伪的怀疑或缺陷理论，例如“跨窗口同步可能使用错误窗口”。它不是 Finding，也不能直接进入最终报告。
2. **Evidence（E）**：实际读取、运行或对应版本权威契约得到的直接观察，可支持、反驳或限定 Hypothesis/Finding。**推理不是 Evidence**；推理写在 reasoning 中，并由 Evidence 引用支撑。
3. **Finding（F）**：主代理把一个或多个 Hypothesis 规范化后形成的、可单独裁决的具体问题陈述，必须包含现实影响路径、触发条件/适用条件和 Evidence 引用。Finding 尚不等于“问题已确认”。
4. **Decision**：主代理对 Finding 的最终裁决：`CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`，并分别记录 Severity、Confidence 与 Disposition。Finding 自身按统一评估词汇记录 Provenance（归因不适用时为 `—`），用于区分变更风险与现存风险；Provenance 不等于责任归属，也不参与 Severity/Confidence 计算。当前 Gate 的缺陷阻断/条件由 Finding 的 Gate applicability + target-specific Gate treatment + Decision/Severity/Disposition 共同决定；coverage、Evidence 或 material Hypothesis 的关键完整性缺口可单独映射为 `INCOMPLETE`。

关系不是“所有 H 都必须变成 F”：Hypothesis 可以被 Evidence 直接反驳而关闭；证据不足的 material Hypothesis 可以保留为 residual gap。**material Hypothesis** 指“若为真可能形成 Medium+ Finding、改变任一 Gate/Decision/Severity、使 Confidence 跨越 Decision 所需阈值、揭示系统性模式或新增 highest/high 风险”的假设；纯风格或无实际影响猜测不算 material。只有值得主代理裁决的问题才提升为 Finding。

## 3. 文件模板

### 3.1 `audit.md`（任务、范围与停止状态）

`audit.md` 的**最小 YAML front matter 是核心机器可解析元数据的唯一权威源**；正文不得再复制这些字段。只给 root audit state 使用 YAML，不把 front matter 扩散到 ledger/Finding/investigation，避免双源。

```markdown
---
auditId: 20260822T003000Z-lep-audit
scopeMode: pr
objectiveProfile: [general]
executionMode: audit-only
gateTargets: [CHANGE]
independentValidationRequiredFor: []  # AUDIT 或实际 gateTargets；AUDIT 不与其它值并存
scopeBasis: PLATFORM
scopeConfidence: HIGH
scopeAssumption: null
base: <immutable commit>  # 不适用写 null
head: <immutable commit>  # 不适用写 null
sharedFactsLocation: project-map.md  # 或 embedded
coverageLocation: coverage.md        # 或 embedded
stopPolicy: standard
stopCriteria: null          # user-defined 时写归一后的显式停止/预算条件列表
noMaterialDeltaRounds: 0
gates: {}                 # 收口时写 CHANGE/RELEASE/SYSTEM → Gate
stopReason: null
startedAt: <ISO8601>
updatedAt: <ISO8601>
---

# Audit contract

## State locations
- stateRoot: <解析后的持久化状态根绝对路径> / session-only
- stateDir: <解析后的活动状态目录绝对路径> / session-only
- archiveDir: —

## Target and scope
- name: <审计显示名>
- target: <仓库/分支/commit/PR/工作区/计划/配置/迁移/功能/修复工件>
- scope: <实际纳入的路径、子系统、提交范围或计划章节>
- objectives: <本次必须回答的问题>
- riskTolerance: standard / <已归一的 target-specific 条件>
- availableEvidence: <类型与可用性；不记录秘密>
- deliverable: <门禁报告/问题报告/追溯报告/修复验证报告/用户指定输出>

## Assumptions
- <每行一条>

## Excluded
- <范围 + 理由>

## Residual risks
- <结束时仍存在的风险/证据缺口>

## Embedded shared facts
> 仅当 `sharedFactsLocation=embedded` 时创建；否则省略整个 section。字段语义与独立文件一致。
- <DIRECT fact + source>

## Embedded coverage
> 仅当 `coverageLocation=embedded` 时创建；否则省略整个 section。字段语义与独立文件一致。
| 单元 | Claim ID | Obligation | Exploration round | 风险面 | 风险主张/不变量 | 失败后果 | Risk priority | Gate targets | 验证方法 | 执行者 | Judgment isolation | Sufficiency | 证据视角 | 路径/子系统 | 调查文件 | Finding | 状态 | 核对 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | Q1 | REQUIRED | — | ... | ... | ... | highest | CHANGE | ... | ... | — | — | engineering | ... | investigations/R1-<agent>.md | — | planned | — |

### Embedded discrimination plans
> `highest/high` 单元必填。

#### R1
- Safe prediction: <...>
- Failure prediction: <...>
- Discriminating observation: <...>
- Sufficiency criterion: <足以裁决本风险主张的 Evidence 条件>
```

- front matter 中的 `auditId` 初始化后不改；`independentValidationRequiredFor` 只有用户授权或适用组织/Gate 策略明确改变时才更新；`stopPolicy` / `stopCriteria` 只有用户明确改变停止约束时才更新；`updatedAt`、`gates`、`stopReason`、`noMaterialDeltaRounds` 按过程更新。持久化路径属于运行位置，不复制到 front matter；`stateRoot` / `stateDir` / `archiveDir` 只写正文 State locations。
- `scopeBasis` 只使用 `USER` / `PLATFORM` / `REPOSITORY` / `ASSUMED`；`scopeConfidence` 只使用 `HIGH` / `MEDIUM` / `LOW`，表示所选范围是否忠实于用户意图，**不是 Finding Confidence**。`scopeAssumption` 只在存在推定或重要限定时填写。
- `sharedFactsLocation` 只使用 `project-map.md` / `embedded`；`coverageLocation` 只使用 `coverage.md` / `embedded`。初始化后两者分别固定，审计期间不得切换或双写。选择独立文件时，`audit.md` 不得保留对应 Embedded 内容；选择 `embedded` 时，对应独立文件不得存在。独立与内嵌 coverage 使用同一字段 schema；两种位置都不得改变 H/E/F/Decision、required coverage、Gate relevance 或 Sufficiency 语义。
- `gateTargets` 是主代理决策层字段：`CHANGE` / `RELEASE` / `SYSTEM` / `NONE`；`NONE` 不能与其它值并存。多个 target 必须共享同一个权威 Audit target 和状态快照，分别写入 `gates`，不得只保存一个“最坏 Gate”；不同版本、候选或部署状态拆成独立审计实例。
- `independentValidationRequiredFor` 只使用 `AUDIT` 或当前实际请求的 `CHANGE` / `RELEASE` / `SYSTEM`；默认空列表。`AUDIT` 表示本次审计的所有最高风险 `Claim ID` 都强制 independent validation，不能与其它值并存；Gate target 值只约束至少一个单元支撑该 target 的最高风险 `Claim ID`，且用于满足该组的两个异质单元都必须支撑该 target。显式要求的作用域必须至少有一个最高风险组。它只记录已明确的任务/组织/Gate 要求，不记录平台是否有可用执行者。
- `stopPolicy` 默认 `standard`；用户明确逐文件/逐行/穷尽时为 `exhaustive`；有明确调查预算/停止标准时为 `user-defined`。`stopPolicy=user-defined` 时 `stopCriteria` 必须是非空、可执行的归一条件列表；其它模式默认 `null`。用户预算、最大轮数、资源/授权上限等不得只留在聊天上下文。`noMaterialDeltaRounds` 只持久化探索轮计数，阈值与完成规则由主流程定义。

### 3.2 `project-map.md`（共享事实，隔离判断）

`project-map.md` 是可选的**补充事实层**：target/base/head/scope/excluded 以 `audit.md` 为唯一权威源，本文件不重复保存；这里只记录会被多个风险单元复用的 DIRECT 项目事实。若不建本文件，则把等价内容写入 `audit.md` 的 Embedded shared facts。禁止写 Hypothesis、Finding、Decision、严重度判断、Risk tolerance、其他调查者结论或“这里可能有 bug”之类暗示。

```markdown
# Project map

## Project / subsystem map
- <subsystem> → <职责/入口/关键依赖>

## Terminology
- <term> = <项目内实际含义>（source: ...）

## Public entrypoints
- <CLI/API/UI/SDK/migration/...> → <入口位置>

## Changed / touched areas
- <path> → <变更/触达事实；全项目审计无明确变更时写 —>

## Shared facts
| Fact ID | DIRECT fact | Source |
|---|---|---|
| P1 | ... | path:line / command / authoritative contract |

## Known baseline failures
- <已有失败及直接来源>
```

- 主代理先建立最小 map，再派发；只收集会被多个风险单元重复使用的事实，不为“完整地图”扫描无关文件。`P<n>` 是共享 factual context id；它可以作为 Finding 的上下文引用，但 material Decision 仍应引用至少一个调查/验证 Evidence (`R*-E*` / `F*-E*`)。
- 调查者只接收与自己风险单元相关的共享事实摘要，不批量读取其他风险单元的判断。调查者可反驳共享事实层（独立 `project-map.md`，或 `audit.md` Embedded shared facts）的补充事实：发现错误时回报 `MAP-CORRECTION` + 直接 Evidence，由主代理统一修正。主代理随后必须执行依赖失效传播：识别以该事实为 material 前提的 coverage、Hypothesis、Finding、Decision 与 Gate applicability；进行中的单元补发更正，已完成单元新增最小 `REQUIRED` 补充复核单元，复核完成前旧单元不得单独满足该风险主张的 required coverage；所有受影响 Finding 暂时改为 Decision=`PENDING`、Severity=`—`、Confidence=`—`、Disposition=`OPEN`，并对每个请求 Gate 写 `UNRESOLVED`。旧 Decision / Severity / Confidence 只保留在追加式 Decision 变更记录中，不得留作 live ledger 值或用于最终报告/Gate；补充复核完成后重新执行 disconfirmation，重新评估 Decision / Severity / Confidence / Provenance / Disposition / Gate applicability，并重算所有受影响 Gates。不得只更新 coverage 后沿用旧裁决。
- `MAP-CORRECTION` 只用于补充共享事实；若调查者发现 `audit.md` 的 canonical metadata 或 target/scope/excluded 可能错误或冲突，必须作为任务契约/基线冲突返回，由主代理重新解析并在必要时重新规划受影响 coverage，不能静默修改 shared facts 规避契约。
- **共享事实，隔离判断**：可共享 `audit.md` 的任务/范围事实，以及权威共享事实位置中的术语、入口、changed files、DIRECT 项目事实；必须隔离其他人的 Hypothesis、Evidence 解释、Finding、Decision、主代理预期答案。

### 3.3 `ledger.md`（Finding → Decision）

ledger 只保存**主代理规范化 Finding 的 Decision 摘要**，不保存调查者原始 Hypothesis/Evidence 文本。Finding 内容与风险评估维度在 `findings/F<n>.md`，调查来源在 `investigations/`，主代理直接验证在 `verification/`。Severity / Confidence / Evidence Strength 使用任务协议已经加载的统一评估词汇。

```markdown
| Finding | Decision | Severity | Confidence | 主验证方法 | Disposition | 模式范围 | Decision rationale |
|---|---|---|---|---|---|---|---|
| F1 | CONFIRMED | High | High | user-path-trace（见 verification/F1.md） | OPEN | ISOLATED | F1-E1(ES3) + R2-E3(ES2) 支持，counter-hypothesis 已反驳 |
```

- `Decision`：最终值与语义使用任务统一 assessment model；ledger 仅额外允许工作态 `PENDING`，任务收口前不得保留 `PENDING`。
- `Severity`：`Critical` / `High` / `Medium` / `Low` / `—`。按统一评估模型的 Impact / Likelihood / Reachability / Recoverability 映射；**不得使用 Confidence 作为降级理由**。最终非 `REJECTED` Decision（`CONFIRMED` / `CONDITIONAL` / `NEEDS-DECISION`）必填 Severity；工作态 `PENDING` 与 `REJECTED` 写 `—`，确保 gate 不依赖缺省值或失效旧值猜测。
- `Confidence`：`Very-High` / `High` / `Medium` / `Low` / `—`，表示 Finding 为真的确定程度，不表示影响大小；最终非 `REJECTED` Decision 必填 Confidence，且 `CONFIRMED` 只能使用 `High` / `Very-High`；工作态 `PENDING` 与 `REJECTED` 写 `—`。
- `主验证方法`：使用任务风险地图中的统一 verification archetype；主代理对决定性 Evidence 的直接复核及新增 Evidence 写入 `verification/F<n>.md`。只有 Decision=`PENDING` 时可暂写 `unknown`；最终 Decision 定稿前必须替换为实际方法。
- `Disposition` 与 Decision 正交，但合法组合固定：`PENDING` / `CONDITIONAL` / `NEEDS-DECISION` 只使用 `OPEN`；`CONFIRMED` 可使用 `OPEN` / `REMEDIATING` / `RESOLVED-VERIFIED` / `ACCEPTED-RISK`；`REJECTED` 写 `—`。`RESOLVED-VERIFIED` 表示 Finding 曾真实成立，但 DIRECT Evidence 已验证它在本次审计的唯一权威状态快照中不再适用；消除机制可以是修复、后续提交、revert 或 superseding change。此时保留原 Decision 与 Provenance，把请求 Gate 的 applicability 按该同一快照重新定稿，并在 `verification/F<n>.md` / Decision rationale 记录 resolution Evidence。证据补齐或授权决策完成后，先更新 Decision，再进入相应 Disposition。
- `ACCEPTED-RISK` 只能由当前用户明确决定，或由任务开始前已经归一且无歧义覆盖该 Finding 的授权风险策略触发；主代理不得自行“接受”风险。`gateTargets=NONE` 时，只有授权明确覆盖该 Finding 本身才设置 `ACCEPTED-RISK`。存在多个真实 `gateTargets` 时，只有授权明确覆盖该 Finding 的所有相关请求 target 才设置全局 `ACCEPTED-RISK`；只针对单个 target 的接受保留实际 Disposition，并在 Finding 的 `Gate treatment` 中把该 target 写为 `ACCEPTED`；`ACCEPTED` 只用于 Decision=`CONFIRMED`、Gate applicability=`APPLIES` 且授权明确覆盖该 Finding/target 的情况，不能用来绕过 `PENDING` / `CONDITIONAL` / `NEEDS-DECISION` 或 Evidence/coverage 缺口。设置全局 `ACCEPTED-RISK` 或 target-specific `ACCEPTED` 时必须保存授权依据。
- `模式范围`：`ISOLATED` / `SYSTEMIC` / `UNKNOWN`；未做同类搜索时写 `UNKNOWN`。
- `Decision rationale` 必须引用 Finding/verification 中的 Evidence ID，不写“两个 agent 都认为”等投票理由。

Decision 变更记录只追加：

```markdown
| 时间 | Finding | 变更 |
|---|---|---|
| ISO8601 | F1 | Decision PENDING → CONFIRMED；Severity High；Confidence High；依据 F1-E1(ES3)、R2-E3(ES2) |
```

以下变化必须追加记录：Decision、Severity、Confidence、Disposition、模式范围或决定性 Evidence/反证结论发生实质变化；Finding 的 Provenance、Gate applicability 或非默认 Gate treatment 变化若影响 Gate/归因，也追加记录。纯格式编辑不记录。`gates` 是 `audit.md` 的派生输出状态，按最终 Gate 重新计算并更新，不混入 Finding 的 Decision 变更记录。

### 3.4 `coverage.md`（风险覆盖矩阵）

```markdown
| 单元 | Claim ID | Obligation | Exploration round | 风险面 | 风险主张/不变量 | 失败后果 | Risk priority | Gate targets | 验证方法 | 执行者 | Judgment isolation | Sufficiency | 证据视角 | 路径/子系统 | 调查文件 | Finding | 状态 | 核对 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | Q1 | REQUIRED | — | boundary-conditions | `get_block` 不得发生下溢 | 错误结果 | highest | CHANGE,RELEASE | implementation-trace | SA-fix | ISOLATED | MET | engineering | vendor/lepton_jpeg | investigations/R1-SA-fix.md | F1 | verified | R1-H1→F1；R1-H2→refuted(R1-E4) |
| R2 | Q1 | REQUIRED | — | boundary-conditions | `get_block` 不得发生下溢 | 错误结果 | highest | CHANGE,RELEASE | state-invariant-analysis | SB-check | ISOLATED | MET | engineering | vendor/lepton_jpeg | investigations/R2-SB-check.md | F1 | verified | R2-H1→F1 |
```

- `单元` 使用审计内唯一 id（`R1` / `R2`）。一个单元只表示“一个风险主张 + 一个验证方法 + 一个有界范围”；第二种方法创建第二个单元。
- `Claim ID` 使用审计内稳定 id（`Q1` / `Q2`），机械标识同一风险主张/不变量、适用条件和有界范围；同一组的不同 archetype 单元必须复用该 id，并保持风险面、风险主张/不变量、失败后果、Risk priority、Gate targets 与路径/子系统一致。任一这些组级语义实质不同或主张被缩窄时创建新 `Claim ID`，不得靠近似自由文本临场归组。
- `Obligation` 只使用 `REQUIRED` / `EXPLORATORY`。完成 Task Contract、最高风险所需的异质覆盖、`independentValidationRequiredFor` 明确要求的 independent validation、或已发现 material gap 的收口所必需的单元必须为 `REQUIRED`；只有当前完成义务之外的额外搜索才为 `EXPLORATORY`。`REQUIRED` 不得为了触发停止规则而降成 `EXPLORATORY`。探索单元产生 material delta 时自身仍保持 `EXPLORATORY`，由它产生的新完成义务另建 `REQUIRED` 单元。
- `Exploration round`：`REQUIRED` 固定写 `—`；`EXPLORATORY` 使用 `X1` / `X2`…，同一轮的单元必须在读取该轮任何结果前一并规划。只有一整轮 exploratory 单元都已完成 H/E 处置后，主代理才按主流程更新 `noMaterialDeltaRounds`。
- `Risk priority` 只使用 `highest` / `high` / `normal`，其设计语义由 `review-dimensions.md` 负责；这里把它作为一等状态持久化，不能再埋入“失败后果”自由文本。它是 coverage 派发优先级，不是 Finding Severity。
- `Gate targets` 由主代理在规划 coverage 时填写，只表示该单元的完成/缺口会影响哪些请求 Gate；多个值用逗号分隔，`gateTargets=NONE` 或该单元仅服务非门禁 Deliverable 时写 `—`。调查者不需要看到这个字段。某 coverage 缺口只使这里列出的 Gate 进入相应完整性判断，不能污染其它 Gate。
- `highest/high` 单元必须保存由 `review-dimensions.md` 设计的 **Discrimination plan**：`Safe prediction / Failure prediction / Discriminating observation / Sufficiency criterion`；本文件只规定其存储位置，不重复定义设计语义。独立 `coverage.md` 写在对应 coverage 条目下；内嵌 coverage 则写 `audit.md` 的 Embedded discrimination plans。两种保存方式必须保持同一字段结构：

```markdown
### Discrimination plan
- Safe prediction: <...>
- Failure prediction: <...>
- Discriminating observation: <...>
- Sufficiency criterion: <...>
```
- `Sufficiency` 是主代理对计划 criterion 的核对结果：`planned/dispatched/reported` 阶段写 `—`；`highest/high` 单元在主代理核对时定稿 `MET` / `NOT-MET`；没有 criterion 的 normal 单元写 `N/A`。判定可引用当前风险主张已经汇总的其它 DIRECT Evidence，但必须保持 Evidence 来源与判断隔离可追溯。`verified` 只表示 H/E 已核对，不自动等于 Evidence 充分；`NOT-MET` 必须映射 residual gap 或补充 `REQUIRED` coverage。若该单元列出某个 Gate target，则在 criterion 重新达到 `MET` 前，该 target 不得 `READY`。
- `Judgment isolation` 在 `planned` / `dispatched` / `reported` 阶段可写 `—`；主代理在核对实际信息暴露后、coverage 达到 verified 前定稿为 `ISOLATED` / `NOT-ISOLATED` / `N/A`。实际隔离边界以 `auditor-persona.md` 为规范；不同 executor 名称本身不足以证明隔离。`N/A` 仅用于该单元不参与 independent validation 声称。只有相关单元由不同执行者完成、均为 `ISOLATED` 且未接触其它判断路径结论时，才可声称 independent validation。
- `状态` 单向推进：`planned → dispatched → reported → verified`。`reported` 表示调查文件已到达；`verified` 只有在主代理完成该单元的 H/E 核对后才能写。对 `highest/high` 单元，进入 `verified` 前还必须把 `Sufficiency` 从 `—` 定稿为 `MET` / `NOT-MET`。
- `核对` 必须逐个处理 material Hypothesis：`H→F<n>`、`H→refuted(E...)` 或 `H→residual-gap(...)`。`H→F<n>` 前还必须确认该 H 的 disconfirmation 四项完整；不能因为调查者写“无问题”或只给支持 Evidence 就直接 verified。
- `Finding` 列列出由该单元促成的 F id；没有写 `—`。同一 F 可以被多个异质单元共同支持。
- 每个最高风险 `Claim ID` 用于满足异质要求的单元必须全部 `Obligation=REQUIRED`、使用不同 archetype 且 `verified` 才算异质覆盖。不同合格隔离执行者可用时默认由不同执行者完成且相关单元均为 `Judgment isolation=ISOLATED`；未同时满足时必须隔离重跑，或在确受能力限制时于 `audit.md` Residual risks 披露后按有界降级收口。只有同一 `Claim ID` 的相关单元由不同执行者完成、均为 `Judgment isolation=ISOLATED` 且判断路径未共享前序结论时，才可额外计为 independent coverage。能力不可用时单执行者异质覆盖仍可完成；但 `independentValidationRequiredFor=AUDIT` 时所有最高风险组、值为某个 Gate target 时所有支撑该 target 的最高风险组都必须真正完成 independent coverage，能力限制披露不能替代该 required completion 义务。

### 3.5 `investigations/<unit>-<agent>.md`（Hypothesis + Evidence）

调查者只记录 Hypothesis、Evidence、reasoning、已验证正确行为与缺口；**不得创建最终 Finding ID、Decision 或最终严重度**。

```markdown
## R1-H1 Hypothesis
- Coverage unit：R1
- Claim ID：Q1
- 风险面：boundary-conditions
- 验证方法：implementation-trace
- 假设：<可证伪的具体陈述>
- 潜在影响：<若为真，现实上会造成什么；不写最终严重度>
- 适用/触发条件：<...>
- Safe prediction（planned）：<来自 coverage discrimination plan；不适用写 —>
- Failure prediction（planned）：<来自 coverage discrimination plan；不适用写 —>
- Discriminating observation（planned）：<来自 coverage discrimination plan；不适用写 —>
- Sufficiency criterion（planned）：<来自 coverage discrimination plan；不适用写 —>
- Counter-hypothesis：<最强现实安全解释；若成立会使原 H 为假或显著缩窄>
- Expected safe behavior：<若 counter 为真，应观察到什么 guard/lock/caller constraint/contract/runtime behavior>
- Evidence searched for disconfirmation：<实际检查范围>
- Disconfirmation result：counter-supported / counter-refuted / unresolved
- Evidence refs：R1-E1, R1-E2
- Investigation result：supported / refuted / unresolved
- Reasoning：<Evidence → 假设的推理；明确这是推理，不是 Evidence>
- 建议：promote-to-finding / close / residual-gap

### R1-E1 Evidence
- Polarity：supports / refutes / context
- Strength：ES1 / ES2 / ES3 / ES4
- Reproducibility：repeatable / conditional / single-observation / not-applicable
- DIRECT source：<实际读取的 path:line、命令结果、目标版本契约等>
- Observation：<只写观察事实>

#### Test discrimination（仅当该 Evidence 依赖测试判别力）
- Test：<name/path>
- Discrimination：YES / PARTIAL / NO / UNKNOWN
- Basis：<safe/failure 是否产生不同结果；PRE-fix/变异/等价检查>
- Test issue：ENCODES_FAILURE / MISSING_REGRESSION / —
```

- Evidence 必须是 DIRECT；“根据经验推测”“看起来可能”属于 reasoning/Hypothesis，不得编号成 E。每条 Evidence 使用任务协议统一的 Strength / Reproducibility 词汇评定。测试被用于 material Evidence 时，把 test-discrimination 记录放在对应 investigation/verification Evidence 附近，不新增 ledger 字段。
- 一个 Hypothesis 可引用多个支持和反证 Evidence；**每个准备 `promote-to-finding` 的 material Hypothesis 必须完成 Counter-hypothesis / Expected safe behavior / Evidence searched / Disconfirmation result 四项**。若 H 与 risk-unit 预测完全一致，`Expected safe behavior` 可引用 Safe prediction 而不重复抄写；仍必须记录实际反证搜索。
- `Investigation result` 是调查者的局部判断，不是 Decision；主代理可以不同意。
- 没有 material Hypothesis 时写“无 material hypothesis”，仍列出已检查范围、关键 Evidence/已验证正确行为与缺口。
- `H`/`E` id 在审计内通过 unit 前缀保持唯一，例如 `R2-H3` / `R2-E7`。

### 3.6 `findings/F<n>.md`（主代理规范化 Finding）

只有主代理可以创建/修改 Finding。一个 Finding 可以聚合多个 Hypothesis。主代理自己发现问题时也先在 `investigations/<unit>-main.md` 记录 H/E，再提升为 Finding，不绕过四层链。

```markdown
# F1 <短标题>

- 风险面：<一个主要风险面；必要时附次要风险面>
- Finding statement：<具体、可裁决的问题陈述>
- 位置/范围：<path:line / public entrypoint / config / plan section>
- Provenance：INTRODUCED / EXPOSED / REGRESSED / PRE_EXISTING / UNKNOWN / —（不适用变更归因）
- 原因→影响：<现实影响链>
- 触发/适用条件：<...>
- Source hypotheses：R1-H1, R2-H1
- Supporting evidence：R1-E1, R2-E3, F1-E1
- Refuting/limiting evidence：<E ids 或 —>
- Disconfirmation summary：<counter-hypothesis + searched Evidence + result；引用来源 H/E>
- Impact：Critical / High / Medium / Low
- Likelihood：High / Medium / Low
- Reachability：Common / Conditional / Privileged
- Recoverability：Irreversible / Manual / Automatic
- Severity mapping：<按统一评估模型的基线/有限调整规则说明；不以 Confidence 调整>
- Provenance evidence：<支持 provenance 的 base/head/history/reachability Evidence；不适用写 —>

## Gate applicability
> `gateTargets=NONE` 时省略；否则只列实际请求的 target。`REJECTED` Finding 可省略本表。
| Gate target | Applicability | Basis | Evidence |
|---|---|---|---|
| CHANGE | APPLIES / DOES-NOT-APPLY / UNRESOLVED | <为何参与/不参与/尚不能判断该 Gate> | <DIRECT Evidence ids> |

## Gate treatment
> 仅当至少一个请求 Gate 使用非默认策略时填写；本节缺省、或本节存在但未列出的 target，都等价于 `STANDARD`。这里只记录已经实际应用到本 Finding 的 target-specific 门禁处理，不改写事实或 Gate applicability。
| Gate target | Treatment | Authorization |
|---|---|---|
| CHANGE | ACCEPTED | <当前用户明确授权或 audit.md 中已归一政策的可追溯引用> |

- 建议验证/退出条件：<可观察、可测试、可判定>
```

- `Gate applicability` 是 Finding 对每个请求决策问题的当前权威适用性；具体三值语义与 Gate 映射由 reporting owner 定义，ledger 不复制。它不替代 Decision：Finding 是否真实由 Decision 表达，是否参与某个当前 Gate 由 applicability 表达。
- `Gate treatment` 只保存已实际应用到该 Finding 的 target-specific 非默认门禁处理；唯一非默认值为 `ACCEPTED`，未建本节或未列出的 target 都是 `STANDARD`。合法性与 Gate 应用规则由 reporting owner 定义；它是授权政策状态，不是 Evidence、Decision、Severity、Provenance 或 applicability。
- Finding 是“可裁决的问题对象”，不是 `CONFIRMED` 的同义词；Provenance 与风险维度/Severity mapping/反证过程保留在 Finding 文件，ledger 只保留最终 Decision / Severity / Confidence，避免把历史归因与风险判断混为一谈。
- 主代理验证产生的新 Evidence 放 `verification/F<n>.md`，Evidence id 用 `F<n>-E<m>`；每条保持与 investigation Evidence 相同的 `Polarity / Strength / Reproducibility / DIRECT source / Observation` 五字段，Finding 文件引用这些 id。
- 多个调查者描述同一逻辑问题时只建立一个 Finding，保留所有来源 Hypothesis/Evidence；不同根因或不同现实影响需独立裁决时才拆分。

## 4. 落盘纪律

- 严格按 `sharedFactsLocation` / `coverageLocation` 写入唯一权威位置：选择独立文件时先写 `audit.md` + 对应文件，选择 `embedded` 时先写 `audit.md` 的对应 Embedded section。不得同时保留两种表示；两种位置都先规划后搜证。
- 派发后权威 coverage（独立文件或内嵌 section）→`dispatched`；调查内容到达后→`reported`；主代理逐个核对 material Hypothesis，把它们映射到 Finding / refuted / residual gap 后→`verified`。
- Finding 创建/合并后更新 `findings/F<n>.md`；Decision 定稿后更新 `ledger.md`；主代理实证写 `verification/F<n>.md`。禁止收尾时一次性把 `planned` 补成 `verified`。
- 每次更新权威审计状态后核对其与当前结论一致；权威状态与最终报告不一致视为缺陷。
- 子代理无法写持久化状态：全文内联返回，主代理写入当前权威审计状态对应的 investigation 内容并注明“主代理代写”；不改变状态权威性。
- 凭据、令牌、真实用户数据不回显；只保存满足审计目的所需的脱敏 Evidence。

## 5. 断点恢复

1. 找到正确状态实例后先读取 `audit.md` 与 `ledger.md`；仅接受当前协议定义且所需字段完整的状态实例，不解析或补全旧格式。严格按 `sharedFactsLocation` / `coverageLocation` 恢复：指向独立文件时该文件必须存在且对应 Embedded section 必须不存在；指向 `embedded` 时对应独立文件必须不存在且 Embedded section 必须存在。发现双源、缺源或指针不一致时状态无效/待消歧，不得静默选择较新的内容。`stopPolicy=user-defined` 时 `stopCriteria` 必须存在且非空；缺失即状态无效，不得猜测或从旧格式迁移。
2. 对当前权威 coverage，`reported` 但未 `verified` 的单元读取对应 investigation，补做 H→F/refuted/gap 核对，不重跑调查者。
3. Finding 存在但 Decision=`PENDING`：继续 disconfirmation、风险维度/Confidence 评估、主代理验证与裁决；`verification/` 已有 Evidence 直接复用，不重复采集。
4. 在 `audit-and-fix` / `fix-verification` 模式下，同时恢复 Disposition `OPEN` / `REMEDIATING` 和 `fix-map.md` 未 `PASSED` 批次。
5. 从 coverage 的 `Claim ID / Obligation / Exploration round / Sufficiency` 恢复风险主张归组、required/exploratory 边界、已完成探索轮与 Evidence 充分性；再恢复 `noMaterialDeltaRounds` 与 residual risks。已完成的 exploration round 不重跑，未完成的 round 不提前计入无 material delta 轮次。
6. **持久化状态**的新会话若已知 `auditId`，先查 `<stateRoot>/<auditId>/` 与 `<stateRoot>/archive/<auditId>/`；精确归档路径不存在时再查 `<stateRoot>/archive/<auditId>-*/`，并用内部 `audit.md.auditId`、target、base/head、scope 与时间验证候选。未知 id 时按同一元数据筛选。命中多个且无法唯一判断时请求用户决定。无匹配时明确披露“历史状态未找到”。`stateDir=session-only` 的状态不承诺跨会话恢复。
7. 最终报告注明恢复路径、中断点和恢复后继续处理的单元/Finding 数量。

## 6. 归档与跨轮复盘

- 审计结束：先清理探针与临时资源；持久化状态再把活动目录移入 `<stateRoot>/archive/<auditId>/`，报告附归档路径。`stateDir=session-only` 时只披露未持久化与跨会话恢复限制。
- 归档路径必须唯一；极端并发导致 `<stateRoot>/archive/<auditId>/` 冲突时，仅对目录名追加短消歧后缀并写入 `archiveDir`，不得修改 front matter 中不可变的 `auditId`，也不得覆盖或静默丢弃。
- 下一轮同工件/同范围审计先读取历史 `audit.md`、存在的 `project-map`、Finding/Decision、反证、模式范围与 residual risks；**共享已确认事实，重新形成新 Hypothesis/判断**，不要机械重跑背景搜集，也不要把旧 Decision 当作新一轮的预期答案；只有满足不同执行者与判断隔离条件时，才把新一轮对应路径声称为 independent validation。
- 归档含敏感信息时按证据脱敏纪律处理。

## 7. Independent validation 声称与状态保存

- **Independent validation 是结果声称，不是全局运行模式**：只有同一 `Claim ID` 的相关 required coverage 由不同执行者完成、实际 `Judgment isolation=ISOLATED`，且判断路径未共享前序结论时，才能声称 independent validation。同一执行者换方法仍可形成异质验证，但不是独立验证。
- **默认分配与降级不在账本重复定义**：按 `SKILL.md` §3/§7 执行默认多代理、隔离重跑、有界降级和明确强制独立验证的完成规则；本账本只保存实际 executor、`Judgment isolation`、required coverage 与 Residual risks。
- **文件颗粒度不是协议模式**：共享事实和 coverage 可使用独立文件，也可内嵌到 `audit.md`；是否拆分由本地 Agent 根据任务规模、可写环境和恢复需要决定，但必须由 `sharedFactsLocation` / `coverageLocation` 固定唯一权威位置。
- **持久化能力单独处理**：使用初始化阶段选定的安全 `stateRoot`；没有安全可写位置时使用同构 session-only 状态并披露跨会话恢复限制。
- 普通无需交叉验证的窄问答不应为了这些状态机制而触发本 Skill。

## 8. 账本与会话日志的分工

- 平台会话/事件日志是**过程事件源**（可重放）；可能含未脱敏原文且会话边界不等于审计边界。
- 本状态结构是**归约后的审计状态**：共享事实与 coverage 可分别位于 `project-map` / `coverage`，也可内嵌到 `audit.md`；`investigations`=H/E，`findings`=规范化问题对象，`ledger`=Decision。持久化与 session-only 只改变保存位置，不改变职责。
