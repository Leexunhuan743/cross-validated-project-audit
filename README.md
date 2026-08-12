# cross-validated-project-audit

多子代理并行发现 + 交叉验证 + 主代理统一验证调度的通用项目审计 skill。审计对象：分支、PR、commit、工作区改动、已实现功能、配置、迁移或实施计划。

## 核心机制

- **多子代理并行发现**：按证据轴（需求忠实度/工程正确性/真实用户路径/交付完整性）派发独立只读子代理，每个子代理必须逐行阅读其负责范围内的真实代码与文件，DIRECT 标注仅限实际读取或运行所得。
- **交叉验证**：高风险不变量由两个独立发现过程覆盖；子代理结论是调查线索，代码追踪、真实运行或权威契约才是证据。
- **主代理统一验证调度**：主代理界定范围、阅读完整 diff、记录锚定前判断、复核每个候选问题、裁决（CONFIRMED / NEEDS-DECISION / CONDITIONAL / REJECTED）、出发布/合并门禁（READY / READY-WITH-CONDITIONS / BLOCKED / INCOMPLETE）。

## 使用

- 模型自动触发（description 中英双语：中文"全面/多代理审计或审查、发布或合并就绪评估、交叉验证修复结果"；英文 "comprehensive or multi-agent audit/review、release/merge gate check、cross-validated fix verification"）。
- 默认只审计、不修改项目；要求修复时须显式说明，修复受 SKILL §6 分批与复核约束。
- 详细流程见 `SKILL.md`；完成标准见 `references/reporting.md` 完成清单。

## 安装

- 将本仓库放入 agent 的 skills 目录，目录名保持 `cross-validated-project-audit`，例如 `~/.omp/agent/skills/cross-validated-project-audit/`。
- `SKILL.md` 必须位于目录根；`references/`、`agents/`、`assets/` 随目录保留，skill 通过相对路径按需读取。
- `agents/openai.yaml` 为惰性元数据（omp 只消费 SKILL.md frontmatter，不读取本文件），无需改动；`assets/icon.svg` 为技能图标。
- 无需显式调用：符合 description 触发条件（全面/多代理审计或审查、发布或合并就绪评估、交叉验证修复结果）时自动加载。
- 自检：运行底部"验证"命令，确认术语扫描 0 命中、三处一致。

## 文件结构

| 文件 | 何时读取 | 内容 |
|---|---|---|
| `SKILL.md` | 每次使用 | 主流程：操作契约 + §1–§7 |
| `references/git-scoping.md` | Git 工件 | 范围界定命令、拓扑预检、交付卫生 |
| `references/review-dimensions.md` | 设计覆盖时 | 4 证据轴、14 实现维、7 计划维 |
| `references/core-failure-patterns.md` | 建立风险地图时 | 14 条高价值失败模式（含安全反例） |
| `references/behavioral-verification.md` | 运行时主张 | 公共入口验证、7 步安全执行序、证据四态 |
| `references/platform-runtime-patterns.md` | 平台/编码/语言语义 | Windows、Unicode、PowerShell、Rust、第三方差异 |
| `references/fix-verification.md` | 实施修复时 | 修复映射、动态分批、新代理复核、裁决反馈 |
| `references/reporting.md` | 输出报告前 | 报告层级、门禁映射、完成清单 |
| `agents/openai.yaml` | 无需读取 | 惰性元数据；omp 只消费 SKILL.md frontmatter，不读取本文件 |

## 版本谱系

`universal-audit-review-v0.1/`（助手旧版基线）→ `audit-project-artifacts-v1.0/`（用户手动首版）→ `v1.1/`（第一轮审计整改）→ `v1.2/`（第二轮整改，现行最优前身）→ **`cross-validated-project-audit/`（本版，已去版本号，为唯一现行版）**。各版本逐行 diff 对比依据留存于本机工作目录。

## 本版相对 v1.2 的变更

- 术语统一：全仓用"候选问题"，英文 `finding` 与"候选项"清零。
- 恢复旧报告术语映射：ADOPT→CONFIRMED、DECIDE→NEEDS-DECISION、REJECT→REJECTED、P0–P3→Critical–Low（SKILL §4.5）。
- description 补英文触发分支（v1.2 纯中文，英文请求不触发）。
- 审计部分适当化：SKILL.md 138→91 行；删去对强模型属 no-op 的微指令；负向禁令正面化（保留的负向均为与正向目标配对的硬护栏）。
- 新增子代理逐行阅读义务：DIRECT 仅指实际读取或运行所得，臆断只能标 INFERRED 或略去。
- 改名 `cross-validated-project-audit`：名字体现交叉验证机制（原 `audit-project-artifacts` 只描述审计对象）。

## 有意取舍

- **harness 无关**：不指名 task/hub/agent:// 等编排接口，子代理与主代理的统一调度由当前平台能力承担。
- **双语 description**：英文触发分支常驻约 90 字符，为覆盖英文请求而保留（接受该 pointer 成本）。
- **7 个 references 的认知负载**：按触发条件渐进披露，换取 SKILL 主文件精简与常驻负载最小化。
- **主代理负载集中**：子代理网络访问禁止后，外部契约查阅由主代理统一执行（behavioral-verification §3.6），大型多波次审计时主代理负载高——下一轮迭代的候选改进点。

## 验证

- 术语扫描（skill 内容文件）：`grep -rni 'finding\|候选项' SKILL.md references/ agents/` 应 0 命中。
- 三处一致：frontmatter `name`、openai.yaml `$cross-validated-project-audit` token、display_name。
