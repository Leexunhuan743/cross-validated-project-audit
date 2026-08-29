# 修复与 fix-commit 验证

`executionMode=audit-and-fix`、`objectiveProfiles` 含 `fix-verification`，或审计对象本身是整改 commit/分支时读取本文件。目标不是证明"改过了"，而是证明原 Finding 消失、所有已确认同类实例得到处理、测试能识别回退且没有引入更高价值的新缺陷。

## 1. 建立修复映射

如果当前审计没有可复用的规范化原 Finding，先把用户描述、issue/PR、历史报告或 commit message 中的缺陷主张仅作为 Hypothesis seed，按本 Skill 的 H/E/F/Decision 流程重建并裁决；不得因为旧报告写了“bug/High/fixed”就直接视为已确认事实。然后为每个原 Finding 建立：

`Finding | 根因模式 | 已知实例 | 修复范围 | 明确排除项 | 行为变化 | 验收测试 | PRE-fix 应失败 | 回归范围 | 残留风险`

`executionMode=audit-and-fix` 且首个 Finding 真正进入 `REMEDIATING` 时，修复映射与批次状态写入唯一权威的 `state.json.fixWorkflow`；若审计后没有需要修复的 Finding，不为空流程创建批次。需要表格阅读时可生成 `fix-map.md`，但它只是派生视图，不参与 validator、恢复或批次解锁。`executionMode=audit-only` 仅核验外部已完成的修复时不创建批次 DAG，直接用 Finding、verification 和 resolution Evidence 表达结果。

读取 PRE-fix 代码和原始报告，核对实际 diff、调用者、公共入口和测试，不只看 commit message 或"测试已通过"。

`audit-and-fix` 在初始 Task Contract 就把 target 定义为有界 PRE-fix → POST-fix 转换，并固定 PRE-fix 基线、允许修改路径和最终验收条件。完成该已声明转换后，FINAL 状态保存可复核的 POST-fix 身份；两端都已提交时用 Git `base/head`，没有授权 commit 或任一端含相关未提交内容时用 `git-worktree` 的 PRE/POST HEAD 与确定性内容 manifest。这允许原 Finding 的历史 Evidence 与当前 resolution Evidence 在同一任务契约中共存，而不靠越权 commit 固定工作树。若基线/目标被外部更换、超出允许路径或权威事实发生契约外变化，则按 ledger 接替整个审计，不把原批次当成仍然有效。

## 2. 动态划分批次

按以下因素组合修复，不使用固定项目数：

- 是否共享根因和修复策略。
- 是否属于同一子系统、数据边界或生命周期。
- 是否可由同一组验收命令一次验证。
- 是否具有相同回滚、兼容和数据风险。
- 是否会互相遮蔽失败原因。

高风险、不可逆、难回滚或证据复杂的问题单独成批；多个同根因、同验证路径的低风险实例可以合并。每批声明允许修改的路径、验收条件和停止条件。

划分后先把批次写入 `state.json.fixWorkflow.batches[]` 的显式依赖图；下表只可作为派生阅读视图：

```text
| 批次 | 依赖批次 | 根因/子系统 | 允许修改路径 | 验收命令 | 批间门状态/依据 |
|---|---|---|---|---|---|
| fix-batch-1 | —         | 根因 A | … | … | PENDING |
| verify-batch-1 | fix-batch-1 | —   | — | … | PENDING |
| 综合回归 | 全部 verify 批次 | — | — | … | PENDING |
```

批间门状态只使用 `PENDING` / `PASSED` / `FAILED`。

机器字段和约束以 [audit-ledger.md](audit-ledger.md) §3.7 为准：workflow 保存 `generation/finalRegressionBatchId/findingMappings`；每个 mapping 保存根因、实例、修复/排除范围、行为变化、验收、PRE 失败、回归范围和残留风险；batch 保存 `id/kind/status/attempt/transitionReason?/scope/allowedPaths/acceptanceChecks/dependsOn/findingIds/evidenceRefs/validatedGeneration`。改变修复工件或验收 Evidence、使已通过依据失效时，先递增 generation，再把受影响批次及传递下游置为 PENDING；attempt 大于 1 时记录重试/失效原因。所有更新与 Finding/Disposition/Evidence 在同一 `state.json` 原子替换中完成。

批间门规则：

- 所有依赖批次达到 `PASSED` 后，下游批次才可开始；`PENDING` / `FAILED` 均阻断下游。
- 正常验收转换只允许 `PENDING → PASSED|FAILED`。失败后重试必须记录新 attempt、修复范围与重跑依据，才允许 `FAILED → PENDING`；发生下一条所述实质失效时允许 `PASSED → PENDING`。除正常验收、带记录重试和实质失效外不得转换，尤其禁止无记录地把 `FAILED` 直接改为 `PASSED`。
- 已通过批次的工件或批次验收 Evidence 在同一权威 target/snapshot 内发生实质变化时，递增 `fixWorkflow.generation`，该批次及其全部传递下游立即失效并回到 `PENDING`；重新验收且 `validatedGeneration` 等于当前 generation 前不得消费旧 `PASSED`。如果变化的是权威 target、snapshot、scope、objectives、决策问题或 shared facts，不在原实例回滚批次；按 [audit-ledger.md](audit-ledger.md) 接替整个审计实例。
- `fix-batch-*`：修复实施完成、定向检查通过，且其中仍需修复的 Finding 已进入 `REMEDIATING` 后即可标为 `PASSED`，并解锁对应验证批次。Decision=`REJECTED` 的 Finding 不阻断该批；无 Gate 时全局 `ACCEPTED-RISK` 也不阻断，有 Gate 时则必须由该批涉及的所有相关请求 target 分别具备合法 `treatment=ACCEPTED + authorization`。只接受部分 target 不能把该 Finding 视为对整批已处置。此时不得要求 Finding 已经 `RESOLVED-VERIFIED`。
- `verify-batch-*`：异质复核与主代理验证通过，且本批验收所针对的修复上下文已有 DIRECT Evidence 证明原风险在本审计唯一权威 target/state snapshot 中消失、接受风险的 Finding 已取得对应授权后，才可标为 `PASSED`。每个列入该批 `findingIds` 的 Finding 必须已经 `REJECTED`、`RESOLVED-VERIFIED` 或被所有相关 target 合法接受；其中 `RESOLVED-VERIFIED` Finding 的本批 `evidenceRefs` 必须引用它自己的 `resolutionEvidence`，不能只复用旧 supporting Evidence。存在真实 Gate 的已解决 Finding 还必须对所有相关请求 Gate 写 `DOES-NOT-APPLY`；不同版本、候选或部署状态不得在同一批次状态中混合表达。
- `综合回归`：全部依赖验证批次达到 `PASSED`，最终回归通过，且没有尚未处理的新增阻断项或会阻断**本修复验收或相关 Gate**的 material 风险缺口后，才可标为 `PASSED`。与本修复验收和相关 Gate 无关的缺口不回写为该批失败；按第 7 节形成受限 FINAL 或相应 Gate=`INCOMPLETE`。
- 违规提前进入下一批视为过程缺陷，必须在完成清单与报告中披露。

## 3. 确认模式范围

实施前先复核原 Finding 的模式范围：

1. 确认根因模式和至少一个真实实例。
2. 定义安全反例，避免机械替换相似代码。
3. 在授权子系统内有界搜索同类入口。
4. 记录确认实例、排除实例和未覆盖范围。
5. 需要扩大到整个大型仓库时，先报告专项审计需求。

修复不能只处理报告中的首个位置，也不能因"可能系统性"而未经验证批量改写。

## 4. 实施与主代理验证

1. Git 工作区中实施前先 `git status --short` 与 `git diff --stat` 记录既有改动，区分用户改动与本次修复；混杂文件声明提交边界，不把无关改动带进修复。非 Git 工件按其自身版本/副本机制记录修前状态。实施最小且根因级的修复，保护用户已有改动。
2. 运行定向检查，再运行与风险相称的回归检查；用于支撑 material 修复结论的测试按当前 test-discrimination 记录填写 `YES/PARTIAL/NO/UNKNOWN`、Basis 与可选 Test issue，generic green 不能替代判别力。`method=test-discrimination` 的 verified Unit 至少需要一条 `result=YES` 的 DIRECT Evidence；`NO/PARTIAL/UNKNOWN` 仍是合法的缺口 Evidence，但不能支撑该方法的 verified/MET 修复验收。
3. 判别力验证优先在 PRE-fix 版本运行；需恢复旧 guard、做变异或注入失败时，只能在仓库外副本、临时 worktree 或其他可丢弃环境中进行。
4. 对运行时、用户路径、平台、并发和第三方语义调用真实公共路径并记录新的 DIRECT Evidence。若原 Finding 尚无最终 Decision，主代理据这些 Evidence 作 Decision；若原 Finding 已有最终 Decision 且当前只验证修复效果，则不因“验证暂缺”改写原 Decision。只有原 Decision=`CONFIRMED` 才显式写 `disposition=REMEDIATING`；CONDITIONAL / NEEDS-DECISION 省略 disposition，按默认 OPEN 处理，并记录 `VERIFICATION-GAP`。
5. 核对所有已确认实例已修复或有直接证据排除；检查被替换但仍存活的 helper、writer、route、export、feature flag 和旧数据路径。

## 5. 异质方法复核

为每个受影响子系统先从原 Finding 风险面选择**至少一种与原主要发现不同的验证 archetype**。不同只读执行者只有在未参与实现、未读取其他复核结果且相关 Verification Unit 实际 `isolation=ISOLATED` 时，才形成 independent validation；执行者分配、有界降级与强制独立验证按 `SKILL.md` §5。resolution/fix verification 按 auditor persona 的专用隔离边界，可以提供 canonical Finding→修复映射、精确 diff、验收标准、基线失败和模式范围，但不得提供实现者结论、其它复核结果或预期答案；这种目标知情不等于 `NOT-ISOLATED`。Critical/High 修复不得只换一个代理重复 patch review；优先选择能直接区分 PRE-fix/POST-fix 的 `user-path-trace`、`test-discrimination`、`state-invariant-analysis` 或其它适配方法。该修复复核最终写入 Finding verification 的 `resolutionChallenge`，并引用真实 verified Unit；它不同于判断原问题是否成立的 `challenge`，两者不得互相替代。要求复核者回答：

- 原 Finding 是否真正消失，直接证据是什么？
- 所有已确认同类实例是否处理，排除项是否安全？
- 新测试是否会在 PRE-fix/等价 failure 行为下失败？对应 Test discrimination 记录是什么？
- 是否破坏旧数据、旧调用方、错误/取消路径、恢复或回滚能力？
- 被替换的旧入口是否仍可达？
- 修复是否引入新的 material regression Hypothesis？若有，记录 H/E；最终 Finding/Decision/Severity/Confidence 由主代理按 assessment model 决定。

复核者保持只读，不为满足形式自行修改项目。先在 `state.json.claims[]` 建立或复用修复风险 Claim，再在 `verificationUnits[]` 建立新的复核 Unit，调查产物写入 `investigations/<unit>-fix-<批次>.json`。若原方法无法执行而改用替代 archetype，必须更新该 Unit 的 method 并记录缺口，不得静默替换。

符合 §8 适用条件的文档/纯文本类修复可由主代理按轻量判据直接复核，不强制新代理链；其中 Critical/High Finding 仍按 §7 第 3 条获得异质方法复核。

## 6. 验证批次反馈

- `FIX-STILL-FAILS`：修复并重跑受影响检查。
- `CLAIM-REFUTED`：记录主代理反证，不为满足代理意见修改正确代码。
- `MISSED-INSTANCE`：回到模式范围，确认是孤立遗漏还是边界定义错误。
- `NEW-REGRESSION`：先记录新的 H/E，由主代理完成 disconfirmation 后规范化 Finding，并作 Decision/Severity/Confidence。新增 Finding 达到任一相关请求 Gate 的阻断阈值（无 Gate 时为 Critical/High）时，必须在本批及相关请求 Gate 上通过已验证的 resolution 或合法风险接受完成处置；验证消除时才用 `RESOLVED-VERIFIED`，无 Gate 且明确接受整个 Finding 时才用全局 `ACCEPTED-RISK`，有 Gate 时按 target 记录接受。达到上述阈值的 `CONDITIONAL` 必须补齐决定性 Evidence 并重新裁决，`NEEDS-DECISION` 必须取得所需授权决策。上述状态未收口前，当前批次不得静默通过。
- `VERIFICATION-GAP`：写清缺失环境、平台或契约；不改变已有 Finding 的 Decision，尚未验证完成的修复保持 `REMEDIATING`（原 Decision 非 `CONFIRMED` 时按组合表保持 `OPEN`）。

每批都在同一次 `state.json` 原子替换中更新 `fixWorkflow` 及本批产生的 Decision、Disposition、决定性 Evidence 或新 Finding。主代理确认依赖批次为 PASSED、当前批的 `validatedGeneration` 与 workflow generation 相等后才进入下一批。

`FIX-STILL-FAILS` / `CLAIM-REFUTED` / `MISSED-INSTANCE` / `NEW-REGRESSION` / `VERIFICATION-GAP` 是批内反馈，不是 Finding Decision。它们可写入派生报告；机器恢复只依赖 `state.json` 中的 batch 状态、attempt、Evidence 和 Finding 状态，不从 Markdown 反馈反推。

原 Finding 经修复后，只有 DIRECT Evidence 证明它在本审计唯一权威 target/snapshot 中不再适用，才把该 Finding 的 `disposition` 从省略（默认 OPEN）或 `REMEDIATING` 改为 `RESOLVED-VERIFIED`，并写 `resolutionEvidence`；存在真实 Gate 时，还必须把所有相关 applicability 写为 `DOES-NOT-APPLY`，并为每个确定适用性写非空 `evidenceRefs`。后续提交、revert 或 superseding change 同理；不同状态按 ledger 的 supersession 规则拆成独立审计实例。无 Gate 时，明确授权覆盖该 Finding 本身才使用全局 `ACCEPTED-RISK`；有任何 Gate 时禁止全局接受，只能在获得授权的特定 target 写 `treatment=ACCEPTED + authorization`。Disposition 与 Decision 正交：CONFIRMED 表示问题曾确认成立，不表示当前仍存在或已修复。

## 7. 收尾门槛

1. 每个原 Finding 都有最终 Decision 和模式范围；CONFIRMED Finding 的 disposition 省略即 OPEN，进入整改/消除/接受时才显式物化；需要修复的 Finding 另有修复位置和验收 Evidence。
2. 已确认同类实例全部处理或明确排除；未覆盖范围单独披露。
3. Critical/High 修复至少获得一种与原主要发现不同的验证 archetype 并有主代理直接复核；对应 verified Unit、方法和 Evidence 写入 `resolutionChallenge`；执行者与判断隔离按 §5 记录，`independentValidationRequiredFor` 覆盖本次审计或相应 Gate 时不得带缺口通过。
4. 只有项目策略、计划或用户要求时才更新 CHANGELOG、生成物或发布说明。
5. Git-backed 工件检查交付完整性（遗漏/杂散文件、exports、lockfile、vendor、markers、生成物、ignore 规则）；所有工件都清理临时证据包、探针和隔离环境，并确认最终工件只包含预期修改。
6. `executionMode=audit-and-fix` 时核对 `state.json.fixWorkflow`：每批都有 attempt、依赖、状态、验收 Evidence 和当前 validatedGeneration；FINAL 的所有批次均 PASSED，不留 `REMEDIATING` Finding，最终 REGRESSION 传递依赖所有 PASSED FIX 和 VERIFY。修复尚未验证、批次失败或仍有会阻断该修复验收的 material 缺口时保持 ACTIVE，以中间/受阻报告如实交付，不能把全绿外观或有限结论写成 FINAL 修复完成；与本修复验收无关的缺口仍按主流程形成受限 FINAL 或相应 Gate=`INCOMPLETE`。任何被 validator 拒绝的跳批状态都不能写入最终报告。audit-only 的外部修复核验不为形式创建批次。
7. 运行最终回归，并报告未运行检查、既有失败和平台缺口。
8. 符合 §8 适用条件的文档/纯文本类工件按轻量判据验收（主代理直接复核；Critical/High 仍须异质方法复核）。

## 8. 文档/纯文本类工件的修复验收（轻量判据）

审计对象是文档、报告、计划，或确实不存在解析、schema、构建、加载、运行时等可执行/可判定验证路径的纯文本配置时，前几节的“判别测试/验收命令”不直接适用。存在上述验证路径的配置仍按前述正常验证流程执行。符合轻量条件时，按以下判据验收修复：

1. **逐项对照**：每个已确认问题 → 修复位置 → 通过条件，逐一核对已落地；旧表述不再出现（含同义改写残留），但历史记录/变更记录中作为"改前值"的表述不算残留。
2. **残留扫描**：对被修模式的旧表述做全文扫描（grep 旧短语、旧编号、已删除文件名），确认无存活引用。
3. **复读与交叉引用**：重读所有被改区域，受影响的关键主张重新建立"主张 → 证据/来源"映射；确认未引入新不一致（计数、编号范围、章节互指、版本注、引文与正文）。
4. **留痕**：修订按工件自身惯例记录（版本注/变更记录段），头部元数据（版本号、日期）同步更新。
5. **计划类工件**：复检原 Audit objectives 中约定的计划就绪条件全部满足。
6. **收口**：全部通过后保持原 Finding 的 Decision 不变；当前风险在本审计唯一权威 target/state snapshot 中验证消失后，才把 `Disposition` 更新为 `RESOLVED-VERIFIED`；存在真实 Gate 时，还必须把所有相关请求 Gate 的 applicability 写为 `DOES-NOT-APPLY`。只有新 Evidence 改变“问题是否成立”时才重新作 Decision。无法验证修复效果时，原 Decision=`CONFIRMED` 的 Finding 保持 `REMEDIATING`；`resolutionChallenge` 不写不可消费的 GAP 状态，缺口写入 residual risk、limits 或未通过批次；`CONDITIONAL` / `NEEDS-DECISION` 省略 disposition、保持默认 `OPEN`，并记录 `VERIFICATION-GAP`。这种未完成修复保持 ACTIVE，不宣称 FINAL。不同版本、候选或部署状态拆成独立审计实例。

符合本节适用条件的文档/纯文本类修复可由主代理直接复核，不强制新代理链；Critical/High Finding 仍须异质方法复核。其余 state 更新与代码类工件相同；只有 `executionMode=audit-and-fix` 才执行分批和 fixWorkflow。
