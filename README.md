# cross-validated-project-audit

通用项目审计 Skill：先把请求归一为简单任务契约，再建立共享事实地图与风险地图，按“Risk → verification method → executor”选择异质调查路径，并严格用 `Hypothesis → Evidence → Finding → Decision` 分层，由主代理统一裁决。支持全项目、某次变更、PR、指定作者提交、安全审计与修复验证；可输出发布/合并门禁或其它指定审计交付物。

## 任务入口

用户不必学习内部状态机，只需要自然语言说明目标。Skill 会先归一为：

```text
Audit target
Audit scope
Audit objectives
Risk tolerance
Available evidence
Deliverable
```

内部再派生：

- `scopeMode`：`project` / `change` / `pr` / `author-commits`
- `objectiveProfile`：`general`，可叠加 `security` / `fix-verification`
- `executionMode`：`audit-only` / `audit-and-fix`
- `gateTargets`：`CHANGE` / `RELEASE` / `SYSTEM` / `NONE`，可同时请求多个真实 Gate
- `independentValidationRequiredFor`：仅记录用户、组织策略或某个 Gate 明确强制的独立验证完成条件；机械约束其作用域内所有最高风险 `Claim ID`，默认多执行者分配不要求用户重复声明
- 状态保存位置与文件颗粒度由实现根据本地环境自动选择，不改变审计语义；持久化能力由实际 `stateRoot/stateDir` 决定

安全审计和修复验证是目标画像，不与 PR/项目/作者范围互斥。例如“审这个 PR 的安全修复是否有效”可表示为 `scopeMode=pr` + `objectiveProfile=security,fix-verification`。`gateTargets` 则回答“站在哪个决策问题上放行”：目标变更能否合并用 `CHANGE`，当前候选能否发布用 `RELEASE`，当前系统是否满足健康/安全目标用 `SYSTEM`；不要求放行判断时为 `NONE`。同一审计中的多个 Gate 必须共享同一个权威 Audit target 和状态快照；release candidate 与另一套已部署系统等不同状态拆成独立审计。

## 快速示例

| 你可以这样说 | 典型内部解释 | 默认关注点 |
|---|---|---|
| “全面审计这个项目” | `scopeMode=project` | 主要子系统风险覆盖、关键不变量、残留风险 |
| “审这个 PR，告诉我能不能合并” | `scopeMode=pr` + `gateTargets=CHANGE` | change-attributable 风险、回归、交付完整性 |
| “审这个分支/commit/工作区” | `scopeMode=change` | 目标变更、受影响上下文、真实当前树状态 |
| “审某个作者在指定范围内的提交” | `scopeMode=author-commits` | 作者身份、不可变提交范围、历史与当前状态 |
| “做安全审计” | 当前范围 + `objectiveProfile=security` | 信任边界、可达性、状态/边界条件、攻击路径 |
| “这个 release candidate 能不能发布？” | 当前范围 + `gateTargets=RELEASE` | 当前候选仍存在的 release-relevant 风险，不因 `PRE_EXISTING` 自动忽略 |
| “当前系统整体是否达到安全/健康要求？” | 当前范围 + `gateTargets=SYSTEM` | 当前系统状态与审计目标，而不是风险由哪次变更引入 |
| “确认这个修复是否真的解决问题” | 当前范围 + `objectiveProfile=fix-verification` | 原 Finding 是否消失、同类实例、回归与测试判别力 |
| “审完后直接修复本地问题” | 上述任一范围 + `executionMode=audit-and-fix` | 审计完成后按 Finding 分批修复并异质复核；满足执行者隔离条件时再声称 independent validation |

## 核心机制

- **契约先于方法**：派发前固定 target、scope、objectives、risk tolerance、evidence 与 deliverable；范围按 `USER → PLATFORM → REPOSITORY → ASSUMED` 解析，只有不同合理范围会实质改变结论时才询问。
- **四层语义**：调查者产生 Hypothesis + DIRECT Evidence；主代理完成 disconfirmation 后规范化 Finding，并在 Decision 层分别定稿 Decision、Severity 与 Confidence。
- **风险先于代理**：先确定风险面与可判定不变量；coverage 用稳定 `Claim ID` 归组同一风险主张的不同验证方法，明确区分 `REQUIRED/EXPLORATORY` 与探索轮，high/highest 单元先写 Safe/Failure prediction、最小判别观察和 Evidence sufficiency criterion，并在核对后记录 `MET/NOT-MET`，再选择验证方法，最后才分配 agent。
- **共享事实，隔离判断**：`audit.md` 统一提供 target/base/head/scope；共享 DIRECT 事实可放在独立 `project-map.md`，也可内嵌到 `audit.md`；隔离 Hypothesis、Finding、Decision 和预期答案。
- **方法异质性降低相关错误**：每个最高风险 `Claim ID` 至少两个不同 archetype；有不同隔离执行者可用时，默认由不同执行者完成这些 required 路径且实际判断隔离必须成立。隔离未成立时先重跑，客观受限则披露实际执行者/隔离能力限制；只有实际满足不同执行者 + 判断隔离时才声称 independent validation。显式强制独立验证时，其作用域内所有最高风险组都必须真正完成，能力限制不能替代。两个代理重复相同方法只算冗余复核。
- **反证优先**：每个准备提升为 Finding 的 material Hypothesis 都必须记录 counter-hypothesis、预期安全行为、实际反证搜索和结果；测试用于 material 结论时另记录 `YES/PARTIAL/NO/UNKNOWN` 判别力，而不是用“tests green”代替。
- **Severity ≠ Confidence**：风险维度先映射 Severity，Confidence 另行表示“有多确定”；单条 Evidence 另用 Strength + Reproducibility 描述质量。
- **冲突靠判别，不靠投票**：material 支持/反证 Evidence 冲突时，定位最小分歧前提并寻找能区分双方的 DIRECT Evidence；无法取得时保留不确定性。
- **变更风险 ≠ 现存风险**：需要变更归因时记录 `INTRODUCED / EXPOSED / REGRESSED / PRE_EXISTING / UNKNOWN` Provenance；归因不适用写 `—`，不把审查中发现的旧 bug 误报成本次变更引入。`gateTargets` 再区分“CHANGE 能否合并”和“RELEASE/SYSTEM 当前是否可放行”；Finding 为每个请求 Gate 保存 `APPLIES / DOES-NOT-APPLY / UNRESOLVED` applicability，target-specific 风险接受另存为 Gate treatment，不与事实适用性混用。
- **报告面向决策**：默认先输出 Executive report（Gate(s) / Top risks / Required actions / Residual uncertainty），再给可追溯 Audit appendix。
- **执行能力与状态保存分离**：能否声称 independent validation 只看实际 executor 与 `Judgment isolation`，不靠全局模式字段；shared facts 与 coverage 分别固定一个权威位置，不允许独立文件与内嵌状态双源并存。`audit.md` 用最小 YAML front matter 保存核心机器可读元数据。Git 仓库中只有 `.audits/` 已被忽略或用户明确授权 repository-local metadata 时才写仓库内状态；否则优先外部 state root，仍不可持久化时保持同构 session-only 状态。
- **显式停止条件**：required coverage、material Hypothesis、Finding Decision 和 residual risks 闭环后停止；连续两轮无 material delta 时不再无依据扩张。用户自定义预算/最大轮数/资源上限持久化为 `stopCriteria`，恢复后不靠聊天记忆。关键 Evidence 客观不可得时可用 `INCOMPLETE` 完成；流程已收口不等于可以输出 clean conclusion，仍按最终 Decision、Sufficiency 与 material gaps 选择措辞。

## 输出与 Gate

默认报告先给决策，再给追溯：**Executive report → Audit appendix**。Executive report 优先回答每个请求 gate target 的“能否合并/发布/是否达标”、最大风险、必须做什么、还有什么没验证；完整 H/E/F/Decision、coverage、probes 与 commit matrix 只在附录或追溯模式展开。例如同一审计可以同时得到 `Change Gate: READY-WITH-CONDITIONS` 与 `Release Gate: BLOCKED`，不强行合成一个 Gate。

| Gate | 含义 |
|---|---|
| `READY` | 当前任务契约和 required coverage 已闭环，没有已知阻断或条件项 |
| `READY-WITH-CONDITIONS` | 没有阻断项，但仍有明确非阻断条件、Medium/Low 待处理项或残留风险 |
| `BLOCKED` | 存在对当前 `gateTarget` 相关、且当前仍适用的已确认 Critical/High 风险，尚未完成处置 |
| `INCOMPLETE` | 关键 Evidence、环境、material Hypothesis 处置或 required coverage 不足，无法可靠判断是否可放行 |

`INCOMPLETE` 不等于“审计没做完”：当关键证据客观不可得且缺口已经明确记录时，它可以是一次完整执行后的正确结论。

## 使用

- 自动触发：触发与排除范围以 `SKILL.md` frontmatter description 为准。
- 默认 `executionMode=audit-only`；只有用户要求实施本地修复时才进入 `audit-and-fix`。audit-only 不会为了保存审计状态默认修改 `.git/info/exclude` / `.gitignore`；提交、推送、PR 操作、部署及生产/外部写入仍需分别授权。
- `Risk tolerance` 只影响各 `gateTargets` 的门禁策略和明确的风险接受，不改变事实、严重度或证据等级；只针对某个 Gate 的风险接受必须落到 Finding 的 `Gate treatment=ACCEPTED` 并保存授权依据，不会自动放行其它 Gate，`gateTargets=NONE` 时不自行制造 Gate。
- 不用于快速摘要、纯风格检查或无需交叉验证的普通窄范围问答。

## 安装

- 将本目录放入本地 Agent/harness 约定的 skills 目录，目录名保持 `cross-validated-project-audit`；实际根路径按本地环境约定。
- `SKILL.md` 必须位于目录根；`references/`、`agents/`、`assets/` 随目录保留，通过相对路径按需读取。
- `agents/openai.yaml` 为可选客户端元数据，不参与本 Skill 的规范语义；`assets/icon.svg` 为技能图标。
- 实际加载、自动触发或显式调用方式由本地 Agent/harness 的 skill 机制决定；本 Skill 不依赖特定编排接口。

## 文件结构与按需加载

`SKILL.md` 是唯一调度入口；reference 不互相链式加载。每个核心概念只有一个 normative owner，其它模块只在执行边界引用/约束，不重复定义枚举。

| 文件 | 类型 | 何时读取 | 内容 |
|---|---|---|---|
| `SKILL.md` | core | 每次使用 | 任务契约、核心原则、模块加载与 §1–§7 主流程 |
| `references/audit-ledger.md` | core-state | 初始化/恢复/写 H/E/F/Decision | 四层状态、project-map、含 Claim ID 的 coverage、断点恢复与归档 |
| `references/review-dimensions.md` | core-risk | 建立风险覆盖时 | 11 核心风险面、7 archetype、证据视角与计划类风险 |
| `references/assessment-model.md` | core-decision | H→Finding / Decision 定稿时 | disconfirmation、风险维度、Provenance、Severity、Confidence、Evidence Strength |
| `references/auditor-persona.md` | conditional | 实际派发子代理前 | 调查者模板与判断隔离纪律 |
| `references/git-scoping.md` | conditional | Git/PR/commit/作者/history | 范围界定、身份/提交范围、Provenance 历史证据、交付卫生 |
| `references/behavioral-verification.md` | conditional | 运行时/公共路径主张 | 公共入口验证、8 步安全执行序、运行时 Evidence |
| `references/platform-runtime-patterns.md` | conditional | 平台/编码/语言特有语义 | Windows、Unicode、PowerShell、Rust、Node/npm、第三方差异 |
| `references/core-failure-patterns.md` | conditional | 需要 hypothesis seeds/模式搜索 | 13 条失败模式与安全反例 |
| `references/fix-verification.md` | conditional | 修复验证/实施修复 | 修复映射、批次门、异质复核、回归验证 |
| `references/reporting.md` | output | 最终输出/gate | Executive report、Audit appendix、门禁与输出一致性检查 |
| `agents/openai.yaml` | metadata | 无需读取 | 惰性元数据 |

## 有意取舍

- **入口简单，内部正交**：用户只表达六项任务契约；范围类型、安全目标、修复验证与是否允许本地修改在内部拆成正交字段，避免一个“mode”承载多种含义。
- **风险驱动调度**：风险面是覆盖主键、验证方法决定异质性，Agent 只是执行资源；共享事实减少重复劳动，independent validation 只由不同 executor + 实际 `Judgment isolation=ISOLATED` 证明。
- **原则集中，细节渐进披露**：Git 命令、状态模板、平台语义等仍放在 reference 中，不为统一格式而重复规则。
- **harness 无关**：不指名 task/hub/agent:// 等编排接口，子代理与主代理的调度由当前平台能力承担。
