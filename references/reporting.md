# 审计报告与门禁

在输出最终审计结果前读取本文件。报告按 **Finding → Decision** 聚合，不按代理、Hypothesis 或 Evidence 条目逐份倾倒。默认采用两层输出：先给可直接做发布/合并/整改决策的 **Executive report**，再给可追溯的 **Audit appendix**；用户不应先读 ledger 才知道能不能发布。

先读取 `audit.md` 的任务契约。用户明确指定的 Deliverable 永远优先；未指定时：要求发布/合并/gate → 门禁报告；`objectiveProfile` 含 `fix-verification` → 修复验证报告；其余 → 问题报告。追溯附录只在用户要求或 §3 条件触发时展开。

## 0. Deliverable 契约

| Deliverable | 最低必须包含 |
|---|---|
| 门禁报告 | Executive：每个请求 gate target 的 Gate + Top risks + Required actions + Residual uncertainty；Appendix：范围/基线 + Findings/Decision + coverage/evidence 索引 |
| 问题报告 | Executive：Top risks + Required actions/建议 + Residual uncertainty；Appendix：范围/基线 + Findings/Decision + 已验证正确 + coverage/evidence 索引 |
| 修复验证报告 | Executive：修复是否通过 + 未解除风险 + Required actions + Residual uncertainty；Appendix：原 Finding → Disposition → 验证 Evidence + 漏修/新回归 |
| 追溯报告 | 对应基础报告 + 完整 Audit appendix（ledger、Evidence、coverage、investigations、probes/commit matrix 索引） |
| 用户自定义 | 满足用户字段，同时至少披露实际范围、关键 Evidence 与 residual risks |

单一数据源规则：

1. `findings/F<n>.md` 提供 Finding statement、位置/范围、Provenance、影响链、触发条件、disconfirmation、Impact/Likelihood/Reachability/Recoverability、Severity mapping、Gate applicability、适用时的 target-specific Gate treatment 与 H/E 引用；
2. `ledger.md` 提供 Decision、最终 Severity、Confidence、主验证方法、Disposition、模式范围和 Decision rationale；
3. coverage 只从 `audit.md.coverageLocation` 指向的唯一权威位置读取：独立 `coverage.md` 或 `audit.md` 的 Embedded coverage；两种存储方式使用同一 `Claim ID / Obligation / Exploration round / Risk priority / Sufficiency / Judgment isolation / H→F|refuted|gap / Gate-target` 语义；Gate 只把 `REQUIRED` 单元作为完成义务；
4. `investigations/` 只用于追溯 Hypothesis/Evidence，不直接生成最终问题结论。

## 1. 默认输出：Executive report + Audit appendix

### Executive report

默认只保留决策需要的信息，顺序固定：

1. **Gates / Decision**：`gateTargets != NONE` 时逐项给 `Change Gate` / `Release Gate` / `System Gate` 的 `READY` / `READY-WITH-CONDITIONS` / `BLOCKED` / `INCOMPLETE` + 一句理由；同一审计可同时出现不同结果，不折叠成一个最坏值。`gateTargets=NONE` 时写“Gate：未请求”，不自行制造放行结论。
2. **Top risks（最多 3 项）**：优先 Critical/High，再按对请求 Gate/用户影响与 Confidence 排序；每项只写 F id、短标题、Severity/Confidence、Provenance 和一句现实影响；有多个 `gateTargets` 时附受影响 Gate 标签。
3. **Required actions**：只列解除 BLOCKED/INCOMPLETE 或满足用户明确验收所必须完成的动作及退出条件。
4. **Recommendations**：不阻断当前门禁但值得处理的 `PRE_EXISTING` 风险、Medium/Low Finding 或改进项；没有则省略。
5. **Residual uncertainty**：未验证平台/环境、关键 Evidence/coverage gap、停止原因和 residual risks；在实际需要变更归因的审计中，可能改变重要结论的 `UNKNOWN` Provenance 也列在这里。

不要在 Executive report 倾倒完整 ledger、代理过程、命令日志或所有 Low Finding。用户先看到“能不能合并/发布、最大风险、必须做什么、还不知道什么”。

### Audit appendix

默认给**紧凑可追溯附录**，包含：

- 任务契约、scope resolution、状态持久化说明、实际范围、base/head、关键假设/排除项，以及实际达到的异质/independent validation 程度；
- Findings/Decision 表（含 Provenance、Severity、Confidence、Disposition）；
- required risk coverage、Sufficiency、异质方法与 independent validation 完成度；
- 关键 Supporting/Refuting Evidence 索引；
- investigations、verification、probes、fix-map、commit/author matrix 等实际存在工件的路径/摘要索引。

用户要求“完整追溯/证据链”或 §3 条件触发时，再展开完整 ledger、material H/E 链和必要命令/环境细节；普通报告不复制权威审计状态中的全部调查正文。

## 2. Finding 的报告字段

每个报告 Finding 包含：F id、Finding statement、位置/范围、Provenance、Impact / Likelihood / Reachability / Recoverability、Severity、Confidence、原因→实际影响、触发/适用条件、Disconfirmation summary、关键 Supporting/Refuting Evidence（含 Strength/Reproducibility）、主验证方法、Decision、模式范围、建议修复与可判定退出条件；请求 `gateTargets != NONE` 时直接使用 Finding 中的权威 Gate applicability，以及存在时的 target-specific Gate treatment，不在报告阶段重新推理相关性或重新解析风险接受。最终 Decision / Severity / Confidence 只取 `ledger.md`；调查者的“潜在影响”或局部 result 不得覆盖主代理 Decision。

## 3. 追溯模式

以下情况默认展开：用户要求完整证据链；gate 存在争议；Critical/High Finding 有冲突 Evidence；关键材料/环境/异质方法缺失导致 `INCOMPLETE`。

附录按层级展示：

```text
Risk unit → Hypothesis → Evidence → Finding → Decision
```

包括：当前状态中的共享事实摘要、权威 coverage、material Hypothesis 的处置映射、Finding 的 H/E 来源、会改变结论的 REJECTED Finding 及反证、与 gate 直接相关的命令/环境/基线失败。普通报告不默认倾倒完整 investigation 正文。

## 4. 门禁映射

以下是 `Risk tolerance=standard`。非 standard 策略必须派发前归一为可判定附加条件，可按 `gateTarget` 分别定义；同一 target 的多个非 standard 条件若 effect 冲突，必须在审计开始前消解，不得按书写顺序、最近规则或默认宽松原则自动选择。用户可收紧默认条件。非 standard 策略不得将由 Decision 未定、required coverage 未完成、Sufficiency 未满足、关键 Evidence 缺失或 Gate applicability 未解决造成的 `INCOMPLETE` 提升为 `READY` 或 `READY-WITH-CONDITIONS`；它只能改变已充分确定风险的门禁处理。只有风险接受明确覆盖该 Finding 的所有相关请求 Gate 时才使用全局 Disposition `ACCEPTED-RISK`；只接受某一个 Gate 时，Finding 必须显式记录 `Gate treatment=ACCEPTED` 与授权依据并保留实际 Disposition，使其它 Gate 仍按真实风险计算。缺省/未填写 Gate treatment 等价于 `STANDARD`。`ACCEPTED` 只对 Decision=`CONFIRMED` 且 applicability=`APPLIES` 的已知风险生效，不能排除 `PENDING` / `CONDITIONAL` / `NEEDS-DECISION` 或 Evidence/coverage 完整性缺口。套用下表时，只有该 target 明确为 `ACCEPTED` 的 Finding 才从该 target 的阻断/条件集合中排除，并必须在 Executive report 中披露授权依据；不得降低 Severity、Confidence 或改写 Evidence。Confidence 只表示确定度，不直接改变默认 Gate 优先级；关键低 Confidence 风险若 Evidence 不足以裁决，应通过 `CONDITIONAL` / `INCOMPLETE` 表达。

先按 `audit.md.gateTargets` 读取每个非 `REJECTED` Finding 的权威 Gate applicability，再分别套用下表；coverage 单元只影响其 `Gate targets` 列出的请求 Gate。Gate applicability 只使用 `APPLIES` / `DOES-NOT-APPLY` / `UNRESOLVED`：`APPLIES` 表示在本审计唯一权威 target/state snapshot 与 Finding 已声明条件下，该问题会参与该 Gate；`DOES-NOT-APPLY` 表示有足够依据证明它不参与该 Gate；`UNRESOLVED` 表示**相关性或当前适用性本身**缺少决定性 Evidence。Finding 是否真实仍由 Decision 表达，因此 `CONDITIONAL` 不自动等于 `UNRESOLVED`。Risk tolerance/风险接受不能改写 applicability。多个 gate target 共用这一 target/state snapshot；不同版本、候选或部署状态必须拆成独立审计实例。

- `CHANGE`：判断**目标变更本身**能否接受/合并/安全集成。Finding 的 CHANGE applicability 由以下规则和对应 DIRECT Evidence 在 Finding 中定稿：`INTRODUCED` / `REGRESSED` / `EXPOSED` 默认属于 change-attributable；纯 `PRE_EXISTING` 且未被目标变更扩大/激活的 Finding 仍报告，但默认不单独阻断 CHANGE。若 DIRECT Evidence 证明该既有风险会使目标变更无法安全集成/运行，则它仍与 CHANGE 相关。归因适用时 `UNKNOWN` 且可能改变 Critical/High 的 CHANGE Gate，属于关键归因缺口。
- `RELEASE`：判断当前 release candidate/目标 head 是否可 ship/deploy。Finding 的 RELEASE applicability 由当前候选状态的 DIRECT Evidence 定稿：Provenance 不决定是否阻断；只要 Finding 在当前候选状态仍适用且 release-relevant，就按风险参与 Gate。历史 Finding 已有 `RESOLVED-VERIFIED` 时不作为当前活动阻断项；若 Critical/High 的当前适用性尚未验证，优先映射 `INCOMPLETE`，不要把历史成立直接当作当前仍存在，也不要假设已修复。
- `SYSTEM`：判断当前审计系统是否满足约定健康/安全/运行目标。Finding 的 SYSTEM applicability 由 Audit objectives 与当前系统状态 DIRECT Evidence 定稿：与 `RELEASE` 类似，Provenance 不决定是否阻断，但相关性由 Audit objectives 与当前系统状态决定；历史 Finding 只有在当前系统仍适用时才作为活动风险。
- `NONE`：不计算 Gate；只报告 Findings/Decision 与 residual uncertainty。

一个 `CONFIRMED` Finding 后来被修复、revert 或 supersede 时，Decision 与 Provenance 保持不变；只有 DIRECT current-state Evidence 证明该 Finding 在本审计唯一权威 target/state snapshot 中不再适用，才可使用 `RESOLVED-VERIFIED`。存在真实 Gate 时，还必须把该 Finding 对所有相关请求 Gate 的 applicability 记录为 `DOES-NOT-APPLY`。若是否已消失尚不能验证，则不能使用 `RESOLVED-VERIFIED`，相应 applicability 写 `UNRESOLVED`；新的 DIRECT Evidence 证明风险仍存在时同样保持或退回 `OPEN` / `REMEDIATING`。多个 gate target 必须分别计算并保存在权威审计状态中，不得自动取“最坏 Gate”覆盖其它结果；不同状态由独立审计实例表达。

coverage 的异质/independent 完整性按 `Claim ID` 分组，不按自由文本或全表总数猜测：同一组至少两个 `REQUIRED` 单元使用不同 archetype 才满足最高风险异质覆盖；只有这两个单元还由不同 executor 完成且各自 `Judgment isolation=ISOLATED` 时才满足 independent validation。`independentValidationRequiredFor=AUDIT` 约束本审计所有最高风险组；值为当前 target 时，约束至少一个单元列出当前 target 的所有最高风险组，且同组用于满足要求的两个单元都必须列出当前 target。显式要求的作用域没有最高风险组，或任一受约束组只披露能力限制，均按缺口处理。

| 优先级 | 条件 | 门禁结论 |
|---|---|---|
| 1 | 存在 Gate applicability=`APPLIES`、Decision=`CONFIRMED` 且 Severity=Critical/High、Disposition 为 `OPEN` / `REMEDIATING` 的 Finding | `BLOCKED` |
| 2 | 非 `REJECTED` Finding 对当前 target 的 Gate applicability=`UNRESOLVED` 且若适用可能形成 Critical/High 阻断；或 Finding 仍为 Decision=`PENDING` 且该 target 的 Gate applicability!=`DOES-NOT-APPLY`；或支撑当前 Gate 的 `REQUIRED` coverage 尚未 `verified`；或列出当前 target 的 `Risk priority∈{highest, high}` required 单元 `Sufficiency=NOT-MET`；或会影响当前 Gate 的关键 Evidence、目标环境、material Hypothesis 处置、要求的异质 coverage 缺失；或支撑当前 target 的任一最高风险 `Claim ID` 未满足异质 coverage；或该组未同时满足“不同 executor 完成 + 各自 `Judgment isolation=ISOLATED`”且 `audit.md` Residual risks 未记录实际执行者/隔离能力限制；或 `independentValidationRequiredFor=AUDIT` 而本审计没有最高风险组、或任一最高风险组缺少 independent validation；或 `independentValidationRequiredFor` 包含当前 target，而支撑当前 target 的最高风险组不存在、或任一此类组缺少 independent validation；或存在 Gate applicability=`APPLIES` 且 Severity=Critical/High、Decision=`NEEDS-DECISION` / `CONDITIONAL` 的 Finding；或若成立预计为 Critical/High 且与当前 Gate 相关的 material Hypothesis 因决定性验证缺失只能保留 residual gap | `INCOMPLETE` |
| 3 | 无前两项，但存在 Gate applicability=`APPLIES` 且 Decision=`CONFIRMED`、Severity=Medium/Low、Disposition 为 `OPEN` / `REMEDIATING` 的 Finding，或 Gate applicability=`APPLIES` 的非关键 `NEEDS-DECISION` / `CONDITIONAL`，或非关键 `UNRESOLVED` applicability、非阻断 residual risk 或其它条件项 | `READY-WITH-CONDITIONS` |
| 4 | 不满足以上三项，支撑当前 `gateTarget` 的所有 `REQUIRED` coverage 均已 `verified`，其中 `Risk priority∈{highest, high}` 单元均 `Sufficiency=MET`；支撑当前 target 的每个最高风险 `Claim ID` 均已由至少两个不同 archetype 的 required 单元完成异质 coverage；这些组均由不同 executor 完成且各自 `Judgment isolation=ISOLATED`，或实际执行者/隔离能力限制已披露；若 `independentValidationRequiredFor=AUDIT`，本审计必须存在最高风险组且每组真正满足 independent validation；若包含当前 target，必须存在支撑当前 target 的最高风险组且每组真正满足同一条件 | `READY` |

对**每个请求的 gateTarget**分别按 `BLOCKED > INCOMPLETE > READY-WITH-CONDITIONS > READY` 取首个命中项。先应用该 Finding 对当前 target 的 `Gate treatment`：缺省 `STANDARD` 正常参与下表；合法的 `ACCEPTED` 只排除该 Finding 自身的风险阻断/条件，不排除 coverage/Evidence/环境完整性缺口。Hypothesis 的 supported/refuted/unresolved **不是 gate 状态**；Gate 输入来自 material H 的最终处置、Finding 的 Gate applicability + Gate treatment + Decision/Severity/Disposition，以及 required coverage/Evidence/环境完整性缺口；Provenance 与 current-state Evidence 用于形成 Finding 中的 applicability，不在报告阶段临场重算。

## 5. 阻断与解除条件

每个 BLOCKED Finding 必须有：

```text
[ ] <需要完成的动作>
    退出条件：<可观察、可测试、可判定的通过条件>
```

没有足够 Evidence 的 Hypothesis 不得直接阻断；若仍 material，可形成带明确缺口的 Finding 并使用 `CONDITIONAL`。`NEEDS-DECISION` 只用于关键事实已足够、剩余的是产品/兼容/范围/风险取舍；Evidence 足够确认问题时才使用 `CONFIRMED`。报告文字本身不是通过门禁。

## 6. 无确认问题的措辞

只有同时满足以下条件时，才能使用 clean conclusion：主流程完成条件已满足；没有 `CONFIRMED` Finding；所有最终 Finding 都是 `REJECTED`；所有 high/highest required coverage 的 `Sufficiency=MET`；不存在 material `residual-gap`、决定性 Evidence/环境缺口或未满足的显式 independent-validation 要求。

> 在已审计范围和已执行检查内未发现已确认缺陷。

不满足上述任一条件时，即使流程已经按残留风险或 `INCOMPLETE` Gate 收口，也必须使用未完成措辞，并列明实际缺口或待决事项：

> 已完成的审查未发现已确认缺陷，但仍存在未闭合的风险覆盖、Hypothesis、Evidence、环境、授权决策或强制独立验证事项，不能视为全面无缺陷结论。

不得声称“绝对安全”“没有 bug”或“所有场景均正确”。

## 7. 输出前一致性检查

审计是否完成、何时停止扩张由主流程的 completion/stop 规则决定；本文件只检查最终输出是否忠实反映权威审计状态：

- [ ] 已确认本审计只绑定一个权威 target/state snapshot；`gateTargets != NONE` 时每个请求 target 都按 Finding Gate applicability + target-specific Gate treatment + 权威 ledger + `coverageLocation` 指向的权威 coverage 中 `Obligation=REQUIRED` 的单元（含 Claim ID/Risk priority/Sufficiency 及 `independentValidationRequiredFor`）分别机械映射并写入 `audit.md` front matter 的 `gates`；没有重新解析自由文本风险接受、用报告措辞覆盖 Decision，或把多个 Gate 折叠成单一最坏值。
- [ ] Executive report 先回答请求的 Gate(s)/Top risks/Required actions/Residual uncertainty；Recommendations 与 Required actions 分开。
- [ ] Provenance 适用时正确区分 change-attributable / `PRE_EXISTING` / `UNKNOWN`；不适用时显示 `—`，没有把旧风险写成本次引入。
- [ ] Audit appendix 能追溯关键 Finding → Supporting/Refuting Evidence → 当前权威 coverage；普通报告没有倾倒无关 investigation/日志。
- [ ] “未发现已确认缺陷”的措辞已按 §6 直接核对最终 Decision、Sufficiency、material residual gap 与显式 independent-validation 要求，没有把“流程已收口”误当成 clean conclusion。
- [ ] `stopReason`、residual risks、关键验证缺口和恢复/归档路径（实际存在时）已披露；修复验证报告与 `fix-map`/Disposition 一致。
