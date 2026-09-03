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
- **条件概念按需出现**：没有 Gate 就不创建 Gate；不做变更归因就不写 Provenance；Disposition 只在真实进入整改、验证消除，或无 Gate 时明确接受整个 Finding 后物化；没有探索轮就不维护探索计数；先验接触（`priorContact`）、失败派发登记（`dispatches[]`）与超范围外溢（`peripheralObservations`）同样只在触发时物化。可选字段仅在触发时物化，未触发保持缺省；可参考 `scripts/fixtures/valid-ordinary-no-gate/state.json` 起步。
- **先验接触必须显式化**：主代理是被审变更的实现者或此前的非正式验证者时，契约写 `priorContact` 并新建一个 REQUIRED 变更面扫描 Claim（`scopeMode=project` 无 diff 可扫，改为披露并建议独立第二审计者）。
- **阴性结论也要复核**：verified 有最低复核深度（重导决定性证据链或复跑探针，FINAL 前抽样），漏网缺陷可以藏在一个标签同为 verified 的干净单元里。
- **合法结束不等于 clean conclusion**：关键证据不可得时，受限报告或 INCOMPLETE 是正确结果。
- **状态改变不覆盖历史**：权威 target/snapshot/scope/shared facts 发生契约外实质变化时，旧实例冻结为 SUPERSEDED，新实例从 ACTIVE 重新取证，不把旧裁决复制为当前结论。事先约定的 audit-and-fix PRE→POST 转换是同一任务契约的执行，不是外部换目标。
- **穷尽要求可证明**：用户明确要求逐文件/逐行时，非空 scope inventory、完成项、排除项和最终 snapshot 写入 `scopeCoverage`；未闭合成员在没有已确认 blocker 时导致相关 Gate 推导为 INCOMPLETE，已有 blocker 时保持 BLOCKED 并同时披露缺口。
- **未提交修复有身份**：Git 工作树没有授权 commit 时，用 PRE/POST HEAD 加确定性内容 manifest 形成 `git-worktree` snapshot，不创建越权 commit，也不把未提交内容冒充 Git object。

## 协议状态

`state.json` 是唯一实时权威状态（`"schemaVersion": 3`，定义详见 `SKILL.md §5`）。

```text
<stateRoot>/<auditId>/state.json                        # 唯一全局权威状态
<stateRoot>/<auditId>/investigations/<unit>-<executor>.json  # 调查者证据工件
<stateRoot>/<auditId>/verification/F<n>.json            # 主代理复核与挑战工件
<stateRoot>/<auditId>/report.md                         # 可选派生输出
<stateRoot>/<auditId>/fix-map.md                        # 可选（由 fixWorkflow 派生）
<stateRoot>/<auditId>/probes/<unit>-<executor>/         # 复核附件：被证据引用的判别性探针；噪音清理
<stateRoot>/<auditId>/scratch/<unit>-<executor>/        # 隔离实验区；用完即清
<stateRoot>/archive/<auditId>/                          # 已归档实例
```

**写入分工**：被审计目标树对调查者严格只读；`.audits/<auditId>/` 是审计工作区，按 unit + executor 分片管理：
- 结论工件写入 `investigations/<R_ID>-<EXECUTOR>.json`（唯一结论文件）；
- 判别性探针、复现脚本存放在 `probes/<R_ID>-<EXECUTOR>/`，主代理复核后：被 Evidence 引用的探针保留为复核附件、一次性噪音清理；
- 实验产物（装依赖、改状态、跑构建）存放在 `scratch/<R_ID>-<EXECUTOR>/`，用完即清，`FINAL` 前清空；
- `state.json` 与 `verification/` 只由主代理写入；
- 隔离靠路径唯一分片、互不查阅他人文件、临时产物及时清空以及主代理接收时核对范围保证。

初始化建议使用 `scripts/audit_init.py` 命令行脚手架直接生成合规骨架（省去手写嵌套结构与快照不一致的风险），亦可参考 `scripts/fixtures/valid-ordinary-no-gate/state.json`。

## Validator

Skill 自带标准库 validator，无第三方依赖，需 Python 3.9+（仅用标准库，`from __future__ import annotations` 与标准 typing，无版本专属语法）：

```text
python -B scripts/validate_audit_state.py <state-directory>
python -B scripts/validate_audit_state.py --state-root <state-root>
python -B scripts/validate_audit_state.py --self-test scripts/fixtures
```

以下是机械可判子集；语义判断（Evidence 是否可信、Severity 是否合理）仍由主代理负责。

它检查十二类不变量（完整清单见 `SKILL.md` §5）：身份与引用、不变量前提字段、契约字段、快照绑定、证据图、反证、结论强度、Finding-Gate 绑定、Gate 推导、批次新鲜度、覆盖闭合与探索、风险接受绑定。`--state-root` 另外检查 supersession 图的双向链接、唯一后继与无环。

**它不做表单校验**——不检查枚举、id 格式、路径词法、目录布局、未建模字段。字段形状以 fixture 为准。代价是缺字段会静默跳过依赖它的检查，因此不变量 0、1 与 1b 专门守会让检查静默失效的情况：不变量 0 管身份与引用（重复 id 会静默覆盖、悬空引用会静默解析为空），不变量 1/1b 管驱动不变量判定的前提字段缺失及驱动枚举闭合，一律报错。

`--self-test` 跑 38 个 fixture（8 个正例 + 30 个反例）。改动 validator 后应跑一遍。

validator 通过只证明状态内部一致，不证明代码事实和风险判断正确。

辅助脚手架是 `scripts/audit_init.py`（零第三方依赖，Python 3.9+）：它提供三大骨架生成命令，解决"凭空手写多层嵌套 JSON 容易手滑与快照漂移"的痛点。它自动绑定当前不可变 snapshot，生成带 TODO 的合法骨架；它不接管流程、不生成 Claim、不做事实判断：

```text
# 1. 开局：生成 state.json 骨架并建好工作区
python -B scripts/audit_init.py init --audit-id <ID> --target "<TARGET>" --scope "<SCOPE>" \
    --scope-mode <project|change|pr|author-commits> \
    [--gate RELEASE] [--block-at Medium] [--snapshot-kind git --snapshot-head <SHA>]

# 2. 派发：为调查者生成 investigation 骨架及配套 probes/scratch 目录
python -B scripts/audit_init.py investigation --audit-id <ID> --unit R1 --claim Q1 \
    --method <ARCHETYPE> --executor <EXECUTOR> [--clean]

# 3. 复核：为主代理生成 verification 骨架及第二挑战结构
python -B scripts/audit_init.py verification --audit-id <ID> --finding F1 \
    --method <ARCHETYPE> --checked-evidence R1-E1
```

字段形状与真实填空仍可对照 `scripts/fixtures/` 示例；骨架生成后由代理填入实际代码行、观察事实与反证。

## 成本与边界

这是高成本协议：最高风险 Claim 至少需两种异质方法，Critical/High Finding 还需第二挑战和主代理直接复核；显式 independent validation 要求通常还会增加隔离执行者、运行时间和 token 消耗。因此只在“错误放行的代价明显高于多路验证成本”时使用。

它不保证找到所有 bug，不会因为多个代理同意就认定事实，也不用状态 validator 替代真实源码、运行时和对应版本契约验证。普通窄 review 应直接审查，不必启动本协议。

## Gate

只有用户明确要求决策时才创建 CHANGE / RELEASE / SYSTEM Gate（推导规则见 `SKILL.md §7`）；多个 Gate 共享同一 target/snapshot 并分别计算。默认阻断未处置的 Critical/High，用户可针对各 target 把阈值收紧到 Medium 或 Low；其他完成条件应转成 REQUIRED Claim。

| Gate | 含义 |
|---|---|
| `READY` | required 输入闭环，没有阻断、未决或条件项 |
| `READY-WITH-CONDITIONS` | 没有阻断，但有明确非阻断条件或残留风险 |
| `BLOCKED` | 存在当前适用、已确认、达到该 target 阻断阈值且未处置的风险 |
| `INCOMPLETE` | 关键 Evidence、required 验证、Sufficiency、异质/强制独立验证或适用性不足 |

四值结果由 validator 机械重算比对，已知 BLOCKED 优先于其它完整性缺口（确认阻断已足以拒绝放行，但报告仍披露未完成部分）。风险接受只排除明确授权的已知 Finding，不填补证据或覆盖缺口。

## 使用与安装

- 将整个目录放入本地 Agent/harness 约定的 skills 目录，目录名保持 `cross-validated-project-audit`；必须同时保留根目录 `SKILL.md`、`references/` 和 `scripts/`。
- 自动触发与排除范围以 `SKILL.md` frontmatter description 为准；显式调用方式由客户端决定。本 Skill 不依赖某一种编排接口。
- `agents/` 与 `assets/` 只服务 OpenAI 系产品（ChatGPT / Codex / API / Atlas）：`agents/openai.yaml` 是它的客户端元数据，`assets/icon.svg` 是它的图标。其它 harness 可整个忽略这两个目录，协议本身不需要它们。
- 默认 `executionMode=audit-only`。只有用户明确要求实施本地修复时才进入 `audit-and-fix`；这仍不授权 commit、push、PR、部署或生产/外部写入。audit-only 不修改被审计的产品工件、被跟踪的 Git 记录或外部系统；审计状态固定写入被审计仓库根目录下的 `.audits/<auditId>/`，不另选位置。
- audit-only 首次运行可将 `.audits/` 追加至 `.git/info/exclude`（仅本地生效，不修改共享的 `.gitignore`，不触碰任何 tracked 文件）；仓库非 Git 或不可写时照常写入并在报告中披露。不做会话内状态；无法写入 `.audits/` 时停止并说明原因，不退回会话内记录。
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
| `scripts/audit_init.py` | 脚手架工具：一键生成 state/investigation/verification 合法骨架，Python 3.9+ |
| `scripts/validate_audit_state.py` | 可选校验器，Python 3.9+ |

§4 是参考手册、§6 是结论标准，两者都不属于主流程——建风险地图时按需查 §4，定稿判断时按需查 §6，有把握可跳过。必读部分（§1–§3、§5、§7–§8）约 410 行，另有前言 11 行。

## 设计取舍

- 保留 H/E/F/Decision、disconfirmation、Sufficiency、异质/独立验证和 INCOMPLETE，因为它们阻止真实的过度结论。
- 删除 19 列 coverage 和多份 live ledger；用 Claim registry + Verification Units + validator 降低状态漂移。
- 只维护一个语义模型，不另建“简化模式”；普通审计只是省略未触发的高级字段。
- **用最小模板代替精简协议**：可选字段本身不是负担，前提是没人逼你填满它。`scripts/fixtures/valid-ordinary-no-gate/state.json` 让"少写"成为默认路径，而不是要求每个人记住哪些字段能省。
- **validator 只守不变量，不守形状**：形状由 fixture 示范。代价是漏写可能静默跳过检查，因此把"会让检查静默失效"的三种情况（重复 id、悬空引用、前提字段缺失）提升为硬错误——这是不变量检查，不是表单检查。
- 自动发现仍由客户端决定，但 frontmatter 已收窄到高风险或明确交叉验证请求，避免普通 review 被重型协议误触发。
