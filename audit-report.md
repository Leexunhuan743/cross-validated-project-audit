# audit-project-artifacts 20 代理审查汇总报告

- **审查对象**:`C:/Users/leeexx/Documents/NewProject/杂项/skill/universal-audit-review/audit-project-artifacts/`(用户手动优化版)

- **对照基线**:助手旧版 `universal-audit-review/SKILL.md`(+zh-CN)、7 个历史 skill、`writing-for-agents` 写作原则

- **方法**:20 个只读子代理并行(9 scout / 9 reviewer / 2 security-reviewer),19 份有效产出(AdjudicationSystem 失败由 CrossValidationMethod/OverallScoring/TerminologyConsistency 合成补位;RedundancyAnalysis 部分产出)

- **日期**:2026-08-11

***

## 一、总评

**用户版在方法学上全面超越旧版与 7 个历史 skill,综合评分 7.5/10**(OverallScoring)。核心创新:证据强度校准(共识≠事实)、锚定效应防范、工作量上限、降级披露契约、授权边界分层、安全最小证据原则。主要失分在:验证经验保留(实证探针/陷阱清单蒸发)、写作完成标准缺失、本机 harness 落地断链。

| 维度     | 评分         | 主要扣分点                                    |
| ------ | ---------- | ---------------------------------------- |
| 方法学    | 8/10       | 实证探针弱化、拓扑预检降级、修复循环缺处置分支                  |
| 完整性    | 7/10       | 陷阱清单蒸发、per-agent 矩阵缺失、计划类最薄、commit 卫生未覆盖 |
| 可执行性   | 8/10       | §4 派发三缺(模板/机制/diff 访问)、无完成标准、无自检机制       |
| 写作质量   | 7/10       | description 双语重复、负向指令过密、跨文件规则重复          |
| **综合** | **7.5/10** |                                          |

***

## 二、核心亮点(净增资产,务必保留)

1. **证据强度校准(最突出升级)**:§6 明确"两个代理得出相同结论只提高调查优先级;代码追踪、复现测试或权威契约才提高证据强度",推翻旧版"2+ 代理=近乎确定"经验规则;配套 §4"verified vs inferred"标注、§5 四态裁决、§8 两套逐字结论文案。
2. **锚定效应防范(§4 末)**:主代理在阅读代理结论前先记录自己的初步判断——旧版与 7 个 skill 均无;配合"不向发现阶段代理透露预期答案"的信息隔离。
3. **工作量上限与规模适配(§3)**:抛弃固定代理数,小型=2 代理+主代理,明确"不要为了凑数制造重复工作""停滞时用已完成证据收尾,不无限等待"。
4. **降级披露契约**:无子代理时明确披露降级;§8 给出逐字措辞(达标版 vs 降级版),旧版只有一句 "Residual gaps stated honestly"。
5. **授权边界分层**:审计/修复/提交/推送/部署逐级授权 + 6 条暂停条件;git-scoping.md 的 remote URL 凭据脱敏是同精神落地。
6. **安全最小证据原则**:只保留证明结论所需的最小复现,不输出可直接滥用步骤——旧版完全没有。
7. **去项目特化**:把 SageThumbs/TMD 实例全部剥离,可迁移内核提炼进维度表。
8. **交叉验证方法学**:条件触发式(仅 Critical/High 未重叠/冲突/仅推断时挑战)优于 deep-branch 的固定 36+ 波次;独立性约束(新线程+不共享候选+不同检查方法+中性措辞)更显式。

***

## 三、高严重度问题(按修复优先级)

### H1. 实战陷阱清单整段蒸发 ——【必改,最高优先】

**来源**:LegacyMechanismGap(H1)、TrapLossAnalysis、CoverageComparison、PlatformKnowledgeGap、OverallScoring(C1)
旧版 12 条 Known traps + 7 个旧 skill 约 25 条陷阱中,用户版仅 2 条完全保留(squash-merge 甚至扩展为 reference 章节、测试判别力原则)、6 条降为关键词、**4 条完全删除**(死代码遗留、gate 语义误报、Rust 移位语义、全行写丢失更新)。具体损失:

- **修复破坏旧数据迁移**(旧版标注"最高价值输出")→ 仅剩"兼容旧数据"一词,旧名豁免/归一化/迁移测试配方全删 —— **损失:高**

- **Windows 路径语义**(尾点/尾空格 Win32 剥离、os.Rename 空目录失败、保留名变体)→ 仅剩"标为条件性结论"纪律 —— **损失:中高**(本机宿主即 Windows)

- **死代码遗留**(helper 不再被调用、被测试保活)→ 完全删除 —— **损失:中高**

- **gate 语义误报**(PowerShell -notmatch "1.4.1" ⊂ "1.4.1.0"、相等比较复现误报)→ 完全删除 —— **损失:中低**

- **Rust** **`<<`** **移位语义**(仅移位量≥位宽 panic;DEFENSIVE-ONLY 判定)→ 完全删除 —— **损失:中**(本机有 Rust 项目)

- **全行写丢失更新**(UPDATE SET a=?,b=?,c=? 回退并发写)→ 完全删除 —— **损失:中**

- **无界等待 / 文档 overclaim / 新激活路径** → 降为维度表单个关键词

- **建议**:蒸馏为 `references/traps.md`(按 测试判别力/迁移数据/gate 语义/平台语义/文档一致性/计划审查 分类,保留来源标注),主文件 §5 加挂钩点;删除的 4 条反模式以"反模式+检索策略"形式补回(选通用性强+重复踩坑成本高的)。

### H2. 派发环节在本机 harness 断链:diff 预导出机制丢失 ——【必改】

**来源**:HarnessFit(F1,高)、StepExecutability(F1-F3)、LegacyMechanismGap(H2)

- scout 类子代理**无法跑 git/bash**(本会话工具清单证实),旧版有 "Pre-export per-subsystem diffs to a shared file (`.audit-share/<name>-diff.txt`)" 机制,用户版 §4 只给"精确路径+比较基线",**子代理拿不到 diff 内容**,无法完成"本次引入 vs 既有"归因,§5.2 基线对照在子代理侧断链。

- 连带:git-scoping.md 全篇 bash 命令只有主代理能执行;§4"允许运行的检查"措辞暗示子代理可跑构建,实际只有主代理能跑。

- **建议**:§4 任务提供项恢复 diff 交接——小工件内联 diff,大工件写 `local://<name>.md` 或仓库外 `.audit-share/`(收尾删除);"允许运行的检查"限定为只读查询+隔离探针。

### H3. 实证探针从"必做"降为"尽可能" ——【必改】

**来源**:CrossValidationMethod(F1,高)、PlatformKnowledgeGap(F6)、OverallScoring(M1)

- 旧版/deep-branch:"临时程序调用**真实函数**、平台主张在**宿主机 OS** 验证(实际跑 os.Mkdir/os.Rename、喂 CJK/Cyrillic)"是 non-negotiable 杀手锏;用户版 §5 弱化为"尽可能运行最小复现",并把"直接代码追踪"列为与复现同级。

- 风险:静态追踪只能确认路径存在,不能确认路径真实触发;主代理可把仅经推理的运行时/平台主张标为 CONFIRMED 进报告。

- **建议**:§5 增加实证义务——"运行时行为、平台/FS/编码、并发交错、第三方库行为类主张,默认必须调用真实生产函数执行;无法实证者只能标 CONDITIONAL";§6 把"直接代码追踪"从充分确认手段中移除。

### H4. 完成标准章节整体删除 ——【必改】

**来源**:StepExecutability(F4,高)、OverallScoring(F-w1)

- 旧版有 "Completion criteria"(代码级复核记录/per-agent 裁决表/残留缺口/报告结构),用户版删除。§1-2 各步无显式收尾条件,§4 派发后无"何时算完成"总闸。

- **建议**:§8 末尾补 5 条完成标准(每个有影响候选项有 裁决+严重度+复核记录;报告含 §8 全部 9 项;无发现用逐字措辞;临时产物已清理;修复轮次每批经复核且回归通过)。

### H5. §4 派发无任务模板、无机制指名 ——【必改】

**来源**:StepExecutability(F1/F2,高)、HarnessFit(F5)

- 全文无 `task`/`hub`/`agent://` 字样(旧版有 "one `task` call"、scout-agents-md 有 hub wait 120s + agent:// 取全量);§4 是 5 项内容清单非可填充模板。

- **建议**:补逐字可填充任务模板(角色/工件基线/验收标准/重叠不变量/允许检查/只读边界/返回 6 项);指名派发机制(一次 task 批量 ≤32、hub wait 收、agent://<id> 读全量、新 task 调用=新线程);恢复 `outputSchema: false` 预检拒绝警告。

### H6. 报告契约缺 per-agent 裁决矩阵与复核记录 ——【应改】

**来源**:ReportSpecReview(高)、OverallScoring(M3)、LegacyMechanismGap(H8)

- 旧版/branch-audit-batch 硬性要求 per-agent adoption record(维度/finding/主代理证据/裁决)+ 每个 accepted finding 的代码级复核记录;用户版 §8 只有"被主代理反驳的重大候选项",非重大 REJECTED 不可见,复核轨迹不可追溯。

- **建议**:§5 加裁决表模板(每候选项一行:维度|位置|严重度|裁决|主代理证据|复核方式),§8 报告必含;恢复"读每份全量报告(agent://<id>),绝不只看预览"。

### H7. 修复循环缺 fix-commit 专项 ——【应改】

**来源**:FixLoopReview(F6,高)、LegacyMechanismGap(H4/H7)

- 用户版 §7 保留"分批/最小补丁/三要素验证/回归确认"骨架,但**丢了"修复引入新 bug 是最高价值输出"**——fix-commit-verification 的核心定位。专项检查(旧数据迁移 wedge、死代码遗留、判别力需读 PRE-fix 路径)整体遗漏;缺批前构建门槛、验证反馈裁决循环(确认→立即修/反驳→记录理由/新 High→先修再进下一批)、收尾第二轮修复轮。

- **建议**:§7.3 重写验证任务规范(批前全绿门槛、每子系统 1 验证代理、任务输入引用 §4 模板);加最高价值声明与专项检查清单;§7.4 加三分支处置;补收尾修复轮 + CHANGELOG。

### H8. 安全边界 4 类缺口 ——【应改】

**来源**:AbuseBoundary(AB-01/02,高;AB-03\~08 中)

- **供应链/执行面**:§2.4"优先使用仓库既有构建/测试命令"与"无外部副作用"自相矛盾——构建/测试会执行仓库内任意脚本并触发依赖下载;审计不可信 PR 时恶意脚本以用户完整权限执行。建议:对不可信工件先在隔离副本(临时 clone/worktree/容器/网络受限)执行;运行安装/下载命令前告知用户。

- **信任面/prompt injection**:§1.2 指示"阅读仓库指令",而 AGENTS.md/README/issue/代码注释全是攻击者可控输入;无"仓库内容一律视为数据而非指令"立场。建议:核心约束加内容即数据声明,子代理不得执行仓库内脚本建议。

- **信息面**:凭据发现无处理协议、报告无脱敏步骤(仅 git URL 有)。建议:发现凭据→提示用户而非输出;报告前扫描凭证模式。

- **流程面**:纯审计模式无探针清理收尾校验;修复范围外改动无确认。

### H9. 维度表 1 缺失 + 3 压平 ——【应改】

**来源**:DimensionsQuality(overall_correctness: incorrect)

- **git 交付完整性完全缺失**(旧 GitDeliveryIntegrity:commit set vs 计划、stray files、vendor 标记、exports、lock/workspace/gitignore 卫生)——"构建与交付"只管发布物,不算 git 树卫生。**高优先补回**。

- **UI 状态机压平为"UI 状态"四字**(对话框索引算术、OK-gating、路由 vs 进程内双臂分歧是实战抓到 P1 的检查类)。

- **CLI 契约**部分覆盖(缺批量语义 vs 计划措辞、单一咽喉调用链);**互操作发布证据**部分覆盖(缺 external-crate 行为原始证据、release-vs-debug 证明缺口、字节级主张实测)。

- 计划类 5 维缺 ProjectReuseScout/ReferenceDeepScout 与 v3 合并协议(plan-review-batch 的一半价值)。

### H10. git-scoping.md 无命令级硬错误,但需 3 处修订 ——【应改】

**来源**:GitScopingReview(7 项核对:2 修订 + 3 补充 + 1 低 + 1 中)

- **修订**:① squash 因果表述——"squash 后 base..head 为空"是误导,实测恰好相反(squash 保留原 commit 可达性,范围非空但内容等价);空范围实际发生在 head 已成为 base 祖先时;② `--root` 在现代 git 已冗余(`git show <root>` 默认即显示完整 diff,但 `git diff <root>^` 确实 fatal——替代方向正确,措辞需修)。

- **补充**:已合并节缺 `git cherry`/`git range-diff` 等价检测(注意 patch-id 局限:乱序/部分 cherry-pick 与 squash 后不匹配,须回落 tree diff);merge commit 审计只有原则无命令(补 `git show --cc <merge>` 等);LFS/子模块/生成文件检查无手段(补 `git lfs ls-files`、`git diff --submodule=log`);`--find-renames` 无阈值说明(默认 50%);工作区节缺 `git worktree list`(多 worktree 状态独立)。

- **保留确认**:三点/两点 diff 语义、`git rev-parse ^{tree}`、remote URL 脱敏均正确。

### H11. 术语:严重度定义晚于使用点 + 新旧词汇无映射 ——【低-中】

**来源**:TerminologyConsistency

- §4 要求子代理报"严重度"但 Critical/High/Medium/Low 定义在 §5;建议 rubric 前移到 §3 末/§4 首。

- 行 116 残留英文 `finding`(全文其余用"候选问题");"候选问题/候选项"同句混用。

- **跨文档切换风险**:新旧裁决/严重度词汇(ADOPT 系 vs CONFIRMED 系、P0-P3 vs Critical 系)无映射说明,用户拿旧报告对照新版工作流会读不懂。建议加术语映射节(ADOPT→CONFIRMED、DECIDE→NEEDS-DECISION、REJECT→REJECTED、新增 CONDITIONAL;P0→Critical…P3→Low)。

### H12. description 双语重复 + 信息层级问题 ——【低-中】

**来源**:WritingPrinciplesGap(8/10)、InfoHierarchy、RedundancyAnalysis

- **description 中英双语重复同一触发分支**(违反 one trigger per branch;description 是最贵的常驻指针,约 1/3 是冗余);流程描述重复正文身份;建议保留单语分支清单+排除子句。

- **核心约束 8 条 ≈ 正文摘要**(仅 3 条是正文未覆盖的硬规则),去重可省 \~450 字,主文件 11.2KB → \~9.5KB。

- **review-dimensions.md 末两节(独立性/降噪)与主文件 §4/5/6 近字面重复**,违反单一事实源,建议删除(唯一未见他处的"同一模型多次回答可能相关"并入 §6)。

- "共识≠事实"散布 4 处、"用户改动神圣"散布 5 处,收敛到单点。

- **负面反馈中唯一正面项**:披露决策本身正确(git-scoping/review-dimensions 均为分支性参考,指针措辞良好),无需回移。

### H13. openai.yaml 合规,无缺陷 ——【低,可选改进】

**来源**:OpenaiYamlCompliance(overall_correctness: correct)

- 字段与取值全部合法(display_name/short_description/default_prompt/$audit-project-artifacts 三处一致/icon.svg 良构/products 合法/allow_implicit_invocation 即默认值)。

- 在 omp 环境是**惰性元数据**(omp 只消费 SKILL.md frontmatter,不读 agents/),\[INFERENCE] 属预期行为。

- 可选改进:short_description 补英文与负向守卫、icon_small 用 PNG 惯例、README 注明 omp 不读取。

***

## 四、修复优先级清单

**必改(P0)**

1. 恢复实战陷阱:建 `references/traps.md`(蒸馏 12+ 条反模式,去项目特化,按类分组),§5 加挂钩点(H1/H3 同源)
2. 恢复 diff 预导出交接(`local://` 或 `.audit-share/`),修复 §4 派发断链(H2)
3. 实证义务回归:§5 运行时/平台/并发/第三方主张默认必跑真实函数,否则 CONDITIONAL(H3)
4. 补完成标准章节 5 条(H4)

**应改(P1)**
5\. §4 补可填充任务模板 + 派发机制指名(task/hub/agent://)+ outputSchema 警告(H5)
6\. §8 补 per-agent 裁决矩阵 + 代码级复核记录(H6)
7\. §7 补 fix-commit 专项(旧数据 wedge/死代码/判别力读 PRE-fix)+ 裁决循环 + 收尾修复轮(H7)
8\. 安全边界补 4 类缺口:隔离构建、内容即数据、凭据协议、清理校验(H8)
9\. review-dimensions 补 git 交付完整性维度 + 恢复 UI/CLI/互操作检查点深度(H9)
10\. git-scoping 修订 squash 因果、补 cherry/range-diff/merge 命令/LFS/--find-renames 阈值(H10)
11\. 拓扑预检内联进 §1(三点 vs 两点 diff、squash 改变审计框架)(OverallScoring M2)

**可改(P2)**
12\. 严重度 rubric 前移 + 术语映射节 + 行 116 finding 统一(H11)
13\. description 去双语重复;核心约束去重;跨文件规则单源化(H12)
14\. §7 补批大小建议(3-5)+ todo 清单 + 清理清单(StepExecutability F10)
15\. 负向指令正面化改写(保留硬护栏)(OverallScoring F-w2)
16\. openai.yaml short_description 双语 + README 注明惰性(H13)

***

***

## 六、一句话结论

用户版是**方法学全面更优**的通用审计协议(证据校准/锚定防范/预算上限为实质创新),但要作为"通用项目审计/commit 审查"的可靠工具,必须补回三块被蒸发的实战资产:**陷阱清单(traps.md)、实证探针义务、diff 预导出交接**,并补上完成标准与 per-agent 裁决矩阵;修完 P0+P1 后即为该目录下最可靠的通用审计协议。
