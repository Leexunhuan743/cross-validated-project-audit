# cross-validated-project-audit

面向高风险项目、变更、PR、安全问题和修复结果的多代理交叉审计 Skill。它先固定范围与决策问题，再按 `Risk → verification method → executor` 选择异质路径，然后**用工具代跑证据、由主代理独占裁决**，输出可追溯到具体命令的报告。

适用于用户明确要求交叉验证、发布/合并门禁、严格修复验证，或经确认的高风险多路安全/作者审计；不用于普通代码评审、快速摘要、纯风格检查和无需多路径验证的窄问答。

## 它解决什么问题

审计本身就是证据工程，但多代理审计最常见的失败不是"想得不够深"，而是三类可机械消除的失败：

1. **格式漂移**——字段知识散在散文、脚手架、校验器、每个调查者的记忆四处；任何一处漂移都由子进程买单，最后约 30% 预算花在"这条证据该进哪个字段"上。
2. **自报当证据**——"我跑了测试，通过了"没有任何东西可以核对。
3. **结论强于证据**——发现是拼出来的，严重度是感觉出来的，没人复核。

本 skill 的对策是**三条硬规则 + 一个模板真相源**：模板渲染任务书（格式不可能漂移）、`run`/`mutate` 亲自执行并留痕（诚实靠工具不靠纪律）、`decide` 需要 main token 且结论强度受已有记录约束（越权与夸大都被机械拦截）。

## 三层分工

| 层 | 谁写 | 写什么 |
| --- | --- | --- |
| 世界（F 层） | 调查者子进程 | 位置 / 触发条件 / 影响 / 预期 / 实测 / 反假设 / 搜证范围 / 信心档 |
| 账本（D 层） | `scripts/audit_forms.py` | 槽位 id、证据记录（cwd/退出码/输出尾部）、行号锚点、变异哈希、聚合与排序、报告渲染、模板迁移 |
| 裁决（J 层） | 主代理 | Decision / Severity / Confidence / 动作 / 翻盘问题（`decide` 需要 `init` 打印的 main token） |

**格式是工具的职责，判断才是你的职责。** 子进程不需要记住任何字段名——`brief` 渲染出来的任务书里已经写好了它要填的每一格。

## 快速开始

```bash
S=<skill-root>/scripts/audit_forms.py

# 主代理
python -B $S init --repo-root . --profile change --target "<对象>" --scope "<范围>" \
    --snapshot "git:<base>..<head>" --unit R1 --unit R2      # 打印 main token（只显示一次）
python -B $S brief --unit R1 --out briefs/R1.md --task "<这个单元要回答什么>"
python -B $S dispatch --unit R1 --job <执行者 id>
python -B $S init --add-unit R6                               # 首轮收口后追加漫游单元（不重建实例）

# 子进程（任务书里就是这几条）
python -B $S new  --unit R1 --count 3
python -B $S run  --unit R1 --slot 1 --cmd "<可重跑命令>" --expect-exit 0
python -B $S run  --unit R1 --cmd "<对照实验>" --purpose "验证装置有效"     # 单元级证据
python -B $S mutate --unit R1 --slot 1 --file src/x.js --from "<锚点>" --to "<改坏>" --cmd "<检查命令>"
python -B $S fill --unit R1 --verify-paths                   # 迭代到 0 问题

# 主代理
python -B $S challenge --unit R1 --slot 1 --out challenges/R1-1.md
python -B $S challenge --unit R1 --slot 1 --verdict target-stands --job <复核者 id>
python -B $S decide --unit R1 --slot 1 --decision CONFIRMED --severity High --why "..." --token <token>
python -B $S note --kind disclosure --text "..."
python -B $S check && python -B $S report --out report.md
```

产物全部落在 `.audit-forms/`（`init` 会写进 `.git/info/exclude`，审计产物不进被审仓库的历史）：`audit.json`（契约）、`forms/R*.json`（槽位与证据）、`decisions.json`、`challenges.json`、`briefs/`、`challenges/`、`report.md`。

## 三条硬规则

- **证据必须由 `run` 代跑**，`exit` 与输出尾部由工具记录。自报不算证据；没有运行记录的槽位默认填不过（要留在静态阅读层面需显式 `--allow-static` 且 confidence 降为 Low）。
- **判别力必须由 `mutate` 记录**：改坏一处字面量（锚点必须恰好出现 1 次）→ 跑指定检查 → 逐字节还原并校验 sha256。`exit != 0` 说明这套检查真的抓得住这类坏；`--control` 用来声明阳性对照（这次变异**应该**被抓到，用来证明装置本身有效）。
- **裁决只归主代理，且结论不得强于证据**：`CONFIRMED` 至少要有 1 条运行记录；`Critical/High` 还要有一条按预期复现的记录，并通过一次已登记的**盲化对抗复核**（`challenge` 只给复核者「结论 + 最小复现配方」，不给原始推理，要求它用五条假设来反驳）。

严重度偏离调查者的 `severityHint` 时必须写 `--severity-because`；跳过盲化复核要用 `--allow-unchallenged` 并写明理由。两个逃生口都会在报告里原样披露。

## 四种容器

| 容器 | 装什么 |
| --- | --- |
| 槽位 `slots[]` | 一条要报告的东西：缺陷，或负结果（`kind=verification`） |
| 槽位证据 `evidence{}` | `run --slot N` 留下的可执行记录 |
| 变异记录 `mutations{}` | `mutate --slot N` 留下的判别力记录 |
| 单元级证据 `unitEvidence[]` | 不属于任何单条发现的运行：对照实验、装置自检、跨文件辅助实验（省略 `--slot`） |

**为什么必须有第四种**：调查者需要跑对照实验时，如果没有合法位置放这些记录，他会拿多余的空槽当证据桶，于是槽位里出现"这不是一条缺陷"的条目，严重度统计和报告一起被污染。这是真实审计里最贵的教训之一——缺容器时，人不会少做事，只会把事情做在错的地方。

## 结论语义

| Decision | 含义 |
| --- | --- |
| `CONFIRMED` | 有运行记录支撑，默认要过盲化复核 |
| `CONDITIONAL` | 成立，但前提未闭合 |
| `NEEDS-DECISION` | 需要有人拍板（风险接受或范围取舍） |
| `REJECTED` | 怀疑被推翻 |
| `VERIFIED` | `kind=verification` 槽位专用：这次核实确认了安全行为（如 fail-closed 真的 fail-closed） |

`kind=verification` 的槽位必须是 `VERIFIED`，不允许 `CONFIRMED`——"我核实过这里安全"与"我发现了一个缺陷"是两类结论，混在一起严重度统计就失去意义。

## 报告

`report` 从已填事实渲染，不做自由发挥，依次是：结论摘要（含机械推导的放行裁决行 `BLOCKED` / `READY-WITH-CONDITIONS` / `READY` / `INCOMPLETE`）→ 按严重度排序的发现（位置、触发条件、预期/实测、证据命令、判别力、可翻盘的问题）→ 已核实为安全 / 按设计 → 已排除（怀疑被推翻）→ 需要的动作（按优先级聚合）→ **过程披露**（对本审计不利的事实）→ **残留不确定性**（未闭合的前提）。

最后两节不许省：审计报告的价值不在于它说得多确定，而在于它把不确定的部分标出来了。

## 用户需要提供什么

自然语言说明目标即可，`init` 会把它归一成 target / scope / snapshot / objectives / units：

| 请求 | 典型解释 |
| --- | --- |
| "全面审计这个项目" | 仓库级风险覆盖；不承诺逐文件穷尽 |
| "严格审这个 PR，能不能合并" | change profile + 变更范围 |
| "做这个范围的安全审计" | security profile |
| "审某作者在指定范围的提交" | 不可变 Git 范围 |
| "确认这个修复是否真的生效" | fix-verification profile（`kind=verification` 的槽位正是为它设计的） |

## 安装

- 整个目录放进本地 Agent/harness 约定的 skills 目录，目录名保持 `cross-validated-project-audit`；根目录 `SKILL.md`、`templates/`、`scripts/`、`references/` 都要保留。
- 需要 Python 3.9+，只用标准库，无第三方依赖。
- 自动触发范围以 `SKILL.md` frontmatter 的 description 为准，显式调用方式由客户端决定；本 skill 不依赖某一种编排接口。
- `agents/` 与 `assets/` 只服务 OpenAI 系产品（ChatGPT / Codex / API / Atlas），其它 harness 可整个忽略。
- 默认只审计、不改代码：不修改被审仓库的任何 tracked 文件，只有用户明确要求时才进入修复流程，且修复不隐含 commit / push / 部署授权。

## 文件

| 文件 | 作用 |
| --- | --- |
| `SKILL.md` | 何时启动、三条硬规则、命令面、工作流、容器与结论语义、走形对照 |
| `scripts/audit_forms.py` | **唯一运行时**：16 个子命令（`init/brief/new/run/mutate/fill/prune/decide/challenge/dispatch/note/migrate/check/report/templates-check/self-test`） |
| `templates/bug.json` | 槽位模板：F 层字段、必填与枚举、每个字段对应的机械检查或评审问题、字段预算 |
| `templates/decision.json` | 裁决模板（J 层，仅主代理可写） |
| `references/failure-patterns.md` | 真实审计里的失败模式与 Hypothesis seeds（按需读） |
| `references/git-scoping.md` | 复杂 git 范围、变基、提交历史切分（按需读） |
| `references/platform-runtime-patterns.md` | Windows / PowerShell、并发、I/O 陷阱（按需读） |

## 安全边界与不变量

`check` 跑一组机械可判定的不变量（并打印检查项数）：声明过的 unit 有表单文件 / 模板版本已知 / 没有 TODO 残留 / 单元级证据必须带命令记录 / 阳性对照失败即错误 / 每个槽位已裁决且有运行记录 / 裁决不重复且指向存在的槽位 / 证据记录时的槽位主张必须与现在一致 / `kind=verification` 必须是 `VERIFIED`、`kind=defect` 不许是 `VERIFIED` / 严重度偏离提示值必须写理由 / `Critical/High` 有按预期复现的记录与已登记的盲化复核 verdict。

`report` 在还有未填或未裁决的槽位时会**拒绝出报告**（`--force` 可强制，报告里会带着这些标记）——半成品报告比没有报告更危险，因为读的人看不出它没审完。

**清单不在这里维护**——规则改名或新增时，以 `check` 的实际输出与 `self-test` 为准（这份列表曾经写着「8 条」，而代码里已经是 16 个报错点，正是散文会漂移的证据）。

不可判定的部分交给 `decide --why` 与报告里的「可翻盘的问题」，而不是编造更多不变量。模板预算同样由工具强制（`templates-check`）：必填字段 ≤12、每个字段必须对应一条机械检查或一条评审问题（逃生口字段除外）、整模板最多一个逃生口字段。

**它不保证找到所有 bug**，也不会因为多个代理同意就认定事实，更不能用 `check` 通过代替真实的源码、运行时与权威契约验证。它保证的是：报告里每一条结论，都能顺着证据记录回到一条真的被执行过的命令。

## 设计取舍

- **只维护一个平面**：状态平面（`state.json` + validator + 45 个 fixture）已删除。实测中它的 Gate 推导、派发凭据、修复批次 DAG 在两次真实审计里一次都没被用到，却占了 426KB 代码和每次执行都要记住的格式知识。唯一被保留的能力是机械推导的放行裁决行——它现在是 `report` 里的一行，而不是一套状态机。
- **格式归生成器，判断归人**：任务书、空壳、校验、报告、迁移全部从 `templates/*.json` 渲染。"每次执行都保持同一格式"由生成器保证，而不是要求每个调查者记住。
- **证据归工具，诚实不靠纪律**：`run`/`mutate` 是仅有的两个证据入口，它们把"我认为测试拦得住"换成"记录显示 exit=1"。
- **反向机制只留一条**：其余机制都在压缩调查者的搜索空间（题目由主代理给、证据必须按预期复现），所以保留「漫游单元」——首轮收口后派 1–2 个没有题目的单元，专门找主代理没想到的问题。它的证据标准与首轮完全一致，这是题目自由、不是标准放松。
- **任务描述进契约**：`brief --task` 把"这个单元要回答什么"写进 `audit.json`，重渲染不丢；留空时任务书里明写「未指定」，派发时也会被点出来——单元的任务靠散文口头交代，就是格式漂移的另一种形式。
- **默认收窄触发**：frontmatter 只覆盖高风险与明确交叉验证请求，避免普通 review 被重协议误触发；宽泛触发（"做个安全审计"）先讲清成本再启动。
