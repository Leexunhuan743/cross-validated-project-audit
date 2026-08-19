# cross-validated-project-audit

通用项目审计 skill：多个只读子代理按证据轴并行发现，主代理统一复核、实证并裁决，输出发布/合并门禁结论。审计对象：分支、PR、commit、工作区改动、已实现功能、配置、迁移或实施计划。

## 核心机制

- **多代理并行发现**：按证据轴（需求忠实度 / 工程正确性 / 真实用户路径 / 交付完整性）派发独立只读子代理；每个子代理必须逐行阅读其负责范围内的真实代码与文件，`DIRECT` 标注仅限实际读取或运行所得，臆断只能标 `INFERRED` 或略去。

- **交叉验证**：最高风险不变量由两个独立发现过程覆盖；子代理结论只是调查线索，代码追踪、真实运行或对应版本权威契约才是证据。

- **状态落盘与断点恢复**：范围、候选账本、覆盖矩阵与子代理发现产物启动即写入工作目录 `.audits/`（初始化处理 Git 忽略规则，用 `git rev-parse --git-path info/exclude` 取得真实排除文件路径以兼容 linked worktree；Markdown 账本，零机器格式维护负担）——盘上即真相；会话中断可续审，结束后归档供跨轮复盘（`references/audit-ledger.md`）。

- **主代理统一验证调度**：界定范围、记录锚定前判断、复核每个候选问题并裁决（`CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`），输出门禁（`READY` / `READY-WITH-CONDITIONS` / `BLOCKED` / `INCOMPLETE`）。

## 使用

- 自动触发：触发与排除范围以 `SKILL.md` frontmatter description 为准。

- 默认只审计、不修改项目源码（唯一写入：`.audits/` 与忽略规则，忽略规则用 `git rev-parse --git-path info/exclude` 取得真实路径，不产生 git status）；要求修复须显式说明，修复受 `SKILL.md` §6 分批与复核约束。

- 完整流程见 `SKILL.md`；门禁映射与完成清单见 `references/reporting.md`。

- 不用于快速摘要、纯风格检查或普通窄范围问答（以 `SKILL.md` frontmatter 的触发与排除范围为准）。

## 安装

- 将本仓库放入 agent 的 skills 目录，目录名保持 `cross-validated-project-audit`，例如 `~/.omp/agent/skills/cross-validated-project-audit/`。

- `SKILL.md` 必须位于目录根；`references/`、`agents/`、`assets/` 随目录保留，通过相对路径按需读取。

- `agents/openai.yaml` 为惰性元数据（omp 只消费 `SKILL.md` frontmatter，不读取本文件），无需改动；`assets/icon.svg` 为技能图标。

- 无需显式调用：符合 description 触发条件时自动加载。

## 文件结构

| 文件                                        | 何时读取       | 内容                                    |
| ----------------------------------------- | ---------- | ------------------------------------- |
| `SKILL.md`                                | 每次使用       | 主流程：操作契约 + §1–§7                      |
| `references/git-scoping.md`               | Git 工件     | 范围界定命令、拓扑预检、交付卫生                      |
| `references/review-dimensions.md`         | 设计覆盖时      | 4 证据轴、14 实现维、7 计划维 + FACT/JUDGMENT 裁决与计划就绪条件                    |
| `references/core-failure-patterns.md`     | 建立风险地图时    | 13 条失败模式 + 模式范围方法（含安全反例）                    |
| `references/behavioral-verification.md`   | 运行时主张      | 公共入口验证、8 步安全执行序、证据四态                  |
| `references/platform-runtime-patterns.md` | 平台/编码/语言语义 | Windows、Unicode、PowerShell、Rust、Node/npm、第三方差异 |
| `references/fix-verification.md`          | 实施修复时      | 修复映射、动态分批、新代理复核、裁决反馈                  |
| `references/audit-ledger.md`               | 每次使用（启动即读） | Markdown 账本/矩阵模板、忽略规则、落盘纪律、断点恢复、归档与降级     |
| `references/auditor-persona.md`            | 派发子代理前     | 平台中性审计员模板、实例化规则与检查表                    |
| `references/reporting.md`                 | 输出报告前      | 报告层级、门禁映射、完成清单                        |
| `agents/openai.yaml`                      | 无需读取       | 惰性元数据；omp 只消费 `SKILL.md` frontmatter  |

## 有意取舍

- **harness 无关**：不指名 task/hub/agent:// 等编排接口，子代理与主代理的统一调度由当前平台能力承担。

- **9 个 references 的认知负载**：按触发条件渐进披露，换取 `SKILL.md` 主文件精简与常驻负载最小化。

