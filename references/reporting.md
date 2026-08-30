# 审计报告与 Gate

最终报告按 Finding → Decision 聚合，不按代理或 H/E 条目倾倒。Finding、Decision、Gate、Disposition 和其它 live 结论字段只从最终 `state.json` 读取；investigation/verification JSON 不能覆盖这些状态。用户可见的“已验证正确行为”只能从 `state.json` 引用且状态为 verified 的 Unit 对应 `coverageSummary.verifiedBehaviors` 读取，并必须能回指同一 artifact 中的 DIRECT Evidence——schemaVersion 3 中每条 `{behavior, evidenceRefs[]}` 的 refs 由 validator 核对回指；v2 归档实例为裸字符串，引用时须标注无机械回指。不得从 Claim statement 或未 verified artifact 自行推导。

`phase=SUPERSEDED` 的 state 只能作为历史附录或接替链证据，不生成当前 Findings、当前 Gate 或 clean conclusion。最终报告必须绑定新 FINAL 实例的 auditId、target 和不可变 snapshot。

## 1. 输出结构

先读 `audit.deliverable`。用户格式优先；默认两层：

不同交付物即使采用用户自定义版式，也至少保留以下内容：

| Deliverable | 最低内容 |
|---|---|
| Gate 报告 | 每个请求 target 的 Gate、Top risks、Required actions、Residual uncertainty，以及范围/snapshot 与决定性 Q/F/G 依据 |
| 问题报告 | Findings、已验证正确行为、Required actions/Recommendations、Residual uncertainty，以及范围/snapshot 与关键 Evidence 索引 |
| 修复验证报告 | 每个原 Finding 的 Decision/Disposition、修复或接受状态、resolution Evidence；另列漏修实例、新回归、未通过批次和未解除风险 |
| 追溯报告 | 对应基础报告，加完整 `Claim → Unit → H → E → F → Decision` 索引和实际存在的 investigation/verification/fix 工件 |
| 用户自定义 | 满足用户字段，同时至少披露实际范围、snapshot、关键 Evidence、已知限制和 material residual risks |

### Executive report

1. **Gates / Decision**：只有 `audit.gates` 存在时，逐 target 给结果和一句依据；无 Gate 时直接给审计结论，不写“Gate 未请求”占版面。
2. **Top risks**：最多三项，按 Severity、Gate/用户影响和 Confidence 排序；写 F id、短标题、Severity/Confidence、现实影响，适用时写 Provenance 和受影响 Gate。
3. **Required actions**：只列解除 BLOCKED/INCOMPLETE 或满足用户明确验收所必需的动作和退出条件。
4. **Recommendations**：非阻断的 Medium/Low、PRE_EXISTING 风险和改进项；没有则省略。
5. **Residual uncertainty**：material residual risk、关键 Evidence/环境缺口、停止原因、validator/持久化/independent validation 限制；`priorContact` 声明而未建扫描单元（`scopeMode=project`）时的先验接触与利益冲突披露；失败/取消派发（`dispatches[]`）暗示的潜在覆盖缺口。

### Audit appendix

紧凑附录包含：

- target、snapshot、scope、scope resolution、假设和排除项；
- Finding / Decision / Severity / Confidence / 条件字段；
- required Claim、验证方法、Claim-level Sufficiency，以及实际异质/独立验证程度；
- 关键 Supporting/Refuting Evidence 和存在的 investigation/verification 索引；audit-and-fix 可附由 `state.json.fixWorkflow` 派生的 fix-map，但不得把它当作另一份状态；
- validator 命令与结果、未执行检查和基线失败。

用户要求完整追溯、Gate 有争议、Critical/High 存在冲突 Evidence，或关键缺口导致 INCOMPLETE 时，再展开：

```text
Claim → Verification Unit → Hypothesis → Evidence → Finding → Decision
```

普通报告不复制完整 state 或 investigation 正文。

## 2. Finding 报告字段

每个报告 Finding 从 `state.json.findings[]` 读取：

- id、statement、locations、causeImpact、conditions；
- Decision、Severity、Confidence、risk 四维；
- disconfirmation 摘要和关键 Supporting/Refuting Evidence；
- verificationMethod、exitCriteria；
- 只有字段真实存在时才显示 `patternScope`、Provenance、Disposition、Gate applicability/treatment。

调查者的 potentialImpact、recommendation 或局部 result 不是最终字段。省略的 disposition 在 Gate 计算中等价于 `OPEN`，但普通报告不必专门显示 `OPEN`。

## 3. Gate applicability

只有 `audit.gates.targets` 中的 target 才计算 Gate。FINAL 的每个非 REJECTED Finding 必须对每个请求 target 写：

- `APPLIES`：在当前唯一 target/snapshot 和声明条件下参与该 Gate；
- `DOES-NOT-APPLY`：有足够 Evidence 证明不参与；
- `UNRESOLVED`：当前适用性本身缺少决定性 Evidence。

`APPLIES` 和 `DOES-NOT-APPLY` 必须同时写非空 `evidenceRefs`，引用已连接到该 Finding 的 DIRECT Evidence；`basis` 只是人类可读解释。APPLIES 至少需 supports/context，DOES-NOT-APPLY 至少需 refutes/context current-state Evidence；RESOLVED-VERIFIED 的每个 target 还必须引用 resolutionEvidence。`UNRESOLVED` 不得伪造确定性 Evidence。

Finding 是否真实由 Decision 表达；是否参与某个决策问题由 applicability 表达。Gate 阈值和风险接受不能改写二者。

- `CHANGE`：判断目标变更能否接受/合并/安全集成。INTRODUCED / REGRESSED / EXPOSED 通常相关；纯 PRE_EXISTING 默认不单独阻断，除非 Evidence 表明目标变更依赖或扩大了它。
- `RELEASE`：判断当前候选能否发布。当前是否仍适用决定相关性，Provenance 不决定放行。
- `SYSTEM`：判断当前系统是否满足约定健康/安全目标。由 objectives 和当前状态 Evidence 决定。

只有 target/snapshot 本身承诺包含某个 artifact 时，“路径不存在”才可直接形成缺包 Finding；artifact 只是没有随审计输入提供时，应记录 Evidence gap/residual risk，不得外推为 release distribution 缺陷。

`RESOLVED-VERIFIED` 要求 DIRECT current-state Evidence；有 Gate 时所有相关 applicability 必须为 DOES-NOT-APPLY。无法验证风险是否消失时不能使用该 Disposition。

## 4. Gate 算法

对每个 target 独立计算。Claim 只在自身 `gateTargets` 包含当前 target 时参与完整性判断；Finding 只在当前 target applicability 为 APPLIES/UNRESOLVED 时参与；Residual risk 只在 `affectsGates` 包含当前 target 时参与，省略该字段表示仅在报告中披露、不参与任何 Gate。默认 `blockAtOrAbove=High`；用户只可按 target 设为 `Medium|Low` 以收紧阈值。其它完成要求必须转成 REQUIRED Claim，无法归一时结果为 INCOMPLETE。

按下列优先级取第一个命中项：

| 优先级 | 条件 | 结果 |
|---|---|---|
| 1 | 存在 APPLIES + CONFIRMED 且 Severity 达到当前 target 的阻断阈值，未 RESOLVED-VERIFIED、也未获得当前 target 风险接受 | `BLOCKED` |
| 2 | 当前 target 没有任何携带该 `gateTargets` 的 REQUIRED Claim；或相关 REQUIRED Claim 的 Unit 集合为空，任一已物化 Unit 未 verified；high/highest Claim Sufficiency 不是 MET；highest Claim 少于两个 verified 异质方法；显式 independent 要求未满足；`exhaustive` scope inventory 非空义务未闭合；存在 PENDING、达到阻断阈值的 CONDITIONAL/NEEDS-DECISION、可能形成关键阻断的 UNRESOLVED applicability、影响当前 target 的 material residual gap或决定性 Evidence/环境缺口 | `INCOMPLETE` |
| 3 | 无前两项，但存在 APPLIES、低于阻断阈值、非 REJECTED 且未获得当前 target 合法风险接受的 Finding，或存在影响当前 target 的非 material residual risk / 其它明确条件项 | `READY-WITH-CONDITIONS` |
| 4 | 所有相关 required 输入闭环，且没有阻断、未决或条件项 | `READY` |

细则：

- highest Claim 的异质性按 `claimId` 归组：至少两个 verified REQUIRED Unit 使用不同 method。
- Independent validation 的机械判据以 [audit-ledger.md](audit-ledger.md) §3.4 为准：在支撑该 highest Claim 的 REQUIRED Unit 中，存在不同 executor、不同 method 且 `isolation=ISOLATED` 的 Unit 达到两组时成立；未隔离 Unit 不参与计数。`AUDIT` 约束所有 highest Claim；Gate target 值约束所有支撑该 target 的 highest Claim。明确要求却没有任何 highest Claim 也是缺口。
- Claim `sufficiency=NOT-MET` 不能因其 Unit 已 verified 而放行。
- 合法 `treatment=ACCEPTED` 只从当前 target 的已知 Finding 风险集合排除该 Finding；其 authorization 必须结构化绑定当前 auditId、完整 snapshot 和 target，不能从旧实例复制。不排除 coverage、Evidence、环境或 independent-validation 缺口。有 Gate 时禁止全局 ACCEPTED-RISK，避免越过未授权 target。
- 每个 Gate 的 `basis` 必须非空并引用至少一个实际决定性 Q/F/G id；READY 使用固定 token `ALL-REQUIRED-INPUTS-SATISFIED`，无 highest Claim 导致的显式独立验证缺口使用 `INDEPENDENT-VALIDATION-GAP`，当前 target 零 REQUIRED coverage 使用 `REQUIRED-COVERAGE-GAP`，穷尽 inventory 未闭合使用 `EXHAUSTIVE-COVERAGE-GAP`。随后写入 `audit.gates.decisions` 并运行 validator。

## 5. 无 Gate 与 clean conclusion

没有 Gate 时不创造 READY/BLOCKED；直接报告 Findings、已验证正确行为、Required actions 和 Residual uncertainty。

FINAL 中如有 REQUIRED Unit 未 verified，报告必须沿该 Unit 的 `residualRiskId` 显示对应 material `G<n>`，不得宣称 clean conclusion。无 Gate 且存在显式 `independentValidationRequiredFor=["AUDIT"]` 时，FINAL 必须至少有一个 highest Claim，且每个 highest Claim 均满足独立验证；否则 state 非法，不能以 warning 或受限措辞代替硬要求。没有显式 independent 硬要求时，若存在 highest Claim 但没有任何最高风险异质验证由不同隔离执行者完成，可产生受限审计，但必须在 Residual uncertainty 披露“未形成 independent validation”；不得静默写成独立交叉验证。

无 Gate 的 FINAL 也必须至少包含一个 REQUIRED Claim。`audit.objectives` 虽然非空，但它们只是任务问题；没有被物化为至少一个可验证 Claim 时，不存在能支持 FINAL 或 clean conclusion 的验证范围，validator 会拒绝该状态。

只有同时满足以下条件，才能写：

> 在已审计范围和已执行检查内未发现已确认缺陷。

条件：

1. Task Contract 与实际范围闭环；若 `stop.policy=exhaustive`，`scopeCoverage` declared inventory 非空、与最终 snapshot 绑定，且每个 member completed 或带理由 excluded；
2. 所有最终 Finding 均 REJECTED，或没有形成 Finding；
3. 每个 required Claim 都有非空 Unit 集合且全部 verified，每个 verified Unit 至少有一条 DIRECT Evidence，high/highest Claim Sufficiency 为 MET，highest 异质覆盖完成；
4. 不存在 material residual gap、决定性 Evidence/环境缺口或未满足的显式 independent 要求；
5. 最终 state 通过 validator，或无机械能力时已经按同一不变量人工核对并明确披露。

否则使用受限措辞，具体列出仍未闭合的风险；不得写“绝对安全”“没有 bug”或“所有场景都正确”。

## 6. 输出前检查

- [ ] 报告绑定一个 auditId/target/snapshot，范围与 FINAL state 一致。
- [ ] 报告显示 auditId；若追溯了被接替实例，附录明确区分 predecessor/successor，不把 SUPERSEDED 结论当前化。
- [ ] 只有真实请求的 Gate 被分别计算；没有折叠成单一最坏值。
- [ ] Gate 先按本文件算法重算，再由 validator 核对缓存结果。
- [ ] Finding 字段来自 state；H/E 只作引用，没有用代理共识覆盖 Decision。
- [ ] Required actions 与 Recommendations 分开，退出条件可判定。
- [ ] Provenance、Disposition、Gate、探索、fix 字段只在适用时显示。
- [ ] material residual risk、未运行检查、基线失败、能力和恢复限制已披露。
- [ ] clean conclusion 已按 §5 单独核对，不以“流程结束”替代。
