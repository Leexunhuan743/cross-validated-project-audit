# 审计账本与断点恢复

审计主代理在**派发任何子代理之前**读取本文件并初始化审计状态；之后在自然里程碑更新状态（事实地图完成、风险单元派发、调查结果到达、Finding 定稿、Decision 定稿、模式范围定稿、门禁输出）。优先持久化到 `.audits/`；若环境不可写，则使用同构的会话内 Markdown 状态作为本次运行的**权威审计状态**并披露可恢复性降低。目标：能持久化时，会话中断后无需重跑已经完成的调查即可续审；跨轮审计可查询上一轮事实、Finding、Decision、反证与残留风险。子代理的“完成”声明、返回文本长度与顺序都不是权威。

审计状态一律用 **Markdown 作为唯一作者格式**：人机皆可直接读写，无转义与机器格式维护负担。机器格式（如 JSONL）不在纯 skill 阶段手写；平台具备会话/事件日志读取能力时，由配套插件以确定性 reducer 投影生成。

## 1. 持久化状态目录与会话降级

持久化可用时，审计状态写在**工作目录**下的 `.audits/`。初始化时主代理按顺序处理忽略规则；若最终判定不可写，则按第 5 步切换到会话内同构状态：

1. 工作目录是 Git 仓库：运行 `git check-ignore .audits/`——已被忽略则什么都不写；
2. 未忽略时，运行 `git rev-parse --git-path info/exclude` 取得真实排除文件路径（linked worktree 中 `.git` 可能是文件而非目录，不能假设 `.git/info/exclude` 可直接写），避免重复后把 `.audits/` 追加进该路径；随后重新运行 `git check-ignore -q .audits/` 确认规则实际生效。仍未忽略时披露，不声称忽略已成功；排除文件不可写但 `.audits/` 可写时披露并继续（不得提交其中内容）；
3. 用户明确要求忽略规则随仓库提交时，才写项目 `.gitignore`，并在报告中披露该项目修改；
4. 工作目录不是 Git 仓库：直接使用 `.audits/`，无需忽略规则；
5. `.audits/` 不可写时改用会话内账本（沿用本文件同样的 Markdown 结构）并披露。

其余项目文件仍遵守只读契约。

```text
<工作目录>/.audits/<ownerKey>--<auditId>/
├── audit.md             # 任务契约、基线、停止策略与最终 gate
├── project-map.md       # 共享的最小 DIRECT 事实地图；不含假设、Finding、Decision
├── coverage.md          # 风险覆盖矩阵（Risk → method → executor）
├── ledger.md            # Finding → Decision 当前状态表 + 决策变更记录
├── fix-map.md           # 可选：修复映射与批次依赖图
├── investigations/     # 独立调查产物：Hypothesis + Evidence
│   └── <unit>-<agent>.md
├── findings/            # 主代理规范化后的 Finding；一项一文件
│   └── F<n>.md
├── verification/       # 主代理实证档案；verification/F<n>.md
└── probes/              # 主代理批准的隔离探针（结束时清理）
```

- `auditId`：先把审计名做 NFKC 规范化并去除首尾空白得到 `canonicalName`；`slug = sanitizeKey(canonicalName)`（只保留字母、数字、`-`、`_`，其余折叠为 `-`；禁止路径分隔符、`..` 与空 id），短摘要固定为 `SHA-256(UTF-8(canonicalName))` 的小写十六进制前 8 位。`auditId = <slug 前 23 字符>-<短摘要>`；空 slug 时使用 `audit-<短摘要>`。短摘要用于降低规范化名称冲突概率，不保证绝对无碰撞。
- 持久化可用时，主代理把活动状态目录的解析后绝对路径记录为 `stateDir` 并按该路径定位；会话内降级时写 `stateDir=session-only`。持久化审计归档前计算并写入最终 `archiveDir`，归档后恢复与复盘按 `archiveDir` 或 §5 的实例搜索规则定位。

## 2. 四层语义模型

审计中固定区分四层，不允许混用：

1. **Hypothesis（H）**：可证伪的怀疑或缺陷理论，例如“跨窗口同步可能使用错误窗口”。它不是 Finding，也不能直接进入最终报告。
2. **Evidence（E）**：实际读取、运行或对应版本权威契约得到的直接观察，可支持、反驳或限定 Hypothesis/Finding。**推理不是 Evidence**；推理写在 reasoning 中，并由 Evidence 引用支撑。
3. **Finding（F）**：主代理把一个或多个 Hypothesis 规范化后形成的、可独立裁决的具体问题陈述，必须包含现实影响路径、触发条件/适用条件和 Evidence 引用。Finding 尚不等于“问题已确认”。
4. **Decision**：主代理对 Finding 的最终裁决：`CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`，并附独立的 Severity、Confidence 与处置状态。Finding 自身按统一评估词汇记录 Provenance（归因不适用时为 `—`），用于区分变更风险与现存风险；Provenance 不等于责任归属，也不参与 Severity/Confidence 计算。Finding 的风险阻断/条件由 Decision 驱动；coverage、Evidence 或 material Hypothesis 的关键完整性缺口可独立映射为 `INCOMPLETE`。

关系不是“所有 H 都必须变成 F”：Hypothesis 可以被 Evidence 直接反驳而关闭；证据不足的 material Hypothesis 可以保留为 residual gap。**material Hypothesis** 指“若为真可能形成 Medium+ Finding、改变 gate/Decision/Severity、使 Confidence 跨越 Decision 所需阈值、揭示系统性模式或新增 highest/high 风险”的假设；纯风格或无实际影响猜测不算 material。只有值得主代理裁决的问题才提升为 Finding。

## 3. 文件模板

### 3.1 `audit.md`（任务与停止状态）

```markdown
| 键 | 值 |
|---|---|
| auditId | lep-2026-08-a1b2c3d4 |
| name | LEPTON 交叉审计 v1.5 |
| ownerKey | <平台会话 id 或安全兜底值> |
| stateDir | <解析后的活动状态目录绝对路径> / session-only |
| archiveDir | — |
| target | <仓库/分支/commit/PR/工作区/计划/配置/迁移/功能/修复工件> |
| scopeMode | project / change / pr / author-commits |
| objectiveProfile | general / security / fix-verification / security,fix-verification |
| executionMode | audit-only / audit-and-fix |
| scope | <实际纳入的审计路径、子系统、提交范围或计划章节；排除项只写 `excluded`> |
| objectives | <本次审计必须回答的问题> |
| riskTolerance | standard / <已归一为可判定条件的策略> |
| availableEvidence | <仓库、diff、PR 元数据、需求、CI、日志、目标环境、权威契约等的可用性；不记录秘密> |
| deliverable | <门禁报告/问题报告/追溯报告/修复验证报告/用户指定输出> |
| base | <不可变基线；不适用写 —> |
| head | <不可变目标；不适用写 —> |
| stopPolicy | standard / exhaustive / user-defined |
| noMaterialDeltaRounds | 0 |
| stopReason | — |
| gate | READY / READY-WITH-CONDITIONS / BLOCKED / INCOMPLETE / —（不要求门禁） |
| assumptions | 每行一条 |
| excluded | 每行一条（范围与理由） |
| residualRisks | 每行一条（结束时仍存在的残留风险/证据缺口） |
| startedAt / updatedAt | ISO8601 |
```

- `ownerKey` 必须唯一标识主会话/主代理：优先取平台会话 id 或等价标识；用于路径前按文件名安全规则清洗，禁止路径分隔符及 Windows 非法字符。禁止 `default`、`main`、`unknown`、空串或审计名本身等占位符。确实拿不到时使用紧凑 `startedAt`（如 `20260815T215947+08`）+ 至少 4 位随机后缀；创建目录前检查是否占用，冲突则重新生成。
- `auditId`、`ownerKey`、`stateDir` 初始化后不再改动；`archiveDir` 仅归档时填写。六项任务契约与派生字段在派发前必须有值。
- `stopPolicy` 是内部字段，不增加用户入口负担：默认 `standard`；用户明确要求逐文件/逐行/穷尽时为 `exhaustive`；用户给出明确调查预算/停止标准时为 `user-defined`。`noMaterialDeltaRounds` 只持久化探索轮的连续无 material delta 计数；何时更新、何时停止扩张由主流程的 stop/completion 规则统一决定，本文件不重复定义阈值。

### 3.2 `project-map.md`（共享事实，隔离判断）

`project-map.md` 是对 `audit.md` 任务契约的**补充事实层**：target/base/head/scope/excluded 以 `audit.md` 为唯一权威源，本文件不重复保存；这里只记录会被多个风险单元复用的 DIRECT 项目事实，避免每个代理从 README 和仓库根目录重复建立同一背景。禁止写 Hypothesis、Finding、Decision、严重度判断、Risk tolerance、其他调查者结论或“这里可能有 bug”之类暗示。

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
- 子代理只接收与自己风险单元相关的 map 摘要或文件访问权；风险地图本身保存在 `coverage.md`，调查者只看到自己被分配的风险主张，不批量读取其他风险单元的判断。调查者可反驳 `project-map.md` 的补充事实：发现错误时回报 `MAP-CORRECTION` + 直接 Evidence，由主代理统一修正。若被修正事实已作为某 coverage 单元的 material 前提，主代理必须识别受影响单元：进行中的单元补发更正；已完成单元新增最小补充复核单元，在复核完成前旧单元不得单独满足该风险主张的 required coverage。
- `MAP-CORRECTION` 只用于 `project-map.md` 的补充事实；若调查者发现 `audit.md` 的 target/base/head/scope/excluded 可能错误或冲突，必须作为任务契约/基线冲突返回，由主代理重新解析并在必要时重新规划受影响 coverage，不能静默改 map 规避契约。
- **共享事实，隔离判断**：可共享 `audit.md` 的 target/base/head/scope/excluded，以及 `project-map.md` 的术语、入口、changed files、DIRECT 项目事实；必须隔离其他人的 Hypothesis、Evidence 解释、Finding、Decision、主代理预期答案。

### 3.3 `ledger.md`（Finding → Decision）

ledger 只保存**主代理规范化 Finding 的 Decision 摘要**，不保存调查者原始 Hypothesis/Evidence 文本。Finding 内容与风险评估维度在 `findings/F<n>.md`，调查来源在 `investigations/`，主代理直接验证在 `verification/`。Severity / Confidence / Evidence Strength 使用任务协议已经加载的统一评估词汇。

```markdown
| Finding | Decision | Severity | Confidence | 主验证方法 | 处置状态 | 模式范围 | Decision rationale |
|---|---|---|---|---|---|---|---|
| F1 | CONFIRMED | High | High | user-path-trace（见 verification/F1.md） | OPEN | ISOLATED | F1-E1(ES3) + R2-E3(ES2) 支持，counter-hypothesis 已反驳 |
```

- `Decision`：`CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`；可暂写 `PENDING`，但任务收口前不得保留 `PENDING`。
- `Severity`：`Critical` / `High` / `Medium` / `Low` / `—`。按统一评估模型的 Impact / Likelihood / Reachability / Recoverability 映射；**不得使用 Confidence 作为降级理由**。所有非 `REJECTED` Finding 必填 Severity；`REJECTED` 写 `—`，确保 gate 不依赖缺省值猜测。
- `Confidence`：`Very-High` / `High` / `Medium` / `Low` / `—`，表示 Finding 为真的确定程度，不表示影响大小；所有非 `REJECTED` Finding 必填 Confidence，且 `CONFIRMED` 只能使用 `High` / `Very-High`；`REJECTED` 写 `—`。
- `主验证方法`：使用任务风险地图中的统一 verification archetype；主代理对决定性 Evidence 的直接复核及新增 Evidence 写入 `verification/F<n>.md`。只有 Decision=`PENDING` 时可暂写 `unknown`；最终 Decision 定稿前必须替换为实际方法。
- `处置状态`（remediation status）与 Decision 正交，但合法组合固定：`PENDING` / `CONDITIONAL` / `NEEDS-DECISION` 只使用 `OPEN`；`CONFIRMED` 可使用 `OPEN` / `FIX-IN-PROGRESS` / `FIXED-VERIFIED` / `ACCEPTED-RISK`；`REJECTED` 写 `—`。证据补齐或授权决策完成后，先更新 Decision，再进入相应处置状态。
- `ACCEPTED-RISK` 只能由当前用户明确决定，或由任务开始前已经归一且无歧义覆盖该 Finding 的授权风险策略触发；主代理不得自行“接受”风险。设置时在 Decision 变更/处置记录中保存授权依据。
- `模式范围`：`ISOLATED` / `SYSTEMIC` / `UNKNOWN`；未做同类搜索时写 `UNKNOWN`。
- `Decision rationale` 必须引用 Finding/verification 中的 Evidence ID，不写“两个 agent 都认为”等投票理由。

Decision 变更记录只追加：

```markdown
| 时间 | Finding | 变更 |
|---|---|---|
| ISO8601 | F1 | Decision PENDING → CONFIRMED；Severity High；Confidence High；依据 F1-E1(ES3)、R2-E3(ES2) |
```

以下变化必须追加记录：Decision、Severity、Confidence、处置状态、模式范围或决定性 Evidence/反证结论发生实质变化；Finding 的 Provenance 变化若影响 gate/归因，也追加记录。纯格式编辑不记录。

### 3.4 `coverage.md`（风险覆盖矩阵）

```markdown
| 单元 | 风险面 | 风险主张/不变量 | 失败后果/优先级 | 验证方法 | 执行者 | 证据视角 | 路径/子系统 | 调查文件 | Finding | 状态 | 核对 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | boundary-conditions | `get_block` 不得发生下溢 | 错误结果；highest | implementation-trace | SA-fix | engineering | vendor/lepton_jpeg | investigations/R1-SA-fix.md | F1 | verified | R1-H1→F1；R1-H2→refuted(R1-E4) |
| R2 | boundary-conditions | `get_block` 不得发生下溢 | 错误结果；highest | state-invariant-analysis | SB-check | engineering | vendor/lepton_jpeg | investigations/R2-SB-check.md | F1 | verified | R2-H1→F1 |
```

- `单元` 使用审计内唯一 id（`R1` / `R2`）。一个单元只表示“一个风险主张 + 一个验证方法 + 一个有界范围”；第二种方法创建第二个单元。
- `状态` 单向推进：`planned → dispatched → reported → verified`。`reported` 表示调查文件已到达；`verified` 只有在主代理完成该单元的 H/E 核对后才能写。
- `核对` 必须逐个处理 material Hypothesis：`H→F<n>`、`H→refuted(E...)` 或 `H→residual-gap(...)`。`H→F<n>` 前还必须确认该 H 的 disconfirmation 四项完整；不能因为调查者写“无问题”或只给支持 Evidence 就直接 verified。
- `Finding` 列列出由该单元促成的 F id；没有写 `—`。同一 F 可以被多个异质单元共同支持。
- 最高风险不变量至少有两个**不同 archetype**、信息隔离且都 `verified` 的单元，才算异质独立覆盖。

### 3.5 `investigations/<unit>-<agent>.md`（Hypothesis + Evidence）

调查者只记录 Hypothesis、Evidence、reasoning、已验证正确行为与缺口；**不得创建最终 Finding ID、Decision 或最终严重度**。

```markdown
## R1-H1 Hypothesis
- Coverage unit：R1
- 风险面：boundary-conditions
- 验证方法：implementation-trace
- 假设：<可证伪的具体陈述>
- 潜在影响：<若为真，现实上会造成什么；不写最终严重度>
- 适用/触发条件：<...>
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
```

- Evidence 必须是 DIRECT；“根据经验推测”“看起来可能”属于 reasoning/Hypothesis，不得编号成 E。每条 Evidence 使用任务协议统一的 Strength / Reproducibility 词汇评定。
- 一个 Hypothesis 可引用多个支持和反证 Evidence；**每个准备 `promote-to-finding` 的 material Hypothesis 必须完成 Counter-hypothesis / Expected safe behavior / Evidence searched / Disconfirmation result 四项**。没有实际反证搜索不得直接提升。
- `Investigation result` 是调查者的局部判断，不是 Decision；主代理可以不同意。
- 没有 material Hypothesis 时写“无 material hypothesis”，仍列出已检查范围、关键 Evidence/已验证正确行为与缺口。
- `H`/`E` id 在审计内通过 unit 前缀保持唯一，例如 `R2-H3` / `R2-E7`。

### 3.6 `findings/F<n>.md`（主代理规范化 Finding）

只有主代理可以创建/修改 Finding。一个 Finding 可以聚合多个独立 Hypothesis。主代理自己发现问题时也先在 `investigations/<unit>-main.md` 记录 H/E，再提升为 Finding，不绕过四层链。

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
- 建议验证/退出条件：<可观察、可测试、可判定>
```

- Finding 是“可裁决的问题对象”，不是 `CONFIRMED` 的同义词；Provenance 与风险维度/Severity mapping/反证过程保留在 Finding 文件，ledger 只保留最终 Decision / Severity / Confidence，避免把历史归因与风险判断混为一谈。
- 主代理验证产生的新 Evidence 放 `verification/F<n>.md`，Evidence id 用 `F<n>-E<m>`；每条保持与 investigation Evidence 相同的 `Polarity / Strength / Reproducibility / DIRECT source / Observation` 五字段，Finding 文件引用这些 id。
- 多个调查者描述同一逻辑问题时只建立一个 Finding，保留所有来源 Hypothesis/Evidence；不同根因或不同现实影响需独立裁决时才拆分。

## 4. 落盘纪律

- 正常模式先写 `audit.md` + `project-map.md` + `coverage.md` 的 planned 风险单元，再派发；显式降级且省略 project-map/coverage 时，先建立降级协议要求的最小状态与 investigation 任务头，再开始调查。
- 派发后 coverage→`dispatched`；调查文件到达后→`reported`；主代理逐个核对 material Hypothesis，把它们映射到 Finding / refuted / residual gap 后→`verified`。
- Finding 创建/合并后更新 `findings/F<n>.md`；Decision 定稿后更新 `ledger.md`；主代理实证写 `verification/F<n>.md`。禁止收尾时一次性把 `planned` 补成 `verified`。
- 每次更新权威审计状态后核对其与当前结论一致；权威状态与最终报告不一致视为缺陷。
- 子代理无法写持久化状态：全文内联返回，主代理写入当前权威审计状态对应的 investigation 内容并注明“主代理代写”；不改变状态权威性。
- 凭据、令牌、真实用户数据不回显；只保存满足审计目的所需的脱敏 Evidence。

## 5. 断点恢复

1. 找到正确状态实例后先读取 `audit.md` 与 `ledger.md`；正常模式再读取 `project-map.md` / `coverage.md`，降级模式读取实际存在的状态工件并保留其省略项披露。
2. 存在 `coverage.md` 时，`reported` 但未 `verified` 的单元读取 investigation 文件，补做 H→F/refuted/gap 核对，不重跑调查者；降级模式无 coverage 时按 `investigations/` → `findings/` → `ledger.md` 继续四层链。
3. Finding 存在但 Decision=`PENDING`：继续 disconfirmation、风险维度/Confidence 评估、主代理验证与裁决；`verification/` 已有 Evidence 直接复用，不重复采集。
4. 在 `audit-and-fix` / `fix-verification` 模式下，同时恢复处置状态 `OPEN` / `FIX-IN-PROGRESS` 和 `fix-map.md` 未 `PASSED` 批次。
5. 恢复 `noMaterialDeltaRounds` 与 residual risks；已完成的 exploration round 不重跑。
6. **持久化模式**的新会话先在 `.audits/` 匹配 `*--<auditId>`，再查 `.audits/archive/`；命中多个时读取 target、base/head、scope、派生字段、时间确定实例，仍无法唯一判断时请求用户决定。无匹配时明确披露“历史状态未找到”。会话内降级状态不承诺跨会话恢复。
7. 最终报告注明恢复路径、中断点和恢复后继续处理的单元/Finding 数量。

## 6. 归档与跨轮复盘

- 审计结束：所有模式先清理探针与临时资源；**持久化模式**再把状态目录移入 `.audits/archive/<ownerKey>--<auditId>/`，报告附归档路径。会话内降级模式只披露未持久化与跨会话恢复限制。
- 归档路径整体必须唯一；冲突时只在 `ownerKey` 一侧追加消歧值（如 `<ownerKey>-<startedAt>--<auditId>`），不得覆盖或静默丢弃。
- 下一轮同工件/同范围审计先读取历史 `audit.md`、存在的 `project-map`、Finding/Decision、反证、模式范围与 residual risks；**共享已确认事实，重新独立形成新 Hypothesis/判断**，不要机械重跑背景搜集，也不要把旧 Decision 当作新一轮的预期答案。
- 归档含敏感信息时按证据脱敏纪律处理。

## 7. 降级与披露

- 无法持久化：使用会话内同构状态并披露“审计状态未持久化、跨会话恢复能力降低”。只要 H/E/F/Decision 与当前模式要求的状态仍完整保存在权威会话状态中，该限制本身不否定事实性审计完成；若 Deliverable 明确要求可恢复/持久化证据，则把它作为未满足条件披露。
- 已符合本 Skill 的审计触发条件，但子代理能力不可用或用户明确要求降级速度时：可以省略完整 `coverage.md` 和不需要复用的 `project-map.md`，但最少仍保留 `audit.md` + `investigations/main.md` + `findings/` + `ledger.md`，保证 H/E/F/Decision 四层可追溯；同时披露缺失的风险覆盖矩阵与异质独立覆盖。普通无需交叉验证的窄问答不应因此触发本 Skill。
- 降级不改变四层语义与评估模型：Hypothesis 不能冒充 Finding，推理不能冒充 Evidence，Finding 不能冒充 Decision；Confidence 不能冒充 Severity，低 Strength Evidence 不能因数量多冒充高强度证据。

## 8. 账本与会话日志的分工

- 平台会话/事件日志是**过程事件源**（可重放）；可能含未脱敏原文且会话边界不等于审计边界。
- 本状态结构是**归约后的审计状态**：`project-map`=共享事实，`investigations`=独立 H/E，`findings`=规范化问题对象，`ledger`=Decision，`coverage`=风险覆盖；持久化与会话内模式职责相同，不得混写。
