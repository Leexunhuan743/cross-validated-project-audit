# cross-validated-project-audit

面向高风险项目、变更、PR、安全问题和修复结果的多代理交叉审计 Skill。它先固定范围和决策问题，再按 `Risk → verification method → executor` 选择异质路径，由调查者产生 Hypothesis 与 DIRECT Evidence，由主代理统一形成 Finding 和 Decision。

适用于用户明确要求交叉验证、发布/合并门禁、安全审计、作者提交审计或严格修复验证；不用于普通代码评审、快速摘要、纯风格检查和无需多路径验证的窄问答。

## 用户需要提供什么

自然语言说明目标即可。Skill 会归一：

```text
Audit target
Audit scope
Audit objectives
Decision constraints (Gate blocking threshold / explicit risk acceptance, if any)
Available evidence
Deliverable
```

常见入口：

| 请求 | 典型解释 |
|---|---|
| “全面审计这个项目” | project 范围的仓库级风险覆盖；不自动承诺逐文件穷尽 |
| “严格审这个 PR，告诉我能不能合并” | pr + CHANGE Gate |
| “做这个范围的安全审计” | 当前 scope + security profile |
| “审某作者在指定范围的提交” | author-commits + 不可变 Git 范围 |
| “这个候选能不能发布” | RELEASE Gate |
| “确认这个修复是否真的生效” | fix-verification profile |
| “审完后修复本地问题” | audit-and-fix；不自动授权 commit/push/deploy |

## 核心保证

- **契约先于方法**：先固定 target、scope、objectives、证据和交付物；范围有多种合理解释且会改变结论时才询问。
- **语义分层**：Hypothesis 是可证伪怀疑，Evidence 是直接观察，Finding 是主代理规范化的问题对象，Decision 是最终裁决。**推理永远不是 Evidence。**
- **风险先于代理**：风险主张写一次；每种验证方法成为独立 Unit，最后才选择执行者。代理数量不是覆盖指标。
- **反证优先**：material Hypothesis 提升前必须检查最强现实安全解释和实际反证；被反驳就关闭，不靠降低 Severity 来消除风险。
- **异质不等于独立**：同一执行者的不同方法可以异质，但只有不同执行者、不同方法且判断隔离真实成立时才声称 independent validation。
- **公共路径优先**：用户可见、平台、并发和第三方语义优先从真实入口或对应版本权威契约获取 Evidence，内部看起来正确不算数。
- **Severity ≠ Confidence ≠ Evidence Strength**：影响大小、整体确定度、单条证据质量分别表达，不许互相折算。
- **冲突靠判别，不靠投票**：支持与反证冲突时寻找能区分双方的直接观察，不按证据条数或代理数量取胜。
- **条件概念按需出现**：没有 Gate 就不创建 Gate；不做变更归因就不写 Provenance；Disposition 只在真实进入整改、验证消除，或无 Gate 时明确接受整个 Finding 后物化；没有探索轮就不维护探索计数。**把可选字段照着完整 schema 填满，不会让审计更严谨，只会多一批没有信息的字段**——`references/audit-ledger.md` §3.1.1 给了一份实测通过的最小 `state.json`，照抄起步即可。
- **合法结束不等于 clean conclusion**：关键证据不可得时，受限报告或 INCOMPLETE 是正确结果。
- **状态改变不覆盖历史**：权威 target/snapshot/scope/shared facts 发生契约外实质变化时，旧实例冻结为 SUPERSEDED，新实例从 ACTIVE 重新取证，不把旧裁决复制为当前结论。事先约定的 audit-and-fix PRE→POST 转换是同一任务契约的执行，不是外部换目标。
- **穷尽要求可证明**：用户明确要求逐文件/逐行时，非空 scope inventory、完成项、排除项和最终 snapshot 写入 `scopeCoverage`；未闭合成员在没有已确认 blocker 时使相关 Gate 为 INCOMPLETE，已有 blocker 时保持 BLOCKED 并同时披露缺口。
- **未提交修复有身份**：Git 工作树没有授权 commit 时，用 PRE/POST HEAD 加确定性内容 manifest 形成 `git-worktree` snapshot，不创建越权 commit，也不把未提交内容冒充 Git object。

## 协议 v2 状态

`state.json` 是唯一实时权威状态；旧式 `audit.md + coverage.md + ledger.md` 多源模型已取消。

```text
<stateRoot>/<auditId>/state.json
<stateRoot>/<auditId>/investigations/<unit>-<executor>.json
<stateRoot>/<auditId>/verification/F<n>.json
<stateRoot>/<auditId>/report.md                         # 可选派生输出
<stateRoot>/<auditId>/fix-map.md                        # 可选；由 fixWorkflow 派生
<stateRoot>/<auditId>/probes/                           # 临时；收口清理
<stateRoot>/archive/<auditId>/                          # 已归档实例
```

`state.json` 将两个容易混淆的层次拆开：

- `claims[]`：风险主张、范围、失败后果、优先级和义务，只写一次；
- `verificationUnits[]`：方法、执行者、状态和 H 的归约结果，可一 Claim 多 Unit；Evidence 是否足以支持结论由主代理在 Claim 聚合一次。

Finding、Decision、Residual risk、实际 Gate 和 audit-and-fix 批次 DAG 都只在 state 中保存。Investigation/verification JSON 保存可追溯 Evidence，但不作为第二份 live Decision；其 `auditBinding` 必须匹配当前 auditId 与 snapshot，不能把旧实例 Evidence 复制成当前证据。`fix-map.md` 仅是从 `state.json.fixWorkflow` 生成的人类可读视图，不参与恢复裁决。

**初始化时可直接照抄 `references/audit-ledger.md` §3.1.1 的最小模板**——它只含真正必填的字段（已用 validator 实测通过），并附一张"什么情况下才需要加字段"的对照表。

## Validator

Skill 自带标准库 validator，无第三方依赖，需 Python 3.9+（仅用标准库，`from __future__ import annotations` 与标准 typing，无版本专属语法；已在 3.13 验证）：

```text
python -B scripts/validate_audit_state.py <state-directory>
python -B scripts/validate_audit_state.py --state-root <state-root>
python -B scripts/validate_audit_state.py --self-test scripts/fixtures
python -B -m unittest -v scripts/test_validate_audit_state.py
```

它检查：

- JSON/UTF-8、枚举、含未提交 Git 工作树的 snapshot 变体、id 与跨文件引用；
- Claim / Verification Unit 关系；
- H/E/F/Decision 归约、Evidence 的 audit/snapshot 绑定、Finding-verification Evidence 链和 Critical/High 的 Decision/修复挑战；
- Decision / Severity / Confidence / Disposition 合法组合；
- high/highest Claim-level Sufficiency、highest 异质方法和显式 independent 要求；
- **Gate 是否强于当前状态允许的结果**（validator 会按状态重算并与声明比对）；
- Gate、Provenance、探索与 exhaustive scope coverage，以及 audit-and-fix 批次 DAG、依赖、generation、验收 Evidence 和 FINAL 状态；
- `--state-root` 下的闭合活动/归档布局、缺失 state 的半成品目录、误入 archive 的 ACTIVE 实例、重复 audit id、双向 supersession 链、多后继和环。

仓库自带 99 个回归测试覆盖上述每一项，改动 validator 后应全量跑一遍。

validator 通过只证明状态内部一致，不证明代码事实和风险判断正确。Python 或持久化不可用时，Agent 必须按同一不变量人工检查并披露限制。

### 可选的状态辅助脚本

写状态时最耗时的是机械劳动：同一个 `auditBinding` 要抄进每份 artifact、`reconciliations` 必须镜像 investigation 的 hypotheses、id 前缀有固定约定。这些与审计判断无关，却最容易写错。

```text
python -B scripts/audit_state_helper.py init <dir> --audit-id X --target T --scope S --objective O
python -B scripts/audit_state_helper.py bind <dir>            # 把 auditBinding 传播到所有被引用的 artifact
python -B scripts/audit_state_helper.py bind <dir> --check    # 只报告不修改
python -B scripts/audit_state_helper.py lint <dir>            # 机械一致性检查（只读）
```

它**只做机械操作**：不推断 Severity、Decision、Sufficiency 或 Gate 结果，也不替代 validator——合法性仍由 validator 裁决。没有 Python 时手工照 §3.1.1 模板写即可，协议不依赖它。

## 成本与边界

这是高成本协议：最高风险 Claim 至少需两种异质方法，Critical/High Finding 还需第二挑战和主代理直接复核；显式 independent validation 要求通常还会增加隔离执行者、运行时间和 token 消耗。因此只在“错误放行的代价明显高于多路验证成本”时使用。

它不保证找到所有 bug，不会因为多个代理同意就认定事实，也不用状态 validator 替代真实源码、运行时和对应版本契约验证。普通窄 review 应直接审查，不必启动本协议。

## Gate

只有用户要求决策时才创建 CHANGE / RELEASE / SYSTEM Gate；多个 Gate 共享同一 target/snapshot 并分别计算。默认阻断未处置的 Critical/High，用户可按 target 把阈值收紧到 Medium 或 Low；其它完成条件应转成 REQUIRED Claim。结果：

| Gate | 含义 |
|---|---|
| `READY` | required 输入闭环，没有阻断、未决或条件项 |
| `READY-WITH-CONDITIONS` | 没有阻断，但有明确非阻断条件或残留风险 |
| `BLOCKED` | 存在当前适用、已确认、达到该 target 阻断阈值且未处置的风险 |
| `INCOMPLETE` | 关键 Evidence、required 验证、Sufficiency、异质/强制独立验证或适用性不足 |

四值结果的完整推导算法见 `references/reporting.md` §4。validator 会按状态重算并与声明比对，不接受比状态更强的结论。

已知 BLOCKED 优先于其它完整性缺口：即使审计还有未覆盖范围，确认的阻断风险已经足以拒绝放行；报告仍必须同时披露未完成部分。风险接受只排除获得明确授权的已知 Finding，不填补 Evidence 或 coverage 缺口。授权必须结构化绑定当前 auditId 与完整 snapshot；有 Gate 时还必须绑定具体 target，无 Gate 时才可使用全局 `ACCEPTED-RISK`。

## 使用与安装

- 将整个目录放入本地 Agent/harness 约定的 skills 目录，目录名保持 `cross-validated-project-audit`；必须同时保留根目录 `SKILL.md`、`references/`、`scripts/`、`agents/` 和 `assets/`。
- 自动触发与排除范围以 `SKILL.md` frontmatter description 为准；显式调用方式由客户端决定。本 Skill 不依赖某一种编排接口。
- 默认 `executionMode=audit-only`。只有用户明确要求实施本地修复时才进入 `audit-and-fix`；这仍不授权 commit、push、PR、部署或生产/外部写入。audit-only 不修改被审计的产品工件、Git metadata 或外部系统；协议产物只能写入平台/用户指定的独立安全 state root，或审计开始前已被忽略的仓库内 `.audits/` sidecar。
- audit-only 不为保存状态自动修改 `.gitignore` 或 `.git/info/exclude`；仓库内 sidecar 不属于产品工件、不得混入产品路径或交付。没有安全持久化位置时，使用同构 session-only 状态并披露无法机械校验和跨会话恢复；不会向目标目录落盘。
- 没有请求合并、发布或系统就绪判断时不创建 Gate；普通摘要、纯风格检查和无需交叉验证的窄问答不应启动本协议。

## 文件与按需加载

**先判档位，再加载**（判据见 `SKILL.md` §1 末尾）：

- **标准档（默认）**：审 PR、变更、普通项目，且用户没有要求实施修复、没有要求穷尽、没有强制独立验证。
- **完整档**：`executionMode=audit-and-fix`、`objectiveProfiles` 含 `fix-verification`、`audit.stop.policy=exhaustive`，或存在 `independentValidationRequiredFor` 时。

| 文件 | 何时读取 | 档位 |
|---|---|---|
| `SKILL.md` | 每次使用：任务契约、权限、调度、主流程和收口 | 必读 |
| `references/audit-ledger.md` | 初始化、恢复、更新 v2 状态（标准档可跳过 §3.7） | 标准 |
| `references/review-dimensions.md` | 建立风险地图、选择验证方法 | 标准 |
| `references/assessment-model.md` | material H 提升、Finding/Decision 定稿 | 标准 |
| `references/auditor-persona.md` | 实际派发子代理 | 标准 |
| `references/reporting.md` | 最终报告；有 Gate 时还有 Gate 推导 | 标准 |
| `references/git-scoping.md` | Git/PR/commit/作者范围、历史或 Provenance | 按需 |
| `references/behavioral-verification.md` | runtime/公共路径/平台/并发/第三方行为 | 按需 |
| `references/platform-runtime-patterns.md` | 平台、编码、语言版本特有语义 | 按需 |
| `references/core-failure-patterns.md` | 风险地图有盲区或需要 Hypothesis seeds | 按需 |
| `references/fix-verification.md` | 实施修复或严格修复验证 | 完整档 |
| `scripts/validate_audit_state.py` | 可选校验器，Python 3.9+ | 可选 |
| `scripts/audit_state_helper.py` | 可选机械辅助：init / bind / lint | 可选 |

`agents/openai.yaml` 是客户端元数据，`assets/icon.svg` 是图标。当前仓库只维护中文协议 v2，不再附带独立英文变体。

## 设计取舍

- 保留 H/E/F/Decision、disconfirmation、Sufficiency、异质/独立验证和 INCOMPLETE，因为它们阻止真实的过度结论。
- 删除 19 列 coverage 和多份 live ledger；用 Claim registry + Verification Units + validator 降低状态漂移。
- 保留一个语义模型，不另建“简化模式”；普通审计只是省略未触发的高级字段。
- **按档位加载模块，而不是按档位改规则**：标准档不读 `fix-verification.md`、不物化 `fixWorkflow` / `scopeCoverage` / `exploration` / `independentValidationRequiredFor`。档位只决定加载范围，任何档位下已物化的对象都遵守同一套校验，validator 也不区分档位。
- **用最小模板代替精简协议**：可选字段本身不是负担，前提是没人逼你填满它。§3.1.1 的模板让"少写"成为默认路径，而不是要求每个人记住哪些字段能省。
- 自动发现仍由客户端决定，但 frontmatter 已收窄到高风险或明确交叉验证请求，避免普通 review 被重型协议误触发。
