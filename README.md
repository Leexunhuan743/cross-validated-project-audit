# cross-validated-project-audit

面向高风险项目、变更、PR、安全问题和修复结果的多代理交叉审计 Skill。它先固定范围和决策问题，再按 `Risk → verification method → executor` 选择异质路径，由调查者产生 Hypothesis 与 DIRECT Evidence，由主代理统一形成 Finding 和 Decision。

适用于用户明确要求交叉验证、发布/合并门禁、严格修复验证，或经确认的高风险多路安全/作者审计；不用于普通代码评审、快速摘要、纯风格检查和无需多路径验证的窄问答。

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
- **异质不等于独立**：同一执行者的不同方法可以异质，但 independent validation 还须叠加异质覆盖与不同执行者等前置条件。
- **公共路径优先**：用户可见、平台、并发和第三方语义优先从真实入口或对应版本权威契约获取 Evidence，内部看起来正确不算数。
- **Severity ≠ Confidence ≠ Evidence Strength**：影响大小、整体确定度、单条证据质量分别表达，不许互相折算。
- **冲突靠判别，不靠投票**：支持与反证冲突时寻找能区分双方的直接观察，不按证据条数或代理数量取胜。
- **条件概念按需出现**：没有 Gate 就不创建 Gate；不做变更归因就不写 Provenance；Disposition 只在真实进入整改、验证消除，或无 Gate 时明确接受整个 Finding 后物化；没有探索轮就不维护探索计数；先验接触（`priorContact`）、失败派发登记（`dispatches[]`）与超范围外溢（`peripheralObservations`）同样只在触发时物化。**把可选字段照着完整 schema 填满，不会让审计更严谨，只会多一批没有信息的字段**——照 `scripts/fixtures/valid-ordinary-no-gate/state.json` 抄起步即可。
- **先验接触必须显式化**：主代理是被审变更的实现者或此前的非正式验证者时，契约写 `priorContact` 并新建一个 REQUIRED 变更面扫描 Claim（`scopeMode=project` 无 diff 可扫，改为披露并建议独立第二审计者）——契约作者的先验决定他会问什么问题，盲区不能只靠自觉。
- **阴性结论也要复核**：verified 有最低复核深度（重导决定性证据链或复跑探针，FINAL 前抽样），漏网缺陷可以藏在一个标签同为 verified 的干净单元里。
- **合法结束不等于 clean conclusion**：关键证据不可得时，受限报告或 INCOMPLETE 是正确结果。
- **状态改变不覆盖历史**：权威 target/snapshot/scope/shared facts 发生契约外实质变化时，旧实例冻结为 SUPERSEDED，新实例从 ACTIVE 重新取证，不把旧裁决复制为当前结论。事先约定的 audit-and-fix PRE→POST 转换是同一任务契约的执行，不是外部换目标。
- **穷尽要求可证明**：用户明确要求逐文件/逐行时，非空 scope inventory、完成项、排除项和最终 snapshot 写入 `scopeCoverage`；未闭合成员在没有已确认 blocker 时使相关 Gate 为 INCOMPLETE，已有 blocker 时保持 BLOCKED 并同时披露缺口。
- **未提交修复有身份**：Git 工作树没有授权 commit 时，用 PRE/POST HEAD 加确定性内容 manifest 形成 `git-worktree` snapshot，不创建越权 commit，也不把未提交内容冒充 Git object。

## 协议状态

`state.json` 是唯一实时权威状态，`"schemaVersion": 3`。旧式 `audit.md + coverage.md + ledger.md` 多源模型已取消，v2 状态不被接受——v2 与 v3 的形态差异集中在 `coverageSummary.verifiedBehaviors`（v2 为裸字符串数组，v3 为 `[{behavior, evidenceRefs[]}]` 对象数组，refs 必填且仅限本工件 evidence）。

```text
<stateRoot>/<auditId>/state.json
<stateRoot>/<auditId>/investigations/<unit>-<executor>.json
<stateRoot>/<auditId>/verification/F<n>.json
<stateRoot>/<auditId>/report.md                         # 可选派生输出
<stateRoot>/<auditId>/fix-map.md                        # 可选；由 fixWorkflow 派生
<stateRoot>/<auditId>/probes/<unit>-<executor>/         # 临时；探针、复现脚本；按 unit+executor 分片，收口清理
<stateRoot>/<auditId>/scratch/<unit>-<executor>/        # 临时；隔离环境实验；按 unit+executor 分片，收口清理
<stateRoot>/archive/<auditId>/                          # 已归档实例
```

`state.json` 将两个容易混淆的层次拆开：

- `claims[]`：风险主张、范围、失败后果、优先级和义务，只写一次；
- `verificationUnits[]`：方法、执行者、状态和 H 的归约结果，可一 Claim 多 Unit；Evidence 是否足以支持结论由主代理在 Claim 聚合一次。

Finding、Decision、Residual risk、实际 Gate 和 audit-and-fix 批次 DAG 都只在 state 中保存。Investigation/verification JSON 保存可追溯 Evidence，但不作为第二份 live Decision；其 `auditBinding` 必须匹配当前 auditId 与 snapshot，不能把旧实例 Evidence 复制成当前证据。`fix-map.md` 仅是从 `state.json.fixWorkflow` 生成的人类可读视图，不参与恢复裁决。

**写入分工**：被审计目标树对调查者严格只读；`.audits/<auditId>/` 是审计工作区，调查者可写但分三区，都按 unit + executor 分片——结论只写 `investigations/<R_ID>-<EXECUTOR>.json` 这一个文件，临时产物（探针、复现脚本、证据包）写 `probes/<R_ID>-<EXECUTOR>/`（保留待复核，主代理复核后清），隔离环境实验（装依赖、起容器、改状态、跑构建）写 `scratch/<R_ID>-<EXECUTOR>/`（用完即清），收口前两者均须为空；`state.json` 与 `verification/` 只由主代理写。给调查者可写区是必要的：判别探针三纪律要求构造最小复现和变异副本，不给写文件的地方这些要求落不了地。实验区也留在 `.audits/` 而非系统临时目录，是因为 ES3/ES4 要求"足以让别人重复的最小信息"——装了什么依赖、在什么环境跑出来正是这类信息，放到系统临时目录会随系统清理丢失。 `probes/` 与 `scratch/` 收口前必须清空——validator 不检查目录布局，残留不会让它 FAIL，只会静默跟着归档走；该留的要点应已写进 Evidence 的 `reproducibility` 与运行时档案。

这样安排是安全的：state 对文件的引用发生在主代理接收**之后**，"先落盘、后被引用"意味着写一半失败留下的孤儿文件不会被 state 消费。调查者回报的只是路径与摘要，无需把 JSON 正文重输出一遍（重输出会引入格式漂移）。隔离靠四件事保证——路径按 unit + executor 分片、不列目录或读他人文件、临时产物及时清空（scratch 用完即清、probes 复核后清）、主代理接收时核对归属并在平台提供工具调用审计时核对实际写入范围。

**初始化时可照抄 `scripts/fixtures/valid-ordinary-no-gate/state.json`**——它只含真正必填的字段（已用 validator 实测通过）；也可用 `scripts/audit_init.py init` 直接生成同样的合法空骨架，省去手写嵌套结构。

## Validator

Skill 自带标准库 validator，无第三方依赖，需 Python 3.9+（仅用标准库，`from __future__ import annotations` 与标准 typing，无版本专属语法）：

```text
python -B scripts/validate_audit_state.py <state-directory>
python -B scripts/validate_audit_state.py --state-root <state-root>
python -B scripts/validate_audit_state.py --self-test scripts/fixtures
```

以下是机械可判子集；语义判断（Evidence 是否可信、Severity 是否合理）仍由主代理负责。

它检查十二类不变量（完整清单见 `SKILL.md` §5）：身份与引用、不变量前提字段、契约字段、快照绑定、证据图、反证、结论强度、Finding-Gate 绑定、Gate 推导、批次新鲜度、覆盖闭合与探索、风险接受绑定。`--state-root` 另外检查 supersession 图的双向链接、唯一后继与无环。

**它不做表单校验**——不检查枚举、id 格式、路径词法、目录布局、未建模字段。字段形状以 fixture 为准。代价是缺字段会静默跳过依赖它的检查，因此不变量 0 和 1 专门守会让检查静默失效的情况：不变量 0 管身份与引用（重复 id 会静默覆盖、悬空引用会静默解析为空），不变量 1 管驱动不变量判定的前提字段缺失，合计三类触发条件，一律报错。

`--self-test` 跑 34 个 fixture（7 个正例 + 27 个反例）。改动 validator 后应跑一遍。

validator 通过只证明状态内部一致，不证明代码事实和风险判断正确。Python 或持久化不可用时，Agent 必须按同一不变量人工检查并披露限制。

唯一的辅助脚本是 `scripts/audit_init.py`（190 行，零依赖）：它只生成一个 `phase=ACTIVE`、claims/findings 全空的合法 `state.json` 骨架，再立即调用 validator 验一遍——解决的是"第一次要凭空手写近百行嵌套 JSON"这个真实手滑源。它不接管流程、不生成 Claim、不做判断。

```text
python -B scripts/audit_init.py init --audit-id <ID> --target "<TARGET>" --scope "<SCOPE>" \
    --scope-mode <project|change|pr|author-commits> \
    [--gate RELEASE] [--block-at Medium] [--snapshot-kind git --snapshot-head <SHA>]

# --scope-mode 默认 change：全项目审计必须显式传 project，否则静默建错范围粒度
```

除此之外没有状态辅助脚本：把 `auditBinding` 抄进每份 artifact、`reconciliations` 镜像 investigation 的 hypotheses 这类重复手写，改由 fixture 示范形状、照抄起步。

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

四值结果由 validator 按状态重算并与声明比对，不接受比状态更强的结论。

已知 BLOCKED 优先于其它完整性缺口：即使审计还有未覆盖范围，确认的阻断风险已经足以拒绝放行；报告仍必须同时披露未完成部分。风险接受只排除获得明确授权的已知 Finding，不填补 Evidence 或 coverage 缺口。授权必须结构化绑定当前 auditId 与完整 snapshot；有 Gate 时还必须绑定具体 target，无 Gate 时才可使用全局 `ACCEPTED-RISK`。

## 使用与安装

- 将整个目录放入本地 Agent/harness 约定的 skills 目录，目录名保持 `cross-validated-project-audit`；必须同时保留根目录 `SKILL.md`、`references/` 和 `scripts/`。
- 自动触发与排除范围以 `SKILL.md` frontmatter description 为准；显式调用方式由客户端决定。本 Skill 不依赖某一种编排接口。
- `agents/` 与 `assets/` 只服务 OpenAI 系产品（ChatGPT / Codex / API / Atlas）：`agents/openai.yaml` 是它的客户端元数据，`assets/icon.svg` 是它的图标。其它 harness 可整个忽略这两个目录，协议本身不需要它们。
- 默认 `executionMode=audit-only`。只有用户明确要求实施本地修复时才进入 `audit-and-fix`；这仍不授权 commit、push、PR、部署或生产/外部写入。audit-only 不修改被审计的产品工件、Git metadata 或外部系统；审计状态固定写入被审计仓库根目录下的 `.audits/<auditId>/`，不另选位置、不建平台 state root。
- audit-only 不为保存状态自动修改 `.gitignore` 或 `.git/info/exclude`；`.audits/` 未被 git 忽略时照常写入并在报告中披露，禁止为放审计文件去改忽略规则。不做会话内状态；无法写入 `.audits/` 时停止并说明原因，而不是退回会话内记录。
- 没有请求合并、发布或系统就绪判断时不创建 Gate；普通摘要、纯风格检查和无需交叉验证的窄问答不应启动本协议。

## 文件与按需加载

全部规则内联在 `SKILL.md`，没有第二套语义、也没有档位差异：任何情况下已物化的对象都遵守同一套校验，validator 也不区分。

| 文件 / 章节 | 何时读取 |
|---|---|
| `SKILL.md` §1–§3、§5 | **每次使用**：触发边界、六条机制、主流程、状态字段与不变量 |
| `SKILL.md` §4.1–§4.3 | 建风险地图时：风险面清单、验证方法 archetype、场景→方法组合 |
| `SKILL.md` §4.4–§4.5 | 派发调查者时：派发模板、返回后检查、MAP-CORRECTION |
| `SKILL.md` §4.6–§4.7 | 计划类工件 / 修复验证（按需） |
| `SKILL.md` §4.8 | 漏检代价高于过度结论风险时：自由发现单元（可选，默认不启用） |
| `SKILL.md` §6 | 定稿判断时：证据强度、运行时验证档案、Decision/Provenance 语义 |
| `SKILL.md` §7–§8 | 收口时：Gate 推导、校验 |
| `references/failure-patterns.md` | 风险地图有盲区或需要 Hypothesis seeds（按需） |
| `references/git-scoping.md` | 涉及复杂 git 范围、变基、提交历史切分（按需） |
| `references/platform-runtime-patterns.md` | 涉及跨平台（Windows/Linux/macOS）、并发/异步、I/O 模式（按需） |
| `scripts/audit_init.py` | 开局可选：生成合法空骨架，Python 3.9+ |
| `scripts/validate_audit_state.py` | 可选校验器，Python 3.9+ |

§4 是参考手册、§6 是结论标准，两者都不属于主流程——建风险地图时按需查 §4，定稿判断时按需查 §6，有把握可跳过。必读部分（§1–§3、§5、§7–§8）共 417 行，另有前言 11 行。

## 设计取舍

- 保留 H/E/F/Decision、disconfirmation、Sufficiency、异质/独立验证和 INCOMPLETE，因为它们阻止真实的过度结论。
- 删除 19 列 coverage 和多份 live ledger；用 Claim registry + Verification Units + validator 降低状态漂移。
- 只维护一个语义模型，不另建“简化模式”；普通审计只是省略未触发的高级字段。
- **用最小模板代替精简协议**：可选字段本身不是负担，前提是没人逼你填满它。`scripts/fixtures/valid-ordinary-no-gate/state.json` 让"少写"成为默认路径，而不是要求每个人记住哪些字段能省。
- **validator 只守不变量，不守形状**：形状由 fixture 示范。代价是漏写可能静默跳过检查，因此把"会让检查静默失效"的三种情况（重复 id、悬空引用、前提字段缺失）提升为硬错误——这是不变量检查，不是表单检查。
- 自动发现仍由客户端决定，但 frontmatter 已收窄到高风险或明确交叉验证请求，避免普通 review 被重型协议误触发。
