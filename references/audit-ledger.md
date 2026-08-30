# 权威审计状态、结构与恢复

本文件是协议 v2 状态结构的规范所有者。目标不是记录所有过程文字，而是让范围、风险覆盖、H/E/F/Decision 和 Gate 只有一个实时答案。

## 1. 唯一权威状态

可持久化时，每个审计实例使用独立目录：

```text
<stateRoot>/<auditId>/
├── state.json                         # 唯一实时权威状态
├── investigations/<unit>-<executor>.json # 调查者 H/E；一单元一文件
├── verification/F<n>.json             # 主代理直接复核
├── report.md                           # 可选；由 state.json 派生
├── fix-map.md                          # 可选；由 state.json.fixWorkflow 派生
└── probes/                             # 临时探针；收口时清理

<stateRoot>/archive/<auditId>/             # 已归档实例；可在名称后加冲突后缀
```

目录布局是闭合 allowlist：根目录只能有 `state.json`、可选的 `report.md` / `fix-map.md`，以及 `investigations/`、`verification/`、`probes/` 三个目录；`investigationFile` 只能指向 `investigations/<flat>.json`，`verificationFile` 只能指向 `verification/<flat>.json`，且前两个目录只能有被 `state.json` 引用的平铺 JSON。`probes/` 容纳批准的临时探针与主代理自己的操作留痕（一次性脚本、接收归一化的 diff 记录、执行附录的临时工件）；它们不能承载任何 state 引用的正式 artifact，且 FINAL 前必须清空。禁止同时创建旧式 `audit.md`、`project-map.md`、`coverage.md`、`ledger.md` 或独立 live Finding 表。调查和 verification 文件是证据来源；当前任务契约、Claim、Verification Unit、Finding、Decision、Disposition、Residual risk、Gate 和修复批次状态只以 `state.json` 为准。`fix-map.md` 若存在只是 `state.json.fixWorkflow` 的派生人类视图，恢复和 validator 不消费它。

安全 state root 的选择顺序：

1. 平台或用户明确指定的外部目录；
2. Git 仓库中已经被忽略且可写的 `.audits/`；
3. 非 Git 工作目录中用户工件之外的明确安全位置；
4. 没有安全写入位置时，使用会话内同构对象并披露 `session-only`、无 validator 和无跨会话恢复。

audit-only 默认不得修改 `.gitignore`、`.git/info/exclude` 或其它 Git metadata。仓库内 `.audits/` 仅在审计开始前已被忽略时才是可写的审计 metadata sidecar；它不属于被审计的产品工件、不得混入产品路径或交付。状态目录绝对路径不是任务语义，不写入 `state.json`，避免移动或归档后失效。

持久化 `<stateRoot>` 也是闭合布局：只允许 `archive/` 和实际 audit-instance 目录；`archive/` 中只允许 archived audit-instance 目录。两层都禁止散落文件、链接和未建模条目；`--state-root` 会将它们视为恢复/归档错误，而不是忽略。

`auditId` 使用仅含字母、数字、`-` 或 `_` 的文件名安全短 id，并在整个 state root 内唯一。创建前检查活动和归档目录；冲突时加短后缀，不覆盖。状态移动到 archive 不改变 id。

## 2. 四层语义

1. **Hypothesis（H）**：可证伪的怀疑，不进入最终报告。
2. **Evidence（E）**：真实读取、运行或对应版本权威契约中的 DIRECT 观察；reasoning 不是 Evidence。
3. **Finding（F）**：主代理规范化的、可单独裁决的问题对象，必须有现实影响路径、触发条件和 H/E 引用。
4. **Decision**：主代理对 Finding 是否成立的裁决。`PENDING` 是工作态；最终只使用 `CONFIRMED` / `CONDITIONAL` / `NEEDS-DECISION` / `REJECTED`。

不是每个 H 都变成 F。Investigation 的 `hypotheses[]` 只记录 material H，并必须逐项归约为：`FINDING`、`REFUTED` 或 `RESIDUAL-GAP`。若为真可能形成 Medium+ Finding、改变 Decision/Severity/Gate、揭示系统性模式或新增 highest/high 风险时，H 才是 material；其它观察写入 coverageSummary，不创建 H id。

## 3. `state.json`

### 3.1 顶层与任务契约

本节分三层：**§3.1.1** 写任何 `state.json` 都要读；**§3.1.2** 全是条件字段，不触发就整段跳过，不必预读；**§3.1.3** 给了一份可直接照抄的最小模板。

#### 3.1.1 必读：顶层结构与必填字段

最小结构：

```json
{
  "schemaVersion": 2,
  "phase": "ACTIVE",
  "audit": {
    "id": "20260822-auth-review",
    "target": "PR 123 at head <immutable-id>",
    "scope": "auth entrypoint and direct consumers; excludes unrelated UI",
    "objectives": ["identify security regressions"],
    "deliverable": "finding report",
    "scopeMode": "pr",
    "objectiveProfiles": ["general", "security"],
    "executionMode": "audit-only",
    "scopeResolution": {"basis": "PLATFORM", "confidence": "HIGH"},
    "snapshot": null,
    "startedAt": "<ISO8601>",
    "updatedAt": "<ISO8601>"
  },
  "sharedFacts": [],
  "claims": [],
  "verificationUnits": [],
  "findings": [],
  "residualRisks": []
}
```

- `phase`：`ACTIVE` / `FINAL` / `SUPERSEDED`。FINAL 不得含 `Decision=PENDING`；SUPERSEDED 是被新审计接替的冻结历史，不是可恢复的工作态。
- `availableEvidence` 是**可选的**证据类型清单，只供主代理判断"能取到什么证据"时参考。它不参与任何校验，也从不影响 Gate 或 Decision；省略即可，不要为填满字段而写。
- `objectiveProfiles` 必须包含且只包含一次 `general`；适用时再加入 `security` / `fix-verification`。`scopeResolution` 的来源选择、候选和询问规则由 [SKILL.md 的 Scope Resolution Protocol](../SKILL.md#scope-resolution-protocol) 唯一定义；`scopeResolution.assumption` 只在 `basis=ASSUMED` 时创建。
- 协议对象默认闭合。只有每个支持位置的可选 `metadata` 对象可保存非语义、工具私有且 JSON 可表示的附加信息；其内容不能新增、覆盖或参与 task contract、Evidence、Finding、Gate 或恢复语义。未知协议字段一律是校验错误。执行附录（命令与工作目录、仓外目录清单、开工/收工 git status、结果工件哈希）短期可落 `audit.metadata`：它是过程记录而非语义字段，报告引用时须标注其来源；将其升为一等触发式字段时，须一并解决"过程证据放非语义字段"的章程张力。
- `audit.snapshot` 始终存在。Git base/head、archive hash、部署版本等不可变身份写入其中；ACTIVE 在身份尚未形成时必须显式写 `null`，每个 FINAL 必须写不可变 identity，使结论不会被错用到漂移工件。非 null 形状是以 `kind` 区分的有界联合：

```json
{"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"}
{"kind": "git-worktree", "base": "<PRE HEAD>", "head": "<POST HEAD>", "initialSha256": "<PRE manifest SHA-256>", "finalSha256": "<POST manifest SHA-256>"}
{"kind": "archive", "sha256": "<64-hex-digest>"}
{"kind": "deployment", "version": "<non-empty-immutable-version>"}
{"kind": "other", "identity": "<non-empty-immutable-identity>"}
```

`git.base` 与 `git-worktree.base` 可为 null；每种 kind 不得混入其它变体的字段。不能用分支名、“当前部署”等可漂移别名充当不可变身份。`git-worktree` 变体的 manifest 规则见 §3.1.2「未提交修复与 audit-and-fix」。

- `auditBinding`：每个 investigation/verification JSON 顶层必须包含 `auditBinding={auditId,snapshot}`；其中 `auditBinding.auditId == state.json.audit.id`，且 `auditBinding.snapshot` 与 `state.json.audit.snapshot` 深度相等，不比较 audit 的其它字段。ACTIVE 尚无 snapshot 时明确写 `snapshot:null`。更换 auditId 或实质更换 snapshot 后必须重新取证并写新绑定，不能只复制旧 artifact。唯一例外是同一任务契约从 `snapshot:null` 填入刚形成的最终不可变身份：主代理必须先证明取证期间目标没有契约外漂移，再把所有仍适用 artifact 的 binding 与 state 在同一次收口中更新；无法证明就接替或重跑。`auditBinding` 是防止误消费的结构化归属声明，不是证明“确实执行过”的密码学凭据。

#### 3.1.2 条件字段（按需物化，不触发就整段跳过）

| 触发条件 | 读哪一组 |
|---|---|
| 用户请求了合并、发布或系统就绪判断 | Gate |
| 用户要求穷尽或自定义了停止条件 | 穷尽覆盖 |
| 用户、组织策略或已请求 Gate 强制独立验证 | 独立验证 |
| 主代理与目标变更存在先验接触 | 先验接触与变更面扫描 |
| 发生失败或被取消的派发 | 失败派发登记 |
| 发生契约外实质变化、需冻结旧实例另起新实例 | 接替 |
| 存在未提交修复，或 `executionMode=audit-and-fix` | 未提交修复与 audit-and-fix |

**Gate**（`gates` 的字段结构在本节；结果如何推导见 [reporting.md](reporting.md) §4）

- 默认 Gate 阻断阈值为 High。用户要更严格时，在对应 target 写 `policies.<target>.blockAtOrAbove=Medium|Low`；不支持自由文本 `audit.riskTolerance`。其它可判定完成条件转成 REQUIRED Claim；无法归一时记录 material residual risk，并使相关 Gate 为 INCOMPLETE。无 Gate 的 FINAL 同样至少要有一个 REQUIRED Claim：非空 objectives 不能由零个验证对象真空收口；尚未形成可验证风险主张时保持 ACTIVE，或用受限状态与 residual risk 如实交付。

- 只有真实 Gate 存在时创建：

```json
{
"gates": {
  "targets": ["CHANGE", "RELEASE"],
  "policies": {"RELEASE": {"blockAtOrAbove": "Medium"}},
  "decisions": {
    "CHANGE": {"result": "READY-WITH-CONDITIONS", "basis": ["F2"]},
    "RELEASE": {"result": "INCOMPLETE", "basis": ["Q3"]}
  }
}
}
```

`policies` 只在收紧默认 High 阈值时创建，只接受 `Medium|Low`；放宽已知风险必须走 Finding 的明确风险接受。其它任意 policy key 都非法。

`decisions` 是 FINAL 阶段从同一 state 派生的缓存：ACTIVE 和 SUPERSEDED 时禁止创建，最终报告前按 reporting 重算并由 validator 比对。无 Gate 就省略整个对象；`targets` 不得包含虚构的 `NONE`。

`basis` 必须非空，且只使用导致该结果的现有 `Q<n>` / `F<n>` / `G<n>`，或下列固定 token：

| token | 使用时机 |
|---|---|
| `ALL-REQUIRED-INPUTS-SATISFIED` | 结果为 `READY` |
| `INDEPENDENT-VALIDATION-GAP` | 有显式独立验证要求，但没有 highest Claim |
| `REQUIRED-COVERAGE-GAP` | 当前 target 没有任何 Gate-scoped REQUIRED Claim |
| `EXHAUSTIVE-COVERAGE-GAP` | `exhaustive` 的 scope inventory 未闭合 |

**穷尽覆盖**

- 用户明确穷尽或自定义停止条件时写 `audit.stop={policy, criteria?, reason?}`；`reason` 存在时必须是非空状态事实，供报告披露实际停止依据；默认停止规则不物化。`policy=exhaustive` 还是硬完成义务，必须同时创建 `audit.scopeCoverage`：

```json
{
  "scopeCoverage": {
    "snapshot": {"kind": "git", "base": null, "head": "<immutable-head>"},
    "declaredMembers": ["README.md", "src/main.go"],
    "completedMembers": ["README.md", "src/main.go"],
    "excludedMembers": [{"member": "dist/app.bin", "reason": "generated binary; inspected through source/build coverage"}]
  }
}
```

`declaredMembers` 必须非空、去重；每个 completed/excluded member 必须来自 declared，二者不得重叠，排除项必须有非空原因，`scopeCoverage.snapshot` 必须与当前 audit snapshot 完全一致。FINAL 时 declared 的每个成员都必须 completed 或明确 excluded，且至少一个成员 completed。客观无法完成时，可在 FINAL 写 `residualRiskId` 指向 material residual risk；有 Gate 时该 residual 必须影响全部请求 target：已有确认 blocker 时仍按优先级为 `BLOCKED` 并披露覆盖缺口，否则为 `INCOMPLETE`。无 Gate 时报告不得声称 clean conclusion。没有 exhaustive 要求时省略整个 `scopeCoverage`。

**独立验证**

- 用户、适用组织策略或已请求 Gate 明确要求 independent validation 时，写非空去重数组 `audit.independentValidationRequiredFor`；成员只允许 `AUDIT` 或 `audit.gates.targets` 中的实际 target。`AUDIT` 约束所有 highest Claim，且不得与 target 成员混用；多个 target 可写为如 `["RELEASE", "SYSTEM"]`。没有硬要求时省略。是否成立按 §3.4 的机械判据认定。

**先验接触与变更面扫描**

风险地图作者同时是被审变更的实现者或此前的非正式验证者时，claim 集从构造上继承其盲区（"契约作者的先验决定他会问什么问题"）。为把该盲区显式化：

- 主代理在本次审计开始前接触过目标同一实质内容时，写非空去重数组 `audit.priorContact`，成员只允许 `implementer`（主代理实现了被审变更）或 `informal-verifier`（主代理或其代理者在审计开始前对同一实质内容形成过验证性判断——非正式 review、先前测试、修复实现，无论正式角色）；两个字段可并列。无接触时整个字段省略；不存在 `none` 占位值。字段存在即触发扫描义务。
- 触发时必须新建一个 **REQUIRED** 的变更面扫描 Claim：statement 写成可证伪断言（"变更面及其直接调用者中不存在已声明 claims 之外的 material 风险"）；scope 机械定义为变更触达文件及其直接调用者——`change`/`pr` 用 diff、`author-commits` 用范围内作者触达文件；priority 用 `normal`（覆盖性扫描，不要求 discrimination/sufficiency）。有 Gate 时该 Claim 携带全部请求 target 的 `gateTargets`——其未完成性对放行信心是构造性 material 的。
- `scopeMode=project` 没有 diff 可扫，不建扫描 Claim；改为在 Residual uncertainty 披露先验接触与利益冲突，并建议独立第二审计者。
- `executionMode=audit-and-fix` 的扫描只挂 PRE-fix 评估；POST-fix 由 fixWorkflow VERIFY 批次与 `resolutionChallenge` 承担。`audit-only` 的外部修复核验不建批次 DAG，兜底同样只有 `resolutionChallenge`。
- 扫描单元是正常 investigation：有自己的 hypotheses、evidence 和 coverageSummary（checked 列实际扫过的面）；发现 material 风险走正常 H→F 路径；低于 material 的外溢观察写 `coverageSummary.peripheralObservations`。扫描结论多为 verified clean，其可信度依赖"阴性单元最低复核深度"（§3.4）——两者必须同时执行。

**失败派发登记**

- 仅在发生失败或被取消的派发时创建顶层 `dispatches[]`（平时省略）；每个条目结构化为 `{"unit", "reason", "residue?"}`：unit 是派发目标单元 id 或标签，reason 写失败/取消原因（平台并发限制、执行者不可用等），residue 记录仓外残留及其清理状态（有则写）。被取消前已执行的工作不可恢复为 Evidence，但登记本身让"这里可能存在未覆盖区域"在 state 中可见，供报告披露与后续审计参考。

**接替**

权威 target、scope、snapshot、objectives、决策问题或 shared facts 发生会使旧 Evidence 失效的**契约外**实质变化时，不在原实例里重开。创建新 ACTIVE 实例，并建立双向接替链：

新实例的 `audit` 增加：

```json
{"supersedesAuditId": "old-audit-id"}
```

旧实例同时把 `phase` 改为 `SUPERSEDED`，并在 `audit` 增加：

```json
{"supersession": {"byAuditId": "new-audit-id", "reason": "<material invalidation>", "at": "<ISO8601>"}}
```

一个旧实例只能有一个直接后继，链不得成环。新实例只复用可重新观察的调查线索，不把旧 Unit 的 verified、Decision、Disposition、风险接受或 Gate 复制成 live 结论。

**未提交修复与 audit-and-fix**

`git-worktree` 用于未提交工作树：`base/head` 固定 PRE/POST 时点的 Git HEAD，两个 SHA-256 固定对应时点的确定性内容 manifest。manifest 必须覆盖约定 scope 内的 tracked、staged、unstaged 和适用 untracked 文件，并结构化记录排除项；不得通过创建未授权 commit 或写 Git object database 来伪造身份。

`executionMode=audit-and-fix` 是唯一需预先表达工件转换的情形：初始 Task Contract 把 target 写成有界 PRE-fix → POST-fix 转换，明确允许路径与验收条件。已提交 Git PRE/POST 用 `kind=git` 的 `base/head`；没有授权 commit 或任一端含相关未提交内容时用 `kind=git-worktree` 的 PRE/POST HEAD 与内容 manifest。ACTIVE 期间身份尚未形成时 snapshot 保持显式 `null`，FINAL 报告前必须填入可复核的最终身份。在允许路径内完成该已声明转换是同一契约的执行，不触发 supersession；超出允许路径、更换基线/目标或外部变更使 Evidence 失效时仍必须接替。

### 3.1.3 最小可运行模板：照抄起步，别凭印象填满

本协议有大量可选字段。写状态时最常见的错误不是漏填，而是**照着完整 schema 把可选字段一起填满**——`patternScope` 尤其典型（没做同类搜索却被填成 `UNKNOWN`，等于没有信息却多一个字段要维护）。

下面这份模板**只含真正必填的字段**，已用 validator 实测通过（0 errors / 0 warnings）。它包含 `state.json` 与两份配套 artifact（`investigations/R1-a.json`、`verification/F1.json`），**三份一起放在同一个审计目录下**才能通过校验——单独只有 `state.json` 会报 11 个引用错误。三份的 `auditBinding` 都用同一个 `auditId` 与 `snapshot`；把它们改成你的实际 id 即可。

```json
{
  "schemaVersion": 2,
  "phase": "FINAL",
  "audit": {
    "id": "minimal-audit",
    "target": "the login endpoint",
    "scope": "public login path and its direct callers",
    "objectives": ["decide whether authentication can be bypassed"],
    "deliverable": "finding report",
    "scopeMode": "change",
    "objectiveProfiles": ["general"],
    "executionMode": "audit-only",
    "scopeResolution": {"basis": "USER", "confidence": "HIGH"},
    "snapshot": {"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"},
    "startedAt": "2026-08-29T00:00:00Z",
    "updatedAt": "2026-08-29T00:10:00Z"
  },
  "sharedFacts": [],
  "claims": [
    {
      "id": "Q1",
      "obligation": "REQUIRED",
      "riskArea": "security",
      "statement": "a malformed bearer token cannot reach an authorized handler",
      "consequence": "unauthenticated access",
      "priority": "normal",
      "scope": "public login route"
    }
  ],
  "verificationUnits": [
    {
      "id": "R1",
      "claimId": "Q1",
      "method": "implementation-trace",
      "executor": "investigator-a",
      "status": "verified",
      "investigationFile": "investigations/R1-a.json",
      "reconciliations": [
        {"hypothesisId": "R1-H1", "result": "FINDING", "findingId": "F1", "evidenceRefs": ["R1-E1"]}
      ]
    }
  ],
  "findings": [
    {
      "id": "F1",
      "statement": "the token parser accepts a malformed bearer token",
      "locations": ["src/auth/token.ts:44"],
      "causeImpact": "an attacker can reach an authorized handler without credentials",
      "conditions": "a request carrying a malformed Authorization header",
      "sourceHypotheses": ["R1-H1"],
      "supportingEvidence": ["R1-E1", "F1-E1"],
      "refutingEvidence": [],
      "disconfirmation": {
        "counterHypothesis": "an upstream middleware rejects malformed headers first",
        "evidenceSearched": "the middleware chain and the emitted authorization event",
        "result": "counter-refuted"
      },
      "risk": {"impact": "Medium", "likelihood": "Medium", "reachability": "Common", "recoverability": "Manual"},
      "decision": "CONFIRMED",
      "severity": "Medium",
      "confidence": "High",
      "verificationMethod": "implementation-trace",
      "verificationFile": "verification/F1.json",
      "exitCriteria": "a malformed token request is rejected before authorization"
    }
  ],
  "residualRisks": []
}
```

`investigations/R1-a.json`：

```json
{
  "auditBinding": {"auditId": "minimal-audit", "snapshot": {"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"}},
  "unitId": "R1",
  "claimId": "Q1",
  "method": "implementation-trace",
  "hypotheses": [
    {
      "id": "R1-H1",
      "statement": "the token parser accepts a malformed bearer token",
      "potentialImpact": "an attacker reaches an authorized handler",
      "conditions": "a malformed Authorization header",
      "counterHypothesis": "an upstream middleware rejects malformed headers first",
      "expectedSafeBehavior": "the request is rejected before authorization",
      "evidenceSearched": "the middleware chain and the emitted authorization event",
      "reasoning": "the parser does not validate the header shape before use",
      "disconfirmationResult": "counter-refuted",
      "result": "supported",
      "recommendation": "promote-to-finding",
      "evidenceRefs": ["R1-E1"]
    }
  ],
  "evidence": [
    {
      "id": "R1-E1",
      "polarity": "supports",
      "strength": "ES2",
      "reproducibility": "not-applicable",
      "source": "src/auth/token.ts:44",
      "observation": "the parser accepts a malformed bearer token"
    }
  ],
  "coverageSummary": {
    "checked": ["src/auth/token.ts"],
    "verifiedBehaviors": [],
    "gaps": []
  }
}
```

`verification/F1.json`：

```json
{
  "auditBinding": {"auditId": "minimal-audit", "snapshot": {"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"}},
  "findingId": "F1",
  "method": "implementation-trace",
  "checkedEvidence": ["R1-E1"],
  "evidence": [
    {
      "id": "F1-E1",
      "polarity": "supports",
      "strength": "ES3",
      "reproducibility": "repeatable",
      "source": "src/auth/token.ts:44 re-read by the main agent",
      "observation": "a malformed token reaches the authorized handler"
    }
  ],
  "conclusion": "the Finding holds under the declared conditions",
  "limits": []
}
```

§4 的 schema 示例用的是不同的 `auditId`（`20260822-auth-review`）；上面的模板已统一为 `minimal-audit`，照抄时不用再改 binding。字段含义与校验规则见 §4。

**照抄模板后，只有以下情形才需要加字段：**

| 触发条件 | 加什么 |
|---|---|
| Claim 是 `highest` / `high` | Claim 的 `discrimination`；FINAL 时还要 `sufficiency` |
| 该 Claim 影响某个 Gate | Claim 的 `gateTargets` |
| 要声称 independent validation | Unit 的 `isolation` |
| Finding 是 Critical/High | verification 文件的 `challenge`（§4.2） |
| 做过同类模式搜索 | Finding 的 `patternScope` |
| 用户请求了 Gate | `audit.gates` + 每个非 REJECTED Finding 的 `gates` |
| 需要变更归因 | Finding 的 `provenance` + `provenanceEvidence` |
| 风险已消除或被接受 | `disposition` 及相应 `resolutionEvidence` / 授权 |
| 裁决被改判过 | Finding 的 `decisionHistory` |

**不要为填满而写**：`availableEvidence`、`patternScope`（未做同类搜索时）、`exploration`、`scopeCoverage`、`fixWorkflow`、`metadata`。它们各有触发条件，不触发就整个省略——协议宁可少一个字段，也不要一个没有信息的字段。

### 3.2 Shared facts

只保存会被多个风险单元复用的 DIRECT 事实：

```json
{"id": "P1", "fact": "public POST /login calls auth.validate", "source": "src/http.go:40"}
```

不得写 Hypothesis、严重度、风险接受、其他调查者结论或“这里可能有 bug”。target/scope/snapshot 已由 `audit` 拥有，不在 shared facts 复制。`source` 必须是可核对的工件引用（`path:line`）或可重跑的命令，不得是主代理或调查者的记忆、结论或转述——依赖"我记得合并时取了哪一侧"这类不可核对来源的 shared fact，其下游发现链不可信。

若调查者用 `MAP-CORRECTION + DIRECT Evidence` 证明权威 shared fact 错误，主代理停止消费依赖该事实的结论，按上述双向规则接替整个审计实例。旧 state 仅冻结为追溯历史；新 state 使用纠正后的事实重新建 Claim、Unit 和裁决，不保留局部“仍有效”的 live 状态。

### 3.3 Claim registry：风险主张只写一次

```json
{
  "id": "Q1",
  "obligation": "REQUIRED",
  "riskArea": "security",
  "statement": "malformed tokens cannot reach an authorized handler",
  "consequence": "unauthenticated access",
  "priority": "highest",
  "scope": "public login path",
  "gateTargets": ["CHANGE"],
  "discrimination": {
    "safePrediction": "the request is rejected before authorization",
    "failurePrediction": "an authorized handler is reached",
    "discriminatingObservation": "a public-path request reaches exactly one outcome",
    "sufficiencyCriterion": "implementation and public-path traces agree"
  },
  "sufficiency": "MET"
}
```

- id：稳定 `Q<n>`。只有 statement、适用条件或 scope 实质变化才新建 Claim。
- obligation：`REQUIRED` / `EXPLORATORY`。Task Contract、highest 异质验证、显式 independent 要求或 material gap 收口需要的 Claim 必须 REQUIRED。
- priority：`highest` / `high` / `normal`，是派发优先级，不是 Finding Severity。
- `gateTargets`：只列该 REQUIRED Claim 的完成/缺口会影响的已请求 Gate；无 Gate 或不影响 Gate 时省略。EXPLORATORY Claim 禁止携带；探索发现 Gate 义务时另建 REQUIRED Claim。
- `highest` 必须保存完整四项 discrimination；`high` 只必须保存 `discriminatingObservation + sufficiencyCriterion`；`normal` 默认省略。
- `highest/high` 在 FINAL 阶段必须由主代理汇总该 Claim 所有 Unit 的 DIRECT Evidence 后写一次 `sufficiency=MET|NOT-MET`；ACTIVE 可暂时省略。`MET` 至少要有一个 verified Unit 产生 DIRECT Evidence；REQUIRED Claim 的全部已物化 Unit 都须 verified；highest 还须完成两个异质方法。拿不到证据时写 `NOT-MET`，不能空集合放行。normal 不写 Sufficiency。
- 只有 EXPLORATORY Claim 写 `explorationRound: X<n>`。探索产生新完成义务时另建 REQUIRED Claim，不把原 Claim 改类。

### 3.4 Verification units：一种方法一条记录

```json
{
  "id": "R1",
  "claimId": "Q1",
  "method": "implementation-trace",
  "executor": "investigator-a",
  "status": "verified",
  "investigationFile": "investigations/R1-a.json",
  "isolation": "ISOLATED",
  "reconciliations": [
    {"hypothesisId": "R1-H1", "result": "FINDING", "findingId": "F1", "evidenceRefs": ["R1-E1"]}
  ]
}
```

- 一个 Unit = 一个 Claim + 一个 verification archetype；第二种方法新建第二个 Unit，不复制 Claim 字段。
- status 单向推进：`planned → dispatched → reported → verified`。到 reported 才写 investigationFile；主代理逐个核对 H/E 后才 verified。verified 有最低复核深度：主代理至少重导该 Unit 的一条决定性 Evidence 链，或复跑一个判别探针；FINAL 前对每个 Claim 至少抽样重跑一次；客观不可复跑时在 verification 或报告中披露。阴性（无 Finding 的 verified clean）单元同样适用——漏网缺陷恰好可以藏在一个标签同为 verified 的干净单元里，摘要级核对不构成复核。
- `investigationFile` 与 Finding 的 `verificationFile` 必须是位于当前审计目录内的相对 `.json` 路径；禁止绝对路径和目录逃逸，保证移动与归档后仍可解析。
- Unit 的完成义务继承 Claim：REQUIRED Claim 下任何已物化 Unit 都是 required，未完成时会形成完整性缺口；不要预建“可选备用 Unit”，需要义务外搜索时另建 EXPLORATORY Claim。Unit 不保存 Sufficiency；verified 表示 H/E 已核对，且其 investigation 至少包含一条编号 DIRECT Evidence。
- `isolation` 只在需要证明或否定 independent validation 时写 `ISOLATED|NOT-ISOLATED`，不为普通单元填 `N/A`。
- reconciliations 必须与该 investigation 的 hypotheses 一一对应，并服从 H 的记录结果：`promote-to-finding → FINDING`、`close → REFUTED`、`residual-gap → RESIDUAL-GAP`。`FINDING` 必须引用 findingId；`RESIDUAL-GAP` 必须引用已存在的 `residualRiskId: G<n>`；其它组合禁止相应引用。引用的 DIRECT Evidence 必须来自当前 Unit 的 investigation；FINDING 至少有 `supports` Evidence，REFUTED 至少有 `refutes` Evidence。不得用 shared fact、其它 Unit 或 verification Evidence 构造循环归约，也不得遗漏、重复或用矛盾归约覆盖调查结果。
- FINAL 中 REQUIRED Claim 下任一未 verified Unit 必须写 `residualRiskId`，指向已存在且 `material=true` 的 `G<n>`。verified Unit 禁止该字段。这允许产生明确受限的 FINAL，但禁止静默终止 required 工作。
- highest Claim 的异质覆盖按 `claimId` 机械归组：至少两个 verified REQUIRED Unit 使用不同 method。在此基础上，若其中存在不同 executor、不同 method 且实际 `isolation=ISOLATED` 的 Unit 达到两组，才是 independent validation；未隔离的 Unit 不拖累该认定，也不得把 NOT-ISOLATED Unit 计入独立验证组。

### 3.5 Finding

Finding 的必需内容直接保存在 `findings[]`，不再另建 live Finding 文件：

```json
{
  "id": "F1",
  "statement": "token rejection omits correlation context",
  "locations": ["src/http.go:44"],
  "causeImpact": "missing context delays incident diagnosis",
  "conditions": "malformed bearer token",
  "sourceHypotheses": ["R1-H1"],
  "supportingEvidence": ["R1-E1", "F1-E1"],
  "refutingEvidence": [],
  "disconfirmation": {
    "counterHypothesis": "middleware supplies the context",
    "evidenceSearched": "middleware and emitted event",
    "result": "counter-refuted"
  },
  "risk": {
    "impact": "Medium",
    "likelihood": "Medium",
    "reachability": "Common",
    "recoverability": "Manual"
  },
  "decision": "CONFIRMED",
  "severity": "Medium",
  "confidence": "High",
  "verificationMethod": "implementation-trace",
  "verificationFile": "verification/F1.json",
  "exitCriteria": "the emitted event contains the correlation id"
}
```

规则：

- 非 REJECTED 的最终 Finding 必须有 risk、Severity 和 Confidence；Severity 按 [assessment-model.md](assessment-model.md) 的闭合 Impact 映射校验，只有相邻有限修正时才写非空 `severityRationale`。CONFIRMED 只允许 `High|Very-High` Confidence。
- `patternScope` 是**可选的**：只有真正做过同类搜索、能判定 `ISOLATED` / `SYSTEMIC` 时才写。它不参与 Gate 计算，也不影响任何 Decision；**没做同类搜索就省略整个字段，不要用 `UNKNOWN` 充数**。
- REJECTED 一律省略 `risk`、`severity`、`severityRationale`、`confidence` 和 `disposition`，同时必须满足：`refutingEvidence` 非空，且其 verification 文件新产生至少一条被该列表引用的 `refutes` Evidence。旧 supporting Evidence 保留为历史链，不因改标签而删除。
- disposition 省略即 `OPEN`。只有 CONFIRMED 可显式写 `REMEDIATING`、`RESOLVED-VERIFIED` 或 `ACCEPTED-RISK`；后两者分别要求 `resolutionEvidence` 或结构化 `riskAcceptanceAuthorization={text,auditId,snapshot}`。授权必须绑定当前实例与完整 snapshot，不能跨 supersession 复制。
- 可选的 `decisionHistory[]` 只记录**最终裁决形成之后**的实质改判。Decision、Severity、Confidence、Disposition、模式范围或决定性 Evidence/反证结论发生变化时，追加一条：

```json
{"decisionHistory": [{"at": "2026-08-22T00:15:00Z", "summary": "Confidence Medium -> High; runtime trace F1-E1 confirmed the gap", "evidenceRefs": ["F1-E1"]}]}
```

  `at` 为 ISO8601 时间，`summary` 写清"哪个字段、从什么改到什么、依据什么"，`evidenceRefs` 必须引用本审计已存在的 Evidence id。它不是第二份 live 状态：当前值仍只由 `decision` / `severity` / `confidence` / `disposition` 表达，历史条目不得覆盖或替代当前值。没有发生过改判就省略整个字段。
- Provenance 只在归因适用时写 `provenance + provenanceEvidence`。
- `sourceHypotheses` 必须非空、去重，并与所有指向该 F 的 `reconciliations[result=FINDING]` 双向完全一致。`supportingEvidence` 只引用 polarity=supports，`refutingEvidence` 和 `resolutionEvidence` 只引用 refutes，`provenanceEvidence` 只引用 context。
- 有 Gate 时，FINAL 的每个非 REJECTED Finding 必须覆盖每个请求 target：

```json
{
"gates": {
  "CHANGE": {"applicability": "APPLIES", "basis": "the path is changed", "evidenceRefs": ["F1-E1"]},
  "RELEASE": {"applicability": "DOES-NOT-APPLY", "basis": "not present in the candidate", "evidenceRefs": ["F1-E2"]}
}
}
```

applicability 只用 `APPLIES|DOES-NOT-APPLY|UNRESOLVED`。`APPLIES` 和 `DOES-NOT-APPLY` 都必须用非空 `evidenceRefs` 引用已与该 Finding 连接的 DIRECT Evidence；`basis` 只作解释，不是证据。APPLIES 至少引用 supports/context，DOES-NOT-APPLY 至少引用 refutes/context current-state Evidence；`disposition=RESOLVED-VERIFIED` 时每个 target 的 refs 还必须与 `resolutionEvidence` 有交集。`UNRESOLVED` 可省略 `evidenceRefs`。只有 CONFIRMED + APPLIES 且授权明确覆盖该 Finding/target 时，才可增加 `treatment:"ACCEPTED"` 与 `authorization={text,auditId,snapshot,target}`；四个字段分别绑定授权内容、当前实例、完整 snapshot 和当前 Gate。有任何 Gate 时禁止全局 `disposition=ACCEPTED-RISK`；无 Gate 时才可用它表达对整个 Finding 的明确接受，并保存同样绑定实例/snapshot 的结构化授权。

### 3.6 Residual risks 与探索

Residual risk 最小结构：

```json
{"id": "G1", "statement": "target runtime unavailable", "scope": "public-path validation", "material": true, "affectsGates": ["RELEASE"]}
```

Residual id 必须是全局唯一的 `G<n>`。无 Gate 时省略 `affectsGates`；存在 Gate 时，只有 `affectsGates` 列出的 target 消费该 residual，省略表示仅在报告中披露、不参与任何 Gate。Material residual gap 不能藏在 clean conclusion 后。

只有出现 EXPLORATORY Claim 时创建：

```json
{
"exploration": {
  "rounds": [{"id": "X1", "claimIds": ["Q4"], "materialDelta": false}],
  "noMaterialDeltaRounds": 1
}
}
```

同一轮 Claim 在读取任何该轮结果前一次规划；`round.claimIds` 必须非空、去重，且与 EXPLORATORY Claim 的 `explorationRound` 双向完全一致。普通/REQUIRED Claim 不得进入探索轮。连续计数只允许 0–2。required 工作不计入探索轮。

### 3.7 Audit-and-fix 批次状态

只有 `executionMode=audit-and-fix` 且至少一个 Finding 真正进入 `REMEDIATING` 或 `RESOLVED-VERIFIED` 时创建 `fixWorkflow`；尚未形成需修复 Finding 或最终无需修改时不为空流程造批次。创建后它是修复映射和批次恢复的唯一机器权威，不能把 `fix-map.md` 当作第二份状态：

```json
{
  "fixWorkflow": {
    "generation": 2,
    "finalRegressionBatchId": "regression-1",
    "findingMappings": [
      {"findingId": "F1", "rootCausePattern": "unchecked copy length", "knownInstances": ["src/parser.c:90"], "fixScope": "parser entrypoint", "exclusions": [], "behaviorChange": "oversized input is rejected", "acceptanceChecks": ["PRE fails; POST passes"], "preFixExpectedFailure": "input reaches copy", "regressionScope": "parser callers and boundaries", "residualRiskIds": []}
    ],
    "batches": [
      {"id": "fix-1", "kind": "FIX", "status": "PASSED", "attempt": 1, "scope": "parser guard", "allowedPaths": ["src/parser.c"], "acceptanceChecks": ["targeted regression"], "dependsOn": [], "findingIds": ["F1"], "evidenceRefs": ["F1-E2"], "validatedGeneration": 2},
      {"id": "verify-1", "kind": "VERIFY", "status": "PASSED", "attempt": 2, "transitionReason": "first attempt lacked target-runtime evidence", "scope": "independent verification", "allowedPaths": [], "acceptanceChecks": ["trace plus regression"], "dependsOn": ["fix-1"], "findingIds": ["F1"], "evidenceRefs": ["F1-E1"], "validatedGeneration": 2},
      {"id": "regression-1", "kind": "REGRESSION", "status": "PASSED", "attempt": 1, "scope": "parser regression surface", "allowedPaths": [], "acceptanceChecks": ["full parser regression"], "dependsOn": ["verify-1"], "findingIds": ["F1"], "evidenceRefs": ["F1-E1"], "validatedGeneration": 2}
    ]
  }
}
```

`findingMappings` 为每个进入 `REMEDIATING` 或 `RESOLVED-VERIFIED` 的 Finding 各写一次。以下字段都必须结构化保存：根因模式、已知实例、修复范围、排除项、行为变化、验收检查、PRE-fix 预期失败、回归范围、residual ids。

`allowedPaths` 是相对于被审计目标根的可移植相对路径，只允许普通路径段；绝对路径、drive/UNC、`.`、`..`、NUL、混合分隔符和空段均非法。validator 的词法检查不替代实际写入前对目标根、symlink/junction 和授权范围的再次 resolve 检查。

批次规则：

- `kind` 只用 `FIX|VERIFY|REGRESSION`，状态只用 `PENDING|PASSED|FAILED`；每批保存有界 scope、允许修改路径（FIX 非空）和非空验收检查。
- REMEDIATING Finding 至少分配到一个 FIX 批次。
- RESOLVED-VERIFIED Finding 必须被一个 PASSED VERIFY 批次映射；每个把该 Finding 列入 `findingIds` 的 PASSED VERIFY 都必须引用其 `resolutionEvidence`，不能用旧 supporting Evidence 冒充修复验收。

失效与重试：

- 每次会使既有批次验收失效的同实例工件/Evidence 变化都递增 `generation`，把受影响批次及全部下游改回 `PENDING`、增加新 attempt 后再运行。
- `attempt>1` 必须用 `transitionReason` 记录重试或失效原因。
- 只有 `PASSED` 可携带等于当前 generation 的 `validatedGeneration`，且必须有 DIRECT `evidenceRefs`。
- PASSED 批次的全部依赖也必须 PASSED；图不得缺边、自环或成环。

FINAL 条件：全部批次与 `finalRegressionBatchId` 指向的 REGRESSION 批次必须 PASSED，且不能留下 `REMEDIATING` Finding；最终回归必须传递依赖每个 PASSED FIX 和 VERIFY 批次。

未完成时：修复尚未验证、批次失败，或仍有会阻断该修复验收的 material 缺口，则保持 ACTIVE 并在中间/受阻报告中披露，不把未完成修复包装成 FINAL。与该修复验收无关的 material 缺口仍按主流程形成受限 FINAL 或相应 Gate=`INCOMPLETE`。

`audit-only` 的外部修复核验不创建批次 DAG，直接以 Finding、verification 和 resolution Evidence 收口。

validator 只检查当前快照及 retry/invalidation 原因，不凭空重建此前每次转换。需要完整逐次审计轨迹时，应由受控版本历史或派生报告保留；当前状态与历史冲突时不得猜测放行。

## 4. Investigation 与主验证文件

### 4.1 `investigations/<unit>-<executor>.json`

```json
{
  "auditBinding": {"auditId": "20260822-auth-review", "snapshot": {"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"}},
  "unitId": "R1",
  "claimId": "Q1",
  "method": "implementation-trace",
  "hypotheses": [
    {
      "id": "R1-H1",
      "statement": "<可证伪陈述>",
      "potentialImpact": "<若为真会怎样>",
      "conditions": "<触发条件>",
      "counterHypothesis": "<最强现实安全解释>",
      "expectedSafeBehavior": "<若安全应观察到什么>",
      "evidenceSearched": "<实际反证范围>",
      "disconfirmationResult": "counter-refuted",
      "evidenceRefs": ["R1-E1"],
      "result": "supported",
      "recommendation": "promote-to-finding",
      "reasoning": "<E 到 H 的推理>"
    }
  ],
  "evidence": [
    {
      "id": "R1-E1",
      "polarity": "supports",
      "strength": "ES2",
      "reproducibility": "not-applicable",
      "source": "path:line / command / versioned contract",
      "observation": "<只写直接观察>"
    }
  ],
  "coverageSummary": {
    "checked": ["<实际范围>"],
    "verifiedBehaviors": ["<已验证正确行为>"],
    "gaps": []
  }
}
```

Hypothesis id 用 `<unit>-H<n>`；Evidence id 用 `<unit>-E<n>`。每个 material H 的 `evidenceRefs` 必须非空；`supported` 至少引用一条 `polarity=supports` 的 DIRECT Evidence，`refuted` 至少引用一条 `polarity=refutes` 的 DIRECT Evidence，不能只改 result 标签消除风险。`supported` 只配 `promote-to-finding`，`refuted` 只配 `close`，`unresolved` 配 `promote-to-finding`（决定性缺口未由新的 DIRECT Evidence 解决前只能形成 CONDITIONAL）或 `residual-gap`；`counter-supported` 的原 H 必须关闭，若缩窄后仍 material 则另建新 H。没有 material H 时 hypotheses 为空，仍填写 coverageSummary。测试成为 material Evidence 时在该 E 增加 `testDiscrimination={test,result,basis,issue?}`。低于 material 的超范围外溢观察写可选的 `coverageSummary.peripheralObservations[]`（字符串数组，主代理接收时集中 triage）。

### 4.2 `verification/F<n>.json`

```json
{
  "auditBinding": {"auditId": "20260822-auth-review", "snapshot": {"kind": "git", "base": null, "head": "0123456789abcdef0123456789abcdef01234567"}},
  "findingId": "F1",
  "method": "implementation-trace",
  "checkedEvidence": ["R1-E1"],
  "evidence": [
    {"id": "F1-E1", "polarity": "supports", "strength": "ES3", "reproducibility": "repeatable", "source": "<source>", "observation": "<observation>"}
  ],
  "challenge": {
    "status": "COMPLETED",
    "mode": "HETEROGENEOUS-METHOD",
    "unitId": "R2",
    "method": "adversarial-challenge",
    "evidenceRefs": ["R2-E1"],
    "result": "counter-refuted"
  },
  "conclusion": "<主代理复核结论>",
  "limits": []
}
```

新增 Evidence id 用 `F<n>-E<m>`。最终 Decision 定稿前，`checkedEvidence` 与 `evidence` 都必须非空：前者只能引用该 Finding 的 source Hypothesis 所属 investigation Evidence，后者记录主代理新的 DIRECT 观察。每条新 `F<n>-E<m>` 必须被回写到该 Finding 的 supporting/refuting/resolution/provenance Evidence 之一；顶层 `method` 必须等于 Finding 的 `verificationMethod`。主代理必须实际重查决定性链，引用旧 Evidence 不能替代新的观察说明。ACTIVE 阶段的 `PENDING` Finding 可暂时省略 `verificationFile`；其它 Decision 必须引用完整验证文件。

暂定 Severity 为 Critical/High 且 Decision 非 REJECTED/PENDING 时，该 verification 文件必须保存第二挑战：

- 已完成写 `challenge={status:"COMPLETED", mode, unitId?, method, evidenceRefs, result}`。`mode` 只能是 `HETEROGENEOUS-METHOD` 或 `EQUIVALENT-DIRECT-DISCONFIRMATION`，`result` 只能是 `counter-supported|counter-refuted`。异质模式必须写 `unitId`，该 Unit 必须 verified、验证产生此 Finding 的同一 Claim，method 必须与 Unit 一致且不同于主验证 method，Evidence 只能由该 Unit 产生；等价直接反证禁止 `unitId`，Evidence 只能引用本次主 verification 新产生的 `F<n>-E<m>`。
- 无法完成只写 `challenge={status:"GAP", gapReason:"..."}`，并且 Decision 必须为 CONDITIONAL。GAP 不携带 mode/method/evidenceRefs/result。
- CONFIRMED 和 NEEDS-DECISION 必须是已完成的 `counter-refuted`。CONDITIONAL 不能用 `counter-supported` 维持原 Finding；该结果意味原 Finding 需关闭或缩窄后重建。

上述 `challenge` 裁决“问题是否成立”，不承担修复验收。修复是否真的生效，由 `resolutionChallenge` 单独表达。

Critical/High Finding 写 `disposition=RESOLVED-VERIFIED` 时，必须在同一 verification 文件写：

```json
{"resolutionChallenge": {"status": "COMPLETED", "unitId": "R3", "method": "user-path-trace", "evidenceRefs": ["R3-E2"], "result": "resolution-supported"}}
```

约束如下：

- 所引 Unit 必须 `verified`，且验证的是产生此 Finding 的同一 Claim；
- `method` 必须不同于主 verification 的 method；
- `evidenceRefs` 只能由该 Unit 产生，且必须回写到 Finding 的 `resolutionEvidence`；
- `status` 只允许 `COMPLETED`。**`resolutionChallenge` 没有 `GAP` 状态。**

因此无法完成时不能保持 `RESOLVED-VERIFIED`：回到 `REMEDIATING`，把缺口写进 residual risk、verification 的 `limits` 或仍未通过的 fixWorkflow 批次，并保持 `ACTIVE`。

## 5. 更新、校验与恢复

- 调查者先通过平台消息或 state root 外的批准临时位置交付完整 JSON；主代理先在 state root 外保留 staged 原件，并在隔离副本中把 canonical artifact 与 proposed `state.json` 组合后运行 validator。发布顺序固定为：原子创建 canonical artifact，再原子替换 `state.json` 作为 commit record；禁止 state-first，避免 dangling reference。两步之间中断只可能留下 unreferenced artifact：恢复时不消费它，先核对其 binding/unit/method 与仍保留的 staged hash，把它移动到 state-root 外 quarantine 后恢复旧合法 state，再从 staged 原件重试；无法唯一匹配时保留现场并请求决定。完成后才删除 staging/quarantine。不要到收尾时一次性把 planned 补成 verified。
- **内容级不合格接收**：上一条处理崩溃中断，本条处理更高频的 schema 漂移与语义不一致（自相矛盾的 result/recommendation、自造字段、嵌套结构漂移）。规则：①staged 原件强制保留到审计收口，主代理不得就地改写调查工件——任何归一化（重排键、修剪漂移字段、措辞精化）都必须先留原件，并以 diff/脚本形式把转换记录留痕进 `probes/`；②机械形式问题（键序、空白、可直接从 Evidence 核对的措辞）主代理可代为归一，但必须留痕；③改变语义含量的动作一律不得代做：调查者自报的 result/recommendation 与其 Evidence 极性机械冲突、或把 H 降级为覆盖摘要等重分类，必须退回调查者重写，或由主代理以新 DIRECT Evidence 按正常流程重建——凭自由裁量静默重分类是证据洗白。可选的 `audit_state.py receive` 只做"校验 + 落盘 canonical + 报告差异"三件机械事，不做归一、不写 state 引用、不推 `reported`；binding 不匹配时与 `bind` 同款拒绝并提示重新取证。
- 每次 material 接收事务达到稳定态后运行 validator；它不用于调查者正在写文件、尚未被 state 接收的中间时刻。FAIL 时不得生成强于当前合法状态的报告或 Gate。
- 可选的 `scripts/audit_state.py bind <dir>` 可在每份 artifact 落盘后把 `audit.id` / `audit.snapshot` 传播成它的 `auditBinding`，省去逐文件手写；`lint <dir>` 只读地报告 id 前缀、`reconciliations` 与 hypotheses 的镜像关系等机械问题，适合在 validator 之前先跑一遍。两者都不做语义判断，也不替代 validator。注意 `bind` 遇到**已存在但不匹配**的 binding 会拒绝覆盖（该证据属于另一次审计，须重新取证），只有 `--force` 例外。
- target、snapshot、scope、objectives、决策问题或权威 shared facts 发生契约外实质变化时，按 §3.1 接替整个审计实例；不分“还是同一问题”而在原 state 里重开。事先声明的 audit-and-fix 转换按前段执行。
- 恢复时先检查闭合布局：若只有 unreferenced investigation/verification artifact，按上一条的 quarantine 规则恢复；除此之外再读取 state.json 并验证 schemaVersion、audit id、target/snapshot/scope 和所有引用文件。旧式 Markdown 状态不自动迁移。冲突实例无法唯一识别时呈现候选并请求决定，不覆盖或删除。
- `reported` Unit 只在 artifact 的 auditBinding 匹配当前实例时读取已有 investigation 后继续主代理核对；`PENDING` Finding 继续反证和直接复核；修复流程从 `state.json.fixWorkflow` 恢复未结束 batch，不从派生 fix-map 猜状态。
- 归档前 phase 改为 FINAL、重算 Gates、运行 validator、清理 probes；随后移动整个目录到 `<stateRoot>/archive/<auditId>/`。归档后 report 仍是派生物，事实变化必须产生新审计状态而不是改历史报告。
- 发生归档、恢复冲突或接替后，运行 `python <skill-root>/scripts/validate_audit_state.py --state-root <stateRoot>`。它会检查固定布局、缺失 `state.json` 的半成品审计目录、误入 archive 的 ACTIVE 实例、目录名和 audit id、活动/归档重复 id、双向接替链、多后继和环。
- 接替操作中断时不猜测哪边权威：保留两个目录，运行 `--state-root`，依据双向链修复缺失的单个元数据写入；若存在多个后继或无法唯一确定，则保留现场并请求决定，不删除或覆盖。SUPERSEDED 实例不恢复执行，不产生当前报告或 Gate。

validator 是协议不变量的可执行子集；它通过不证明 Investigation 真实读过代码、Evidence 来源可信或 Severity 判断合理，这些仍由主代理的直接复核和最终报告负责。
