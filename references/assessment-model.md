# 反证、风险评估与证据强度

在 material Hypothesis 提升为 Finding、主代理作 Decision/Severity，或需要比较 Evidence 质量时读取本文件。目标是把“问题有多严重”“有多确定”“证据有多强”拆开，避免用降低 Severity 掩盖不确定性。

## 1. Disconfirmation 是标准步骤

每个准备提升为 Finding 的 material Hypothesis 都必须回答一次：**What would make this hypothesis false or materially narrower?**

记录四项：

```text
Counter-hypothesis: <最强的现实安全解释/限制条件；若成立会使原 H 为假或显著缩小>
Expected safe behavior: <若 counter 为真，应观察到的 guard / lock / caller constraint / contract / runtime behavior>
Evidence searched: <实际检查了哪些 caller、guard、lock、lifecycle、contract、runtime、history 等>
Result: counter-supported / counter-refuted / unresolved
```

规则：

- 不允许使用明显不现实的“稻草人反例”；优先检查最可能让原 Hypothesis 不成立的保护条件。
- `counter-supported`：原 H 应关闭或缩窄后重新表述；缩窄后若仍 material，按新的 H 重新完成 disconfirmation，不得直接提升为 Finding。
- `counter-refuted`：可继续提升，但仍保留找到的 limiting Evidence。
- `unresolved`：优先保留为 residual gap；若已有足够 Evidence 使其仍值得规范化为 Finding，必须显式保留未解条件，Decision 不得写 `CONFIRMED`，并相应降低 Confidence 而不是降低 Severity。
- 暂定 Severity 为 Critical/High 的 Finding 在 Decision 定稿前必须尝试第二种异质 archetype 的挑战或等价直接反证搜索；只有完成该要求且 Evidence 足够时才可 `CONFIRMED`。做不到时保留验证缺口并在 Decision/相关 Gate 中体现；普通 Finding 不要求为了形式额外派代理，但仍必须有上述最小 disconfirmation 记录。

## 2. Finding 风险评估维度

主代理在 Finding 形成后、Decision 定稿前评估以下维度。维度描述的是**如果 Finding 陈述为真，在已写明触发条件下的现实风险**，不描述“主代理有多确定”。

| 维度 | 取值 | 含义 |
|---|---|---|
| Impact | `Critical` / `High` / `Medium` / `Low` | 一旦触发的后果规模；安全边界、大范围不可恢复数据损失等属于高影响锚点 |
| Likelihood | `High` / `Medium` / `Low` | 在 Finding 已声明的适用条件下，现实触发频度/概率；不是“Finding 为真的概率” |
| Reachability | `Common` / `Conditional` / `Privileged` | 普通真实路径可达、需要特定但现实条件、或仅高权限/内部路径可达 |
| Recoverability | `Irreversible` / `Manual` / `Automatic` | 发生后恢复所需成本与是否可自动恢复 |

### Severity 映射

Severity 先以 `Impact` 为基线，再只允许以下有限修正，避免每个审计员自行发明公式：

1. 默认 `Severity = Impact`。
2. 当 `Likelihood=Low` 且（`Reachability=Privileged` 或 `Recoverability=Automatic`）时，可下调一级；必须写明为什么现实风险显著受限。
3. 当 `Likelihood=High`、`Reachability=Common`、`Recoverability=Irreversible` 同时成立时，可上调一级，最高为 `Critical`。
4. 现实可达的安全边界绕过、严重数据丢失或大范围不可恢复故障不得仅因“触发不常见”降到 Medium/Low。
5. 任何偏离上述映射的 Severity 必须在 Decision rationale 中写明特殊原因。

**禁止把 Confidence 用作 Severity 修正项。** 例如“如果为真是 Critical，但证据还弱”应表达为 `Severity=Critical, Confidence=Low/Medium, Decision=CONDITIONAL`，而不是把 Severity 偷偷降成 Medium。

## 3. Confidence

Confidence 是 Finding 的一等属性，回答“我们有多确定这条 Finding 陈述为真”。它与 Severity 正交。

| Confidence | 典型条件 |
|---|---|
| `Very-High` | 目标平台/版本公共路径可重复验证，且关键反证已被直接排除；或多个异质高强度 Evidence 无实质冲突 |
| `High` | 至少一条强、可复核的完整证据链，disconfirmation 已完成，且没有未解释的 material 反证 |
| `Medium` | 支持链基本成立，但目标环境、触发条件、重复性或某个关键限制条件仍未完全验证 |
| `Low` | 主要依赖局部 indication，或存在 material 反证/关键条件尚未解决 |

约束：

- `CONFIRMED` 要求 `Confidence ∈ {High, Very-High}`；因事实/环境/验证证据不足而达不到时使用 `CONDITIONAL` 或保留 residual gap；只有事实已足够、剩余的是授权取舍时才使用 `NEEDS-DECISION`。不要通过降低 Severity 假装确定。
- `REJECTED` 表示主代理认为 Finding 不成立，Confidence 字段写 `—`；反驳强度由 Decision rationale 和 refuting Evidence 表达。
- Confidence 变化是实质 Decision 元数据变化，必须进入变更记录。

## 4. Evidence Strength 与可复现性

每条编号 Evidence 除 `Polarity / DIRECT source / Observation` 外，还记录 `Strength` 和 `Reproducibility`。**没有 ES0：直觉、经验和猜测不是 Evidence，只能作为 Hypothesis/reasoning。**

| Strength | 标准 |
|---|---|
| `ES1` | 局部 DIRECT indication：真实代码/日志/输出/契约片段已看到，但完整调用链、状态条件或影响尚未闭合 |
| `ES2` | 完整可追踪链：调用/数据/状态/契约链已闭合，另一调查者可从引用来源自行重查；不依赖未说明猜测 |
| `ES3` | 可执行或确定性复现：有最小步骤、输入、环境与可观察结果，可由另一人重复验证；包括可重复的 schema/build/load/artifact validation |
| `ES4` | 目标权威复现：ES3 在与该主张相关的目标平台/版本/构建条件下，通过真实公共入口成立；对应版本权威契约可作为额外佐证，但非目标环境复现或仅内部 helper 复现不能升级为 ES4 |

`Reproducibility` 只使用：

- `repeatable`：按记录步骤稳定重现/重查；
- `conditional`：只有明确写出的时序、平台、状态或外部前提下可重现；
- `single-observation`：当前只有一次 DIRECT 观察；
- `not-applicable`：纯静态权威事实不存在执行复现，但可由精确来源重复核对。

规则：

- Strength 是**单条 Evidence 的质量**；Confidence 是主代理对整个 Finding 的综合确定度，两者不得混用。
- 多条 ES1 不会因为数量多自动变成 ES3/ES4。
- **仅有“测试/测试套件通过”这一事实**、代理共识、无来源日志或无法重复的一次偶发失败，不能单独高于 ES1；若测试本身对目标错误具有判别力，并记录了可重复的输入、环境、PRE-fix/POST-fix 或等价可观察差异，则按 ES3/ES4 的复现标准评级，而不是被本条限制。
- 目标平台/公共路径的可重复反证可以推翻多条较弱支持 Evidence；冲突 Evidence 必须保留并解释，不按数量投票。
- `ES3/ES4` 必须记录足够的最小复现信息，使其他人员可以重复；缺少关键输入、环境或步骤时降级为 ES1/ES2。

### Material Evidence 冲突：用判别性证据裁决

当支持与反证 Evidence 对同一 material 主张给出冲突结论时，不按代理数量、Evidence 条数或主观可信度投票。主代理先找出双方依赖的**最小分歧前提**，再优先设计能够区分双方的直接观察、实验或契约核对。至少记录：

```text
Disputed assumption: <双方真正分歧的事实/前提>
Supporting side relies on: <支持结论依赖什么>
Refuting side relies on: <反证结论依赖什么>
Discriminating evidence: <什么 DIRECT 观察可使两种解释产生不同预期>
Result: <实际观察；或 unavailable + 原因>
Resolution: resolved-supporting / resolved-refuting / narrowed / unresolved
```

规则：

- 记录位置沿用现有状态层：Finding 形成前写在对应 investigation 的 reasoning/disconfirmation 附近；Finding 已形成则写入 `verification/F<n>.md` 并引用双方 Evidence ID，不新增第二套账本字段。
- 优先选择最小、低副作用、最贴近目标公共路径的判别方法；不要为了“第三票”重复同一 archetype。
- `resolved-supporting`：保留支持方向，但不自动等于 `CONFIRMED`，仍按完整 Decision 条件裁决。
- `resolved-refuting`：Finding 形成前关闭或缩窄原 Hypothesis；Finding 已形成时必须重新评估 Decision，反证足以否定主张时改为 `REJECTED`。
- `narrowed`：缩窄 Hypothesis/Finding 的适用条件并保留双方 Evidence；若 Finding 已形成，重新评估风险维度、Severity、Confidence，以及适用时的 Provenance，不得把局部结果泛化。
- `unresolved`：不得 `CONFIRMED`；material Finding 使用 `CONDITIONAL`，关键缺口按相关 Gate 规则处理。
- 若冲突来自目标版本、环境或契约不一致，先固定实际适用的版本/环境，再比较 Evidence Strength；不能混用不同目标条件下的“正确”结果。

## 5. Provenance：区分变更风险与现存风险

Provenance 只在任务需要判断“风险与某个可比较变更/提交范围的关系”时填写；不涉及变更归因的全项目/静态工件审计写 `—`。需要归因但当前历史/基线 Evidence 不足时才写 `UNKNOWN`。Provenance 回答“这个风险与目标变更是什么关系”，**不表示责任归属，也不改变 Severity/Confidence**。

| Provenance | 判定标准 |
|---|---|
| `INTRODUCED` | 目标变更新增了此前不存在的缺陷机制，例如新功能/新路径本身带入错误 |
| `EXPOSED` | 根因在 base 已存在，但目标变更使其首次现实可达、扩大触发面或把潜在风险变成 material 风险 |
| `REGRESSED` | base 中已有行为/契约是正确的，目标变更使其变错，或重新引入已修复的历史缺陷 |
| `PRE_EXISTING` | 风险在 base 已存在，且目标变更没有实质新增、回归、扩大或激活该风险 |
| `UNKNOWN` | 当前历史/基线 Evidence 不足以可靠判定 |

规则：

- Provenance 必须由 base/head、历史实现、调用可达性或其它 DIRECT Evidence 支撑；不能从 `git blame`、文件作者或 commit message 单独推断。
- `INTRODUCED` 与 `REGRESSED` 的区别：新能力/新路径自身带入缺陷用 `INTRODUCED`；已有可比较行为在 base 正确、head 变错用 `REGRESSED`。
- `EXPOSED` 必须说明“既有根因 + 本次变更新增的可达/影响增量”；不能把纯既有问题包装成本次引入。
- 作者提交审计中的 Provenance 只描述目标提交集合与风险的技术关系，不等于个人责任结论。
- 历史范围中确认成立的 Finding，不因后续提交已修复、revert 或 supersede 而改成 `REJECTED`，也不改写原 Provenance。只有 DIRECT Evidence 验证该 Finding 在本审计唯一权威 target/state snapshot 中不再适用，才保持 Decision=`CONFIRMED` 与原 Provenance、把 Disposition 设为 `RESOLVED-VERIFIED` 并记录 resolution Evidence；存在真实 Gate 时，还必须把该 Finding 对所有相关请求 Gate 的 applicability 写为 `DOES-NOT-APPLY`。若当前适用性对 `RELEASE` / `SYSTEM`（或 `CHANGE` 的安全集成）重要但尚未验证，不得假设已修复，应保留相应 current-state Evidence 缺口，由主代理在 Finding 的 Gate applicability 中显式标记未决，再交 Gate 层处理。不同版本、候选或部署状态必须拆成独立审计实例。
- 归因适用但无法证明时写 `UNKNOWN`，不要为了报告整齐猜测归因；归因本身不适用时写 `—`，不得用 `UNKNOWN` 伪装“不适用”。

## 6. Decision 语义与最小检查

最终 Decision 只使用以下四值；`PENDING` 只是 ledger 的临时工作状态，不是最终 Decision：

| Decision | 语义 |
|---|---|
| `CONFIRMED` | DIRECT Evidence 与 disconfirmation 足以支持 Finding 在声明条件下真实成立 |
| `CONDITIONAL` | Finding 仍 material，但决定性事实、环境或验证条件尚未闭合；这是证据/条件缺口，不是产品选择 |
| `NEEDS-DECISION` | 关键事实已足够建立，剩余问题是产品、兼容、范围或风险取舍，需要授权决策而不是继续搜证 |
| `REJECTED` | DIRECT 反证或适用条件证明该 Finding 不成立，或已被缩窄到不再构成 material Finding |

主代理对一个 Finding 定稿前至少检查：

1. Finding 有 Supporting Evidence，也已执行并记录 disconfirmation；
2. Impact / Likelihood / Reachability / Recoverability 已填写；
3. 适用变更归因的场景已填写 Provenance，并有 DIRECT Evidence 支撑；
4. Severity 按 §2 映射并与 Confidence 分离；
5. 非 `REJECTED` Finding 已填写 Confidence，且与当前最高质量、冲突和反证 Evidence 相称；
6. 暂定 Severity 为 Critical/High 的 Finding 在最终 Decision 前已尝试第二种异质 archetype 的挑战或等价直接反证；只有挑战完成且 Evidence 足够时才可 `CONFIRMED`。无法完成或仍有决定性事实/环境缺口时，Finding 使用 `CONDITIONAL`；若事实已足够而剩余的是授权取舍，使用 `NEEDS-DECISION`；关键缺口足以影响阻断判断时由 gate 层映射为 `INCOMPLETE`。
