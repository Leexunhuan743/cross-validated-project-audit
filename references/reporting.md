# 审计报告与门禁

在输出最终审计结果前读取本文件。报告按 **Finding → Decision** 聚合，不按代理、Hypothesis 或 Evidence 条目逐份倾倒。默认采用两层输出：先给可直接做发布/合并/整改决策的 **Executive report**，再给可追溯的 **Audit appendix**；用户不应先读 ledger 才知道能不能发布。

先读取 `audit.md` 的任务契约。用户明确指定的 Deliverable 永远优先；未指定时：要求发布/合并/gate → 门禁报告；`objectiveProfile` 含 `fix-verification` → 修复验证报告；其余 → 问题报告。追溯附录只在用户要求或 §3 条件触发时展开。

## 0. Deliverable 契约

| Deliverable | 最低必须包含 |
|---|---|
| 门禁报告 | Executive：gate + Top risks + Required actions + Residual uncertainty；Appendix：范围/基线 + Findings/Decision + coverage/evidence 索引 |
| 问题报告 | Executive：Top risks + Required actions/建议 + Residual uncertainty；Appendix：范围/基线 + Findings/Decision + 已验证正确 + coverage/evidence 索引 |
| 修复验证报告 | Executive：修复是否通过 + 未解除风险 + Required actions + Residual uncertainty；Appendix：原 Finding → 处置状态 → 验证 Evidence + 漏修/新回归 |
| 追溯报告 | 对应基础报告 + 完整 Audit appendix（ledger、Evidence、coverage、investigations、probes/commit matrix 索引） |
| 用户自定义 | 满足用户字段，同时至少披露实际范围、关键 Evidence 与 residual risks |

单一数据源规则：

1. `findings/F<n>.md` 提供 Finding statement、位置/范围、Provenance、影响链、触发条件、disconfirmation、Impact/Likelihood/Reachability/Recoverability、Severity mapping 与 H/E 引用；
2. `ledger.md` 提供 Decision、最终 Severity、Confidence、主验证方法、处置状态、模式范围和 Decision rationale；
3. 正常模式由 `coverage.md` 提供风险覆盖、H→F/refuted/gap 核对与异质方法完成度；显式降级模式若省略 coverage，必须把该缺口披露并限制完整性/门禁声称；
4. `investigations/` 只用于追溯 Hypothesis/Evidence，不直接生成最终问题结论。

## 1. 默认输出：Executive report + Audit appendix

### Executive report

默认只保留决策需要的信息，顺序固定：

1. **Gate / Decision**：需要门禁时给 `READY` / `READY-WITH-CONDITIONS` / `BLOCKED` / `INCOMPLETE` + 一句理由；不要求 gate 时写“Gate：未请求”，不自行制造发布结论。
2. **Top risks（最多 3 项）**：优先 Critical/High，再按发布/用户影响与 Confidence 排序；每项只写 F id、短标题、Severity/Confidence、Provenance 和一句现实影响。
3. **Required actions**：只列解除 BLOCKED/INCOMPLETE 或满足用户明确验收所必须完成的动作及退出条件。
4. **Recommendations**：不阻断当前门禁但值得处理的 `PRE_EXISTING` 风险、Medium/Low Finding 或改进项；没有则省略。
5. **Residual uncertainty**：未验证平台/环境、关键 Evidence/coverage gap、停止原因和 residual risks；在实际需要变更归因的审计中，可能改变重要结论的 `UNKNOWN` Provenance 也列在这里。

不要在 Executive report 倾倒完整 ledger、代理过程、命令日志或所有 Low Finding。用户先看到“能不能合并/发布、最大风险、必须做什么、还不知道什么”。

### Audit appendix

默认给**紧凑可追溯附录**，包含：

- 任务契约、实际范围、base/head、关键假设/排除项；
- Findings/Decision 表（含 Provenance、Severity、Confidence、处置状态）；
- required risk coverage 与异质方法完成度；
- 关键 Supporting/Refuting Evidence 索引；
- investigations、verification、probes、fix-map、commit/author matrix 等实际存在工件的路径/摘要索引。

用户要求“完整追溯/证据链”或 §3 条件触发时，再展开完整 ledger、material H/E 链和必要命令/环境细节；普通报告不复制权威审计状态中的全部调查正文。

## 2. Finding 的报告字段

每个报告 Finding 包含：F id、Finding statement、位置/范围、Provenance、Impact / Likelihood / Reachability / Recoverability、Severity、Confidence、原因→实际影响、触发/适用条件、Disconfirmation summary、关键 Supporting/Refuting Evidence（含 Strength/Reproducibility）、主验证方法、Decision、模式范围、建议修复与可判定退出条件。最终 Decision / Severity / Confidence 只取 `ledger.md`；调查者的“潜在影响”或局部 result 不得覆盖主代理 Decision。

## 3. 追溯模式

以下情况默认展开：用户要求完整证据链；gate 存在争议；Critical/High Finding 有冲突 Evidence；关键材料/环境/异质方法缺失导致 `INCOMPLETE`。

附录按层级展示：

```text
Risk unit → Hypothesis → Evidence → Finding → Decision
```

包括：存在时的 `project-map` 共享事实摘要、coverage 或降级模式等价记录、material Hypothesis 的处置映射、Finding 的 H/E 来源、会改变结论的 REJECTED Finding 及反证、与 gate 直接相关的命令/环境/基线失败。普通报告不默认倾倒完整 investigation 正文。

## 4. 门禁映射

以下是 `Risk tolerance=standard`。非 standard 策略必须派发前归一为可判定附加条件；用户可收紧默认条件。要放行已确认且仍存在的风险，必须把对应 Finding 的处置状态明确记为 `ACCEPTED-RISK`，不得降低 Severity、Confidence 或改写 Evidence。Confidence 只表示确定度，不直接改变默认 gate 优先级；关键低 Confidence 风险若 Evidence 不足以裁决，应通过 `CONDITIONAL` / `INCOMPLETE` 表达。

在需要变更归因的 `change` / `pr` / `author-commits` 门禁中，先区分 **change-attributable**（`INTRODUCED` / `REGRESSED` / `EXPOSED`）与 `PRE_EXISTING`。纯 `PRE_EXISTING` 且未被目标变更扩大/激活的 Finding 仍报告，但默认不声称“本次变更引入”，也不单独阻断该变更；如果 Audit objectives 是整个系统/发布候选的 release readiness，或该既有风险会使目标变更无法安全集成/运行，则仍可按发布相关性进入 gate。归因适用时 `UNKNOWN` 且可能改变 Critical/High 门禁，视为关键归因缺口；归因不适用时使用 `—`，不构成缺口。

| 优先级 | 条件 | 门禁结论 |
|---|---|---|
| 1 | 存在 Decision=`CONFIRMED` 且 Severity=Critical/High、对当前门禁目标发布相关、处置状态为 `OPEN` / `FIX-IN-PROGRESS` 的 Finding | `BLOCKED` |
| 2 | 任一 Finding 仍为 Decision=`PENDING`；或关键 Evidence、目标环境、material Hypothesis 处置、要求的异质 coverage 缺失；或存在 Severity=Critical/High 且 Decision=`NEEDS-DECISION` / `CONDITIONAL`；或若成立预计为 Critical/High 的 material Hypothesis 因决定性验证缺失只能保留 residual gap，无法可靠判断是否存在阻断项 | `INCOMPLETE` |
| 3 | 无前两项，但存在 Decision=`CONFIRMED` 且 Severity=Medium/Low、处置状态为 `OPEN` / `FIX-IN-PROGRESS` 的 Finding，或非关键 `NEEDS-DECISION` / `CONDITIONAL`、非阻断 residual risk 或其它条件项 | `READY-WITH-CONDITIONS` |
| 4 | 不满足以上三项，且 highest 风险不变量要求的异质 coverage 全部 verified | `READY` |

严格按 `BLOCKED > INCOMPLETE > READY-WITH-CONDITIONS > READY` 取首个命中项。Hypothesis 的 supported/refuted/unresolved **不是 gate 状态**；gate 输入只来自 material H 的最终处置、Finding 的 Decision/Severity/处置状态/适用 Provenance，以及 required coverage/Evidence/环境完整性缺口。

## 5. 阻断与解除条件

每个 BLOCKED Finding 必须有：

```text
[ ] <需要完成的动作>
    退出条件：<可观察、可测试、可判定的通过条件>
```

没有足够 Evidence 的 Hypothesis 不得直接阻断；若仍 material，可形成带明确缺口的 Finding 并使用 `CONDITIONAL`。`NEEDS-DECISION` 只用于关键事实已足够、剩余的是产品/兼容/范围/风险取舍；Evidence 足够确认问题时才使用 `CONFIRMED`。报告文字本身不是通过门禁。

## 6. 无确认问题的措辞

异质覆盖、Hypothesis 处置和关键检查达标时：

> 在已审计范围和已执行检查内未发现已确认缺陷。

未完成时：

> 已完成的审查未发现已确认缺陷，但仍存在未闭合的风险覆盖、Hypothesis 或 Evidence 缺口，不能视为全面无缺陷结论。

不得声称“绝对安全”“没有 bug”或“所有场景均正确”。

## 7. 输出前一致性检查

审计是否完成、何时停止扩张由主流程的 completion/stop 规则决定；本文件只检查最终输出是否忠实反映权威审计状态：

- [ ] Gate 按权威 findings + ledger + 当前可用 coverage/等价降级记录的真实状态机械映射；降级模式缺失完整 coverage 矩阵时已反映为完整性限制，没有用报告措辞覆盖 Decision。
- [ ] Executive report 先回答 Gate/Top risks/Required actions/Residual uncertainty；Recommendations 与 Required actions 分开。
- [ ] Provenance 适用时正确区分 change-attributable / `PRE_EXISTING` / `UNKNOWN`；不适用时显示 `—`，没有把旧风险写成本次引入。
- [ ] Audit appendix 能追溯关键 Finding → Supporting/Refuting Evidence → coverage；普通报告没有倾倒无关 investigation/日志。
- [ ] `stopReason`、residual risks、关键验证缺口和恢复/归档路径（实际存在时）已披露；修复验证报告与 `fix-map`/处置状态一致。
