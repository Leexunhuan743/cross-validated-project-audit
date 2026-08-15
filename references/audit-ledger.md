# 审计账本与断点恢复

审计主代理在**派发任何子代理之前**读取本文件并初始化审计状态；之后每完成一步（派发、发现到达、复核、裁决、门禁）增量落盘。目标：会话中断后无需重跑任何子代理即可续审；跨轮审计可查询上一轮裁决与反证。盘上文件是审计状态的真相源——子代理的"完成"声明、返回文本的长度与顺序都不是权威。

## 1. 状态目录（必须仓库外）

审计状态一律写在**被审计仓库之外**的可写目录：会话工作区、系统临时目录或用户状态目录均可。禁止写入被审计仓库——否则污染交付树，违反只读契约（`SKILL.md` 操作契约）。

```text
<状态根>/agent-audits/<auditId>/
├── audit.json          # 审计定义、范围、基线、假设、门禁目标
├── coverage.json       # 覆盖矩阵（含每单元状态）
├── ledger.jsonl        # 候选账本（append-only）
├── findings/           # 各子代理发现产物
│   └── <axis>-<agent>.jsonl
└── probes/             # 主代理批准的仓库外隔离探针（结束时清理）
```

- `auditId = sanitizeKey(审计名)`：只保留字母、数字、`-`、`_`，其余折叠为 `-`；纯符号或超长名取截断加短摘要；禁止路径分隔符、`..` 与空 id。
- 主代理在审计开始时选定状态根并记录到 `audit.json` 的 `stateDir`，报告中必须附该路径。

## 2. 文件 schema

### 2.1 `audit.json`

```jsonc
{
  "id": "lep-2026-08",              // sanitizeKey 后的稳定目录 id
  "name": "LEPTON 交叉审计 v1.5",   // 展示名
  "ownerKey": "sess-…",             // 主会话/主代理标识；拿不到时用启动时间戳
  "stateDir": "<状态根>/agent-audits/lep-2026-08",
  "artifact": { "kind": "branch|pr|commit|workspace|plan|feature|migration|fix-commit",
                "base": "4943fb2", "head": "…", "path": "…" },
  "mode": "audit-only | audit-and-fix | fix-verification",
  "gate": "READY | READY-WITH-CONDITIONS | BLOCKED | INCOMPLETE",  // 最终报告前填写
  "assumptions": ["…"],
  "excluded": ["…"],                // 明确排除的范围与理由
  "notes": "…",
  "startedAt": "ISO8601",
  "updatedAt": "ISO8601"
}
```

### 2.2 `ledger.jsonl`（每候选一行）

```jsonc
{"id":"C1","rev":1,"axis":"engineering","source":"SA-fix","findingRef":"SA-fix-3",
 "location":"vendor/…/model.rs:253",
 "severity":"High/P1","attribution":"本次引入","evidence":"DIRECT",
 "verification":"code-trace","verdict":"open","scope":null,
 "rebuttal":null,"probeCleanup":true,"updatedAt":"ISO8601"}
```

字段与 `SKILL.md` §4 账本列一一对应，外加：

| 字段 | 取值与含义 |
|---|---|
| `verdict` | 状态：`open` → `verified` → 四终态；迁移见下 |
| `evidence` | `DIRECT`（实际读取/运行确认）/ `INFERRED`（推断） |
| `verification` | `code-trace` / `runtime-probe` / `contract` / `test-discrimination` / `minimal-probe` / `unknown`（对应 `SKILL.md` §4 与 `behavioral-verification.md` 的验证方式；尚未验证写 `unknown`） |
| `findingRef` | 来源 findings 条目 id；主代理直接发现写 `null` |
| `scope` | `ISOLATED` / `SYSTEMIC` / `UNKNOWN`，仅模式搜索后填写 |
| `rebuttal` | `rejected` 必填反证；`conditional` 必填缺失条件；`needs_decision` 必填选项与影响 |
| `probeCleanup` | 探针/临时文件是否已清理；无探针写 `true` |
| `rev` | 同 `id` 修订号，从 1 递增 |

规则：

- 新候选以 `verdict:"open"` 追加；主代理复核后追加 `rev+1` 的 `verified` 行；终态裁决为 `confirmed` / `needs_decision` / `conditional` / `rejected`。
- **修订 = 追加新行**（同 `id`、`rev+1`），每行是该候选的**全量快照**：修订行必须重述全部字段，读取时取同 `id` 最大 `rev` 的整行作为当前状态；不跨 rev 合并字段，不原地改旧行。
- 状态迁移白名单（其余迁移非法）：`open → verified | rejected`；`verified → confirmed | needs_decision | conditional | rejected`；四终态不再变化，只能追加修订行。
- 机器键与报告词表一一对应：`confirmed` ↔ `CONFIRMED`、`needs_decision` ↔ `NEEDS-DECISION`、`conditional` ↔ `CONDITIONAL`、`rejected` ↔ `REJECTED`；`open`/`verified` 是账本内部流转态，不出现在报告。
- 一行一条 JSON，行内不得出现未转义换行；读取时坏行跳过并记录，不中断整个账本。
- 快照输出时 `location`、`rebuttal` 截断（约 300/200 字），全文只在盘上。

### 2.3 `coverage.json`（覆盖矩阵单元）

```jsonc
[{"cell":"SA-fix|engineering|正确性|vendor/lepton_jpeg",
  "agent":"SA-fix","axis":"engineering","primaryDim":"正确性与不变量",
  "paths":"vendor/lepton_jpeg",
  "overlapInvariants":["get_block 下溢"],
  "findingRefs":["SA-fix-3","SB-7"],
  "evidenceMethod":"code-trace",
  "status":"verified"}]
```

- `status` 单向推进：`planned → dispatched → reported → verified`；一个单元只有在对应发现已聚合、主代理复核完成后才能标 `verified`；无法判定的单元留在当前状态并在报告"残留缺口"披露。
- `findingRefs` 显式链接本单元产出的发现条目（findings id）。`verified` 的机械判据：`findingRefs` 非空时，每条都已聚合入账（`ledger.jsonl` 中存在 `findingRef` 引回）且对应候选全部到达终态；无候选问题（`findingRefs` 为空）时，仍需主代理直接复核后才可标 `verified`。
- 最高风险不变量必须有至少两个单元覆盖，且都达到 `verified`，才允许使用"未发现已确认缺陷"措辞（`reporting.md` §6）。

### 2.4 `findings/<axis>-<agent>.jsonl`（子代理发现产物）

```jsonc
{"id":"SA-fix-3","axis":"engineering","source":"SA-fix","location":"src/decode/lepton.rs:517",
 "severity":"Low/P3","confidence":"high","attribution":"本次引入","direct":true,
 "claim":"…","causeEffect":"…","trigger":"…","suggestedVerification":"…","updatedAt":"ISO8601"}
```

字段与 `SKILL.md` §3 返回契约第 1 条逐项对应；`direct: true` 即 `DIRECT`，`false` 即 `INFERRED`。子代理只写主代理指定的这一个文件，不得读、写账本或其他代理的文件。

## 3. 写盘纪律

- JSONL **append-only**：只追加行，不原地编辑；JSON 小文件（`audit.json`、`coverage.json`）整体重写。
- 能力允许时用"同目录临时文件 + rename"原子替换；同一审计目录**同一时刻只允许主代理写**（子代理只写自己的 findings 文件，天然无冲突）。
- 每个候选问题在子代理报告到达时立即入账；复核、裁决、模式范围每步增量更新，不得攒到报告前一次性补写。
- 子代理无法写文件：全文内联返回，主代理代写入对应 findings 文件并补 `source:"inline"`；这属于已披露降级，不改变"盘上为真相"的要求。
- 凭据、令牌、真实用户数据不回显：脱敏后入账，原文只保留给用户指定的安全位置或直接丢弃。

## 4. 断点恢复

1. 读取 `<状态根>/agent-audits/` 下同 `auditId` 的 `audit.json` 与 `coverage.json`，还原工件、基线、假设与矩阵状态。
2. 按 `ledger.jsonl` 中每个候选的最大 `rev` 行恢复当前状态；未到终态的逐条继续复核/裁决。
3. 按 `findings/` 中"已报告、未聚合"的条目补聚合进账本。
4. 在报告"范围与基线"注明"恢复自 `<状态目录路径>`，中断点为 X，恢复后续审 N 项"。
5. 无法定位状态目录时视为新审计，并在报告中披露"历史状态未找到，从零开始"。

## 5. 归档与跨轮复盘

- 审计结束：清理 `probes/` 与一切临时探针；随后把状态目录移入 `<状态根>/agent-audits/archive/<ownerKey>--<auditId>/`，报告附归档路径。
- 归档键必须复合：`ownerKey`（主会话/主代理标识）与 `auditId` 组合；没有 ownerKey 时用启动时间戳。可重复的业务审计名不能单独作键，否则同名审计跨会话撞键。
- 归档保留而非删除：下一轮审计先检索同工件/同范围的归档账本，上一轮裁决、反证、模式范围与未覆盖范围直接作为输入，而不是重跑一遍再比。
- 归档内容含敏感信息时，按与证据包相同的脱敏纪律处理后再保留。

## 6. 降级与披露

- 无法写盘（无文件能力、只读沙箱、平台限制）：继续审计，但改为会话内账本；报告"范围与基线"注明"审计状态未持久化"，且 `reporting.md` 完成清单对应项不得打勾。
- 唯一可写目录就是被审计仓库：同样视为无法写盘——不得把审计状态写进被审计仓库（污染交付树、违反只读契约），改用会话内账本并披露。
- 单代理、窄范围且用户明确要快速结果：可最小化账本（至少 `audit.json` + `ledger.jsonl`），但降级必须披露。
- 降级不改变其他纪律：子代理只读、DIRECT/INFERRED 标注、证据轴独立照常执行。
