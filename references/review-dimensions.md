# 风险面、验证方法与证据视角

覆盖设计的固定顺序是：**Risk → verification method → executor**。先回答“哪些风险必须被覆盖、什么 Evidence 能区分正确与错误”，再决定执行者。代理数量不是覆盖指标；共享 `state.json.sharedFacts` 中的 DIRECT 事实不会破坏判断隔离，真正必须隔离的是 Hypothesis、Evidence 的解释、Finding、Decision 和预期答案。

## 1. 核心风险面

先从任务契约、变更边界、公共入口、状态/数据边界和失败后果建立风险地图。只选择与当前工件现实相关的风险面，不要求每次机械覆盖全部项目。

| 风险面 | 核心问题 | 典型触发 |
|---|---|---|
| `correctness` | 输入→处理→输出是否满足核心不变量，错误路径是否产生错误结果 | 所有非平凡实现 |
| `state-consistency` | 状态转换、顺序、重入、取消、部分完成是否留下矛盾状态 | UI、工作流、会话、队列、缓存、长流程 |
| `persistence` | schema、事务、幂等、旧数据、迁移、缓存/文件持久化、回滚是否一致 | DB、缓存、文件格式、迁移 |
| `concurrency` | 竞态、锁序、取消、超时、重试、背压、资源生命周期是否安全 | 多线程、异步、队列、长连接 |
| `boundary-conditions` | 空值、极限值、错误输入、编码、路径、容量、部分失败等边界是否被正确处理 | 外部输入、解析、文件、批量、跨平台 |
| `security` | 信任边界、鉴权授权、注入、秘密、隐私、供应链/执行面是否可被现实利用 | 身份、网络、文件、序列化、外部输入 |
| `compatibility` | API/协议/CLI、旧调用方、版本、平台、第三方真实语义是否兼容 | 公共接口、SDK、协议、跨平台、依赖升级 |
| `regression` | 旧行为是否被破坏，测试能否区分错误实现，历史缺陷是否回归 | 所有非平凡变更、修复、重构 |
| `performance-resource` | 复杂度、内存、I/O、缓存、限流、资源上限和退化路径是否可接受 | 热路径、大数据、后台任务、高并发 |
| `observability-recovery` | 错误传播、脱敏日志、指标、告警、恢复、灾备与重试安全是否足够 | 服务、后台任务、关键流程 |
| `delivery` | commit set、构建、feature flag、依赖、打包、生成物、exports、升级/回滚、发布说明是否完整 | PR、分支、发布候选、fix commit |

CLI、UI、迁移、SDK、计划等不是额外的调度主键；它们用于决定哪些风险面被激活。例如 UI 常激活 `state-consistency` / `boundary-conditions` / `compatibility`，数据迁移常激活 `persistence` / `delivery` / `observability-recovery`。

## 2. 验证方法 archetype

方法 archetype 表示“如何从一种证据路径发现或反驳问题”。异质性来自方法和证据来源不同，而不是代理名字不同。

| Archetype | 主要动作 | 最适合证明/反驳 |
|---|---|---|
| `implementation-trace` | 从真实实现沿调用、数据、错误路径追踪到效果 | 逻辑错误、遗漏 guard、错误调用链、不可达假设 |
| `user-path-trace` | 从 CLI/API/UI/迁移/SDK 等公共入口逆推真实用户行为 | 可达性、集成错误、公开行为与内部实现脱节 |
| `state-invariant-analysis` | 明确状态机/不变量，枚举转换、重入、取消、部分失败 | 状态一致性、并发、生命周期、恢复问题 |
| `test-discrimination` | 判断测试是否会在 PRE-fix/错误实现下失败，并记录判别力；必要时隔离变异 | 伪回归保护、脆弱 mock、只测实现细节 |
| `adversarial-challenge` | 主动构造反例、攻击路径、边界输入和失败注入 | 安全、边界、错误处理、过度自信的 Hypothesis/Finding |
| `history-regression-analysis` | 检查历史实现、revert、相关 commit、旧缺陷与行为变化 | 回归、归因、兼容性、曾经修过又复发的问题 |
| `contract-spec-verification` | 对照需求、schema、协议、官方/对应版本契约和公共承诺 | 需求忠实度、API/协议、第三方/平台语义、文档主张 |

方法可产生辅助证据，但**不得静默换方法后仍把结果算作原 archetype 的验证证明**。某方法因环境不可用无法执行时，记录 coverage gap，再选择能回答同一风险主张的替代方法；替代方法必须在矩阵中显式登记。

### Test discrimination 记录

当测试被用于支撑 material Finding、回归保护或修复验收时，不能只写“tests green”。至少记录：

```text
Test: <name/path>
Discrimination: YES / PARTIAL / NO / UNKNOWN
Basis: <safe behavior 与 failure behavior 是否产生不同结果；PRE-fix/变异/等价检查是什么>
Test issue: ENCODES_FAILURE / MISSING_REGRESSION / —
```

- `YES`：重新引入目标 failure（或等价 PRE-fix 行为）会使测试失败，safe/failure 有清晰不同结果。
- `PARTIAL`：只能区分部分必要条件/实例，不能覆盖完整 Finding。
- `NO`：safe/failure 都可能通过，不能作为该主张的判别性保护。
- `UNKNOWN`：没有做 PRE-fix、变异或等价判别，不能因为测试存在/通过而升级。
- `ENCODES_FAILURE` 表示测试把错误行为写成 expected；`MISSING_REGRESSION` 表示缺少能重现该 Finding 的回归案例。二者是可选 issue，不与四值判别力混成一个枚举。
- 记录写在产生该测试 Evidence 的 investigation/verification JSON 内；`state.json` 不复制 Test discrimination。


## 3. 证据视角（辅助，不作为调度主键）

证据视角用于提醒“从哪一类承诺看问题”，可以附加到风险单元，但不决定代理数量。

| 证据视角 | 核心问题 | 适用条件 |
|---|---|---|
| `requirements` | 是否遗漏、部分实现、越界实现或违背规范 | 有 issue、规范、计划或验收标准 |
| `engineering` | 即使满足需求，运行时/状态/数据/恢复是否仍可能错误 | 所有非平凡实现 |
| `user-behavior` | 真实入口是否产生预期可见行为 | CLI、API、UI、迁移、SDK、runtime |
| `delivery` | 工件能否正确构建、打包、发布、升级和回滚 | PR、分支、发布候选、修复 commit |

一个风险单元可带一个主要视角；多个不同方法可以共享同一视角。**同一视角不代表同一方法，同一方法也不因换视角就自动变成异质验证。**

## 4. 风险驱动的覆盖选择

1. 从 Audit objectives、变更触达边界、公共入口、状态/数据边界和失败后果列出相关风险面。
2. 每个现实风险写成一个可判定 Claim，集中保存到 `state.json.claims[]`：稳定 id、义务、风险面、陈述、失败后果、优先级和有界范围。`highest` 表示判断错误可能直接改变 Gate 或造成重大损害，`high` 表示明确重要影响，`normal` 表示其它相关风险。优先级不是 Finding Severity，也不因 Gate 阈值或风险接受而降低。
3. `highest` Claim 写完整 `Safe prediction / Failure prediction / Discriminating observation / Sufficiency criterion`；`high` 只写最小判别观察和充分性标准，避免把四项计划复制到普通重要风险。标准必须与风险相称，不能因当前环境拿不到证据而降低。计划不是 Evidence；实际观察才编号成 E。
4. 每种方法写成独立 `verificationUnits[]` 记录并引用 Claim，不复制 Claim 字段。每个 highest Claim 至少两个 verified REQUIRED Unit 使用不同 archetype；主代理汇总所有 Unit 的 DIRECT Evidence 后，只在 Claim 定稿一次 `sufficiency=MET|NOT-MET`。
5. 方法异质与执行者独立分开。同一执行者的不同方法可满足异质性；只有不同 executor、不同 method 且相关 Unit 实际 `isolation=ISOLATED` 才是 independent validation。没有明确独立验证硬要求时，能力不足可用方法级验证收口并披露限制；存在硬要求时相应结论保持不完整。
6. 不同调查者可以共享 baseline、scope、术语、公共入口、changed files 等 DIRECT 事实；若共享了前一路径的 Hypothesis/Finding/Decision 或解释性结论，就不能把该 Unit 标为 ISOLATED。两个执行者用同一 archetype、同一证据路径仍只算冗余复核。
7. 所有准备提升为 Finding 的 material Hypothesis 都先完成最小 disconfirmation；暂定 Critical/High 的 Finding 在 Decision 前规划/尝试第二种异质 archetype 或等价直接反证。assessment model 决定裁决前提；本模块不为凑形式复制代理。
8. 一个执行者可以承担多个 normal Unit，一个 Claim 也可以由多个 Unit 覆盖；不要求每个风险面使用所有 archetype，选择最少但足以区分关键失败模式的方法集合。
9. 只有真实开展义务外搜索时才创建 EXPLORATORY Claim 和 `exploration` 对象。本模块只识别 material delta，不重复定义停止阈值。
10. 暂定 Critical/High Finding 的 Decision 第二挑战不另建平行状态：异质挑战必须指向真实 Unit，等价反证必须来自主 verification 新 Evidence，统一写入 `verification/F<n>.json.challenge`。Critical/High 修复效果的不同方法复核另写同文件的 `resolutionChallenge`，避免把“问题曾成立”和“当前已修复”混成一个结论；字段组合由 [audit-ledger.md](audit-ledger.md) 规范。

## 5. 常见目标的风险/方法组合

| 场景 | 优先风险面 | 常用异质方法 |
|---|---|---|
| 小型后端修复 | correctness、boundary-conditions、regression | implementation-trace + test-discrimination |
| 安全审计 | security、boundary-conditions、state-consistency | adversarial-challenge + user-path-trace / contract-spec-verification |
| 鉴权变更 | security、state-consistency、compatibility、regression | adversarial-challenge + state-invariant-analysis + user-path-trace |
| 数据迁移 | persistence、compatibility、observability-recovery、delivery | state-invariant-analysis + history-regression-analysis + user-path-trace |
| CLI / UI | state-consistency、boundary-conditions、compatibility、regression | user-path-trace + state-invariant-analysis + test-discrimination |
| 指定作者提交 | correctness、regression、delivery | implementation-trace + history-regression-analysis；作者身份/范围由 Git scope 模块解析 |
| 发布候选 | compatibility、regression、delivery、observability-recovery | user-path-trace + contract-spec-verification + history-regression-analysis |
| 修复验证 | 原 Finding 风险面 + regression | 与原主要调查方法**不同**的 archetype + test-discrimination / user-path-trace |

## 6. 计划类风险维度

计划工件仍按风险主张审查，而不是按“计划 reviewer”分工：

| 维度 | 重点检查 |
|---|---|
| 事实与复用 | 是否忽略已有 helper/模式/组件；关键 API、schema、预算和平台事实是否真实 |
| 完整性与顺序 | 依赖、迁移顺序、旧新版本共存、消费者、生成物和发布步骤是否覆盖 |
| 失败模式与回滚 | 部分完成、并发发布、重试、回滚、恢复和不可逆步骤 |
| 验收与测试 | 每项成果是否可观察、可测试；验证能否区分成功、失败与回退 |
| 安全与运维 | 权限、秘密、供应链、监控、容量、部署窗口和责任边界 |
| 外部事实 | 对库、协议、平台和历史先例读取原始来源，不用二手摘要替代 |
| 用户取舍 | 范围、优先级、产品语义和多个合理方案的成本/风险差异 |

主代理把计划类 material Hypothesis 提升为 Finding 前，先区分 **FACT** 与 **JUDGMENT**：

- **FACT**：路径、API 签名、既有 helper、依赖版本、schema、平台限制、历史先例——读代码、配置或官方来源解决；默认只更新审计结论，不修改计划。
- **JUDGMENT**：范围、优先级、产品语义、多个合理架构的成本风险取舍——整理真实选项与具体影响，形成 Finding 后 Decision=`NEEDS-DECISION`。
- 证据不足的外部事实形成 Finding 时 Decision=`CONDITIONAL`，不得包装成用户偏好问题。

计划只有满足全部条件才可判为就绪：关键需求有任务承载、依赖顺序真实、失败/回滚得到处理、验收可判定、不存在会让实现者做错或无法继续的问题。阻断项不因审查轮数达标而自动降级。
