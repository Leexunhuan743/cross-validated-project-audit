# Git 工件范围界定

只在审计 Git 分支、PR、commit、指定作者提交、工作区或 **Git-backed** 修复批次时读取本文件。分别报告历史拓扑、审查补丁和最终树状态，不用其中一个替代另外两个。

## 目录

- 派发前预检
- PR 与功能分支
- 单个 commit、范围与 merge commit
- 指定作者提交
- 工作区与多 worktree
- squash、rebase 与 cherry-pick 等价性
- 子模块、LFS、生成文件与交付卫生
- 基线归因

## 派发前预检

先读取上层指令，再运行安全只读查询：

```bash
git status --short
git rev-parse --show-toplevel
git branch --show-current
git worktree list --porcelain
git remote
git for-each-ref --format='%(refname:short)' refs/remotes/
```

不要 clean、stash、reset、checkout 覆盖或删除工作区。已跟踪修改、暂存修改、未跟踪文件和其他 worktree 都是用户数据。

默认不要输出 `git remote -v` 或原始 remote URL。只有任务确需检查远端配置时才读取，并在写入日志、证据包或报告前移除 userinfo、令牌和敏感查询参数。

在派发子代理前确认：

1. 所有目标 refs 可解析为 commit。
2. base/head 与用户或 PR 元数据一致。
3. 审查范围不是因错误目录、坏 ref 或错误比较方式而意外为空。
4. 目标 worktree 与用户指定工件一致。
5. 本地脏状态不会被误算进 PR，也不会被审计操作覆盖。

若范围为空，区分“确实无内容”“补丁已等价合入”“head 已是 base 祖先”“比较方式错误”和“目标 worktree 错误”，不要把空输出直接当结论。

shallow clone 或缺对象导致 `merge-base` 失败时，回退到平台 PR 元数据/补丁并显式记录；无法解析的拓扑列为残留缺口，不要推断。

## PR 与功能分支

优先从用户或当前 PR 元数据获得准确的 base/head，并解析成不可变 commit。若多个基线会改变结论，先询问用户。

```bash
git rev-parse <base>^{commit} <head>^{commit}
git merge-base <base> <head>
git log --oneline --decorate <base>..<head>
git diff --stat <base>...<head>
git diff --name-status <base>...<head>
git diff --find-renames=50% <base>...<head>
```

- 三点 diff（`base...head`）从 merge-base 开始，通常表示 PR 希望引入的补丁。
- 两点 diff（`base head`）比较当前两棵树，表示最终状态差异。
- base 已前进时两者可能不同；审查变更以平台 PR patch 或三点 diff 为主，评估集成状态时再检查两点 diff。
- `--find-renames=50%` 明示默认相似度阈值。若大规模重写使 rename 检测失真，同时查看 `--no-renames`，不要让启发式掩盖新增/删除。
- 平台 PR diff 可能排除未提交工作区内容；不要把本地脏状态误算进 PR。

## 单个 commit、范围与 merge commit

普通 commit：

```bash
git show --stat --summary <commit>
git show --format=fuller --find-renames <commit>
```

根 commit 没有父提交；`git show <root>` 已能显示其完整补丁。不要使用会解析不存在父提交的 `<root>^`。

范围：

```bash
git log --oneline --reverse <base>..<head>
git diff <base>...<head>
```

merge commit 先确定用户要审计合并结果、某一父分支增量还是冲突解决：

```bash
git show --cc --stat <merge>
git show --cc <merge>
git diff <merge>^1 <merge>
git diff <merge>^2 <merge>
```

对 octopus merge 枚举所有父提交。组合 diff 不等于逐父 diff；冲突解决缺陷常只在组合视图或逐父对照中出现。

## 指定作者提交

`scopeMode=author-commits` 时，先把“作者是谁、在哪个不可变范围内”解析清楚，再审查；默认按 Git **author identity** 归因，不把 committer、reviewer 或 merge 执行者混为作者。

1. 解析并记录不可变 `<base>` / `<head>` 或用户给定的提交范围；未给范围且不同合理范围会改变结论时先询问。
2. 先枚举范围内提交及 author name/email，再做身份归一；`--author` 是正则匹配，只可作候选过滤，姓名重名、多个邮箱或机器人代提交时必须核对实际 identity，不靠显示名猜测。
3. 对命中的每个提交读取真实 patch 与父提交关系；同时收集其触达的路径/符号，在目标 `head` 上检查当前实际状态。被后续提交回退、覆盖或重写的内容仍属于历史审计证据，但不得冒充当前树仍存在。
4. 对每个需要变更归因的 material Finding 收集可直接核对的 base/head、目标提交、历史实现和可达性 Evidence；最终 Provenance 由任务统一评估模型判定，本模块不重复定义归因枚举。
5. 报告列出作者身份、范围、命中提交集合和排除的歧义 identity；不得把“该作者改过这个文件”直接等同于“文件中的所有问题都由该作者引入”。

安全只读枚举示例：

```bash
git log --format='%H%x09%an%x09%ae' <base>..<head>
git show --format=fuller --find-renames <selected-commit>
```

若审计的是“该作者全部历史提交”，仓库历史过大时先把时间/分支/版本范围写入 `Audit scope`；无法可靠穷尽时明确标为部分审计。

## 工作区与多 worktree

分别检查：

```bash
git diff
git diff --cached
git status --short
git worktree list --porcelain
```

`git diff` 不含未跟踪文件。若用户要求“全部本地修改”，读取相关未跟踪文件，但不自动加入、删除或改名。多 worktree 的分支、HEAD 和脏状态相互独立；所有命令都从目标 worktree 运行。

## squash、rebase 与 cherry-pick 等价性

不要从 commit 数量或空范围推断内容关系：

```bash
git merge-base <base> <head>
git merge-base --is-ancestor <head> <base>
git diff --stat <base> <head>
git rev-parse <base>^{tree} <head>^{tree}
git cherry -v <base> <head>
```

- 典型 squash merge 不保留原分支提交的祖先关系；原提交范围通常仍非空，但补丁可能已等价进入 base。
- `base..head` 为空通常说明 head 已是 base 的祖先或两者相同，不是 squash 的通用特征。
- `git cherry` 使用 patch-id 帮助识别等价补丁，但对 squash、多提交重排、部分 cherry-pick 和冲突改写可能失效；必须回落到 tree diff 和实际行为。
- 比较两轮 rebase/cherry-pick 序列时使用：

```bash
git range-diff <old-base>..<old-head> <new-base>..<new-head>
```

`range-diff` 用于提交序列对应，不替代最终 tree diff、测试或运行时验证。

## 子模块、LFS、生成文件与交付卫生

根据仓库实际配置运行存在的工具：

```bash
git diff --submodule=log <base>...<head>
git submodule status --recursive
git lfs ls-files
git diff --check <base>...<head>
```

- 检查 `.gitattributes` 后再判断 LFS；没有 Git LFS 时记录未验证，不要安装。
- 子模块 pointer 变化要核对目标 commit 可获取、来源可信以及上层代码兼容。
- 核对计划/提交集合与变更文件是否一致：遗漏文件、杂散文件、冲突标记、patch 标记、vendor 修改、lockfile/workspace、导出表、生成物和 `.gitignore`。
- 生成物若应提交，确认源文件与生成物同步；若不应提交，确认没有污染交付树。
- 二进制/大文件变更用 `git diff --numstat -- <path>` 识别；无法逐行审查的列为残留缺口，不默认跳过也不默认放行。

## 基线归因

涉及“以前是否如此”时读取基线版本：

```bash
git show <base>:<path>
git blame <head> -- <path>
```

`blame` 只定位历史线索，不判断责任。若问题既有但本次变更使其可达、扩大影响或阻碍恢复，Finding 标为 `EXPOSED` 并分别写清既有根因与增量影响；纯既有且未被目标变更实质改变的标为 `PRE_EXISTING`。
