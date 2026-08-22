# 修复与 fix-commit 验证

`executionMode=audit-and-fix`、`objectiveProfile` 含 `fix-verification`，或审计对象本身是整改 commit/分支时读取本文件。目标不是证明"改过了"，而是证明原 Finding 消失、所有已确认同类实例得到处理、测试能识别回退且没有引入更高价值的新缺陷。

## 1. 建立修复映射

如果当前审计没有可复用的规范化原 Finding，先把用户描述、issue/PR、历史报告或 commit message 中的缺陷主张仅作为 Hypothesis seed，按本 Skill 的 H/E/F/Decision 流程重建并裁决；不得因为旧报告写了“bug/High/fixed”就直接视为已确认事实。然后为每个原 Finding 建立：

`Finding | 根因模式 | 已知实例 | 修复范围 | 明确排除项 | 行为变化 | 验收测试 | PRE-fix 应失败 | 回归范围 | 残留风险`

修复映射表写入权威审计状态的 `fix-map`（可持久化时为 `fix-map.md`；每 Finding 一行，随批次推进更新）。

读取 PRE-fix 代码和原始报告，核对实际 diff、调用者、公共入口和测试，不只看 commit message 或"测试已通过"。

## 2. 动态划分批次

按以下因素组合修复，不使用固定项目数：

- 是否共享根因和修复策略。
- 是否属于同一子系统、数据边界或生命周期。
- 是否可由同一组验收命令一次验证。
- 是否具有相同回滚、兼容和数据风险。
- 是否会互相遮蔽失败原因。

高风险、不可逆、难回滚或证据复杂的问题单独成批；多个同根因、同验证路径的低风险实例可以合并。每批声明允许修改的路径、验收条件和停止条件。

划分后把批次写成显式依赖图（每批一行）：

```text
| 批次 | 依赖批次 | 根因/子系统 | 允许修改路径 | 验收命令 | 批间门状态/依据 |
|---|---|---|---|---|---|
| fix-batch-1 | —         | 根因 A | … | … | PENDING |
| verify-batch-1 | fix-batch-1 | —   | — | … | PENDING |
| 综合回归 | 全部 verify 批次 | — | — | … | PENDING |
```

批间门状态只使用 `PENDING` / `PASSED` / `FAILED`。

批次依赖图写在权威审计状态的 `fix-map` 顶部（可持久化时为 `fix-map.md`），随批次状态同步更新。

批间门规则：

- 所有依赖批次达到 `PASSED` 后，下游批次才可开始；`PENDING` / `FAILED` 均阻断下游。
- `fix-batch-*`：修复实施完成、定向检查通过，且其中仍需修复的 Finding 已进入 `REMEDIATING` 后即可标为 `PASSED`，并解锁对应验证批次；已明确转为 `ACCEPTED-RISK` 或 Decision=`REJECTED` 的 Finding 不阻断该批。此时不得要求 Finding 已经 `RESOLVED-VERIFIED`。
- `verify-batch-*`：异质复核与主代理验证通过，且本批验收所针对的修复上下文已有 DIRECT Evidence 证明原风险在本审计唯一权威 target/state snapshot 中消失、接受风险的 Finding 已取得对应授权后，才可标为 `PASSED`。使用 `RESOLVED-VERIFIED` 时，存在真实 Gate 的 Finding 还必须对所有相关请求 Gate 写 `DOES-NOT-APPLY`；不同版本、候选或部署状态不得在同一批次状态中混合表达。
- `综合回归`：全部依赖验证批次达到 `PASSED`，最终回归通过，且没有尚未处理的新增阻断项或会导致 `INCOMPLETE` 的 Critical/High 风险缺口后，才可标为 `PASSED`。
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
2. 运行定向检查，再运行与风险相称的回归检查；用于支撑 material 修复结论的测试按当前 test-discrimination 记录填写 `YES/PARTIAL/NO/UNKNOWN`、Basis 与可选 Test issue，generic green 不能替代判别力。
3. 判别力验证优先在 PRE-fix 版本运行；需恢复旧 guard、做变异或注入失败时，只能在仓库外副本、临时 worktree 或其他可丢弃环境中进行。
4. 对运行时、用户路径、平台、并发和第三方语义调用真实公共路径并记录新的 DIRECT Evidence。若原 Finding 尚无最终 Decision，主代理据这些 Evidence 作 Decision；若原 Finding 已有最终 Decision 且当前只验证修复效果，则不因“验证暂缺”改写原 Decision，把 Disposition 保持 `REMEDIATING` 并记录 `VERIFICATION-GAP`。
5. 核对所有已确认实例已修复或有直接证据排除；检查被替换但仍存活的 helper、writer、route、export、feature flag 和旧数据路径。

## 5. 异质方法复核

为每个受影响子系统先从原 Finding 风险面选择**至少一种与原主要发现不同的验证 archetype**。不同只读执行者只有在未参与实现、未读取其他复核结果且实际 `Judgment isolation=ISOLATED` 时，才形成 independent validation；执行者分配、隔离重跑、有界降级与强制独立验证的完成规则按 `SKILL.md` §3。提供 Finding→修复映射、精确 diff、验收标准、基线失败、模式范围及允许检查。Critical/High 修复不得只换一个代理重复 patch review；优先选择能直接区分 PRE-fix/POST-fix 的 `user-path-trace`、`test-discrimination`、`state-invariant-analysis` 或其它适配方法。要求复核者回答：

- 原 Finding 是否真正消失，直接证据是什么？
- 所有已确认同类实例是否处理，排除项是否安全？
- 新测试是否会在 PRE-fix/等价 failure 行为下失败？对应 Test discrimination 记录是什么？
- 是否破坏旧数据、旧调用方、错误/取消路径、恢复或回滚能力？
- 被替换的旧入口是否仍可达？
- 修复是否引入新的 material regression Hypothesis？若有，记录 H/E；最终 Finding/Decision/Severity/Confidence 由主代理按 assessment model 决定。

复核者保持只读，不为满足形式自行修改项目。先在权威 coverage（独立 `coverage.md`，或 `audit.md` 的 Embedded coverage）建立验证单元，再按调查产物模板写入 `investigations/<unit>-fix-<批次>.md`。若原方法无法执行而改用替代 archetype，必须同步更新该 coverage 记录，不得静默替换。

符合 §8 适用条件的文档/纯文本类修复可由主代理按轻量判据直接复核，不强制新代理链；其中 Critical/High Finding 仍按 §7 第 3 条获得异质方法复核。

## 6. 验证批次反馈

- `FIX-STILL-FAILS`：修复并重跑受影响检查。
- `CLAIM-REFUTED`：记录主代理反证，不为满足代理意见修改正确代码。
- `MISSED-INSTANCE`：回到模式范围，确认是孤立遗漏还是边界定义错误。
- `NEW-REGRESSION`：先记录新的 H/E，由主代理完成 disconfirmation 后规范化 Finding，并作 Decision/Severity/Confidence；新增 `CONFIRMED` Critical/High 必须在本批及相关请求 Gate 上通过已验证的 resolution 或合法风险接受完成处置；只有满足全局 Disposition 条件时才使用 `RESOLVED-VERIFIED` / `ACCEPTED-RISK`；新增 Critical/High `CONDITIONAL` 必须补齐决定性 Evidence 并重新裁决，`NEEDS-DECISION` 必须取得所需授权决策。上述状态未收口前，当前批次不得静默通过。
- `VERIFICATION-GAP`：写清缺失环境、平台或契约；不改变已有 Finding 的 Decision，尚未验证完成的修复保持 `REMEDIATING`。

每批都更新权威 `fix-map`；只有 Decision、Disposition 或决定性 Evidence 实际变化时才同步更新权威 ledger。主代理确认批间门通过后才进入下一批。

`FIX-STILL-FAILS` / `CLAIM-REFUTED` / `MISSED-INSTANCE` / `NEW-REGRESSION` / `VERIFICATION-GAP` 是批内反馈，不写入 ledger 的 Decision 列；只有 Finding 的最终 Decision/Disposition 变化、决定性 Evidence 变化或新回归 Finding 才更新 `ledger.md`。

原 Finding 经修复后，只有 DIRECT Evidence 证明它在本审计唯一权威 target/state snapshot 中不再适用，才把权威 ledger 中该 Finding 的 `Disposition` 由 `OPEN` / `REMEDIATING` 改为 `RESOLVED-VERIFIED`；存在真实 Gate 时，还必须把该 Finding 对所有相关请求 Gate 的 applicability 写为 `DOES-NOT-APPLY`。对由后续提交、revert 或 superseding change 消除的历史 Finding 同理；不同版本、候选或部署状态必须拆成独立审计实例。若决定接受该风险，`gateTargets=NONE` 时只有授权明确覆盖该 Finding 本身才使用 `ACCEPTED-RISK`；存在真实 Gate 时，只有授权覆盖所有相关请求 Gate 才改为全局 `ACCEPTED-RISK`，否则使用 target-specific `Gate treatment=ACCEPTED`。`Disposition` 与 `Decision`（问题是否成立）正交：`CONFIRMED` 只表示“问题曾确认成立”，不表示“当前仍存在”或“已修复”。

## 7. 收尾门槛

1. 每个原 Finding 都有最终 Decision、模式范围结论与 `Disposition`；需要修复的 Finding 另有修复位置和验收 Evidence；接受风险或被驳回的 Finding 记录对应依据。
2. 已确认同类实例全部处理或明确排除；未覆盖范围单独披露。
3. Critical/High 修复至少获得一种与原主要发现不同的验证 archetype 并有主代理直接复核；执行者与判断隔离按 §5 记录，`independentValidationRequiredFor` 覆盖本次审计或相应 Gate 时不得带缺口通过。
4. 只有项目策略、计划或用户要求时才更新 CHANGELOG、生成物或发布说明。
5. Git-backed 工件检查交付完整性（遗漏/杂散文件、exports、lockfile、vendor、markers、生成物、ignore 规则）；所有工件都清理临时证据包、探针和隔离环境，并确认最终工件只包含预期修改。
6. 核对批次依赖图：每批都有批间门状态与验收依据，进入下一批前批间门已通过；任何跳过批间门的批次与理由写入报告。
7. 运行最终回归，并报告未运行检查、既有失败和平台缺口。
8. 符合 §8 适用条件的文档/纯文本类工件按轻量判据验收（主代理直接复核；Critical/High 仍须异质方法复核）。

## 8. 文档/纯文本类工件的修复验收（轻量判据）

审计对象是文档、报告、计划，或确实不存在解析、schema、构建、加载、运行时等可执行/可判定验证路径的纯文本配置时，前几节的“判别测试/验收命令”不直接适用。存在上述验证路径的配置仍按前述正常验证流程执行。符合轻量条件时，按以下判据验收修复：

1. **逐项对照**：每个已确认问题 → 修复位置 → 通过条件，逐一核对已落地；旧表述不再出现（含同义改写残留），但历史记录/变更记录中作为"改前值"的表述不算残留。
2. **残留扫描**：对被修模式的旧表述做全文扫描（grep 旧短语、旧编号、已删除文件名），确认无存活引用。
3. **复读与交叉引用**：重读所有被改区域，受影响的关键主张重新建立"主张 → 证据/来源"映射；确认未引入新不一致（计数、编号范围、章节互指、版本注、引文与正文）。
4. **留痕**：修订按工件自身惯例记录（版本注/变更记录段），头部元数据（版本号、日期）同步更新。
5. **计划类工件**：复检原 Audit objectives 中约定的计划就绪条件全部满足。
6. **收口**：全部通过后保持原 Finding 的 Decision 不变；当前风险在本审计唯一权威 target/state snapshot 中验证消失后，才把 `Disposition` 更新为 `RESOLVED-VERIFIED`；存在真实 Gate 时，还必须把所有相关请求 Gate 的 applicability 写为 `DOES-NOT-APPLY`。只有新 Evidence 改变“问题是否成立”时才重新作 Decision；无法验证修复效果时保持 `REMEDIATING`。不同版本、候选或部署状态拆成独立审计实例。

符合本节适用条件的文档/纯文本类修复可由主代理直接复核，不强制新代理链；Critical/High Finding 仍须异质方法复核。其余流程（分批、账本更新）与代码类工件相同。
